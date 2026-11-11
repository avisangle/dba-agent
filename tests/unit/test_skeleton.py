"""DBA-2: repo skeleton, `python -m tools` dispatcher, CLAUDE.md conventions.

No database or external service is touched. CLI tests run the real
dispatcher in a subprocess; discovery tests run it against a copy of
`tools/` in a temp dir so the source tree is never modified.
"""

import ast
import importlib
import inspect
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
THIS_FILE = Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()
NAME_LITERAL = "oradba"  # this file is excluded from the absence scan

if str(REPO_ROOT) not in sys.path:  # `tools` is imported in-process too
    sys.path.insert(0, str(REPO_ROOT))

EXISTING_RULES = [
    (
        "- Running or continuing the SQLcl MCP spike: follow `spike/HANDOFF.md` exactly; "
        "record results in `spike/RESULTS.md`."
    ),
    "- Python: always inside the repo's `.venv` (`source .venv/bin/activate && python ...`).",
    "- Never commit credentials, wallets, saved SQLcl connections or `spike/work/`.",
]
DB_RULE = (
    "Only non-production databases. The local throwaway Oracle 23ai Free test "
    "container started from `tests/docker-compose.yml` may be connected to without "
    "asking. Any other database needs the user's confirmation before connecting."
)
OLD_DB_RULE = "Only non-production databases. Confirm with the user before connecting."
SKELETON_DIRS = [
    "plugin/checks",
    "plugin/skills",
    "plugin/profiles",
    "db/tiers",
    "tests/unit",
    "tests/integration",
    "docs/decisions",
]
NEW_TOP_LEVEL = ["plugin/", "tools/", "db/", "tests/", "docs/", "pyproject.toml"]


def _clean_env():
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    return env


def _run_tools(*args, cwd=REPO_ROOT):
    return subprocess.run(
        [sys.executable, "-m", "tools", *args],
        cwd=cwd,
        env=_clean_env(),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _repo_files():
    """Tracked plus untracked-but-not-ignored files, so uncommitted work counts."""
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [p for p in out.splitlines() if (REPO_ROOT / p).is_file()]


def _config():
    return importlib.import_module("tools.config")


# --- behavioural tests -------------------------------------------------------


def test_config_pack_home_defaults_to_dot_name_and_honours_env_override(
    monkeypatch, tmp_path
):
    """AC: tools/config.py defines PACK_NAME = "oradba", VERSION, pack_home();
    pack_home() is ~/.<PACK_NAME> unless <PACK_NAME upper>_HOME is set."""
    config = _config()
    assert config.PACK_NAME == NAME_LITERAL
    assert isinstance(config.VERSION, str) and config.VERSION.strip()

    env_var = f"{config.PACK_NAME.upper()}_HOME"
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv(env_var, raising=False)
    assert Path(config.pack_home()) == fake_home / f".{config.PACK_NAME}"

    override = tmp_path / "custom-pack-home"
    monkeypatch.setenv(env_var, str(override))
    assert Path(config.pack_home()) == override


def test_cli_help_version_and_bad_invocations():
    """AC: --help exits 0 and lists every command; `version` prints
    "<PACK_NAME> <VERSION>"; unknown command exits 2 with stderr message;
    no command exits 2."""
    config = _config()

    help_ = _run_tools("--help")
    assert help_.returncode == 0, help_.stderr
    for module in (REPO_ROOT / "tools" / "commands").glob("*.py"):
        if module.name == "__init__.py":
            continue
        name = importlib.import_module(f"tools.commands.{module.stem}").NAME
        assert name in help_.stdout, f"command {name!r} missing from --help"

    version = _run_tools("version")
    assert version.returncode == 0, version.stderr
    assert version.stdout.strip() == f"{config.PACK_NAME} {config.VERSION}"

    unknown = _run_tools("no-such-command-xyz")
    assert unknown.returncode == 2
    assert unknown.stderr.strip(), "unknown command must explain itself on stderr"

    missing = _run_tools()
    assert missing.returncode == 2


GREET_MODULE = '''
NAME = "greet"
HELP = "greet someone (test-only command)"


def add_arguments(parser):
    parser.add_argument("--who", default="world")


def run(args):
    print(f"hello {args.who}")
    return 3
'''

BROKEN_MODULE = '''
NAME = "broken"
HELP = "missing run()"


def add_arguments(parser):
    pass
'''


def test_command_discovery_adds_module_and_rejects_incomplete_module(tmp_path):
    """AC: any module in tools/commands/ with NAME, HELP, add_arguments, run
    becomes a subcommand with no other edit, and the process exits with run()'s
    return value; a module missing one attribute makes --help fail naming it."""
    shutil.copytree(
        REPO_ROOT / "tools",
        tmp_path / "tools",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    commands = tmp_path / "tools" / "commands"

    (commands / "greet_cmd.py").write_text(GREET_MODULE)
    help_ = _run_tools("--help", cwd=tmp_path)
    assert help_.returncode == 0, help_.stderr
    assert "greet" in help_.stdout

    greet = _run_tools("greet", "--who", "dba", cwd=tmp_path)
    assert greet.stdout.strip() == "hello dba"
    assert greet.returncode == 3

    (commands / "broken_cmd.py").write_text(BROKEN_MODULE)
    broken = _run_tools("--help", cwd=tmp_path)
    assert broken.returncode != 0
    assert "broken_cmd" in broken.stderr + broken.stdout


def test_pack_name_literal_appears_only_in_config():
    """AC: the literal name appears in no tracked file except tools/config.py
    (spike/ and this test excluded). Case-sensitive, per the issue wording."""
    files = _repo_files()
    assert "tools/config.py" in files, "tools/config.py must exist and not be ignored"
    assert NAME_LITERAL.encode() in (REPO_ROOT / "tools/config.py").read_bytes()

    excluded = {"tools/config.py", THIS_FILE}
    offenders = [
        p
        for p in files
        if p not in excluded
        and not p.startswith("spike/")
        and NAME_LITERAL.encode() in (REPO_ROOT / p).read_bytes()
    ]
    assert offenders == []


def test_skeleton_tooling_config_and_stdlib_only_tools():
    """AC: pyproject configures pytest (testpaths tests/, `integration` marker)
    and ruff, with empty runtime deps and pytest/ruff/pyyaml as dev deps;
    skeleton dirs exist with a placeholder; .gitignore gains build/cache dirs;
    no file under tools/ imports a third-party package."""
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())

    pytest_cfg = pyproject["tool"]["pytest"]["ini_options"]
    assert [p.rstrip("/") for p in pytest_cfg["testpaths"]] == ["tests"]
    assert any(m.split(":")[0].strip() == "integration" for m in pytest_cfg["markers"])
    assert "ruff" in pyproject["tool"]

    assert pyproject["project"].get("dependencies", []) == []
    dev = pyproject.get("dependency-groups", {}).get("dev") or pyproject["project"].get(
        "optional-dependencies", {}
    ).get("dev", [])
    dev_names = {re.split(r"[<>=!~\[; ]", d, maxsplit=1)[0].lower() for d in dev}
    assert {"pytest", "ruff", "pyyaml"} <= dev_names

    files = _repo_files()
    for d in SKELETON_DIRS:
        assert any(f.startswith(d + "/") for f in files), f"{d}/ missing or empty"

    gitignore = (REPO_ROOT / ".gitignore").read_text().splitlines()
    for entry in ("dist/", ".pytest_cache/", ".ruff_cache/"):
        assert entry in gitignore

    tool_sources = [f for f in files if f.startswith("tools/") and f.endswith(".py")]
    assert tool_sources, "tools/ has no Python files"
    third_party = []
    for path in tool_sources:
        tree = ast.parse((REPO_ROOT / path).read_text(), filename=path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                roots = [node.module.split(".")[0]]
            else:
                continue
            third_party += [
                f"{path}: {r}"
                for r in roots
                if r not in sys.stdlib_module_names and r != "tools"
            ]
    assert third_party == []


def test_claude_md_and_readme_conventions():
    """AC: CLAUDE.md keeps the existing rules, replaces the database rule with
    the narrow wording, documents test/lint commands and stdlib-only tools, and
    has the layout table; README layout lists new top-level paths, no status."""
    claude = (REPO_ROOT / "CLAUDE.md").read_text()
    for rule in EXISTING_RULES:
        assert rule in claude
    assert DB_RULE in claude
    assert OLD_DB_RULE not in claude
    assert "source .venv/bin/activate && pytest tests/unit" in claude
    assert "pytest -m integration" in claude
    assert "ruff check ." in claude
    assert re.search(r"stdlib[ -]only", claude, re.IGNORECASE)
    claude_rows = [ln for ln in claude.splitlines() if ln.lstrip().startswith("|")]
    for path in ("tools/", "plugin/", "tests/"):
        assert any(path in row for row in claude_rows), f"{path} not in CLAUDE.md layout table"

    readme = (REPO_ROOT / "README.md").read_text()
    readme_rows = [ln for ln in readme.splitlines() if ln.lstrip().startswith("|")]
    for path in NEW_TOP_LEVEL:
        assert any(f"`{path}" in row for row in readme_rows), f"{path} not in README layout"
    status = re.compile(
        r"\b(deployed|not yet|done|in progress|shipped|coming soon|todo|wip)\b",
        re.IGNORECASE,
    )
    assert not status.search(readme), status.search(readme)


# --- contract test -----------------------------------------------------------


def test_contract_for_dependents_dba3_dba4(capsys):
    """Contract for DBA-3 (command discovery, tools/config.py), DBA-4 (pytest
    config, `integration` marker) and later stories. Shape only."""
    config = _config()
    assert isinstance(config.PACK_NAME, str)
    assert isinstance(config.VERSION, str)
    assert callable(config.pack_home)
    assert all(
        p.default is not inspect.Parameter.empty
        for p in inspect.signature(config.pack_home).parameters.values()
    )
    assert isinstance(config.pack_home(), Path)

    main_mod = importlib.import_module("tools.__main__")
    params = inspect.signature(main_mod.main).parameters
    assert "argv" in params and params["argv"].default is None
    assert isinstance(main_mod.main(["version"]), int)
    capsys.readouterr()

    version_cmd = importlib.import_module("tools.commands.version")
    assert isinstance(version_cmd.NAME, str)
    assert isinstance(version_cmd.HELP, str)
    assert callable(version_cmd.add_arguments)
    assert callable(version_cmd.run)
    assert len(inspect.signature(version_cmd.add_arguments).parameters) == 1
    assert len(inspect.signature(version_cmd.run).parameters) == 1

    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    assert "ini_options" in pyproject["tool"]["pytest"]
    assert "ruff" in pyproject["tool"]
    for d in SKELETON_DIRS:
        assert (REPO_ROOT / d).is_dir()

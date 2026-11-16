"""DBA-18: the plugin manifest, `tools.package` (`collect`, `build_zip`) and the
`package` command.

No database or SQLcl is touched. `collect` and `build_zip` run on a temp tree
seeded with files that must stay out of the zip. The command tests that make
lint or the index fail run `python -m tools` from a copy of tools/, plugin/,
db/, README.md and LICENSE in a temp dir, so the source tree is never modified.

Claude Code plugin format (via Context7, 2026-11-13): the manifest is
`.claude-plugin/plugin.json` at the plugin root; `name` is required, kebab-case;
`version` is X.Y.Z; skills are found in `skills/<name>/SKILL.md` by default.

Pinned here, as the contract /implement follows:
- `collect(root) -> list[Path]`: the files to package, as paths relative to
  `root` (absolute paths under `root` are accepted too).
- `build_zip(root, out)`: `out` is the zip file to write. Credential files are
  left out and the build succeeds.
- The `package` command writes `<out-dir>/<PACK_NAME>-<VERSION>.zip`, `--out-dir`
  defaulting to `dist`.
- The literal pack name appears in plugin.json, the one tracked file besides
  tools/config.py allowed to hold it, because JSON cannot read the constant;
  test_plugin_manifest keeps the two equal. tests/unit/test_skeleton.py's
  absence scan must allow exactly that one file (an /implement change, with the
  CLAUDE.md rule and a decision record).
"""

import importlib
import inspect
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.config import PACK_NAME, VERSION  # noqa: E402

MANIFEST = REPO_ROOT / "plugin" / ".claude-plugin" / "plugin.json"
SKILLS = ("oracle-dba", "offline-analysis")
ZIP_NAME = f"{PACK_NAME}-{VERSION}.zip"
TOP_LEVEL = ("plugin/", "tools/", "db/")

# A tree with what the zip holds and what it must not.
KEEP = {
    "README.md": "# readme\n",
    "LICENSE": "Apache License\n",
    "plugin/.claude-plugin/plugin.json": '{"name": "x", "version": "0.0.1"}\n',
    "plugin/skills/demo/SKILL.md": "---\nname: demo\ndescription: d\n---\nbody\n",
    "plugin/checks/storage/demo.sql": "select 1 from dual\n",
    "plugin/config/cursor.json": "{}\n",
    "tools/__init__.py": "",
    "tools/commands/demo.py": "X = 1\n",
    "db/tiers/read-only.sql": "-- grants\n",
}
DROP_NON_PACKAGE = {
    "tools/__pycache__/config.cpython-313.pyc": "",
    "plugin/skills/__pycache__/x.pyc": "",
    "tests/unit/test_x.py": "",
    "spike/spike.py": "",
    ".git/HEAD": "ref: refs/heads/main\n",
    ".venv/bin/activate": "",
    ".github/workflows/ci.yml": "",
    "docs/decisions/D-X.md": "",
    "pyproject.toml": "",
    "CLAUDE.md": "",
    "pending.md": "",
    "dist/old.zip": "",
}
DROP_CREDENTIALS = {
    "plugin/wallet/cwallet.sso": "x",
    "plugin/wallet/ewallet.p12": "x",
    "tools/keystore.jks": "x",
    "db/tiers/cwallet.sso.lck": "x",
    "db/tnsnames.ora": "ERP = (DESCRIPTION=...)\n",
    "plugin/.env": "ORACLE_PASSWORD=secret\n",
    "tools/.env": "X=1\n",
    # SQLcl connection store: <home>/connections/<name>/{dbtools.properties,cwallet.sso}
    "plugin/homes/read-only/connections/erp/dbtools.properties": "name=erp\nuserName=ro\n",
    "plugin/homes/read-only/connections/erp/cwallet.sso": "x",
    "tools/.dbtools/connections/erp/dbtools.properties": "name=erp\n",
}
CREDENTIAL_NAME = re.compile(
    r"(?i)(\.sso|\.p12|\.jks)$|(^|/)cwallet[^/]*$|(^|/)tnsnames\.ora$|(^|/)\.env$"
    r"|(^|/)dbtools\.properties$|(^|/)\.dbtools/|(^|/)connections/"
)


def _package():
    return importlib.import_module("tools.package")


def _seed(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "src"
    _seed(root, {**KEEP, **DROP_NON_PACKAGE, **DROP_CREDENTIALS})
    return root


def _relative(paths, root: Path) -> set[str]:
    return {(Path(p).relative_to(root) if Path(p).is_absolute() else Path(p)).as_posix()
            for p in paths}


def _names(zip_path: Path) -> list[str]:
    with zipfile.ZipFile(zip_path) as zf:
        return zf.namelist()


def _env():
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    return env


def _run_tools(cwd: Path, *args):
    return subprocess.run(
        [sys.executable, "-m", "tools", *args],
        cwd=cwd, env=_env(), stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=120, check=False,
    )


def _copy_repo(dest: Path) -> Path:
    """Copy what the package holds into `dest`, a tree the command can run from."""
    ignore = shutil.ignore_patterns("__pycache__")
    for name in ("tools", "plugin", "db"):
        shutil.copytree(REPO_ROOT / name, dest / name, ignore=ignore)
    for name in ("README.md", "LICENSE"):
        shutil.copy2(REPO_ROOT / name, dest / name)
    return dest


# --- manifest ----------------------------------------------------------------


def test_plugin_manifest_matches_config_and_lists_both_skills():
    """AC: plugin/.claude-plugin/plugin.json is a valid manifest whose `name` is
    PACK_NAME and `version` is VERSION, so a rename in one place fails. The skills
    `oracle-dba` and `offline-analysis` are in the default skills folder, each
    SKILL.md named after its folder, and the manifest does not point skills
    elsewhere. (Listing them in a live Claude Code session is the manual check
    recorded in the PR body.)"""
    import json

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["name"] == PACK_NAME
    assert manifest["version"] == VERSION
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", manifest["name"])
    assert re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"])
    assert isinstance(manifest.get("description"), str) and manifest["description"].strip()
    if "skills" in manifest:
        assert (MANIFEST.parent.parent / manifest["skills"]).resolve() == \
            (REPO_ROOT / "plugin" / "skills").resolve()
    for skill in SKILLS:
        text = (REPO_ROOT / "plugin" / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
        meta = yaml.safe_load(text.split("---")[1])
        assert meta["name"] == skill


# --- collect / build_zip -----------------------------------------------------


def test_collect_takes_plugin_tools_db_and_readme_only(tree):
    """AC: the package holds plugin/, tools/, db/, README.md and LICENSE (DBA-47)
    and nothing else;
    __pycache__, tests/, spike/, .git, .venv, .github, docs/decisions/ are left
    out, and so is every credential file."""
    collected = _relative(_package().collect(tree), tree)
    assert collected == set(KEEP)


def test_build_zip_leaves_out_credentials(tree, tmp_path):
    """AC: a package built from a tree seeded with *.sso, *.p12, *.jks, cwallet*,
    tnsnames.ora, .env and SQLcl connection store files contains none of them;
    the build succeeds."""
    out = tmp_path / "out" / ZIP_NAME
    out.parent.mkdir()
    _package().build_zip(tree, out)
    names = _names(out)
    assert set(names) == set(KEEP)
    assert [n for n in names if CREDENTIAL_NAME.search(n)] == []


def test_build_zip_is_byte_identical_across_runs_and_mtimes(tree, tmp_path):
    """AC: two builds of the same tree are byte-identical (fixed entry order and
    timestamps), even when file modification times differ between the builds."""
    first, second = tmp_path / "a.zip", tmp_path / "b.zip"
    _package().build_zip(tree, first)
    for i, rel in enumerate(sorted(KEEP)):
        os.utime(tree / rel, (1_000_000_000 + i * 7919, 1_000_000_000 + i * 7919))
    _package().build_zip(tree, second)
    assert first.read_bytes() == second.read_bytes()
    assert _names(first) == sorted(_names(first))


# --- package command ---------------------------------------------------------


def test_package_command_writes_the_versioned_zip_from_the_repo(tmp_path):
    """AC: `python -m tools package --out-dir DIR` on this repo writes
    DIR/<PACK_NAME>-<VERSION>.zip holding plugin/, tools/, db/, README.md and LICENSE,
    including the manifest, the snippets and every tool command; twice gives the
    same bytes."""
    first, second = tmp_path / "one", tmp_path / "two"
    for out in (first, second):
        result = _run_tools(REPO_ROOT, "package", "--out-dir", str(out))
        assert result.returncode == 0, result.stdout + result.stderr
    assert sorted(p.name for p in first.iterdir()) == [ZIP_NAME]
    names = _names(first / ZIP_NAME)
    assert all(n in ("README.md", "LICENSE") or n.startswith(TOP_LEVEL) for n in names), names
    assert not [n for n in names if "__pycache__" in n or n.endswith(".pyc")]
    for required in ("README.md", "LICENSE", "plugin/.claude-plugin/plugin.json",
                     "plugin/config/codex.toml", "plugin/checks/INDEX.md",
                     "plugin/skills/oracle-dba/SKILL.md", "plugin/skills/offline-analysis/SKILL.md",
                     "tools/__main__.py", "tools/commands/package.py", "tools/commands/config.py",
                     "tools/commands/support_bundle.py", "db/tiers/read-only.sql"):
        assert required in names, required
    assert (first / ZIP_NAME).read_bytes() == (second / ZIP_NAME).read_bytes()


@pytest.mark.parametrize("breakage", ["lint", "index"])
def test_package_refuses_when_lint_or_index_check_fails(tmp_path, breakage):
    """AC: `package` runs `lint` and `index --check` first and exits 1 without
    writing a zip when either fails (D-DBA-7: no package with a stale index)."""
    root = _copy_repo(tmp_path / "copy")
    if breakage == "lint":
        # Header is valid, body is not (L009): the index regenerates cleanly.
        shutil.copy2(REPO_ROOT / "tests/fixtures/checks/L009-semicolon/storage/l009_semicolon.sql",
                     root / "plugin/checks/storage/l009_semicolon.sql")
        assert _run_tools(root, "index").returncode == 0
        assert _run_tools(root, "index", "--check").returncode == 0, "precondition"
        assert _run_tools(root, "lint").returncode == 1, "precondition"
    else:
        with open(root / "plugin/checks/INDEX.md", "a", encoding="utf-8", newline="\n") as f:
            f.write("\nstale line\n")
        assert _run_tools(root, "lint").returncode == 0, "precondition"
        assert _run_tools(root, "index", "--check").returncode == 1, "precondition"

    out = tmp_path / "out"
    result = _run_tools(root, "package", "--out-dir", str(out))
    assert result.returncode == 1, result.stdout + result.stderr
    assert not out.exists() or not any(out.iterdir())


# --- contract test -----------------------------------------------------------


def test_contract_output_for_dependents():
    """Contract (DBA-18 Output for dependents; no story consumes it yet, the
    release epic will): `tools.package` exports `collect(root)` and
    `build_zip(root, out)`; `package` and `config` are commands meeting the
    tools/commands contract, `package` taking `--out-dir` (default `dist`) and
    `config` taking `--client` and `--sqlcl-bin`; plugin/config/ holds the six
    snippets. Shape only."""
    package = _package()
    assert list(inspect.signature(package.collect).parameters) == ["root"]
    assert list(inspect.signature(package.build_zip).parameters)[:2] == ["root", "out"]

    import argparse

    for module_name, command in (("package", "package"), ("config", "config")):
        module = importlib.import_module(f"tools.commands.{module_name}")
        assert module.NAME == command
        assert isinstance(module.HELP, str) and module.HELP
        assert callable(module.run)
        parser = argparse.ArgumentParser()
        module.add_arguments(parser)
        options = {o for a in parser._actions for o in a.option_strings}
        if command == "package":
            assert "--out-dir" in options
            assert Path(parser.parse_args([]).out_dir) == Path("dist")
        else:
            assert {"--client", "--sqlcl-bin"} <= options

    config_dir = REPO_ROOT / "plugin" / "config"
    for name in ("claude-code.md", "claude-desktop.json", "cursor.json",
                 "vscode-copilot.json", "cline.json", "codex.toml"):
        assert (config_dir / name).is_file(), name

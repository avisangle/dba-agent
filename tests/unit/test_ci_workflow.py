"""DBA-8: GitHub Actions CI (`.github/workflows/ci.yml`) and `.github/scripts/install-sqlcl.sh`.

No database, network or GitHub API is touched. The workflow is parsed with
pyyaml. The install script runs against fake `curl`/`wget` shims placed first
on PATH; they log the URL and hand back a locally built zip laid out like the
real SQLcl download (`sqlcl/bin/sql`), so a skipped checksum is observable.

External facts the assertions rely on (verified, not guessed):
- `tests/docker-compose.yml` (DBA-4) holds the image reference
  `gvenzl/oracle-free:...` and reads `ORACLE_TEST_PASSWORD`.
- `tests/integration/conftest.py` (DBA-4) reads `SQLCL_BIN` and fails instead
  of skipping when `REQUIRE_INTEGRATION == "1"` (string compare).
- `python -m tools lint` exists (DBA-3).
- SQLcl downloads are served from `download.oracle.com`.

pyyaml reads the bare key `on:` as boolean True, so triggers are looked up
under both. Matrix key names are not pinned; the tests look for a matrix list
with the required values.
"""

import os
import re
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
INSTALL_SCRIPT = REPO_ROOT / ".github" / "scripts" / "install-sqlcl.sh"

UNIT_SYSTEMS = {"ubuntu-latest", "macos-latest", "windows-latest"}
UNIT_PYTHONS = {"3.10", "3.13"}
JAVA_VERSIONS = {"17", "21"}
SQLCL_VERSIONS = {"25.3.2", "latest"}
# D-DBA-8-minimum-sqlcl-25-3-2: the oldest supported build, pinned with its hash.
PINNED_ZIP = "sqlcl-25.3.2.317.1117.zip"
PINNED_SHA256 = "0af1ecb1da1a840d800cfe88fe20a35aeb9ceac9ff38729be0025b937b101d7e"
SHA_PINNED = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}$")
SHA256_LITERAL = re.compile(r"\b[0-9a-fA-F]{64}\b")

posix_only = pytest.mark.skipif(
    sys.platform == "win32", reason="install-sqlcl.sh is a bash script run on Linux runners"
)


# --- helpers -----------------------------------------------------------------


def _workflow():
    assert WORKFLOW.is_file(), f"{WORKFLOW.relative_to(REPO_ROOT)} missing"
    data = yaml.safe_load(WORKFLOW.read_text())
    assert isinstance(data, dict)
    return data


def _triggers(wf):
    on = wf.get("on", wf.get(True))
    if isinstance(on, str):
        on = {on: None}
    elif isinstance(on, list):
        on = dict.fromkeys(on)
    assert isinstance(on, dict), f"unexpected `on:` shape: {on!r}"
    return on


def _job(wf, name):
    jobs = wf.get("jobs") or {}
    assert name in jobs, f"job {name!r} missing; have {sorted(jobs)}"
    return jobs[name]


def _matrix_lists(job):
    """Every list value in the job's strategy.matrix, as sets of strings."""
    matrix = (job.get("strategy") or {}).get("matrix") or {}
    return {k: v for k, v in matrix.items() if isinstance(v, list)}


def _matrix_key_with(job, wanted):
    for key, values in _matrix_lists(job).items():
        if {str(v) for v in values} == wanted:
            return key, values
    raise AssertionError(f"no matrix list equal to {sorted(wanted)}: {_matrix_lists(job)}")


def _runs(job):
    return [s.get("run", "") for s in job.get("steps", []) if isinstance(s, dict)]


def _step_running(job, needle):
    for step in job.get("steps", []):
        if needle in (step.get("run") or ""):
            return step
    raise AssertionError(f"no step runs {needle!r}; runs: {_runs(job)}")


def _uses(wf):
    out = []
    for job in (wf.get("jobs") or {}).values():
        if "uses" in job:  # reusable workflow call
            out.append(job["uses"])
        for step in job.get("steps", []):
            if "uses" in step:
                out.append(step["uses"])
    return out


SHIM = '''#!{python}
"""Fake {tool}: log the call, write the prepared zip where the real tool would."""
import os, re, sys
from pathlib import Path
from urllib.parse import urlparse

tool, args = "{tool}", sys.argv[1:]
with open(os.environ["FAKE_DOWNLOAD_LOG"], "a") as log:
    log.write(tool + " " + " ".join(args) + "\\n")
urls = [a for a in args if a.startswith(("http://", "https://"))]
remote = Path(urlparse(urls[-1]).path).name if urls else "download.zip"
out, i = None, 0
while i < len(args):
    a = args[i]
    nxt = args[i + 1] if i + 1 < len(args) else None
    if tool == "curl":
        if a in ("-o", "--output") or re.match(r"^-[A-Za-z]*o$", a):
            out, i = nxt, i + 1
        elif a.startswith("--output="):
            out = a.split("=", 1)[1]
        elif a in ("-O", "--remote-name") or re.match(r"^-[A-Za-z]*O[A-Za-z]*$", a):
            out = remote
    else:
        if a in ("-O", "--output-document") or re.match(r"^-[A-Za-z]*O$", a):
            out, i = nxt, i + 1
        elif a.startswith("--output-document="):
            out = a.split("=", 1)[1]
    i += 1
if out is None:
    out = "-" if tool == "curl" else remote
data = Path(os.environ["FAKE_SQLCL_ZIP"]).read_bytes()
if out == "-":
    sys.stdout.buffer.write(data)
else:
    Path(out).write_bytes(data)
'''


def _run_install(tmp_path, *args):
    """Run install-sqlcl.sh with fake downloaders; return (result, env_file, log, sandbox)."""
    assert INSTALL_SCRIPT.is_file(), f"{INSTALL_SCRIPT.relative_to(REPO_ROOT)} missing"
    sandbox = tmp_path / "sandbox"
    shims = tmp_path / "shims"
    for d in (sandbox, shims, sandbox / "home", sandbox / "runner-temp", sandbox / "cwd"):
        d.mkdir(parents=True, exist_ok=True)

    fake_zip = tmp_path / "sqlcl-fake.zip"
    with zipfile.ZipFile(fake_zip, "w") as zf:
        info = zipfile.ZipInfo("sqlcl/bin/sql")
        info.external_attr = (stat.S_IFREG | 0o755) << 16
        zf.writestr(info, "#!/bin/sh\necho fake sqlcl\n")
        zf.writestr("sqlcl/lib/README", "fake\n")

    for tool in ("curl", "wget"):
        shim = shims / tool
        shim.write_text(SHIM.format(python=sys.executable, tool=tool))
        shim.chmod(0o755)

    env_file = sandbox / "github_env"
    env_file.touch()
    log = sandbox / "downloads.log"
    log.touch()
    env = dict(os.environ)
    env.update(
        PATH=f"{shims}{os.pathsep}{env['PATH']}",
        HOME=str(sandbox / "home"),
        RUNNER_TEMP=str(sandbox / "runner-temp"),
        GITHUB_ENV=str(env_file),
        FAKE_SQLCL_ZIP=str(fake_zip),
        FAKE_DOWNLOAD_LOG=str(log),
    )
    env.pop("SQLCL_BIN", None)
    result = subprocess.run(
        ["bash", str(INSTALL_SCRIPT), *args],
        cwd=sandbox / "cwd",
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return result, env_file, log, sandbox


def _exported_sqlcl_bin(env_file):
    lines = [ln for ln in env_file.read_text().splitlines() if ln.startswith("SQLCL_BIN=")]
    return lines[-1].split("=", 1)[1] if lines else None


# --- behavioural tests -------------------------------------------------------


def test_triggers_permissions_and_actions_pinned_by_sha():
    """AC: runs on pull requests and on pushes to main; permissions are
    `contents: read`; every action is pinned by a 40-char commit SHA."""
    wf = _workflow()
    on = _triggers(wf)
    assert "pull_request" in on
    push = on.get("push") or {}
    assert "main" in (push.get("branches") or []), f"push must target main: {push!r}"

    assert wf.get("permissions") == {"contents": "read"}, wf.get("permissions")
    for name, job in wf["jobs"].items():
        perms = job.get("permissions")
        assert perms in (None, {"contents": "read"}), f"job {name} widens permissions: {perms}"

    uses = _uses(wf)
    assert uses, "workflow uses no actions (checkout, setup-python, setup-java expected)"
    unpinned = [u for u in uses if not u.startswith("./") and not SHA_PINNED.match(u)]
    assert unpinned == []


def test_lint_and_unit_jobs():
    """AC: `lint` runs `ruff check .` and `python -m tools lint`; `unit` runs
    `pytest tests/unit` on ubuntu, macos and windows with Python 3.10 and 3.13.
    Edge: Python versions must be strings, since YAML reads 3.10 as 3.1."""
    wf = _workflow()

    lint_runs = "\n".join(_runs(_job(wf, "lint")))
    assert "ruff check ." in lint_runs
    assert "python -m tools lint" in lint_runs

    unit = _job(wf, "unit")
    os_key, _ = _matrix_key_with(unit, UNIT_SYSTEMS)
    py_key, py_values = _matrix_key_with(unit, UNIT_PYTHONS)
    assert all(isinstance(v, str) for v in py_values), f"quote Python versions: {py_values}"
    assert f"matrix.{os_key}" in str(unit.get("runs-on")), unit.get("runs-on")
    assert any(f"matrix.{py_key}" in str(s.get("with", {})) for s in unit["steps"]), (
        "no step passes the Python version from the matrix"
    )
    assert any("pytest tests/unit" in r for r in _runs(unit))


def test_integration_job_matrix_and_steps():
    """AC: `integration` on ubuntu-latest, matrix Java 17/21 by exactly SQLcl
    25.3.2 and latest (25.2 or a third entry fails); installs SQLcl via
    install-sqlcl.sh <matrix version>; starts the DB with
    `docker compose -f tests/docker-compose.yml up -d --wait`; runs
    `pytest -m integration` with REQUIRE_INTEGRATION set to the string "1"."""
    wf = _workflow()
    job = _job(wf, "integration")
    assert job.get("runs-on") == "ubuntu-latest"

    java_key, _ = _matrix_key_with(job, JAVA_VERSIONS)
    sqlcl_key, sqlcl_values = _matrix_key_with(job, SQLCL_VERSIONS)
    assert all(isinstance(v, str) for v in sqlcl_values), f"quote SQLcl versions: {sqlcl_values}"

    assert any(
        "setup-java" in s.get("uses", "") and f"matrix.{java_key}" in str(s.get("with", {}))
        for s in job["steps"]
    ), "no actions/setup-java step taking the matrix Java version"
    install = _step_running(job, ".github/scripts/install-sqlcl.sh")
    assert f"matrix.{sqlcl_key}" in install["run"], install["run"]
    _step_running(job, "docker compose -f tests/docker-compose.yml up -d --wait")

    pytest_step = _step_running(job, "pytest -m integration")
    require = (pytest_step.get("env") or {}).get(
        "REQUIRE_INTEGRATION", (job.get("env") or {}).get("REQUIRE_INTEGRATION")
    )
    assert require == "1", f"REQUIRE_INTEGRATION must be the string '1', got {require!r}"


def test_no_image_reference_and_password_generated_per_run():
    """AC: the image lives only in tests/docker-compose.yml (absence scan for
    `oracle-free`); ORACLE_TEST_PASSWORD is generated in the run, not a secret
    or a committed literal."""
    assert WORKFLOW.is_file(), "workflow missing"
    text = WORKFLOW.read_text()
    assert "oracle-free" not in text.lower()
    assert "oracle-free" in (REPO_ROOT / "tests" / "docker-compose.yml").read_text()

    wf = _workflow()
    pw_lines = [ln for ln in text.splitlines() if "ORACLE_TEST_PASSWORD" in ln]
    assert pw_lines, "workflow never sets ORACLE_TEST_PASSWORD"
    assert not [ln for ln in pw_lines if "secrets." in ln], pw_lines

    def env_maps():
        yield wf.get("env") or {}
        for job in wf["jobs"].values():
            yield job.get("env") or {}
            for step in job.get("steps", []):
                yield step.get("env") or {}

    literals = [
        m["ORACLE_TEST_PASSWORD"]
        for m in env_maps()
        if "ORACLE_TEST_PASSWORD" in m and "${{" not in str(m["ORACLE_TEST_PASSWORD"])
    ]
    assert literals == [], "ORACLE_TEST_PASSWORD is a committed literal"

    generating = [
        r
        for r in _runs(_job(wf, "integration"))
        if "ORACLE_TEST_PASSWORD" in r and "GITHUB_ENV" in r
    ]
    assert generating, "no integration step generates ORACLE_TEST_PASSWORD into $GITHUB_ENV"


@posix_only
def test_install_sqlcl_latest_downloads_unpacks_and_exports_sqlcl_bin(tmp_path):
    """AC: `install-sqlcl.sh latest` downloads from Oracle's public site (no
    recorded hash needed), unpacks, and exports SQLCL_BIN via $GITHUB_ENV to a
    runnable `sql` inside the runner's own space (not a system path)."""
    result, env_file, log, sandbox = _run_install(tmp_path, "latest")
    assert result.returncode == 0, result.stdout + result.stderr

    calls = log.read_text().splitlines()
    assert calls, "script downloaded nothing (or bypassed curl/wget on PATH)"
    hosts = {urlparse(u).hostname for c in calls for u in re.findall(r"https?://\S+", c)}
    assert hosts == {"download.oracle.com"}, hosts

    sqlcl_bin = _exported_sqlcl_bin(env_file)
    assert sqlcl_bin, f"SQLCL_BIN not written to $GITHUB_ENV: {env_file.read_text()!r}"
    path = Path(sqlcl_bin)
    assert path.is_absolute() and path.is_file(), sqlcl_bin
    assert path.name == "sql"
    assert os.access(path, os.X_OK)
    assert path.resolve().is_relative_to(sandbox.resolve()), f"installed outside runner: {path}"


@posix_only
def test_install_sqlcl_rejects_checksum_mismatch_and_missing_version(tmp_path):
    """AC2/AC3: the script records exactly one SHA-256, the 25.3.2 zip's, and
    verifies it: `install-sqlcl.sh 25.3.2` requests sqlcl-25.3.2.317.1117.zip
    from download.oracle.com, and a zip that does not match fails and exports
    nothing. Running with no version fails before downloading anything."""
    recorded = set(SHA256_LITERAL.findall(INSTALL_SCRIPT.read_text()))
    assert recorded == {PINNED_SHA256}, f"recorded SHA-256 literals: {sorted(recorded)}"

    result, env_file, log, _ = _run_install(tmp_path / "mismatch", "25.3.2")
    assert result.returncode != 0, "a zip with the wrong SHA-256 was accepted"
    urls = [urlparse(u) for u in re.findall(r"https?://\S+", log.read_text())]
    requested = {(u.hostname, Path(u.path).name) for u in urls}
    assert ("download.oracle.com", PINNED_ZIP) in requested, f"requested: {sorted(requested)}"
    assert _exported_sqlcl_bin(env_file) is None

    result, env_file, log, _ = _run_install(tmp_path / "noarg")
    assert result.returncode != 0
    assert (result.stderr + result.stdout).strip(), "missing version must explain itself"
    assert log.read_text() == "", "downloaded without a version argument"
    assert _exported_sqlcl_bin(env_file) is None


@posix_only
def test_install_sqlcl_rejects_25_2_without_downloading(tmp_path):
    """AC4: 25.2 is below the supported minimum and no longer a pinned case:
    `install-sqlcl.sh 25.2` exits non-zero, downloads nothing, exports nothing."""
    result, env_file, log, _ = _run_install(tmp_path, "25.2")
    assert result.returncode != 0, "25.2 is still accepted"
    assert log.read_text() == "", f"25.2 was downloaded: {log.read_text()!r}"
    assert _exported_sqlcl_bin(env_file) is None


@posix_only
def test_install_sqlcl_usage_names_supported_versions(tmp_path):
    """AC5: with no argument the script exits non-zero without downloading, and
    its usage text names 25.3.2 and latest and not 25.2."""
    result, _, log, _ = _run_install(tmp_path)
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert log.read_text() == "", "downloaded without a version argument"
    assert "25.3.2" in output and "latest" in output, output
    assert "25.2" not in output, output


def test_readme_states_minimum_sqlcl_25_3_2():
    """AC6: README states the minimum as SQLcl 25.3.2 and no longer says 25.2+."""
    readme = (REPO_ROOT / "README.md").read_text()
    assert "SQLcl 25.3.2" in readme
    assert "25.2+" not in readme


# --- contract test -----------------------------------------------------------


def test_contract_for_dependents_ci_on_every_pr_and_install_script():
    """Contract (output_for_dependents; no named consumer): CI runs on every
    pull request, unfiltered; `.github/scripts/install-sqlcl.sh` exists as an
    executable bash script taking one version argument. Shape only."""
    on = _triggers(_workflow())
    pr = on["pull_request"] or {}
    for narrowing in ("branches", "branches-ignore", "paths", "paths-ignore"):
        assert narrowing not in pr, f"pull_request trigger narrowed by {narrowing}"
    assert {"lint", "unit", "integration"} <= set(_workflow()["jobs"])

    assert INSTALL_SCRIPT.is_file()
    assert INSTALL_SCRIPT.read_text().splitlines()[0] in (
        "#!/usr/bin/env bash",
        "#!/bin/bash",
    )
    rel = INSTALL_SCRIPT.relative_to(REPO_ROOT).as_posix()
    staged = subprocess.run(
        ["git", "ls-files", "-s", "--", rel],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    if staged:
        assert staged[0] == "100755", f"{rel} tracked without the executable bit"
    elif sys.platform != "win32":
        assert os.access(INSTALL_SCRIPT, os.X_OK), f"{rel} not executable"
    if shutil.which("bash") and sys.platform != "win32":
        syntax = subprocess.run(
            ["bash", "-n", str(INSTALL_SCRIPT)], capture_output=True, text=True, check=False
        )
        assert syntax.returncode == 0, syntax.stderr

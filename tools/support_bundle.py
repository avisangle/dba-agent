"""The files of a support bundle: doctor's results, version lines and check
counts, with every string redacted by `tools.redact.redact`. Nothing here opens
a SQLcl home or starts SQLcl's MCP server: doctor does that with the tier."""

import json
import platform
from dataclasses import asdict

from tools.checks import CHECKS_ROOT, user_checks_root
from tools.checks.header import CheckFormatError
from tools.checks.resolve import resolve_checks
from tools.config import PACK_NAME, VERSION
from tools.doctor.checks import _first_line, run_all
from tools.doctor.env import Env, java_bin, sqlcl_bin
from tools.redact import collect, redact
from tools.tiers import Tier

README = f"""\
Support bundle written by `python -m tools support-bundle` ({PACK_NAME} {VERSION}).

doctor.json    doctor's results, one {{check, status, detail, fix}} entry per check
versions.json  pack, Python and OS versions, and the SQLcl and Java version lines
checks.json    counts of built-in, overridden and added checks, and the ids of
               your own checks (never their SQL)
README.txt     this file

Before anything was written, these were replaced in every file:
  connect strings and TNS descriptors     <connect-string>
  IPv4 and IPv6 addresses                 <ip>
  host names, including this machine's    <host>
  saved connection names                  <connection-N>
  database user, database and service names
                                          <db-user-N>, <db-name-N>, <service-N>
  your home folder and OS user name       <home>, <os-user>
The same name gets the same number in every file.

Nothing was read from SQLcl's home folders: no saved connection, password or
wallet is in this bundle. Redaction works from patterns and the names doctor
reported, so it cannot know every identifier. Read each file before attaching
the bundle to an issue.
"""


class _Recorded:
    """`env` with `run` answered once per command, so the version lines reuse
    the `sql -V` and `java -version` doctor already ran."""

    def __init__(self, env: Env):
        self._env, self._runs = env, {}

    def run(self, cmd: list[str]) -> tuple[int, str, str]:
        key = tuple(map(str, cmd))
        if key not in self._runs:
            self._runs[key] = self._env.run(cmd)
        return self._runs[key]

    def __getattr__(self, name):
        return getattr(self._env, name)


def _version_line(env: Env, cmd: list[str]) -> str:
    code, out, err = env.run(cmd)
    return _first_line(out) or _first_line(err) or f"exit {code}"


def _checks() -> dict:
    try:
        resolved = resolve_checks(CHECKS_ROOT, user_checks_root())
    except CheckFormatError as exc:
        return {"error": str(exc)}
    user = sorted(i for i, r in resolved.items() if r.source == "user")
    builtin = sum(1 for _ in CHECKS_ROOT.rglob("*.sql"))  # one id per file (L014)
    added = len(resolved) - builtin
    return {"builtin": builtin, "overridden": len(user) - added, "added": added,
            "user_check_ids": user}


def _connections(results: list[dict]) -> list[str]:
    """Saved connection names, from the `<check>:<name>` results doctor gives each."""
    names = []
    for r in results:
        _, sep, name = r["check"].partition(":")
        if sep:
            names.append(name)
    return names


def _redacted(value, known):
    """Every string in `value` redacted. Strings are redacted before JSON encoding,
    which would double the backslashes of a Windows path and hide it from `redact`."""
    if isinstance(value, str):
        return redact(value, known)
    if isinstance(value, dict):
        return {k: _redacted(v, known) for k, v in value.items()}
    if isinstance(value, list):
        return [_redacted(v, known) for v in value]
    return value


def build(env: Env, tier: Tier) -> dict[str, str]:
    """File name -> redacted text, for every file of the bundle."""
    env = _Recorded(env)
    results = [asdict(r) for r in run_all(env, tier)]
    versions = {
        "pack": f"{PACK_NAME} {VERSION}",
        "python": platform.python_version(),
        "os": f"{platform.system()} {platform.release()}",
        "sqlcl": _version_line(env, [sqlcl_bin(), "-V"]),
        "java": _version_line(env, [java_bin(), "-version"]),
    }
    doctor_text = "\n".join(v for r in results for v in r.values())
    known = collect(doctor_text, connections=_connections(results), db_users=[tier.db_user])
    data = {"doctor.json": results, "versions.json": versions, "checks.json": _checks()}
    files = {name: json.dumps(_redacted(v, known), indent=2) + "\n" for name, v in data.items()}
    files["README.txt"] = redact(README, known)
    return files

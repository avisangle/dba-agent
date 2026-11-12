"""The files of a support bundle: doctor's results, version lines and check
counts, with every string redacted by `tools.redact.redact`. Nothing here opens
a SQLcl home or starts SQLcl's MCP server: doctor does that with the tier."""

import json
import platform
from dataclasses import asdict

from tools.checks import CHECKS_ROOT, user_checks_root
from tools.checks.header import CheckFormatError
from tools.checks.index import discover
from tools.checks.resolve import resolve_checks
from tools.config import PACK_NAME, VERSION
from tools.doctor.checks import PASS, _java, run_all
from tools.doctor.env import Env, sqlcl_bin
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


def _first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def _version_line(env: Env, cmd: list[str], stderr_first=False) -> str:
    code, out, err = env.run(cmd)
    return _first_line(f"{err}\n{out}" if stderr_first else f"{out}\n{err}") or f"exit {code}"


def _checks() -> dict:
    try:
        builtin = {c.id for c in discover(CHECKS_ROOT)}
        resolved = resolve_checks(CHECKS_ROOT, user_checks_root())
    except CheckFormatError as exc:
        return {"error": str(exc)}
    user = sorted(i for i, r in resolved.items() if r.source == "user")
    overridden = len(builtin.intersection(user))
    return {"builtin": len(builtin), "overridden": overridden,
            "added": len(user) - overridden, "user_check_ids": user}


def _connections(results: list[dict]) -> list[str]:
    """Saved connection names: the `connections` list, then `<check>:<name>` suffixes."""
    names = []
    for r in results:
        if r["check"] == "connections" and r["status"] == PASS:
            names += r["detail"].split(", ")
        names += [r["check"].partition(":")[2]] if ":" in r["check"] else []
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
    results = [asdict(r) for r in run_all(env, tier)]
    versions = {
        "pack": f"{PACK_NAME} {VERSION}",
        "python": platform.python_version(),
        "os": f"{platform.system()} {platform.release()}",
        "sqlcl": _version_line(env, [sqlcl_bin(), "-V"]),
        "java": _version_line(env, [_java(), "-version"], stderr_first=True),
    }
    doctor_text = "\n".join(v for r in results for v in r.values())
    known = collect(doctor_text, connections=_connections(results), db_users=[tier.db_user])
    data = {"doctor.json": results, "versions.json": versions, "checks.json": _checks()}
    files = {name: json.dumps(_redacted(v, known), indent=2) + "\n" for name, v in data.items()}
    files["README.txt"] = redact(README, known)
    return files

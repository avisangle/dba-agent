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
from tools.doctor.checks import first_line, java_bin, run_all
from tools.doctor.env import Env
from tools.redact import collect, redact
from tools.sqlcl import sqlcl_bin
from tools.tiers import Tier

README = f"""\
Support bundle written by `python -m tools support-bundle` ({PACK_NAME} {VERSION}).

doctor.json    doctor's results, one {{check, status, detail, fix}} entry per check
versions.json  pack, Python and OS versions, and the SQLcl and Java version lines
checks.json    counts of built-in, overridden and added checks, and the ids of
               your own checks (never their SQL)
README.txt     this file

Before anything was written, these were replaced in every file:
  connect strings and TNS descriptors      <connect-string>
  IPv4 and IPv6 addresses                  <ip>
  host names, including this machine's     <host>
  every absolute file path, whole          <path>
  your home folder standing alone          <home>
  your OS user name                        <os-user>
  saved connection names                   <connection-N>
  database user, database and service names, and the database
  of each Autonomous Database wallet (Wallet_<NAME>)
                                           <db-user-N>, <db-name-N>, <service-N>
The same name gets the same number in every file. Text shaped like an
address is replaced unless it reads as a version, so a bare version number
such as doctor's SQLcl version may show as <ip>.

Nothing was read from the SQLcl home folder of any tier: no saved connection,
password or wallet is in this bundle. Redaction works from the shape of the
text and the names doctor reported, so it cannot know every identifier. A
relative path that names a database or host, and is not a Wallet_ name, is
not redacted. Read each file before attaching the bundle to an issue.
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
    return first_line(out) or first_line(err) or f"exit {code}"


def _checks() -> dict:
    """Check counts as `index --user` prints them, and the user check ids."""
    try:
        resolved = resolve_checks(CHECKS_ROOT, user_checks_root())
    except CheckFormatError as exc:
        return {"error": str(exc)}
    builtin = {p.stem for p in CHECKS_ROOT.rglob("*.sql")}  # file name is the id (L003)
    user = sorted(i for i, r in resolved.items() if r.source == "user")
    overridden = len(builtin.intersection(user))
    return {"builtin": len(builtin) - overridden, "overridden": overridden,
            "added": len(user) - overridden, "user_ids": user}


def _map_strings(value, fn):
    """`value` with `fn` applied to every string in it (dict keys stay)."""
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, dict):
        return {k: _map_strings(v, fn) for k, v in value.items()}
    if isinstance(value, list):
        return [_map_strings(v, fn) for v in value]
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
    data = {"doctor.json": results, "versions.json": versions, "checks.json": _checks()}
    # Per-connection checks are named `<check>:<connection>`.
    connections = [r["check"].partition(":")[2] for r in results if ":" in r["check"]]
    texts = []
    _map_strings(data, lambda s: texts.append(s) or s)
    known = collect("\n".join(texts), connections=connections, db_users=[tier.db_user])
    # Each string is redacted before JSON encoding, which would double a Windows
    # path's backslashes and hide it from `redact`.
    files = {name: json.dumps(_map_strings(v, lambda s: redact(s, known)), indent=2) + "\n"
             for name, v in data.items()}
    files["README.txt"] = redact(README, known)
    return files

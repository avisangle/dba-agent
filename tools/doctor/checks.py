"""Doctor's checks, in the order they run. `run_all` runs them and marks a check
SKIP, with the reason, when a check it depends on failed."""

import contextlib
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from tools.doctor.env import Env
from tools.mcp_client import McpError, McpTimeout
from tools.sqlcl import _RENAMED, mcp_argv, sqlcl_bin
from tools.tiers import Tier

PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"
# Oldest supported build (D-DBA-8-minimum-sqlcl-25-3-2).
SQLCL_MIN = (25, 3, 2)
SQLCL_MIN_TEXT = ".".join(map(str, SQLCL_MIN))
MCP_TOOLS = ("list-connections", "connect", "run-sql", "disconnect")
PER_CONNECTION = ("connect", "db-version", "grants", "excess-privileges", "restrict-level")
# Refused at restrict level 3 and above. The file need not exist; `host` is sent
# only after `@` was refused, so doctor never runs it on an under-restricted server.
PROBES = ("@doctor_probe.sql", "host echo doctor-probe")
REFUSED = "SP2-0738"


@dataclass(frozen=True)
class Result:
    check: str
    status: str
    detail: str
    fix: str = ""


def _first_line(text: str) -> str:
    return text.strip().partition("\n")[0].strip()


def _numbers(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", version))


def _search(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1) if match else None


def check_python(env: Env) -> Result:
    fix = "install Python 3.10 or newer and run doctor with it"
    code, out, err = env.run([sys.executable, "--version"])
    version = _search(r"Python (\d+\.\d+\S*)", out + err)
    if version is None:
        return Result("python", FAIL, f"no version from {sys.executable}: "
                                      f"{_first_line(err or out) or f'exit {code}'}", fix)
    if _numbers(version)[:2] < (3, 10):
        return Result("python", FAIL, f"{version}, older than 3.10", fix)
    return Result("python", PASS, version)


def check_sqlcl(env: Env) -> Result:
    sql = sqlcl_bin()
    fix = f"install SQLcl {SQLCL_MIN_TEXT} or newer and put `sql` on PATH, or set SQLCL_BIN to it"
    code, out, err = env.run([sql, "-V"])
    if code == 127:
        return Result("sqlcl", FAIL, f"{sql} not found", fix)
    version = _search(r"SQLcl: Release (\d+(?:\.\d+)+)", out + err)
    if version is None:
        return Result("sqlcl", FAIL, f"`{sql} -V` reported no SQLcl version: "
                                     f"{_first_line(err or out) or f'exit {code}'}", fix)
    if _numbers(version)[:len(SQLCL_MIN)] < SQLCL_MIN:
        return Result("sqlcl", FAIL, f"{version}, older than {SQLCL_MIN_TEXT}", fix)
    return Result("sqlcl", PASS, version)


def _java() -> str:
    """The java SQLcl's launcher prefers: $JAVA_HOME/bin/java, else java on PATH."""
    java_home = os.environ.get("JAVA_HOME")
    return str(Path(java_home) / "bin" / "java") if java_home else "java"


def check_java(env: Env) -> Result:
    java = _java()
    fix = "install Java 17 or 21 and put it on PATH, or set JAVA_HOME to it"
    code, out, err = env.run([java, "-version"])
    if code == 127:
        return Result("java", FAIL, f"{java} not found", fix)
    version = _search(r'version "([^"]+)"', err + out)  # java -version writes to stderr
    if version is None:
        return Result("java", FAIL, f"`{java} -version` reported no version: "
                                    f"{_first_line(err or out) or f'exit {code}'}", fix)
    numbers = _numbers(version)
    major = numbers[1] if numbers[0] == 1 and len(numbers) > 1 else numbers[0]  # 1.8 is 8
    if major < 17:
        return Result("java", FAIL, f"{version}, older than 17", fix)
    if major not in (17, 21):
        return Result("java", WARN, f"{version}; SQLcl supports Java 17 and 21", fix)
    return Result("java", PASS, version)


def check_home(env: Env, tier: Tier) -> Result:
    path = env.home_path(tier)
    fix = f"run `python -m tools setup-home --tier {tier.name}`"
    try:
        mode = env.stat_mode(path)
    except FileNotFoundError:
        return Result("home", FAIL, f"{path} is missing", fix)
    if not stat.S_ISDIR(mode):
        return Result("home", FAIL, f"{path} is not a folder", fix)
    if os.name == "posix" and mode & 0o077:
        return Result("home", WARN, f"{path} has mode {stat.S_IMODE(mode):04o}, wider than 0700",
                      f"chmod 700 {path}")
    return Result("home", PASS, str(path))


def _missing_tools(offered: list[str]) -> list[str]:
    """MCP_TOOLS the server does not offer under either SQLcl name."""
    return [
        f"{tool} ({_RENAMED[tool]})" if tool in _RENAMED else tool
        for tool in MCP_TOOLS
        if tool not in offered and _RENAMED.get(tool) not in offered
    ]


def check_connect(session, tier: Tier, name: str) -> Result:
    try:
        session.connect(name)
    except McpError as exc:
        return Result(f"connect:{name}", FAIL, _first_line(exc.message) or str(exc),
                      f"save {name} again with the right user, password and service: "
                      f"see `python -m tools setup-home --tier {tier.name}`")
    return Result(f"connect:{name}", PASS, "connected")


def check_db_version(session, name: str) -> Result:
    check = f"db-version:{name}"
    instance = session.run_sql("select * from v$instance")
    banner = session.run_sql("select banner from v$version")
    error = instance.error or banner.error
    if error or not instance.rows:
        return Result(check, WARN, f"could not read v$instance and v$version: {error}",
                      f"see grants:{name}")
    row = dict(zip(instance.header, instance.rows[0], strict=True))
    version = row.get("VERSION", "")
    banners = [r[0] for r in banner.rows if r]
    text = next((b for b in banners if b.startswith("Oracle")), banners[0] if banners else "")
    detail = f"{row.get('VERSION_FULL') or version} {row.get('EDITION', '')}".strip()
    detail = f"{detail}: {text}" if text else detail
    numbers = _numbers(version)
    if not numbers or numbers[0] < 19:
        return Result(check, WARN, detail,
                      "the checks are written for Oracle 19c and later; some may fail here")
    return Result(check, PASS, detail)


def check_grants(session, tier: Tier, name: str) -> list[Result]:
    """`grants` and `excess-privileges`: the session's privileges and roles against
    the tier's. Roles the tier's roles bring with them count as expected."""
    privs = session.run_sql("select privilege from session_privs")
    roles = session.run_sql("select role from session_roles")
    grants, excess = f"grants:{name}", f"excess-privileges:{name}"
    error = privs.error or roles.error
    if error:
        return [Result(grants, FAIL, f"could not read session_privs and session_roles: {error}",
                       f"run the `python -m tools setup-sql --tier {tier.name}` script"),
                Result(excess, SKIP, f"{grants} failed")]
    held = {r[0] for r in privs.rows if r} | {r[0] for r in roles.rows if r}
    expected = tier.sys_privs | tier.roles
    missing = sorted(expected - held)
    extra = sorted(held - expected - tier.implied_roles)
    listed = ", ".join(sorted(expected))
    return [
        Result(grants, FAIL, f"missing: {', '.join(missing)}",
               f"grant them to the connection's user (`python -m tools setup-sql "
               f"--tier {tier.name}` prints the script)")
        if missing else Result(grants, PASS, f"holds {listed}"),
        Result(excess, FAIL, f"beyond the {tier.name} tier: {', '.join(extra)}",
               f"revoke them from the connection's user; the tier holds only {listed}")
        if extra else Result(excess, PASS, "nothing beyond the tier"),
    ]


def _mcp_command(home: Path) -> str:
    return " ".join([sqlcl_bin(), *mcp_argv(str(home))])


def check_restrict_level(session, name: str, home: Path) -> Result:
    check = f"restrict-level:{name}"
    for probe in PROBES:
        result = session.run_sqlcl(probe)
        if REFUSED not in result.text:
            answer = result.error or _first_line(result.text) or "no output"
            return Result(check, FAIL, f"`{probe}` was not refused: {answer}",
                          f"SQLcl's MCP server must run at restrict level 4: start it as "
                          f"`{_mcp_command(home)}`, in the pack and in your MCP client "
                          "configuration")
    return Result(check, PASS, f"{' and '.join(f'`{p}`' for p in PROBES)} refused ({REFUSED})")


def _skips(checks: list[str], names: list[str] | None, reason: str) -> list[Result]:
    """SKIP for `checks` and for every per-connection check of `names`
    (the bare check names when no connection is known)."""
    per = [f"{c}:{n}" for n in names for c in PER_CONNECTION] if names else list(PER_CONNECTION)
    return [Result(c, SKIP, reason) for c in [*checks, *per]]


def _skip_after(name: str, i: int) -> list[Result]:
    """SKIP for the per-connection checks of `name` after PER_CONNECTION[i]."""
    return [Result(f"{c}:{name}", SKIP, f"{PER_CONNECTION[i]}:{name} failed")
            for c in PER_CONNECTION[i + 1:]]


def _connection_checks(session, tier: Tier, name: str, home: Path) -> list[Result]:
    results = [check_connect(session, tier, name)]
    if results[0].status == FAIL:
        return results + _skip_after(name, 0)
    try:
        results.append(check_db_version(session, name))
        results.extend(check_grants(session, tier, name))
        results.append(check_restrict_level(session, name, home))
    except (McpError, McpTimeout) as exc:
        i = len(results)
        results.append(Result(f"{PER_CONNECTION[i]}:{name}", FAIL,
                              f"SQLcl did not answer: {_first_line(str(exc))}",
                              "run doctor again; if it repeats, run SQLcl's MCP server "
                              "by hand to see its error"))
        results += _skip_after(name, i)
    with contextlib.suppress(McpError, McpTimeout):
        session.disconnect()
    return results


def run_all(env: Env, tier: Tier, connection: str | None = None) -> list[Result]:
    """Every check for `tier`, in order; per-connection checks for `connection`
    alone when given, else for each connection saved in the tier's home."""
    names = [connection] if connection else None
    results = [check_python(env), check_sqlcl(env), check_java(env), check_home(env, tier)]
    failed = [r.check for r in results[1:] if r.status == FAIL]
    if failed:
        return results + _skips(["mcp-start", "connections"], names,
                                f"{' and '.join(failed)} failed")

    home = env.home_path(tier)
    start_fix = f"run `{_mcp_command(home)}` by hand to see SQLcl's error"
    with contextlib.ExitStack() as stack:
        try:
            session = stack.enter_context(env.open_session(home))
            missing = _missing_tools(session.list_tools())
        except (McpError, McpTimeout) as exc:
            results.append(Result("mcp-start", FAIL, _first_line(str(exc)), start_fix))
            return results + _skips(["connections"], names, "mcp-start failed")
        if missing:
            results.append(Result("mcp-start", FAIL, f"tools missing: {', '.join(missing)}",
                                  f"install SQLcl {SQLCL_MIN_TEXT} or newer"))
            return results + _skips(["connections"], names, "mcp-start failed")
        results.append(Result("mcp-start", PASS, f"offers {', '.join(MCP_TOOLS)}"))

        try:
            saved = session.list_connections()
        except (McpError, McpTimeout) as exc:
            saved, error = [], _first_line(str(exc))
        else:
            error = None
        if not saved:
            results.append(Result("connections", FAIL, error or f"no saved connection in {home}",
                                  f"run `python -m tools setup-home --tier {tier.name}` "
                                  "and follow its steps"))
            return results + _skips([], names, "no saved connection")
        results.append(Result("connections", PASS, ", ".join(saved)))

        for name in names or saved:
            results.extend(_connection_checks(session, tier, name, home))
    return results

"""Scripted stand-ins for doctor's `Env` and `SqlclSession` (the DBA-15 seam,
tools/doctor/env.py), shared by the doctor and support-bundle unit tests. The
seam and the SQLcl texts are described in tests/unit/test_doctor.py."""

import re
import stat
import sys
from pathlib import Path

from tools.mcp_client import McpError
from tools.sqlcl import SqlResult
from tools.sqlcl_text import find_error

PYTHON_OK = "Python 3.12.4\n"
SQLCL_26_1 = "\nSQLcl: Release 26.1.0.0 Production Build: 26.1.0.086.1709\n"
JAVA_17 = (
    'openjdk version "17.0.19" 2026-04-21\n'
    "OpenJDK Runtime Environment Homebrew (build 17.0.19+0)\n"
)
TOOLS_26_1 = ["list-connections", "connect", "run-sql", "run-sqlcl", "disconnect"]
AT_PROBE = "@doctor_probe.sql"
HOST_PROBE = "host echo doctor-probe"
# Real SQLcl 26.3.1 (Build 26.3.1.301.1413) answers through sqlcl_run; isError
# is false for all four (issue DBA-15, revision of 2026-11-12).
AT_REFUSED = 'SP2-0738: Restricted command: \n"@doctor_probe.sql"\nnot available\n'
HOST_REFUSED = 'SP2-0738: Restricted command: \n"host echo doctor-probe"\nnot available\n'
REFUSED_BOTH = {AT_PROBE: AT_REFUSED, HOST_PROBE: HOST_REFUSED}
DB_23 = {
    "VERSION": "23.0.0.0.0",
    "VERSION_FULL": "23.26.0.0.0",
    "EDITION": "FREE",
    "BANNER": "Oracle Database 23ai Free Release 23.0.0.0.0 - Develop, Learn, and Run for Free",
    "BANNER_FULL": "Oracle Database 23ai Free Release 23.0.0.0.0 - Version 23.26.0.0.0",
}
DB_19 = {
    "VERSION": "19.0.0.0.0",
    "VERSION_FULL": "19.24.0.0.0",
    "EDITION": "EE",
    "BANNER": "Oracle Database 19c Enterprise Edition Release 19.0.0.0.0 - Production",
    "BANNER_FULL": "Oracle Database 19c Enterprise Edition Release 19.0.0.0.0 - "
                   "Version 19.24.0.0.0",
}
RO_PRIVS = ["CREATE SESSION"]
# SELECT_CATALOG_ROLE brings HS_ADMIN_SELECT_ROLE with it (issue DBA-15)
RO_ROLES = ["SELECT_CATALOG_ROLE", "HS_ADMIN_SELECT_ROLE"]
# USER_TAB_PRIVS row every user sees (measured on 23.26.3, DBA-26): PUBLIC may
# inherit the user's privileges. Not an object grant to the user.
TAB_PRIV_COLUMNS = ("GRANTEE", "OWNER", "TABLE_NAME", "GRANTOR", "PRIVILEGE", "TYPE")
INHERIT_ROW = {"GRANTEE": "PUBLIC", "OWNER": "SYS", "TABLE_NAME": "<user>",
               "GRANTOR": "<user>", "PRIVILEGE": "INHERIT PRIVILEGES", "TYPE": "USER"}


def tab_priv(grant):
    """A USER_TAB_PRIVS row for a tier object grant `SELECT ON SYS.<object>`."""
    privilege, _, target = grant.partition(" ON ")
    owner, _, name = target.partition(".")
    return {"GRANTEE": "<user>", "OWNER": owner, "TABLE_NAME": name, "GRANTOR": owner,
            "PRIVILEGE": privilege, "TYPE": "TABLE"}


def _csv(header, rows):
    lines = [",".join(f'"{h}"' for h in header)]
    lines += [",".join(f'"{v}"' for v in row) for row in rows]
    return "\n".join(lines) + "\n"


def _result(header, rows):
    return SqlResult(_csv(header, rows), header, rows, "", None)


def _select_list(sql):
    """Column names asked for in `select <list> from`, each with its alias (last word)."""
    match = re.search(r"select\s+(.*?)\s+from\s", sql, re.I | re.S)
    items = match.group(1).split(",") if match else []
    return [item.strip() for item in items]


class FakeSession:
    """Stands in for SqlclSession, scripted per test."""

    def __init__(self, tools=TOOLS_26_1, connections=("ro",), connect_errors=None,
                 db=DB_23, privs=RO_PRIVS, roles=RO_ROLES, sqlcl_answers=None,
                 tab_privs=()):
        self.tools = list(tools)
        self.connections = list(connections)
        self.connect_errors = connect_errors or {}
        self.db, self.privs, self.roles = db, list(privs), list(roles)
        # USER_TAB_PRIVS rows (dicts keyed by TAB_PRIV_COLUMNS); tab_priv() builds one
        self.tab_privs = [INHERIT_ROW, *tab_privs]
        self.sqlcl_answers = dict(REFUSED_BOTH if sqlcl_answers is None else sqlcl_answers)
        self.connected = None
        self.sql = []
        self.sqlcl = []  # (connection, command) per run_sqlcl call, in order

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        pass

    def list_tools(self):
        return list(self.tools)

    def list_connections(self):
        return list(self.connections)

    def connect(self, name):
        if name in self.connect_errors:
            raise McpError(0, self.connect_errors[name])
        if name not in self.connections:
            raise McpError(0, f"Connection {name} not found")
        self.connected = name

    def disconnect(self):
        self.connected = None

    def run_sql(self, sql):
        assert self.connected, f"run_sql before connect: {sql}"
        self.sql.append(sql)
        low = sql.lower()
        if "session_privs" in low:
            return _result(["PRIVILEGE"], [[p] for p in self.privs])
        if "session_roles" in low:
            return _result(["ROLE"], [[r] for r in self.roles])
        if "user_tab_privs" in low:
            # Plain column names only; the WHERE clause is not applied.
            header = [re.split(r"[\s.]", i.upper())[-1] for i in _select_list(sql)]
            header = list(TAB_PRIV_COLUMNS) if header == ["*"] else header
            unknown = [h for h in header if h not in TAB_PRIV_COLUMNS]
            assert not unknown, f"fake answers plain USER_TAB_PRIVS columns only: {sql}"
            return _result(header, [[row[h] for h in header] for row in self.tab_privs])
        if "v$instance" in low or "v$version" in low:
            header, row = [], []
            for item in _select_list(sql):
                upper = item.upper()
                names = list(self.db) if upper == "*" else [re.split(r"[\s.]", upper)[-1]]
                for name in names:
                    known = next((c for c in sorted(self.db, key=len, reverse=True)
                                  if c in upper or c == name), None)
                    header.append(name)
                    row.append(self.db.get(name, self.db.get(known, "")) if known else "")
            return _result(header, [row])
        raise AssertionError(f"unexpected SQL: {sql}")

    def run_sqlcl(self, command):
        assert self.connected, f"run_sqlcl before connect: {command}"
        command = command.strip()
        self.sqlcl.append((self.connected, command))
        assert command in self.sqlcl_answers, f"unexpected run_sqlcl command: {command}"
        text = self.sqlcl_answers[command]
        # As SqlclSession.run_sqlcl: isError is false, so error is the code in the text.
        return SqlResult(text, [], [], "", find_error(text))


class FakeEnv:
    """The scripted Env. `outputs` maps python/sqlcl/java to (code, stdout, stderr)."""

    def __init__(self, tmp_path, session=None, session_error=None, mode=0o700,
                 home_exists=True, home=None, **outputs):
        self.outputs = {
            "python": (0, PYTHON_OK, ""),
            "sqlcl": (0, SQLCL_26_1, ""),
            "java": (0, "", JAVA_17),
        }
        self.outputs.update(outputs)
        self.session = session or FakeSession()
        self.session_error = session_error
        self.mode = mode
        self.home = Path(home) if home else tmp_path / "pack" / "homes" / "read-only"
        if home_exists:
            self.home.mkdir(parents=True)
        self.commands = []
        self.opened = []

    def run(self, cmd):
        cmd = [str(c) for c in cmd]
        self.commands.append(cmd)
        prog = Path(cmd[0]).name.lower()
        if cmd[0] == sys.executable or prog.startswith("python"):
            return self.outputs["python"]
        if prog.startswith("java"):
            return self.outputs["java"]
        if prog.startswith("sql"):
            return self.outputs["sqlcl"]
        raise AssertionError(f"unexpected command: {cmd}")

    def open_session(self, home):
        self.opened.append(Path(home))
        if self.session_error is not None:
            raise self.session_error
        return self.session

    def home_path(self, tier):
        assert getattr(tier, "name", tier) in ("read-only", "advisory"), tier
        return self.home

    def stat_mode(self, path):
        if not Path(path).exists():
            raise FileNotFoundError(path)
        return stat.S_IFDIR | self.mode

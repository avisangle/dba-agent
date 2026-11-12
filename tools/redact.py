"""Replace identifiers in text that leaves the machine (the support bundle).

Order matters: the home path, then connect strings, then known names, then
addresses, then host names, then the OS user. Redaction fails closed: a dotted
quad is an address unless its context says version
(docs/decisions/D-DBA-17-redaction-fails-closed.md).
"""

import functools
import getpass
import os
import re
import socket
from pathlib import Path

_OS_CASE = re.I if os.name == "nt" else 0  # paths and user names ignore case on Windows
HOME, OS_USER, HOST, IP, CONNECT = "<home>", "<os-user>", "<host>", "<ip>", "<connect-string>"
PATH = "<path>"

_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
_IPV4 = rf"(?:{_OCTET}\.){{3}}{_OCTET}"
# A bracketed IPv6, an IPv4, or a name with at least one letter (so `10:30:45` is no host).
_HOST = rf"(?:\[[0-9A-Fa-f:.]+\]|{_IPV4}|(?=[\w.-]*[A-Za-z])[A-Za-z0-9][\w.-]*)"
_NAME = r"[A-Za-z0-9_](?:[\w.$#-]*[\w$#])?"  # service name or SID
_EZCONNECT = re.compile(
    rf"(?<![:\w])//{_HOST}(?::\d{{1,5}})?(?:/(?P<service>{_NAME}))?"  # //host[:port][/service]
    rf"|(?<![\w.:/-]){_HOST}:\d{{1,5}}(?:/(?P<service2>{_NAME})|:(?P<sid>\w+))"  # host:port/x, :sid
)
_DESCRIPTION = re.compile(r"\(\s*DESCRIPTION(?:_LIST)?\s*=", re.I)
_DESCRIPTION_NAMES = re.compile(r"\b(?:SERVICE_NAME|SID)\s*=\s*([^)\s]+)", re.I)
# Names in connect errors, 23ai wording: ORA-12514/12505 service or SID,
# ORA-12154 TNS alias, ORA-01045 user (19c: "user X lacks CREATE SESSION").
_UNREGISTERED = re.compile(rf"\b(?:Service|SID) ({_NAME}) is not registered")
_ALIAS = re.compile(rf"\bfind alias ({_NAME}) in ")
_NO_SESSION = re.compile(r"\b[Uu]ser ([A-Za-z][\w$#]*) (?:does not have|lacks) CREATE SESSION")
_USER_AT = re.compile(r"([A-Za-z][\w$#]*)@$")

_IPV4_RE = re.compile(rf"(?<![\w.]){_IPV4}(?!\w|\.\d)")
_VERSION_BEFORE = re.compile(r"(?:release|build|version)\W{0,3}$", re.I)
_H = r"[0-9A-Fa-f]{1,4}"
_IPV6_RE = re.compile(
    rf"(?<![\w:.])(?:(?:{_H}:){{7}}{_H}|(?:{_H}(?::{_H})*)?::(?:{_H}(?::{_H})*)?)(?![\w:])")
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_FQDN_RE = re.compile(
    rf"(?<![\w.-])(?:{_LABEL}\.)+(?P<tld>[A-Za-z][A-Za-z0-9-]*[A-Za-z0-9])(?![\w-]|\.\w)")
_HOST_PORT = re.compile(r"\b(host )([^\s<]\S*?)( port \d)")  # ORA-12541: "at host X port N"
_UNKNOWN_HOST = re.compile(r"(Unknown host specified\.?\s*:\s*)[^\s:<]+")  # ORA-17868
# The TNS admin folder ORA-12154 and ORA-12263 name; an ADB wallet's is `Wallet_<DBNAME>`.
_TNS_PATH = re.compile(r"(\bfind alias \S+ in |\bconfigured as TNS admin: ).+?(?=\.(?:\s|$)|$)",
                       re.M)
# Last parts that make a dotted word a file name, not a host name. None is a
# top-level domain: md, py, sh and zip are, so `notes.md` is redacted as a host.
FILE_TYPES = frozenset({
    "bat", "cfg", "cmd", "csv", "exe", "html", "ini", "jar", "json", "log", "ora", "ps1",
    "sql", "toml", "txt", "xml", "yaml", "yml",
})


class Known:
    """Names collected at run time. Each kind is numbered in order of first
    appearance, so the same name always gets the same token. Oracle folds
    unquoted identifiers, so database names match in any case."""

    def __init__(self, connections=(), db_users=(), db_names=(), services=()):
        self.subs = []  # (pattern, replacement function), applied in this order
        for names, label, fold in ((connections, "connection", False),
                                   (db_users, "db-user", True), (db_names, "db-name", True),
                                   (services, "service", True)):
            key = str.upper if fold else str
            tokens = {}
            for name in filter(None, names):
                tokens.setdefault(key(name), f"<{label}-{len(tokens) + 1}>")
            if tokens:
                alts = "|".join(map(re.escape, sorted(tokens, key=len, reverse=True)))
                pattern = re.compile(rf"(?<![\w$#-])(?:{alts})(?![\w$#-])", re.I if fold else 0)
                self.subs.append((pattern, lambda m, t=tokens, k=key: t[k(m[0])]))


def collect(text: str, connections=(), db_users=()) -> Known:
    """`Known` for `connections` and `db_users`, plus the user (`user@`) and the
    service name or SID of each connect string in `text`, and the service, SID,
    TNS alias or user a connect error names."""
    users, services = list(db_users), []
    for m in _EZCONNECT.finditer(text):
        services += filter(None, m.groups())  # service name or SID
        if user := _USER_AT.search(text, 0, m.start()):
            users.append(user[1])
    services += (_DESCRIPTION_NAMES.findall(text) + _UNREGISTERED.findall(text)
                 + _ALIAS.findall(text))
    users += _NO_SESSION.findall(text)
    return Known(connections=connections, db_users=users, services=services)


def _descriptions(text: str) -> str:
    """Each `(DESCRIPTION=...)` block, to its balancing `)` or the end of the text."""
    parts, pos = [], 0
    while m := _DESCRIPTION.search(text, pos):
        depth, end = 0, len(text)
        for i in range(m.start(), len(text)):
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            if depth == 0:
                end = i + 1
                break
        parts += [text[pos:m.start()], CONNECT]
        pos = end
    return "".join(parts) + text[pos:]


def _ipv4(m: re.Match) -> str:
    before = m.string[max(0, m.start() - 12):m.start()]
    return m[0] if _VERSION_BEFORE.search(before) else IP


def _word(name: str, flags=0) -> re.Pattern:
    """`name` not inside a longer run of letters and digits."""
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", flags)


@functools.cache
def _home_patterns() -> tuple[re.Pattern, ...]:
    """The home path, as written by this OS and resolved; none when home is a root."""
    home = Path.home()
    if home == Path(home.anchor):  # a home of `/` would match every path
        return ()
    paths = dict.fromkeys((str(home), str(home.resolve()), home.as_posix()))
    return tuple(re.compile(rf"{re.escape(path)}(?![\w.-])", _OS_CASE) for path in paths)


@functools.cache
def _identity_patterns() -> tuple[tuple[re.Pattern, str], ...]:
    """This machine's name, with and without its domain, and the OS user."""
    machine = socket.gethostname()
    pats = [(_word(name, re.I), HOST)
            for name in dict.fromkeys((machine, machine.partition(".")[0])) if name]
    try:
        user = getpass.getuser()
    except (OSError, KeyError):  # no login name, e.g. a container without a passwd entry
        user = ""
    if user:
        pats.append((_word(user, _OS_CASE), OS_USER))
    return tuple(pats)


def redact(text: str, known: Known) -> str:
    """`text` with connect strings, addresses, host names, the home path, the TNS
    admin folder of a connect error, the OS user and every name in `known`
    replaced by tokens."""
    for pattern in _home_patterns():
        text = pattern.sub(HOME, text)
    text = _EZCONNECT.sub(CONNECT, _descriptions(text))
    for pattern, replace in known.subs:
        text = pattern.sub(replace, text)
    text = _IPV4_RE.sub(_ipv4, text)
    text = _IPV6_RE.sub(lambda m: m[0] if m[0] == "::" else IP, text)
    text = _FQDN_RE.sub(lambda m: m[0] if m["tld"].lower() in FILE_TYPES else HOST, text)
    text = _HOST_PORT.sub(rf"\1{HOST}\3", text)
    text = _UNKNOWN_HOST.sub(rf"\1{HOST}", text)
    text = _TNS_PATH.sub(rf"\1{PATH}", text)
    for pattern, token in _identity_patterns():
        text = pattern.sub(token, text)
    return text

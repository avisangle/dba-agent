"""Replace identifiers in text that leaves the machine (the support bundle).

Order matters: the home path, then connect strings, then known names, then
addresses, then host names, then the OS user. Redaction fails closed: a dotted
quad is an address unless its context says version
(docs/decisions/D-DBA-17-redaction-fails-closed.md).
"""

import getpass
import os
import re
import socket
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

HOME, OS_USER, HOST, IP, CONNECT = "<home>", "<os-user>", "<host>", "<ip>", "<connect-string>"

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
_UNREGISTERED = re.compile(r"\bService (\S+) is not registered")  # ORA-12514, 23ai wording
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
# Last parts that make a dotted word a file name, not a host name. None is a
# top-level domain: md, py, sh and zip are, so `notes.md` is redacted as a host.
FILE_TYPES = frozenset({
    "bat", "cfg", "cmd", "csv", "exe", "html", "ini", "jar", "json", "log", "ora", "ps1",
    "sql", "toml", "txt", "xml", "yaml", "yml",
})
# (Known field, token label, matched in any case): Oracle folds unquoted identifiers.
_KINDS = (("connections", "connection", False), ("db_users", "db-user", True),
          ("db_names", "db-name", True), ("services", "service", True))


@dataclass(frozen=True)
class Known:
    """Names collected at run time. Each kind is numbered in order of first
    appearance, so the same name always gets the same token."""
    connections: Iterable[str] = ()
    db_users: Iterable[str] = ()
    db_names: Iterable[str] = ()
    services: Iterable[str] = ()
    _subs: tuple = field(default=(), init=False, repr=False, compare=False)

    def __post_init__(self):
        subs = []
        for attr, label, fold in _KINDS:
            names = tuple(n for n in getattr(self, attr) if n)
            object.__setattr__(self, attr, names)
            tokens = {}
            for name in names:
                tokens.setdefault(name.upper() if fold else name, f"<{label}-{len(tokens) + 1}>")
            if tokens:
                alts = "|".join(map(re.escape, sorted(tokens, key=len, reverse=True)))
                pattern = re.compile(rf"(?<![\w$#-])(?:{alts})(?![\w$#-])", re.I if fold else 0)
                subs.append((pattern, tokens, fold))
        object.__setattr__(self, "_subs", tuple(subs))


def collect(text: str, connections=(), db_users=()) -> Known:
    """`Known` for `connections` and `db_users`, plus the user (`user@`) and the
    service name or SID of each connect string in `text`, and the service an
    ORA-12514 names."""
    users, services = list(db_users), []
    for m in _EZCONNECT.finditer(text):
        services += [s for s in (m["service"], m["service2"], m["sid"]) if s]
        if user := _USER_AT.search(text, 0, m.start()):
            users.append(user[1])
    services += _DESCRIPTION_NAMES.findall(text) + _UNREGISTERED.findall(text)
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


def _home_patterns() -> list[re.Pattern]:
    """The home path, as written by this OS and resolved; none when home is a root."""
    home = Path.home()
    if home == Path(home.anchor):  # a home of `/` would match every path
        return []
    fold = re.I if os.name == "nt" else 0
    paths = dict.fromkeys((str(home), str(home.resolve()), home.as_posix()))
    return [re.compile(rf"{re.escape(path)}(?![\w.-])", fold) for path in paths]


def _identity_patterns() -> list[tuple[re.Pattern, str]]:
    """This machine's name, with and without its domain, and the OS user."""
    machine = socket.gethostname()
    pats = [(_word(name, re.I), HOST)
            for name in dict.fromkeys((machine, machine.partition(".")[0])) if name]
    try:
        user = getpass.getuser()
    except (OSError, KeyError):  # no login name, e.g. a container without a passwd entry
        user = ""
    if user:
        pats.append((_word(user, re.I if os.name == "nt" else 0), OS_USER))
    return pats


def redact(text: str, known: Known) -> str:
    """`text` with connect strings, addresses, host names, the home path, the OS
    user and every name in `known` replaced by tokens."""
    for pattern in _home_patterns():
        text = pattern.sub(HOME, text)
    text = _EZCONNECT.sub(CONNECT, _descriptions(text))
    for pattern, tokens, fold in known._subs:
        text = pattern.sub(lambda m, t=tokens, f=fold: t[m[0].upper() if f else m[0]], text)
    text = _IPV4_RE.sub(_ipv4, text)
    text = _IPV6_RE.sub(lambda m: m[0] if m[0] == "::" else IP, text)
    text = _FQDN_RE.sub(lambda m: m[0] if m["tld"].lower() in FILE_TYPES else HOST, text)
    text = _HOST_PORT.sub(rf"\1{HOST}\3", text)
    for pattern, token in _identity_patterns():
        text = pattern.sub(token, text)
    return text

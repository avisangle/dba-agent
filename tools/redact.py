"""Replace identifiers in text that leaves the machine (the support bundle).

Redaction fails closed (docs/decisions/D-DBA-17-redaction-fails-closed.md):
anything that could be an identifier is replaced, chosen by the shape of the
text and never by which error message carries it. Order matters: the home
folder standing alone, connect strings, absolute paths (the one after `-home `
is the tier home), wallet names, addresses and host names, known names, then
this machine's name and the OS user.
"""

import functools
import getpass
import os
import re
import socket
from pathlib import Path

HOME, PATH, OS_USER = "<home>", "<path>", "<os-user>"
HOST, IP, CONNECT = "<host>", "<ip>", "<connect-string>"
TIER_HOME = "<tier-home>"  # the path after `-home ` in a SQLcl command line
NUMBERED = ("connection", "db-user", "db-name", "service")  # `<kind-N>` tokens
_FIXED = "|".join(map(re.escape, (HOME, PATH, OS_USER, HOST, IP, CONNECT, TIER_HOME)))
_TOKEN = re.compile(rf"({_FIXED}|<(?:{'|'.join(NUMBERED)})-\d+>)")
_OS_CASE = re.I if os.name == "nt" else 0  # paths and user names ignore case on Windows

# Connect strings.
_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
_IPV4 = rf"(?:{_OCTET}\.){{3}}{_OCTET}"
# A bracketed IPv6, an IPv4, or a name with at least one letter (so `10:30:45` is no host).
_HOST = rf"(?:\[[0-9A-Fa-f:.]+\]|{_IPV4}|(?=[\w.-]*[A-Za-z])[A-Za-z0-9][\w.-]*)"
_NAME = r"[A-Za-z0-9_](?:[\w.$#-]*[\w$#])?"  # service name, SID or TNS alias
_EZCONNECT = re.compile(
    rf"(?<![:\w])//(?P<h1>{_HOST})(?::\d{{1,5}})?(?:/(?P<s1>{_NAME}))?"  # //host[:port][/svc]
    rf"|(?<![\w.:/-])(?P<h2>{_HOST}):\d{{1,5}}(?:/(?P<s2>{_NAME})|:(?P<s3>\w+))"  # host:port/svc
)
_DESCRIPTION = re.compile(r"\(\s*DESCRIPTION(?:_LIST)?\s*=", re.I)
_DESCRIPTION_NAMES = re.compile(r"\b(HOST|SERVICE_NAME|SID)\s*=\s*([^)\s]+)", re.I)

# Names that SQLcl 26.3.1 connect errors carry (see collect).
_UNKNOWN_HOST = re.compile(r"Unknown host specified\.?\s*:\s*([^\s:<]+)")  # ORA-17868
_HOST_PORT = re.compile(r"\bhost ([^\s<]\S*?) port \d")  # ORA-12541, ORA-12170, ORA-125xx
_UNREGISTERED = re.compile(rf"\b(?:Service|SID) ({_NAME}) is not registered")  # ORA-12514/12505
_ALIAS = re.compile(rf"\bfind alias ({_NAME}) in ")  # ORA-12154
_NO_SESSION = re.compile(r"\b[Uu]ser ([A-Za-z][\w$#]*) (?:does not have|lacks) CREATE SESSION")
# An Autonomous Database wallet names its database: `Wallet_<NAME>[.zip]`. Case
# matters: sqlnet.ora's `WALLET_LOCATION` is no wallet.
_WALLET = re.compile(r"(?<![A-Za-z0-9])(Wallet_)(\w+)")
# In this order, so numbering follows it.
_NAMED = ((_UNKNOWN_HOST, "host"), (_HOST_PORT, "host"), (_UNREGISTERED, "service"),
          (_ALIAS, "service"), (_NO_SESSION, "db-user"), (_WALLET, "db-name"))

# Absolute paths: a root (`/`, `~/`, `C:\`, `C:/`, `\\server`) with at least one
# component, not preceded by a letter or digit. A folder may hold spaces when
# a `\` or `/` follows it. Before `\` it takes anything Windows allows; before
# `/` it never ends in a space, but may hold `. ` so the path is never cut short
# (D-DBA-45-slash-folder-may-cross-a-sentence).
_COMP = r"[^\s\"'`<>|;,()\[\]{}/\\]"  # first character of a component
_RUN = r"[^\s\"'`<>|;,()\[\]{}]"  # a path continues over these
_SEP = r"\\/:*?\"`<>|"  # never inside a `/` folder
_EDGE = rf"[^\s{_SEP}]"  # first and last character of a `/` folder
_FOLDER = rf"(?:[^\\/:*?\"<>|\r\n]+\\|{_EDGE}(?:[^{_SEP}\r\n]*{_EDGE})?/)"
_PATH_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|\\\\|~?/)(?:{_FOLDER})*{_COMP}{_RUN}*"
)
_PATH_TAIL = re.compile(r"[.:]+$")  # sentence punctuation after a path stays outside it

# Addresses and host names.
_IPV4_RE = re.compile(rf"(?<![\w.]){_IPV4}(?!\w|\.\d)")  # a fifth dotted group is a version
_VERSION_BEFORE = re.compile(r"(?:release|build|version)\W{0,3}$", re.I)
_H = r"[0-9A-Fa-f]{1,4}"
_IPV6_RE = re.compile(
    rf"(?<![\w:.])(?=[:\w]*[0-9A-Fa-f])"  # at least one group: a bare `::` is no address
    rf"(?:(?:{_H}:){{7}}{_H}|(?:{_H}(?::{_H})*)?::(?:{_H}(?::{_H})*)?)(?![\w:])")
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_FQDN_RE = re.compile(
    rf"(?<![\w.-])(?:{_LABEL}\.)+(?P<tld>[A-Za-z][A-Za-z0-9-]*[A-Za-z0-9])(?![\w-]|\.\w)")
# Last parts that make a dotted word a file name, not a host name. None is a
# top-level domain: md, py, sh and zip are, so `db.corp.md` is a host.
FILE_TYPES = frozenset({
    "bat", "cfg", "cmd", "csv", "exe", "html", "ini", "jar", "jks", "json", "log", "ora", "p12",
    "pem", "ps1", "sql", "sso", "toml", "txt", "xml", "yaml", "yml",
})


class Known:
    """Names collected at run time, each kind numbered in order of first sight,
    so the same name always gets the same token. Names match in any case."""

    def __init__(self):
        self._tokens: dict[str, str] = {}  # upper-cased name -> token
        self._counts = dict.fromkeys(NUMBERED, 0)
        self._pattern = None  # built on first use after a name is added

    def add(self, kind: str, name: str) -> str:
        """The token for `name`, `<host>` for kind "host" and else `<kind-N>`;
        a name seen before keeps its first token."""
        key = name.upper()
        if key not in self._tokens:
            if kind in self._counts:
                self._counts[kind] += 1
                self._tokens[key] = f"<{kind}-{self._counts[kind]}>"
            else:
                self._tokens[key] = HOST
            self._pattern = None
        return self._tokens[key]

    def sub(self, text: str) -> str:
        if not self._tokens:
            return text
        if self._pattern is None:
            alts = "|".join(map(re.escape, sorted(self._tokens, key=len, reverse=True)))
            self._pattern = re.compile(rf"(?<![\w$#-])(?:{alts})(?![\w$#-])", re.I)
        return self._pattern.sub(lambda m: self._tokens[m[0].upper()], text)


def _gather(text: str, known: Known) -> None:
    """Add to `known` the names `text` carries in connect strings, connect errors
    and wallet names."""
    for m in _EZCONNECT.finditer(text):
        known.add("host", m["h1"] or m["h2"])
        if service := m["s1"] or m["s2"] or m["s3"]:
            known.add("service", service)
    for key, value in _DESCRIPTION_NAMES.findall(text):
        known.add("host" if key.upper() == "HOST" else "service", value)
    for pattern, kind in _NAMED:
        for m in pattern.finditer(text):
            known.add(kind, m[m.lastindex])


def collect(text: str, connections=(), db_users=()) -> Known:
    """`Known` for `connections` and `db_users`, plus every name `text` carries:
    the host and service of each connect string, the host, service, SID, TNS
    alias or user a connect error names, and the database of each wallet name."""
    known = Known()
    for name in filter(None, connections):
        known.add("connection", name)
    for name in filter(None, db_users):
        known.add("db-user", name)
    _gather(text, known)
    return known


def _outside_tokens(text: str, fn) -> str:
    """`fn` applied to the text between tokens, so no step rewrites a token."""
    parts = _TOKEN.split(text)
    return "".join(part if i % 2 else fn(part) for i, part in enumerate(parts))


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


def _wallets(text: str, known: Known) -> str:
    """`Wallet_<NAME>` as `Wallet_<db-name-N>`."""
    return _WALLET.sub(lambda m: m[1] + known.add("db-name", m[2]), text)


def _path(m: re.Match) -> str:
    tail = _PATH_TAIL.search(m[0])
    token = TIER_HOME if m.string.endswith("-home ", 0, m.start()) else PATH
    return token + (tail[0] if tail else "")


def _ipv4(m: re.Match) -> str:
    before = m.string[max(0, m.start() - 12):m.start()]
    return m[0] if _VERSION_BEFORE.search(before) else IP


def _hosts(text: str) -> str:
    text = _IPV4_RE.sub(_ipv4, text)
    text = _IPV6_RE.sub(IP, text)
    return _FQDN_RE.sub(lambda m: m[0] if m["tld"].lower() in FILE_TYPES else HOST, text)


def _identity(text: str) -> str:
    for pattern, token in _identity_patterns():
        text = pattern.sub(token, text)
    return text


def _word(name: str, flags=0) -> re.Pattern:
    """`name` not inside a longer run of letters and digits."""
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", flags)


@functools.cache
def _home_patterns() -> tuple[re.Pattern, ...]:
    """The home folder standing alone, as written by this OS and resolved; none
    when it is a root. A path under it is left whole for the path rule."""
    home = Path.home()
    if home == Path(home.anchor):  # a home of `/` would match every path
        return ()
    paths = dict.fromkeys((str(home), str(home.resolve()), home.as_posix()))
    return tuple(re.compile(rf"{re.escape(path)}(?![\w.\\/-])", _OS_CASE) for path in paths)


@functools.cache
def _identity_patterns() -> tuple[tuple[re.Pattern, str], ...]:
    """This machine's name, with and without its domain, then the OS user."""
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
    """`text` with the home folder, connect strings, absolute paths, wallet
    names, addresses, host names, names in `known`, this machine's name and the
    OS user replaced by tokens, in that order. Host names go before known names,
    so a host whose first label is a known name is `<host>` whole. Names `text`
    carries that `known` lacks are added to it first."""
    _gather(text, known)
    for pattern in _home_patterns():
        text = pattern.sub(HOME, text)
    text = _outside_tokens(_descriptions(text), lambda t: _EZCONNECT.sub(CONNECT, t))
    text = _PATH_RE.sub(_path, text)
    text = _outside_tokens(text, functools.partial(_wallets, known=known))
    text = _outside_tokens(text, _hosts)
    text = _outside_tokens(text, known.sub)
    return _outside_tokens(text, _identity)

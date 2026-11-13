"""DBA-17: `redact(text, known)` and `collect(text, connections, db_users)` in
`tools/redact.py`, driven with SQLcl 26.3.1 connect-error texts verbatim (only
the names were changed) and with text that only looks like an identifier.

Tokens (issues DBA-17, DBA-45): `<host>`, `<ip>`, `<connect-string>`, `<path>`,
`<tier-home>` (an absolute path right after `-home `), `<home>`, `<os-user>`, and
`<connection-N>`, `<db-user-N>`, `<db-name-N>`, `<service-N>` for names collected
into `Known`, numbered consistently within one `Known`.
Known names match case-insensitively (`acme_mon` is the user `ACME_MON`).

The module does not exist yet, so it is imported inside the tests: each test
fails on its own instead of the file erroring at collection.
"""

import getpass
import importlib
import inspect
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

HOME = str(Path.home())

# (text, identifiers that must be absent from redact(text, collect(text)))
ORA_17956 = ("ORA-17956: Unable to parse the wallet location supplied: Couldn't find file at "
             "/tmp/x/Wallet_PRODERP (CONNECTION_ID=NLAJIaGQRAWoCWrS3rX8Zw==)")
ORA_12154_HOME = ("ORA-12154: Cannot connect to database. Could not find alias PRODERP_HIGH in "
                  f"{HOME}/wallets/Wallet_PRODERP/tnsnames.ora.")
ORA_12154_WINDOWS = ("ORA-12154: Cannot connect to database. Could not find alias PRODERP_HIGH in "
                     r"C:\Program Files\Oracle\Wallet_PRODERP\tnsnames.ora.")
ORA_12263 = ("ORA-12263: Failed to access tnsnames.ora in the directory configured as TNS admin: "
             "/opt/oracle/Wallet_PRODERP. The file does not exist, or is not accessible.")
ORA_12154_NON_WALLET = ("ORA-12154: Cannot connect to database. Could not find alias ERP_HIGH in "
                        "/srv/acme/tns_acmeprod/tnsnames.ora.")
WALLET_NO_PATH = "cloud config Wallet_PRODERP.zip not found"
ORA_17868 = ("ORA-17868: Unknown host specified.: erpdbhost: nodename nor servname provided, "
             "or not known")
ORA_12154 = ("ORA-12154: Cannot connect to database. Could not find alias PRODERP_HIGH in "
             "/opt/tns/tnsnames.ora.")
ORA_01045_23AI = ("ORA-01045: Login denied. User ACME_MON does not have CREATE SESSION "
                  "privilege.")
ORA_01045_19C = "ORA-01045: user ACME_MON lacks CREATE SESSION privilege; logon denied"
ORA_12505 = ("ORA-12505: Cannot connect to database. SID ERPSID is not registered with the "
             "listener at host localhost port 1521. (CONNECTION_ID=NLAJIaGQRAWoCWrS3rX8Zw==)")
ORA_12514 = ("ORA-12514: Cannot connect to database. Service ERPPDB is not registered with the "
             "listener at host localhost port 1521. (CONNECTION_ID=orDQpeYDRbuCaw0971flBQ==)")
ORA_12541 = ("ORA-12541: Cannot connect. No listener at host erpdbhost port 1599. "
             "(CONNECTION_ID=+R9JZXPoSJyZW8ciiW9ikw==)")

CASES = [
    pytest.param(ORA_17956, ["PRODERP", "/tmp/x"], id="ORA-17956-wallet-location"),
    pytest.param(ORA_12154_HOME, ["PRODERP", "wallets"], id="ORA-12154-under-home"),
    pytest.param(ORA_12154_WINDOWS, ["PRODERP", "Oracle", "Files"], id="ORA-12154-windows-space"),
    pytest.param(ORA_12263, ["PRODERP", "opt"], id="ORA-12263-tns-admin"),
    pytest.param(ORA_12154_NON_WALLET, ["acme"], id="ORA-12154-non-wallet-folder"),
    pytest.param(ORA_17868, ["erpdbhost"], id="ORA-17868-unknown-host"),
    pytest.param(ORA_12154, ["PRODERP_HIGH"], id="ORA-12154-alias"),
    pytest.param(ORA_01045_23AI, ["ACME_MON"], id="ORA-01045-23ai"),
    pytest.param(ORA_01045_19C, ["ACME_MON"], id="ORA-01045-19c"),
    pytest.param(ORA_12505, ["ERPSID"], id="ORA-12505-sid"),
    pytest.param(ORA_12514, ["ERPPDB"], id="ORA-12514-service"),
    pytest.param(ORA_12541, ["erpdbhost"], id="ORA-12541-no-listener"),
]
ALL_TEXTS = [p.values[0] for p in CASES]


def _redact_module():
    return importlib.import_module("tools.redact")


def _redact_own(text):
    """redact(text, collect(text)), as the issue's acceptance tests state it."""
    mod = _redact_module()
    return mod.redact(text, mod.collect(text))


@pytest.mark.parametrize(("text", "absent"), CASES)
def test_sqlcl_connect_errors_lose_their_identifiers_and_keep_the_code(text, absent):
    """AC: for each SQLcl 26.3.1 connect error, the named identifiers are absent
    and the leading ORA-NNNNN code survives. Falsifiers: redact paths only in
    the ORA-12154/ORA-12263 wording (ORA-17956), keep `<home>/...` readable,
    end a Windows path at the first space, redact only `Wallet_*` folders,
    rely on the host-name pattern for single-label hosts."""
    out = _redact_own(text)
    code = text.split(":", 1)[0]
    assert out.startswith(f"{code}:"), out
    for name in absent:
        assert name not in out, f"{name!r} survived: {out}"


@pytest.mark.parametrize(
    ("text", "tail"),
    [
        pytest.param(ORA_17956, "<path> (CONNECTION_ID=NLAJIaGQRAWoCWrS3rX8Zw==)", id="ORA-17956"),
        pytest.param(ORA_12154_HOME, " in <path>.", id="ORA-12154-home"),
        pytest.param(ORA_12154_WINDOWS, " in <path>.", id="ORA-12154-windows"),
        pytest.param(ORA_12154_NON_WALLET, " in <path>.", id="ORA-12154-non-wallet"),
        pytest.param(ORA_12154, " in <path>.", id="ORA-12154"),
        pytest.param(ORA_12263, "TNS admin: <path>. The file does not exist, or is not accessible.",
                     id="ORA-12263"),
    ],
)
def test_every_absolute_path_is_one_path_token_by_shape(text, tail):
    """AC: every absolute path becomes `<path>` whole, chosen by shape: under the
    home it is `<path>`, not `<home>/...`; a Windows path does not end at a
    space while another `\\` follows; a sentence-ending `.` stays outside.
    Falsifier: let the path swallow the `.`, or keep `<home>/wallets/...`."""
    out = _redact_own(text)
    assert out.endswith(tail), out
    assert "<home>" not in out, out
    assert out.count("<path>") == 1, out


def test_wallet_name_outside_a_path_is_a_collected_database_name():
    """AC: `Wallet_<NAME>` outside a path is `Wallet_<db-name-N>`; collect adds
    NAME to the database names, so `redact("PRODERP", known)` gives the same
    token. Falsifier: rely on the path rule alone."""
    mod = _redact_module()
    known = mod.collect(WALLET_NO_PATH)
    out = mod.redact(WALLET_NO_PATH, known)
    assert "PRODERP" not in out, out
    match = re.search(r"Wallet_(<db-name-\d+>)", out)
    assert match, out
    assert mod.redact("PRODERP", known) == match.group(1)
    assert out.endswith(" not found"), out


def test_names_collected_from_errors_are_replaced_in_unrelated_text():
    """AC: names collected from all the error texts are replaced elsewhere:
    `ERPPDB ERPSID PRODERP_HIGH acme_mon` is exactly three `<service-N>` tokens
    and one `<db-user-N>` (the alias, SID and service are service names; the
    ORA-01045 user is a database user; matching ignores case)."""
    mod = _redact_module()
    known = mod.collect("\n".join(ALL_TEXTS))
    out = mod.redact("ERPPDB ERPSID PRODERP_HIGH acme_mon", known)
    match = re.fullmatch(r"<service-(\d+)> <service-(\d+)> <service-(\d+)> <db-user-\d+>", out)
    assert match, out
    assert len(set(match.groups())) == 3, f"three names, three tokens: {out}"
    # Same name, same token: a second mention maps like the first.
    assert mod.redact("erppdb", known) == out.split()[0]


@pytest.mark.parametrize(
    ("text", "token", "absent"),
    [
        pytest.param("listener on prod-scan.corp.example is down", "<host>",
                     ["prod-scan.corp.example"], id="fqdn"),
        pytest.param("see db.corp.md", "<host>", ["db.corp.md"], id="tld-md-is-a-host"),
        pytest.param("reached 10.20.30.40 first", "<ip>", ["10.20.30.40"], id="ipv4"),
        # compressed form: a full one (`...:8a2e:370:7334`) also has the host:port:sid shape
        pytest.param("bound to 2001:db8::1 only", "<ip>", ["2001:db8"], id="ipv6"),
        pytest.param("url //prod-scan.corp.example:1521/ERPPDB failed", "<connect-string>",
                     ["prod-scan", "ERPPDB", "1521"], id="ezconnect-slashes"),
        pytest.param("url prod-scan.corp.example:1521/ERPPDB failed", "<connect-string>",
                     ["prod-scan", "ERPPDB", "1521"], id="ezconnect"),
        pytest.param("url erpdbhost:1521:ERPSID failed", "<connect-string>",
                     ["erpdbhost", "ERPSID"], id="host-port-sid"),
        pytest.param("tns (DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST=erpdbhost)(PORT=1521))"
                     "(CONNECT_DATA=(SERVICE_NAME=ERPPDB))) failed", "<connect-string>",
                     ["erpdbhost", "ERPPDB", "DESCRIPTION"], id="description-block"),
    ],
)
def test_hosts_addresses_and_connect_strings(text, token, absent):
    """AC: host names and FQDNs -> `<host>` (a dotted name ending in a delegated
    TLD such as `.md` is a host); IPv4 and IPv6 -> `<ip>`; connect strings
    (`//host:port/service`, `host:port/service`, `host:port:sid`,
    `(DESCRIPTION=...)`) -> `<connect-string>`."""
    out = _redact_own(text)
    assert token in out, out
    for name in absent:
        assert name not in out, f"{name!r} survived: {out}"


def test_text_that_only_looks_like_an_identifier_survives():
    """AC: version strings (`Release`/`Build`/`version` context, or a fifth
    dotted group), file names with a non-TLD file type, slash words that are
    not rooted paths, and doctor's probe commands survive unchanged, even with
    a populated `known`. Falsifiers: treat any `/` as a path start; treat
    every dotted quad as an address."""
    mod = _redact_module()
    known = mod.collect("\n".join(ALL_TEXTS))
    for text in [
        "TCP/IP", "read/write", "and/or", "@doctor_probe.sql", "host echo doctor-probe",
        "26.1.0.086.1709", "19.32.0.0.0",
        "SQLcl: Release 26.1.0.0 Production Build: 26.1.0.086.1709",
        "Oracle Database 19c Enterprise Edition Release 19.0.0.0.0 - Version 19.32.0.0.0",
        "tnsnames.ora", "sqlnet.ora", "doctor.json", "listener.log", "health.sql",
    ]:
        assert mod.redact(text, known) == text, text
    assert mod.redact("10.20.30.40", known) == "<ip>"


def test_home_alone_and_os_user():
    """AC: the home directory standing alone is `<home>`; the OS user name is
    `<os-user>`."""
    mod = _redact_module()
    user = getpass.getuser()
    text = f"{HOME} is the home of {user}"
    assert mod.redact(text, mod.collect(text)) == "<home> is the home of <os-user>"


# DBA-17 review: an absolute path whose folders hold spaces is still one `<path>`,
# whichever separator it uses. Found by review: `/` paths ended at the first space,
# so folders after it (a client's name) reached the bundle. Falsifier: let a folder
# hold spaces only before a `\`.

ICLOUD = ("ORA-17956: Unable to parse the wallet location supplied: Couldn't find file at "
          "/Users/u/Library/Mobile Documents/com~apple~CloudDocs/Clients/Acme/Wallet_PRODERP "
          "(CONNECTION_ID=NLAJIaGQRAWoCWrS3rX8Zw==)")
VOLUME = ("ORA-12154: Cannot connect to database. Could not find alias ERP_HIGH in "
          "/Volumes/Backup Disk/tns_acmeprod/tnsnames.ora.")
WINDOWS_SLASH = ("ORA-12263: Failed to access tnsnames.ora in the directory configured as TNS "
                 "admin: C:/Program Files/Oracle/tns_acmeprod. The file does not exist, or is "
                 "not accessible.")


@pytest.mark.parametrize("text, tail", [
    pytest.param(ICLOUD, "<path> (CONNECTION_ID=NLAJIaGQRAWoCWrS3rX8Zw==)", id="posix-icloud"),
    pytest.param(VOLUME, " in <path>.", id="posix-volume"),
    pytest.param(WINDOWS_SLASH, "admin: <path>. The file does not exist, or is not accessible.",
                 id="windows-forward-slash"),
])
def test_a_path_with_spaces_in_its_folders_is_one_path(text, tail):
    mod = _redact_module()
    out = mod.redact(text, mod.collect(text))
    for name in ("Acme", "acmeprod", "Clients", "Disk", "Oracle", "Files"):
        assert name not in out, f"{name!r} survived: {out}"
    assert out.endswith(tail), out
    assert out.count("<path>") == 1, out


@pytest.mark.parametrize("folder", ["Acme Corp. Ltd", " Acme Corp", "Acme`Corp"])
def test_a_windows_folder_takes_any_name_windows_allows(folder):
    """A `\\` folder keeps the full Windows rule: a sentence-like `. `, a leading
    space and a backtick stay inside the path."""
    mod = _redact_module()
    text = f"in C:\\A\\{folder}\\x.ora."
    assert mod.redact(text, mod.collect(text)) == "in <path>."


def test_a_command_line_keeps_its_options_between_two_paths():
    """A folder never ends in a space, so ` -home ` separates two paths; the one
    after `-home ` is the tier home (DBA-45), the SQLcl binary stays `<path>`."""
    mod = _redact_module()
    text = "start it as `/opt/sqlcl/bin/sql -home /Users/u/.pack/homes/read-only -R 4 -mcp`"
    assert mod.redact(text, mod.collect(text)) == (
        "start it as `<path> -home <tier-home> -R 4 -mcp`")


# --- DBA-45: three weak spots and the <tier-home> token ---------------------------

TIER_HOME_LINE = "run sql -home /Users/u/.pack/homes/read-only -R 4 -mcp by hand"
CORP_FOLDER = "at /data/Corp. Acme/wallet/cwallet.sso now"
ORA_12514_ERPDB = ("ORA-12514: Cannot connect to database. Service ERPDB is not registered with "
                   "the listener at host localhost port 1521.")


def test_a_slash_folder_holding_a_sentence_end_stays_inside_the_path():
    """AC (a): a `/` folder whose name holds `. ` does not end the path, so the
    rest of the path is hidden. The sentence-final cases (a path with no later
    `/`) are pinned by test_every_absolute_path_is_one_path_token_by_shape.
    Falsifier: restore `(?!\\.\\s)` in `_FOLDER`."""
    mod = _redact_module()
    assert mod.redact(CORP_FOLDER, mod.collect(CORP_FOLDER)) == "at <path> now"


def test_a_host_whose_first_label_is_a_known_name_keeps_no_domain():
    """AC (b): a fully qualified host whose first label was collected as a
    service is `<host>` whole; the bare name is still the service token.
    Falsifier: run `known.sub` before `_hosts` again."""
    mod = _redact_module()
    known = mod.collect(ORA_12514_ERPDB)
    out = mod.redact("listener on erpdb.acme.com is down; ERPDB is the service", known)
    assert out == "listener on <host> is down; <service-1> is the service", out


def test_collect_learns_the_database_name_of_a_wallet_inside_a_path():
    """AC (c): `collect` learns PRODERP from `Wallet_PRODERP` even where the
    wallet sits in a path (so `_wallets` never sees it during redaction). The
    bare name is redacted in its own call, before the wallet text, so
    `_wallets` cannot learn it and mask the mutation.
    Falsifier: remove `(_WALLET, "db-name")` from `_NAMED`."""
    mod = _redact_module()
    known = mod.collect(ORA_17956)
    assert mod.redact("PRODERP is down", known) == "<db-name-1> is down"


@pytest.mark.parametrize(("text", "expected"), [
    pytest.param(TIER_HOME_LINE, "run sql -home <tier-home> -R 4 -mcp by hand", id="posix"),
    pytest.param(r"sql -home C:\Users\u\.pack\homes\read-only -R 4 -mcp",
                 "sql -home <tier-home> -R 4 -mcp", id="windows"),
])
def test_the_path_after_dash_home_is_the_tier_home(text, expected):
    """AC (d): an absolute path directly after `-home ` is `<tier-home>`, not
    `<path>`. Falsifier: drop the `-home ` context rule."""
    mod = _redact_module()
    assert mod.redact(text, mod.collect(text)) == expected


def test_a_tier_home_path_without_dash_home_is_still_a_path():
    """AC (d): the rule is keyed to the `-home ` context, never to the value
    (D-DBA-17). Falsifier: map every path under `homes/` to `<tier-home>`."""
    mod = _redact_module()
    text = "no saved connection in /Users/u/.pack/homes/read-only"
    assert mod.redact(text, mod.collect(text)) == "no saved connection in <path>"


@pytest.fixture
def os_user(monkeypatch):
    """Set the OS user name for `_identity_patterns`, clearing its cache before
    and after so no other test sees the fake user."""
    mod = _redact_module()

    def set_user(name):
        monkeypatch.setattr(getpass, "getuser", lambda: name)
        mod._identity_patterns.cache_clear()

    yield set_user
    monkeypatch.undo()
    mod._identity_patterns.cache_clear()


# With the OS user `home`, the `-home` option word is itself the user name and
# reads `-<os-user>`: the user is hidden wherever it stands as a word. Only the
# token after it is in question here.
@pytest.mark.parametrize(("user", "expected"), [
    pytest.param("tier", "run sql -home <tier-home> -R 4 -mcp by hand", id="tier"),
    pytest.param("home", "run sql -<os-user> <tier-home> -R 4 -mcp by hand", id="home"),
])
def test_tier_home_token_survives_an_os_user_named_like_it(os_user, user, expected):
    """AC (d): no later step rewrites `<tier-home>`, even when the OS user is
    `tier` or `home`. Falsifier: leave `<tier-home>` out of `_TOKEN`, which
    gives `<<os-user>-home>` or `<tier-<os-user>>`."""
    os_user(user)
    mod = _redact_module()
    assert mod.redact(TIER_HOME_LINE, mod.collect("")) == expected


def test_contract_tier_home_token_and_path_rules():
    """Contract (DBA-45 output_for_dependents; no named consumer): shape only.
    `tools.redact.TIER_HOME == "<tier-home>"`, matched whole by `_TOKEN`;
    `redact(text, known)` signature unchanged; the two contract strings; and the
    decision record D-DBA-45-slash-folder-may-cross-a-sentence with a Status
    line. The README row is pinned in tests/unit/test_support_bundle.py."""
    mod = _redact_module()
    assert mod.TIER_HOME == "<tier-home>"
    assert mod._TOKEN.fullmatch(mod.TIER_HOME), mod._TOKEN.pattern
    assert list(inspect.signature(mod.redact).parameters) == ["text", "known"]
    assert mod.redact(TIER_HOME_LINE, mod.collect("")) == (
        "run sql -home <tier-home> -R 4 -mcp by hand")
    assert mod.redact(CORP_FOLDER, mod.collect("")) == "at <path> now"
    record = REPO_ROOT / "docs" / "decisions" / "D-DBA-45-slash-folder-may-cross-a-sentence.md"
    assert record.is_file(), f"missing {record.relative_to(REPO_ROOT)}"
    assert re.search(r"^\*\*Status:\*\* \S", record.read_text(), re.M), "no **Status:** line"

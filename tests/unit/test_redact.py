"""DBA-17: `redact(text, known)` and `collect(text, connections, db_users)` in
`tools/redact.py`, driven with SQLcl 26.3.1 connect-error texts verbatim (only
the names were changed) and with text that only looks like an identifier.

Tokens (issue DBA-17): `<host>`, `<ip>`, `<connect-string>`, `<path>`, `<home>`,
`<os-user>`, and `<connection-N>`, `<db-user-N>`, `<db-name-N>`, `<service-N>`
for names collected into `Known`, numbered consistently within one `Known`.
Known names match case-insensitively (`acme_mon` is the user `ACME_MON`).

The module does not exist yet, so it is imported inside the tests: each test
fails on its own instead of the file erroring at collection.
"""

import getpass
import importlib
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

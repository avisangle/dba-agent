"""DBA-17 review: connect errors as doctor reports them name hosts, services,
SIDs, TNS aliases and users. Texts are verbatim from SQLcl 26.3.1 against
Oracle 23ai Free, except the 19c ORA-01045 wording (Oracle's error reference);
only the names were changed."""

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.redact import collect, redact  # noqa: E402

CONNECT_ERRORS = [
    ("ORA-17868: Unknown host specified.: erpdbhost: nodename nor servname provided, "
     "or not known", "erpdbhost"),
    ("ORA-12154: Cannot connect to database. Could not find alias PRODERP_HIGH in "
     "/opt/tns/tnsnames.ora.", "PRODERP_HIGH"),
    ("ORA-01045: Login denied. User ACME_MON does not have CREATE SESSION privilege.",
     "ACME_MON"),
    ("ORA-01045: user ACME_MON lacks CREATE SESSION privilege; logon denied", "ACME_MON"),
    ("ORA-12505: Cannot connect to database. SID ERPSID is not registered with the "
     "listener at host localhost port 1521. (CONNECTION_ID=NLAJIaGQRAWoCWrS3rX8Zw==)",
     "ERPSID"),
    ("ORA-12514: Cannot connect to database. Service ERPPDB is not registered with the "
     "listener at host localhost port 1521. (CONNECTION_ID=orDQpeYDRbuCaw0971flBQ==)",
     "ERPPDB"),
    ("ORA-12541: Cannot connect. No listener at host erpdbhost port 1599. "
     "(CONNECTION_ID=+R9JZXPoSJyZW8ciiW9ikw==)", "erpdbhost"),
]


@pytest.mark.parametrize("text, name", CONNECT_ERRORS,
                         ids=["17868-host", "12154-alias", "01045-user-23ai", "01045-user-19c",
                              "12505-sid", "12514-service", "12541-host"])
def test_connect_error_names_are_redacted(text, name):
    out = redact(text, collect(text))
    assert name not in out, out
    assert out.startswith(text[:9]), out  # the ORA code survives


def test_names_from_connect_errors_are_redacted_in_any_other_text():
    """Collected names reach every file: `collect` runs on doctor's text, `redact`
    on each file."""
    known = collect("\n".join(t for t, _ in CONNECT_ERRORS))
    assert re.fullmatch(r"<service-\d+> <service-\d+> <service-\d+> <db-user-\d+>",
                        redact("ERPPDB ERPSID PRODERP_HIGH acme_mon", known))

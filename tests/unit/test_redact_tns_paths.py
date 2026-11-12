"""DBA-17 review: ORA-12154 and ORA-12263 name the TNS admin folder, which for an
Autonomous Database wallet is `Wallet_<DBNAME>`. Texts are verbatim from SQLcl
26.3.1; only the paths were changed."""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.redact import collect, redact  # noqa: E402

HOME = str(Path.home())


@pytest.mark.parametrize("text, kept", [
    (f"ORA-12154: Cannot connect to database. Could not find alias PRODERP_HIGH in "
     f"{HOME}/wallets/Wallet_PRODERP/tnsnames.ora.", "ORA-12154: Cannot connect"),
    ("ORA-12154: Cannot connect to database. Could not find alias PRODERP_HIGH in "
     r"C:\Program Files\Oracle\Wallet_PRODERP\tnsnames.ora.", "ORA-12154: Cannot connect"),
    ("ORA-12263: Failed to access tnsnames.ora in the directory configured as TNS admin: "
     "/opt/oracle/Wallet_PRODERP. The file does not exist, or is not accessible.",
     ". The file does not exist, or is not accessible."),
], ids=["12154-under-home", "12154-windows-spaces", "12263"])
def test_tns_admin_folder_is_redacted(text, kept):
    out = redact(text, collect(text))
    assert "PRODERP" not in out and "Oracle" not in out and "opt" not in out, out
    assert "<path>" in out and kept in out, out

"""DBA-17 review: an absolute path whose folders hold spaces is still one
`<path>`, whichever separator it uses. Found by review: `/` paths ended at the
first space, so folders after it (a client's name) reached the bundle.
Falsifier: let a folder hold spaces only before a `\\`."""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.redact import collect, redact  # noqa: E402

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
    out = redact(text, collect(text))
    for name in ("Acme", "acmeprod", "Clients", "Disk", "Oracle", "Files"):
        assert name not in out, f"{name!r} survived: {out}"
    assert out.endswith(tail), out
    assert out.count("<path>") == 1, out


def test_a_command_line_keeps_its_options_between_two_paths():
    """A folder never ends in a space, so ` -home ` separates two paths."""
    text = "start it as `/opt/sqlcl/bin/sql -home /Users/u/.pack/homes/read-only -R 4 -mcp`"
    assert redact(text, collect(text)) == "start it as `<path> -home <path> -R 4 -mcp`"

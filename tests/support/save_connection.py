"""Create a saved SQLcl connection in a home, with no terminal.

Pipes `conn -save` into `sql -home <home> /nolog`. Checked on macOS arm64 and
Linux aarch64 with SQLcl 26.3. The password travels on stdin, never in argv.
SQLcl exits 0 even when the logon fails, so success is read from its output.
"""

import subprocess


def save_connection(
    sql_bin: str, home: str, name: str, user: str, password: str, dsn: str, timeout: float = 120.0
) -> None:
    """Save `user` at `dsn` (host:port/service) as connection `name` in `home`."""
    script = f'conn -save {name} -savepwd {user}/"{password}"@//{dsn}\nexit\n'
    proc = subprocess.run(
        [sql_bin, "-home", str(home), "/nolog"],
        input=script, capture_output=True, text=True, timeout=timeout, check=False,
    )
    output = (proc.stdout + proc.stderr).replace(password, "***")
    if "\nConnected." not in output:
        raise RuntimeError(f"could not save connection {name!r} ({user}@{dsn}):\n{output[-2000:]}")

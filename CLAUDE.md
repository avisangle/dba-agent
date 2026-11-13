# CLAUDE.md

- Running or continuing the SQLcl MCP spike: follow `spike/HANDOFF.md` exactly; record results in `spike/RESULTS.md`.
- Python: always inside the repo's `.venv` (`source .venv/bin/activate && python ...`).
- Never commit credentials, wallets, saved SQLcl connections or `spike/work/`.
- User-facing tools are stdlib only: nothing under `tools/` imports a third-party package (`docs/decisions/D-DBA-2-python-stdlib-tools.md`).
- The pack name lives only in `PACK_NAME` in `tools/config.py`. Never write the literal name anywhere else; use the constant. One exception: `plugin/.claude-plugin/plugin.json`, which JSON cannot point at the constant; a unit test keeps the two equal (`docs/decisions/D-DBA-18-manifest-holds-pack-name.md`).
- Only non-production databases. The local throwaway Oracle 23ai Free test container started from `tests/docker-compose.yml` may be connected to without asking. Any other database needs the user's confirmation before connecting.

## Layout

| Path | Holds |
|---|---|
| `plugin/` | Claude Code plugin: `.claude-plugin/plugin.json`, `skills/`, `checks/<category>/<id>.sql`, `profiles/`, `config/` (MCP client snippets) |
| `tools/` | Python 3.10+ CLI, `python -m tools <command>`; one module per command in `tools/commands/` |
| `db/tiers/` | SQL templates for tier database users |
| `tests/unit/` | pytest unit tests, no database |
| `tests/integration/` | pytest tests marked `integration`, run against the test container through `sql -mcp` |
| `tests/support/` | Scripts the tests rely on, e.g. the AWR fixture generator |
| `.github/` | CI workflow and the SQLcl install script it uses |
| `docs/decisions/` | One architectural decision record per file |
| `spike/` | SQLcl MCP spike (frozen evidence) |

Each module in `tools/commands/` is a command, discovered automatically; the contract is in `tools/commands/__init__.py`.

## Commands

- Unit tests: `source .venv/bin/activate && pytest tests/unit`
- Integration tests: `source .venv/bin/activate && pytest -m integration`
- Test database, before integration tests: `docker compose -f tests/docker-compose.yml up -d --wait`, with `ORACLE_TEST_PASSWORD` set (`ORACLE_TEST_IMAGE` overrides the image).
- Integration tests read `SQLCL_BIN` (default `sql`), `ORACLE_TEST_DSN` (default `localhost:1521/FREEPDB1`) and `ORACLE_TEST_PASSWORD` (SYSTEM password, no default). Without SQLcl or the database they skip; `REQUIRE_INTEGRATION=1` makes them fail instead.
- Lint: `source .venv/bin/activate && ruff check . && python -m tools lint`

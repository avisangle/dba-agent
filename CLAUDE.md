# CLAUDE.md

- Running or continuing the SQLcl MCP spike: follow `spike/HANDOFF.md` exactly; record results in `spike/RESULTS.md`.
- Python: always inside the repo's `.venv` (`source .venv/bin/activate && python ...`).
- Never commit credentials, wallets, saved SQLcl connections or `spike/work/`.
- User-facing tools are stdlib only: nothing under `tools/` imports a third-party package (`docs/decisions/D-DBA-2-python-stdlib-tools.md`).
- The pack name lives only in `PACK_NAME` in `tools/config.py`. Never write the literal name anywhere else; use the constant.
- Only non-production databases. The local throwaway Oracle 23ai Free test container started from `tests/docker-compose.yml` may be connected to without asking. Any other database needs the user's confirmation before connecting.

## Layout

| Path | Holds |
|---|---|
| `plugin/` | Claude Code plugin: `skills/`, `checks/<category>/<id>.sql`, `profiles/` |
| `tools/` | Python 3.10+ CLI, `python -m tools <command>`; one module per command in `tools/commands/` |
| `db/tiers/` | SQL templates for tier database users |
| `tests/unit/` | pytest unit tests, no database |
| `tests/integration/` | pytest tests marked `integration`, run against the test container through `sql -mcp` |
| `docs/decisions/` | One architectural decision record per file |
| `spike/` | SQLcl MCP spike (frozen evidence) |

Each module in `tools/commands/` is a command, discovered automatically; the contract is in `tools/commands/__init__.py`.

## Commands

- Unit tests: `source .venv/bin/activate && pytest tests/unit`
- Integration tests: `source .venv/bin/activate && pytest -m integration`
- Lint: `source .venv/bin/activate && ruff check .`

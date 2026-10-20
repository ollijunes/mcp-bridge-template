# Changelog

## 0.1.0

- `collect`: a standard-library HTTP API that stores short notes in SQLite,
  with a bearer token and a health endpoint.
- `bridge`: an MCP server on the official Python SDK over Streamable HTTP,
  with `add_note`, `list_notes` and `collect_health` tools, its own bearer
  token and a health endpoint.
- Docker Compose with non-root, read-only containers, an internal network for
  collect and a localhost-only port for the bridge.
- Tests, a Compose smoke test in CI, Gitleaks and a privacy scan of the full
  history.
- Guides for connecting Claude Code, Codex CLI and the MCP Inspector.

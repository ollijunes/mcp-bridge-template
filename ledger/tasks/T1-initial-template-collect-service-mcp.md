# T1 Initial template: collect service, MCP bridge, Compose, tests and CI

- Status: done
- Lane: feat/initial-template-20261020
- Evidence: CI 12/12 with tests on Python 3.11–3.14 (Linux, macOS), the Compose smoke test, lint, secrets and ledger: https://github.com/ollijunes/mcp-bridge-template/actions/runs/39456078236

## Plan

Goal: a stdlib collect service (notes in SQLite) and an MCP bridge (official Python SDK, Streamable HTTP) with bearer tokens from the environment, health checks, Docker Compose with hardened containers, tests, CI with a Compose smoke test, README and security docs. Written from scratch; nothing copied from any private MCP setup.

Checks: pytest with 85 % coverage, ruff check and format, `scripts/check_public_tree.py`, gitleaks over the full history, Compose smoke test in CI.

# T1 Initial template: collect service, MCP bridge, Compose, tests and CI

- Status: doing
- Lane: feat/initial-template-20261020
- Evidence: —

## Plan

Goal: a stdlib collect service (notes in SQLite) and an MCP bridge (official Python SDK, Streamable HTTP) with bearer tokens from the environment, health checks, Docker Compose with hardened containers, tests, CI with a Compose smoke test, README and security docs. Written from scratch; nothing copied from any private MCP setup.

Checks: pytest with 85 % coverage, ruff check and format, `scripts/check_public_tree.py`, gitleaks over the full history, Compose smoke test in CI.

# mcp-bridge-template

## Goal

A minimal, readable template for running your own MCP server (the bridge) next to a small HTTP service (collect) with Docker Compose, bearer tokens from the environment, health checks and tests, for developers who want a working starting point they can read in one sitting. A release is finished when the tests, ruff and the Docker Compose smoke test pass in CI, `scripts/check_public_tree.py` and gitleaks report nothing, and the tree contains no real hostnames, addresses or tokens.

## Environments

Local only. `uv run pytest` runs the services in-process; `docker compose up` runs both containers on the developer's machine, with the bridge bound to 127.0.0.1. CI (`.github/workflows/ci.yml`) runs the tests on Linux and macOS with Python 3.11 to 3.14 and the Compose smoke test on Linux.

## Manual checks

Before a release, connect an MCP client (for example the MCP Inspector) to the bridge with a token, call each tool, and check that a request without the token is refused. Read the README quick start from a fresh clone and follow it exactly.

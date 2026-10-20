# Contributing

This is a template, so the bar for new features is high. A change should make
the template easier to understand, safer by default, or closer to how MCP
servers are built today. Bug fixes and corrections are always welcome.

```sh
uv sync --locked
uv run python -m pytest --cov=collect --cov=bridge --cov-fail-under=85
uv run ruff check .
uv run ruff format --check .
gitleaks git --redact --no-banner .
python3 scripts/check_public_tree.py
```

For changes to Docker or Compose, also run the smoke test:

```sh
cp .env.example .env   # then replace both tokens with real random values
docker compose up -d --build --wait
scripts/smoke_test.sh
docker compose down -v
```

## Rules

- Keep collect on the standard library. It is meant to be read in one go.
- Keep the bridge on the official MCP Python SDK.
- Tests use synthetic tokens they create themselves. Never read a real token
  from the environment in a test.
- Do not add real hostnames, IP addresses, domains or tokens anywhere, not
  even in a temporary commit. Use `example.com`, `127.0.0.1` and the Compose
  service names.
- Do not weaken the container settings, the token checks or the localhost
  binding to make something work. Explain the problem in an issue instead.

Use a public-safe Git author address. Report vulnerabilities through
[SECURITY.md](SECURITY.md), not a public issue.

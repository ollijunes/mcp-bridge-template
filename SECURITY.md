# Security

## Report a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/ollijunes/mcp-bridge-template/security/advisories/new).
Do not put a token, a hostname or a log from your own deployment in a public
issue. Describe the problem with the default configuration and include the
affected version.

## What the template does

- Two tokens. `BRIDGE_TOKEN` protects the MCP endpoint. `COLLECT_TOKEN`
  protects the collect API, which only the bridge calls. A client that has
  the bridge token cannot call collect directly.
- Tokens come from the environment. Nothing is baked into an image. Both
  services refuse to start when a token is missing or shorter than 32
  characters, and the error names the variable, not the value.
- Token checks use a constant-time comparison. A missing or wrong token gets
  HTTP 401 with a fixed body. Request headers are not logged.
- Collect is on an internal Docker network with no published port. The
  bridge publishes its port on `127.0.0.1` only.
- Containers run as a non-root user with a read-only root filesystem, no
  Linux capabilities and `no-new-privileges`. Only collect has a writable
  volume, for its SQLite file.
- Inputs are validated with size and character limits. Error messages are
  fixed and do not echo what was sent. The bridge does not pass collect's
  error bodies or stack traces to the MCP client.
- Health endpoints (`/healthz`) need no token and return only a status word.

## What it does not do

- No TLS. The bridge listens on plain HTTP on localhost. If you expose it to
  another machine, put a reverse proxy with TLS in front of it, or use a
  private network such as a VPN. Do not publish the port on `0.0.0.0`
  without one.
- No per-user accounts, scopes or rate limiting. Anyone with the bridge
  token can read and write every note. Add these before you connect it to
  data that matters.
- No token rotation. To rotate, put new values in `.env` and run
  `docker compose up -d` again; old tokens stop working when the containers
  restart.
- The notes database is not encrypted. Use disk encryption on the host and
  back up the volume if the notes matter.
- MCP clients pass what the model writes into tool calls. Treat everything a
  tool receives as untrusted input, and think about what a tool can change
  before you give it to a model.

## Repository hygiene

The repository contains no real hostnames, addresses or tokens. `.env` is
gitignored and `.env.example` holds placeholder values that fail the length
check on purpose. CI scans the full Git history with Gitleaks and with
`scripts/check_public_tree.py`, which looks for private network addresses,
home-directory paths, email addresses outside example domains and private
files such as `.env`. Automated scans support a manual review; they do not
prove that nothing private slipped in.

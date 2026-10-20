# Connect an MCP client

The bridge speaks MCP over Streamable HTTP at `http://127.0.0.1:8000/mcp`.
Every request needs the header `Authorization: Bearer <BRIDGE_TOKEN>`.

Keep the token out of shell history and out of files that you commit.
The examples below read it from an environment variable. Export it in the
terminal session where you run the client, for example from a password
manager:

```sh
export BRIDGE_TOKEN="$(your-password-manager read bridge-token)"
```

## Claude Code

```sh
claude mcp add --transport http notes http://127.0.0.1:8000/mcp \
  --header "Authorization: Bearer ${BRIDGE_TOKEN}"
```

This stores the expanded header value in your local Claude Code
configuration. To keep only a reference to the variable instead, add the
server to a project `.mcp.json` file:

```json
{
  "mcpServers": {
    "notes": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp",
      "headers": {
        "Authorization": "Bearer ${BRIDGE_TOKEN}"
      }
    }
  }
}
```

Claude Code expands `${BRIDGE_TOKEN}` when it starts. See the
[Claude Code MCP documentation](https://code.claude.com/docs/en/mcp).

## Codex CLI

```sh
codex mcp add notes --url http://127.0.0.1:8000/mcp --bearer-token-env-var BRIDGE_TOKEN
```

Codex stores the variable name, not the token, and reads the value when it
connects.

## MCP Inspector

The [MCP Inspector](https://github.com/modelcontextprotocol/inspector) is a
browser tool for trying servers by hand:

```sh
npx @modelcontextprotocol/inspector
```

Choose the Streamable HTTP transport, enter the URL, and add the
`Authorization` header with your token. Then list the tools and call
`collect_health`.

## Check it works

Ask your client to "add a note saying hello with the tag test", then to
"list my notes with the tag test". A request without the header gets
HTTP 401 from the bridge.

# Add your own tool

The template has one example service (collect) and three tools. To make it
yours, you usually replace collect with your own service and change the
tools to match. This page walks through adding one tool.

## 1. Add the endpoint to your service

In the template, collect is the service. Say you want a tool that deletes a
note. Add a `DELETE /notes/<id>` route in
[collect/collect_service.py](../collect/collect_service.py), behind the same
token check as the other routes, and a test for it in
[tests/test_collect.py](../tests/test_collect.py).

## 2. Add the tool to the bridge

In [bridge/bridge_server.py](../bridge/bridge_server.py), inside
`create_app()`, add a function with the `@server.tool()` decorator:

```python
@server.tool()
async def delete_note(note_id: int) -> dict:
    """Delete one note by its id."""
    return await collect.request("DELETE", f"/notes/{note_id}")
```

The function name becomes the tool name. The docstring is the description
the model sees, so write it for the model: what the tool does and when to use
it. The type hints become the input schema.

`collect.request` already sends the collect token, refuses redirects, times
out after five seconds and turns every failure into a fixed error message.
Extend its response check for the new path so the bridge only returns what
you expect.

## 3. Test it

Add a test in [tests/test_bridge.py](../tests/test_bridge.py) that calls the
tool through the MCP client against a collect server started in the test,
like the existing tests do. Then run:

```sh
uv run python -m pytest --cov=collect --cov=bridge --cov-fail-under=85
docker compose up -d --build --wait
scripts/smoke_test.sh
```

## Before you give a tool to a model

A tool runs whatever the model asks for, with the arguments it chooses.
Before you add one, decide:

- What is the worst thing a wrong call could do? Deleting, sending and paying
  deserve a confirmation step in your client, or should not be tools at all.
- Which inputs need limits? Validate in the service, not only in the bridge.
- What should the model never see? Return only the fields it needs.

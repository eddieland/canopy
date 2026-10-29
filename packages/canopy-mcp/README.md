# canopy-mcp

The MCP server protocol every server canopy ships speaks (D124): `canopy _mcp`, which serves the overseer's verbs, a
chore's history, canopy's reports, read-only git, and a run's card, and the local artifact store (`canopy-artifacts`).
It is a library, with no command of its own, and imports nothing from canopy, so the artifact store, which canopy never
imports, can serve through it too.

```python
import canopy_mcp

server = canopy_mcp.Server("canopy-artifacts", version, TOOLS, call=call, failed=failed)
canopy_mcp.serve(sys.stdin.buffer, write, server)
```

What it promises:

- **Tools and nothing else, over stdio.** JSON-RPC 2.0, one message to a line, and five methods: `initialize`,
  `notifications/initialized`, `ping`, `tools/list`, and `tools/call`. It opens no socket.
- **One account of each tool.** A `Tool` is its name, its description, its request, whose JSON schema is its input
  schema, its result, whose schema is its output schema, and its `Hints`, listed as MCP's tool annotations. Every
  schema has its references inlined and its titles left out, which some models' providers need.
- **Each server's own refusals.** A server says how a call is answered, a refusal included, and what a failure of its
  own tells the client. A line that is not JSON, a method it does not have, or a tool it does not list is a JSON-RPC
  error, and the server goes on serving.

`explain` says what was wrong with a tool's arguments, naming each field, never pydantic's copy of the input. A
validator's own message is passed on, so a validator echoes a value only for a short, bounded field, never free text.

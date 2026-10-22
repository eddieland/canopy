"""canopy's local artifact store (DESIGN §38): pages workers publish for people to read, and the comments on them.

`canopy-artifacts serve` serves the artifacts contract's tools over MCP on stdio, as Louvre serves them over HTTP, so a
skill written for one works against the other. The contract is this package's README.

canopy runs it as a command its runtime's MCP config names, and never imports it (D041). Stdlib, click (D025), and
pydantic, which validates every tool's arguments (D026), and nothing from canopy.
"""

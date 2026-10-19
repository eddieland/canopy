"""The agent runtime (DESIGN §13): everything canopy knows of OpenCode, and nothing about tickets.

How an agent is started, the events it prints, the format of canopy's agent definitions, and the files of the
runtime's own config that could loosen them. Nothing outside this package names the runtime's commands, environment
variables, files, or events (D009), so a new runtime, or a new major version of this one, is a change here and to the
command templates. There is still no adapter interface: one runtime at a time.
"""

"""Adapters: everything that touches the network, processes, disks or UI libraries.

The engine (all other packages) only depends on ports; `import-linter` enforces that. `server`
adapters run in the CLI and the local app, `browser` adapters inside Pyodide.
"""

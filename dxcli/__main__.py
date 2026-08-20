"""Enable `python -m dxcli`.

MCP clients launch servers in a bare environment where a virtualenv's
console script is often not on PATH; `<venv>/bin/python -m dxcli mcp`
always resolves.
"""

from .cli import main

if __name__ == "__main__":
    main()

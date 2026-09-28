"""Root-level entrypoint for the AURA MCP 2.0 Server (mcp_server.py).

Allows starting the stateless AURA MCP 2.0 server directly from the workspace root:
    python mcp_server.py --transport stdio
    python mcp_server.py --transport streamable-http --host 127.0.0.1 --port 8080
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from aura.mcp_server import create_aura_mcp_server, main  # noqa: E402

__all__ = ["create_aura_mcp_server", "main"]

if __name__ == "__main__":
    main()

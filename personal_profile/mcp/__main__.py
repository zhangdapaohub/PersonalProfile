"""python -m personal_profile.mcp → MCP stdio server 入口。"""

import sys

from personal_profile.mcp.server import main

if __name__ == "__main__":
    sys.exit(main())

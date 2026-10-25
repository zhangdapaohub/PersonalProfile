"""MCP 模块（Model Context Protocol server）。

把个人档案以标准 MCP 工具的形式暴露给任意 AI agent（WorkBuddy / Claude / Cursor 等）。
模块独立性约定：本包只允许 import personal_profile.core 与 paths，
禁止 import personal_profile.web / cli / ai（展示层与命令行与本模块互不依赖）。

入口：python -m personal_profile.mcp   （stdio 传输，协议为 newline-delimited JSON-RPC）
"""

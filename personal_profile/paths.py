"""路径单一事实来源：所有模块从这里取项目路径，禁止各自拼相对路径。"""

from __future__ import annotations

import os

# personal_profile/ 的上一级 = 项目根
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.path.join(ROOT, "data")
DATA_PATH = os.environ.get("PP_DATA") or os.path.join(DATA_DIR, "archive.json")
CONFIG_PATH = os.environ.get("PP_CONFIG") or os.path.join(DATA_DIR, "config.json")

# 运行日志目录（server.log / cli.log 等，自动轮转）
LOG_DIR = os.environ.get("PP_LOG_DIR") or os.path.join(ROOT, "logs")

# 维度模板（随包分发）
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "dimensions.json")

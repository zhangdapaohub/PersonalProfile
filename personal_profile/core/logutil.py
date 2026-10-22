"""统一日志：零第三方依赖，文件自动轮转 + 控制台同步输出。

用法：
    from personal_profile.core.logutil import get_logger
    log = get_logger("web")     # 写入 logs/web.log
    log.info("...")             # 同时输出到控制台

设计要点：
- 各子系统独立日志文件（web / cli / core），互不干扰，便于追溯。
- RotatingFileHandler：单文件默认 2MB，保留 5 个历史（server.log.1 ...）。
- 控制台仅输出 INFO 及以上，文件记录 DEBUG 及以上（含堆栈）。
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from personal_profile.paths import LOG_DIR

_FMT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES = 2 * 1024 * 1024
_BACKUP_COUNT = 5

_configured: set[str] = set()


def get_logger(name: str, console: bool = True) -> logging.Logger:
    """取子系统 logger（name 即日志文件名，如 "web" → logs/web.log）。

    console=False 时只写文件（CLI 用：避免日志混入命令输出）。
    """
    logger = logging.getLogger("pp." + name)
    if name in _configured:
        return logger
    _configured.add(name)

    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    fmt = logging.Formatter(_FMT, datefmt=_DATEFMT)

    os.makedirs(LOG_DIR, exist_ok=True)
    fh = RotatingFileHandler(
        os.path.join(LOG_DIR, f"{name}.log"),
        maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    if console:
        sh = logging.StreamHandler(sys.stderr)
        sh.setLevel(logging.INFO)
        sh.setFormatter(fmt)
        logger.addHandler(sh)

    return logger

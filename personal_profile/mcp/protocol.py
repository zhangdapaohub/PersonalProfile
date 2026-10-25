"""MCP stdio 协议层：newline-delimited JSON-RPC 2.0 的编解码与错误码。

职责单一：只做消息的读/写/封装，不含任何业务逻辑。
- 每条消息一行 UTF-8 JSON（MCP stdio 传输规范），读写均不缓冲堆积。
- 输出只允许经过 write_message 走 stdout；任何日志/诊断一律走 stderr，
  否则会污染协议流导致宿主解析失败。
"""

from __future__ import annotations

import json
import sys
from typing import Any, Optional, TextIO

# 协议版本（initialize 时若客户端带版本则回显客户端版本，否则用本值）
PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "personal-profile", "version": "1.0.0"}

# JSON-RPC 2.0 标准错误码
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def read_message(fp: TextIO) -> Optional[dict]:
    """读一条消息。返回 None 表示流结束（EOF）；
    解析失败返回 {"__parse_error__": 原始行} 交由上层回 -32700。

    Windows 关键：真实 stdio 一律走二进制层强制 UTF-8 解码——
    文本层默认跟随系统 locale（中文 Windows=GBK），宿主按 UTF-8 解必乱码。
    """
    buf = getattr(fp, "buffer", None)
    if buf is not None:  # 真实 stdio：二进制读 + UTF-8 解码
        raw = buf.readline()
        if not raw:
            return None
        line = raw.decode("utf-8", errors="replace").strip()
    else:  # 测试注入的 StringIO 等文本流
        line = fp.readline()
        if not line:
            return None
        line = line.strip()
    if not line:  # 空行容错跳过
        return {}
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        return {"__parse_error__": line}
    return msg if isinstance(msg, dict) else {"__parse_error__": line}


def write_message(msg: dict, fp: Optional[TextIO] = None) -> None:
    """写一条消息（单行 UTF-8 JSON + 换行 + flush；不 flush 宿主会一直等）。

    Windows 关键：输出走二进制层以 UTF-8 编码，绕开文本层的 GBK locale——
    否则 tools/list 的中文描述到宿主手里就是乱码。
    """
    data = (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")
    if fp is None:
        buf = sys.stdout.buffer
    else:
        buf = getattr(fp, "buffer", None)
        if buf is None:  # 测试注入的文本流退回文本写
            fp.write(json.dumps(msg, ensure_ascii=False) + "\n")
            fp.flush()
            return
    buf.write(data)
    buf.flush()


def result_response(msg_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def error_response(msg_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def tool_result(payload: Any) -> dict:
    """把工具返回值包装成 MCP tools/call 的标准结果（content[].text 承载 JSON）。"""
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "isError": False,
    }


def tool_error(message: str) -> dict:
    """工具执行失败：按 MCP 规范用 isError 结果在带内返回，消息可直接给 AI 看。"""
    return {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }

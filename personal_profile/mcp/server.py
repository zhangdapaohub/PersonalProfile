"""MCP server 装配层：工具 schema 注册表 + JSON-RPC 分发 + 主循环。

不实现写类工具（写统一走 web API 单写者）；新增工具只需：
1) 在 tools.py 加纯函数并登记 HANDLERS；
2) 在本文件 TOOLS_SCHEMA 加同名 schema。
"""

from __future__ import annotations

import sys
from typing import Any

from personal_profile.core.logutil import get_logger
from personal_profile.mcp import protocol as proto
from personal_profile.mcp.tools import HANDLERS, new_archive

logger = get_logger("mcp", console=False)  # 日志落 logs/mcp.log；绝不污染 stdout

PERSON_ARG = {
    "person": {"type": "string", "description": "人物 id 或唯一人物名（先用 pp_list_persons 查）"},
}
SNAP_ARG = {
    "snapshot_id": {"type": "string", "description": "快照 id（可选，缺省=最新时间态）"},
}

# 首批 6 个只读工具的 schema（对 AI 的自描述入口）
TOOLS_SCHEMA = [
    {
        "name": "pp_list_persons",
        "description": "列出档案库中的全部人物（id/名称/快照数/最新时间态）。做个性化查询前先调用它确定 person。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "pp_get_profile",
        "description": "取某人物某时间态的全量档案值（合并继承后的 resolved 视图，含每项的值来源快照）。个性化需求的主查询：称呼、偏好、健康数据、技能、关系等一律先查这里。",
        "inputSchema": {"type": "object", "properties": {**PERSON_ARG, **SNAP_ARG},
                        "required": ["person"], "additionalProperties": False},
    },
    {
        "name": "pp_query_path",
        "description": "按维度路径精准取值（省 token）。paths 支持精确路径或前缀：\"inbody\" 命中整个健康子树，\"mental.tendency.preferences\" 取单条。",
        "inputSchema": {"type": "object",
                        "properties": {**PERSON_ARG, **SNAP_ARG,
                                       "paths": {"type": "array", "items": {"type": "string"},
                                                 "description": "路径或前缀数组"}},
                        "required": ["person", "paths"], "additionalProperties": False},
    },
    {
        "name": "pp_timeline",
        "description": "取某人物的时间轴概览（各快照的时间/标签/继承关系/可见值数量 + 链接统计）。用于「他在某时期是什么样」「他变了吗」类问题。",
        "inputSchema": {"type": "object", "properties": {**PERSON_ARG},
                        "required": ["person"], "additionalProperties": False},
    },
    {
        "name": "pp_search",
        "description": "按关键词模糊搜索档案值（命中 path/展示名/值文本）。不确定指标叫什么时用它先定位。",
        "inputSchema": {"type": "object",
                        "properties": {**PERSON_ARG, **SNAP_ARG,
                                       "keyword": {"type": "string", "description": "如 体重 / 高考 / 咖啡"}},
                        "required": ["person", "keyword"], "additionalProperties": False},
    },
    {
        "name": "pp_qbank_progress",
        "description": "提问库答题进度（按领域统计已答/未答）+ 未答指标样例。用于引导用户补全档案（个性化数据缺失时推荐用户去 /qbank 页面作答）。",
        "inputSchema": {"type": "object", "properties": {**PERSON_ARG, **SNAP_ARG},
                        "required": ["person"], "additionalProperties": False},
    },
]


def _tool_names() -> set:
    return {t["name"] for t in TOOLS_SCHEMA}


def handle_message(msg: dict) -> dict | None:
    """处理一条协议消息，返回应答（通知类/无需应答返回 None）。

    异常边界：工具内部错误按 MCP 规范转 isError 带内结果；
    协议级错误（未知方法/参数非法）回 JSON-RPC error。
    """
    if "__parse_error__" in msg:
        return proto.error_response(None, proto.PARSE_ERROR, "请求不是合法 JSON")
    method = msg.get("method")
    msg_id = msg.get("id")
    if not method:
        return proto.error_response(msg_id, proto.INVALID_REQUEST, "缺少 method")

    if method == "initialize":
        requested = (msg.get("params") or {}).get("protocolVersion")
        return proto.result_response(msg_id, {
            "protocolVersion": requested if isinstance(requested, str) else proto.PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": proto.SERVER_INFO,
        })
    if method == "notifications/initialized" or method.startswith("notifications/"):
        return None  # 通知不回包
    if method == "ping":
        return proto.result_response(msg_id, {})
    if method == "tools/list":
        return proto.result_response(msg_id, {"tools": TOOLS_SCHEMA})
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        if name not in _tool_names() or name not in HANDLERS:
            return proto.result_response(
                msg_id, proto.tool_error(f"未知工具: {name}（可用: {', '.join(sorted(_tool_names()))}）"))
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return proto.result_response(msg_id, proto.tool_error("arguments 必须为对象"))
        try:
            payload = HANDLERS[name](new_archive(), args)
            logger.info("tools/call %s args=%s -> ok", name, args)
            return proto.result_response(msg_id, proto.tool_result(payload))
        except Exception as e:  # 业务错误/意外异常都转为带内结果，消息可给 AI 看
            logger.exception("tools/call %s args=%s -> error", name, args)
            return proto.result_response(msg_id, proto.tool_error(str(e)))

    if msg_id is not None:
        return proto.error_response(msg_id, proto.METHOD_NOT_FOUND, f"未知方法: {method}")
    return None  # 未知通知静默


def main() -> int:
    """stdio 主循环：读一行处理一行；EOF/Ctrl+C 正常退出。"""
    logger.info("MCP server 启动（stdio, tools=%d）", len(TOOLS_SCHEMA))
    try:
        while True:
            msg = proto.read_message(sys.stdin)
            if msg is None:  # EOF
                break
            if not msg:  # 空行
                continue
            resp = handle_message(msg)
            if resp is not None:
                proto.write_message(resp)
    except (KeyboardInterrupt, BrokenPipeError):
        pass
    finally:
        logger.info("MCP server 退出")
    return 0

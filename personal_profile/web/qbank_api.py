"""提问库 API（独立路由，与展示类 API 完全隔离）。

约定：本模块只认 /api/qbank 前缀；server.py 仅做一行委托，不掺和题库逻辑。
数据流：前端 → qbank_api（用题库定义补全 name/unit）→ Archive.set_value 落库。

路由：
  GET  /api/qbank/tree?person=&snapshot=   题库树 + 每指标作答状态与当前值
  GET  /api/qbank/progress?person=&snapshot=  领域级进度（零状态推导）
  POST /api/qbank/answer                   提交答案 {person, snapshot?, path, value,
                                           new_snapshot?, timestamp?, label?}
"""

from __future__ import annotations

import datetime as _dt
from urllib.parse import parse_qs

from personal_profile.core import qbank
from personal_profile.core.store import Archive, ArchiveError


def _qs(u_query: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(u_query).items() if v}


def _answered_paths(archive: Archive, pid: str, sid: str) -> set[str]:
    """已答 = 该快照合并视图（本态+继承）中出现过的 path。"""
    return set(archive.resolved_leaves(pid, sid).keys())


def _require_snapshot(archive: Archive, q: dict) -> tuple[str, str]:
    try:
        pid, sid = q["person"], q["snapshot"]
    except KeyError as e:
        raise ValueError(f"缺少查询参数: {e}") from e
    archive._person(pid)          # 校验存在性（复用 store 校验与报错文案）
    archive._snapshot(pid, sid)
    return pid, sid


def _tree(archive: Archive, q: dict) -> tuple[int, dict]:
    pid, sid = _require_snapshot(archive, q)
    answered = _answered_paths(archive, pid, sid)
    current = archive.resolved_leaves(pid, sid)
    qbk = qbank.load_qbank()

    domains = []
    for dom in qbk.get("domains", []):
        dims = []
        for dim in dom.get("dimensions", []):
            metrics = []
            for m in dim.get("metrics", []):
                metrics.append({
                    "path": m["path"], "name": m.get("name"), "type": m.get("type"),
                    "input": m.get("input"), "unit": m.get("unit"),
                    "options": m.get("options"), "volatile": bool(m.get("volatile")),
                    "perspective": m.get("perspective", "self"),
                    "q": m.get("q", {}),
                    "answered": m["path"] in answered,
                    "current": current.get(m["path"]),
                })
            dims.append({"key": dim["key"], "name": dim.get("name") or dim["key"], "metrics": metrics})
        domains.append({"key": dom["key"], "name": dom.get("name") or dom["key"], "dimensions": dims})

    return 200, {
        "kind": "qbank-tree",
        "version": qbk.get("version"), "label": qbk.get("label"),
        "person": pid, "snapshot": sid,
        "progress": qbank.progress(qbk, answered),
        "domains": domains,
    }


def _progress(archive: Archive, q: dict) -> tuple[int, dict]:
    pid, sid = _require_snapshot(archive, q)
    answered = _answered_paths(archive, pid, sid)
    return 200, {
        "kind": "qbank-progress", "person": pid, "snapshot": sid,
        **qbank.progress(qbank.load_qbank(), answered),
    }


def _answer(archive: Archive, b: dict) -> tuple[int, dict]:
    pid = b.get("person")
    path = b.get("path")
    if not pid or not path:
        raise ValueError("缺少 person 或 path")
    if "value" not in b:
        raise ValueError("缺少 value（允许空字符串，但不允许缺字段）")

    metrics = qbank.metric_index()
    metric = metrics.get(path)
    if metric is None:
        raise ArchiveError(f"未注册的指标 path: {path}")

    # volatile 指标允许「新建时间态采集」：先建快照再写入
    sid = b.get("snapshot")
    created = None
    if b.get("new_snapshot") or not sid:
        today = _dt.date.today().isoformat()
        # 显式继承当前最新快照：同日多次采集也能衔接（store 默认只认「严格早于」）
        snaps = archive.list_snapshots(pid)  # 已按 timestamp 升序
        parent = snaps[-1]["id"] if snaps else None
        new_sid = archive.add_snapshot(
            pid,
            b.get("timestamp") or today,  # store 仅接受 ISO 日期
            b.get("label") or f"问答采集 {today}",
            inherits_from=parent,
        )
        created = archive.get_snapshot(pid, new_sid)
        sid = created["id"]

    payload = qbank.answer_payload(metric, b["value"])
    # 注意 set_value 签名：(..., value, unit, name) —— unit 在前
    leaf = archive.set_value(pid, sid, payload["path"], payload["value"],
                             payload.get("unit"), payload.get("name"))
    archive.save()
    return 200, {
        "kind": "qbank-answered", "person": pid, "snapshot": sid,
        "path": path, "leaf": leaf,
        "created_snapshot": created,
        "metric": {"name": metric.get("name"), "volatile": bool(metric.get("volatile"))},
    }


def route(archive: Archive, method: str, path: str, u_query: str, body: dict | None) -> tuple[int, dict] | None:
    """入口：非 /api/qbank 前缀返回 None（交回展示路由）；命中则返回 (code, payload)。"""
    if not path.startswith("/api/qbank"):
        return None
    try:
        if method == "GET" and path == "/api/qbank/tree":
            return _tree(archive, _qs(u_query))
        if method == "GET" and path == "/api/qbank/progress":
            return _progress(archive, _qs(u_query))
        if method == "POST" and path == "/api/qbank/answer":
            return _answer(archive, body or {})
        return 404, {"error": f"unknown qbank api: {method} {path}"}
    except ArchiveError as e:
        return 400, {"error": str(e)}
    except (qbank.QbankError, ValueError) as e:
        return 400, {"error": str(e)}

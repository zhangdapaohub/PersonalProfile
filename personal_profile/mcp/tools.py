"""MCP 工具实现：6 个只读工具。

独立性约束（工程红线）：
- 只 import personal_profile.core（store/qbank）与 paths，禁止 import web/cli/ai；
- 只调用 Archive 的读方法（list_persons / list_snapshots / resolved_leaves /
  resolve_trace / get_snapshot），全模块不出现 save()/set_*/add_*/del_*，
  从代码层面保证 MCP 永不写盘（写统一走 web API 单写者）。
- 每次调用新建 Archive 重新 load()：数据文件很小，换来的是对 CLI/Web 写入的
  实时可见（无缓存陈旧问题）。
"""

from __future__ import annotations

from personal_profile.core import qbank
from personal_profile.core.store import Archive, ArchiveError
from personal_profile.paths import DATA_PATH


def new_archive() -> Archive:
    """每次调用全新加载：读到的永远是磁盘最新状态。"""
    return Archive(DATA_PATH).load()


def _resolve_person(archive: Archive, ref: str) -> dict:
    """person 参数兼容「人物 id」或「唯一人物名」，对 AI 更友好。"""
    if not ref:
        raise ArchiveError("缺少 person 参数（人物 id 或名称）")
    p = archive.db["persons"].get(ref)
    if p is not None:
        return p
    hits = [p for p in archive.db["persons"].values() if p["name"] == ref]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise ArchiveError(f"人物名不唯一: {ref}（请改用 identity_id）")
    raise ArchiveError(f"人物不存在: {ref}")


def _resolve_snapshot(archive: Archive, pid: str, snapshot_id: str | None) -> dict:
    """缺省取最新快照（timestamp 最大）；显式给 id 则校验存在。"""
    snaps = archive.list_snapshots(pid)  # 已按 timestamp 升序
    if not snaps:
        raise ArchiveError(f"该人物还没有任何快照: {pid}")
    if snapshot_id is None:
        return snaps[-1]
    for s in snaps:
        if s["id"] == snapshot_id:
            return s
    raise ArchiveError(f"快照不存在: {snapshot_id}（person={pid}）")


def _row(path: str, item: dict) -> dict:
    """trace 条目 → 对 AI 紧凑的一行值。"""
    leaf = item.get("leaf") or {}
    row = {
        "path": path,
        "name": leaf.get("name") or path.rsplit(".", 1)[-1],
        "value": leaf.get("value"),
    }
    if leaf.get("unit"):
        row["unit"] = leaf["unit"]
    row["source"] = item.get("source")  # 值来源快照 id（AI 可区分「现在的他/过去的他」）
    return row


# ---------------- 6 个工具 ----------------

def t_list_persons(archive: Archive, args: dict) -> dict:
    persons = []
    for p in archive.list_persons():
        snaps = archive.list_snapshots(p["identity_id"])
        latest = {"id": snaps[-1]["id"], "timestamp": snaps[-1]["timestamp"],
                  "label": snaps[-1]["label"]} if snaps else None
        persons.append({**p, "latest_snapshot": latest})
    return {"persons": persons}


def t_get_profile(archive: Archive, args: dict) -> dict:
    """个性化主查询：一次拿全某时间态的全量 resolved 值（含来源标注）。"""
    p = _resolve_person(archive, args.get("person"))
    pid = p["identity_id"]
    snap = _resolve_snapshot(archive, pid, args.get("snapshot_id"))
    trace = archive.resolve_trace(pid, snap["id"])
    profile = {path: _row(path, item) for path, item in trace.items()}
    return {
        "person": {"id": pid, "name": p["name"]},
        "snapshot": {"id": snap["id"], "timestamp": snap["timestamp"], "label": snap["label"]},
        "total": len(profile),
        "profile": profile,
    }


def t_query_path(archive: Archive, args: dict) -> dict:
    """精准取数：paths 支持精确 path 或前缀（如 "inbody" 命中 inbody 整个子树）。"""
    paths = args.get("paths")
    if not isinstance(paths, list) or not paths:
        raise ArchiveError("paths 必须为非空字符串数组（支持精确 path 或前缀，如 \"inbody\"）")
    p = _resolve_person(archive, args.get("person"))
    pid = p["identity_id"]
    snap = _resolve_snapshot(archive, pid, args.get("snapshot_id"))
    trace = archive.resolve_trace(pid, snap["id"])

    rows = {}
    for want in paths:
        if not isinstance(want, str) or not want:
            raise ArchiveError("paths 元素必须为非空字符串")
        for path, item in trace.items():
            if path == want or path.startswith(want + "."):
                rows[path] = _row(path, item)
    return {
        "person": {"id": pid, "name": p["name"]},
        "snapshot": {"id": snap["id"], "timestamp": snap["timestamp"], "label": snap["label"]},
        "matched": len(rows),
        "rows": rows,
    }


def t_timeline(archive: Archive, args: dict) -> dict:
    p = _resolve_person(archive, args.get("person"))
    pid = p["identity_id"]
    snaps = []
    for s in archive.list_snapshots(pid):
        snaps.append({
            "id": s["id"], "timestamp": s["timestamp"], "label": s["label"],
            "inherits_from": s["inherits_from"],
            "own_overrides": len(s["overrides"]),
            "visible": len(archive.resolved_leaves(pid, s["id"])),
        })
    type_count: dict = {}
    for lk in p["continuity_links"]:
        type_count[lk["type"]] = type_count.get(lk["type"], 0) + 1
    return {
        "person": {"id": pid, "name": p["name"]},
        "snapshots": snaps,
        "links_total": len(p["continuity_links"]),
        "links_by_type": type_count,
    }


def t_search(archive: Archive, args: dict) -> dict:
    """模糊找指标：关键词命中 path / 展示名 / 值文本。"""
    kw = (args.get("keyword") or "").strip()
    if not kw:
        raise ArchiveError("缺少 keyword")
    p = _resolve_person(archive, args.get("person"))
    pid = p["identity_id"]
    snap = _resolve_snapshot(archive, pid, args.get("snapshot_id"))
    trace = archive.resolve_trace(pid, snap["id"])

    rows = []
    for path, item in trace.items():
        leaf = item.get("leaf") or {}
        hay = " ".join([path, str(leaf.get("name") or ""), str(leaf.get("value"))])
        if kw.lower() in hay.lower():
            rows.append(_row(path, item))
    return {
        "person": {"id": pid, "name": p["name"]},
        "snapshot": {"id": snap["id"], "timestamp": snap["timestamp"], "label": snap["label"]},
        "keyword": kw, "matched": len(rows), "rows": rows,
    }


def t_qbank_progress(archive: Archive, args: dict) -> dict:
    """提问库进度（口径与 Web 一致：已答 = 该时间态合并视图出现过的 path）。"""
    p = _resolve_person(archive, args.get("person"))
    pid = p["identity_id"]
    snap = _resolve_snapshot(archive, pid, args.get("snapshot_id"))
    answered = set(archive.resolved_leaves(pid, snap["id"]).keys())
    qbk = qbank.load_qbank()
    prog = qbank.progress(qbk, answered)

    # 给 AI 一份「可直接引导用户补答」的缺口样例（带问题文本，最多 15 条）
    missing_sample = []
    for m in qbank.iter_metrics(qbk):
        if m["path"] not in answered:
            missing_sample.append({"path": m["path"], "name": m.get("name"),
                                   "domain": m.get("domain_name")})
            if len(missing_sample) >= 15:
                break
    return {
        "person": {"id": pid, "name": p["name"]},
        "snapshot": {"id": snap["id"], "timestamp": snap["timestamp"], "label": snap["label"]},
        **prog,
        "missing_sample": missing_sample,
    }


# 工具注册表：name → (handler, 一句话描述)。schema 定义在 server.py（与描述同处维护）。
HANDLERS = {
    "pp_list_persons": t_list_persons,
    "pp_get_profile": t_get_profile,
    "pp_query_path": t_query_path,
    "pp_timeline": t_timeline,
    "pp_search": t_search,
    "pp_qbank_progress": t_qbank_progress,
}

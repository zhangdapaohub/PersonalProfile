"""CLI 子命令：参数定义 + handler + 输出渲染。

新增命令三步：
1) 写 handler(archive, args) -> payload（payload 带 kind 字段）；
2) build_parser() 里 add_parser + set_defaults(func=...)；
3) 如需 --pretty 专属渲染，在 render_text() 加分支。
"""

from __future__ import annotations

import argparse
import json

from personal_profile.ai.collector import get_collector
from personal_profile.core.config import load_config
from personal_profile.core.store import INHERIT_REQUIRED_LINKS, LINK_TYPES, ArchiveError
from personal_profile.paths import DATA_PATH


# ---------- 工具 ----------

def parse_value(raw: str):
    """--value 解析：优先按 JSON（支持数字/布尔/列表），失败按原始字符串。"""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


def parse_parent(raw: str):
    """--parent 解析：'none' 表示清除继承（改为独立根态）。"""
    raw = (raw or "").strip().lower()
    return None if raw in ("none", "null", "") else raw


# ---------- handlers ----------

def cmd_add_person(a, args):
    pid = a.add_person(args.name, args.id)
    a.save()
    return {"kind": "person", "identity_id": pid, "name": args.name}


def cmd_rename_person(a, args):
    p = a.rename_person(args.person, args.name)
    a.save()
    return {"kind": "person", "identity_id": args.person, "name": p["name"], "note": "已重命名"}


def cmd_rename_snapshot(a, args):
    snap = a.rename_snapshot(args.person, args.snapshot, args.label)
    a.save()
    return {"kind": "snapshot", "person": args.person, "snapshot": args.snapshot,
            "label": snap["label"], "note": "已重命名"}


def cmd_del_person(a, args):
    p = a.get_person(args.person)
    if not args.yes:
        print(f"确认删除人物「{p['name']}」({args.person}) 及其全部快照与链接？此操作不可恢复。")
        if input("输入 yes 确认: ").strip().lower() != "yes":
            return {"kind": "person", "cancelled": True, "note": "已取消删除",
                    "identity_id": args.person, "name": p["name"]}
    removed = a.delete_person(args.person)
    a.save()
    return {"kind": "person", "identity_id": args.person, "name": removed["name"], "note": "已删除"}


def cmd_list_persons(a, args):
    return {"kind": "persons", "persons": a.list_persons()}


def cmd_export_person(a, args):
    data = a.export_person(args.person)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return {"kind": "export", "person": args.person, "file": args.out,
                "name": data["person"]["name"], "snapshot_count": len(data["person"]["snapshots"]),
                "link_count": len(data["links"]), "note": f"已导出至 {args.out}"}
    return {"kind": "export-json", "data": data}


def cmd_import_person(a, args):
    with open(args.file, "r", encoding="utf-8") as f:
        data = json.load(f)
    res = a.import_person(data)
    a.save()
    return {"kind": "import", **res}


def cmd_add_snapshot(a, args):
    sid = a.add_snapshot(args.person, args.timestamp, args.label, args.inherits_from, args.id, break_chain=args.break_chain)
    a.save()
    snap = a.get_snapshot(args.person, sid)
    return {
        "kind": "snapshot",
        "snapshot_id": sid,
        "person": args.person,
        "timestamp": args.timestamp,
        "label": args.label,
        "inherits_from": snap["inherits_from"],
    }


def cmd_set_inherits(a, args):
    parent = parse_parent(args.parent)
    snap = a.set_inherits(args.person, args.snapshot, parent)
    a.save()
    return {
        "kind": "inherits",
        "person": args.person,
        "snapshot": args.snapshot,
        "inherits_from": snap["inherits_from"],
        "note": "已改为独立根态" if parent is None else f"继承关系已建立: {args.snapshot} → {parent}",
    }


def cmd_del_snapshot(a, args):
    snap = a.get_snapshot(args.person, args.snapshot)
    if not args.yes:
        print(f"确认删除快照「{snap.get('label')}」({args.snapshot}，person={args.person}) 及其相关链接？"
              f"继承链将自动衔接。此操作不可恢复。")
        if input("输入 yes 确认: ").strip().lower() != "yes":
            return {"kind": "snapshot", "cancelled": True, "note": "已取消删除",
                    "identity_id": args.person, "snapshot_id": args.snapshot}
    removed = a.delete_snapshot(args.person, args.snapshot)
    a.save()
    return {"kind": "snapshot", "snapshot_id": args.snapshot, "person": args.person,
            "label": removed.get("label"), "note": "已删除（继承链已衔接）"}


def cmd_set(a, args):
    leaf = a.set_value(
        args.person, args.snapshot, args.path, parse_value(args.value), args.unit, args.name
    )
    a.save()
    return {"kind": "value", "person": args.person, "snapshot": args.snapshot,
            "path": args.path, "leaf": leaf}


def cmd_get(a, args):
    leaf = a.resolve_value(args.person, args.snapshot, args.path)
    if leaf is None:
        raise ArchiveError(f"未找到值（本态与继承链均未设置）: {args.path}")
    return {"kind": "value", "person": args.person, "snapshot": args.snapshot,
            "path": args.path, "leaf": leaf}


def cmd_del_value(a, args):
    removed = a.del_value(args.person, args.snapshot, args.path)
    a.save()
    return {"kind": "deleted", "person": args.person, "snapshot": args.snapshot,
            "path": args.path, "removed": removed,
            "note": "本态覆盖已删；父态值（若有）重新生效"}


def cmd_break(a, args):
    snap = a.set_break(args.person, args.snapshot, args.path, not args.off)
    a.save()
    return {"kind": "break", "person": args.person, "snapshot": args.snapshot,
            "path": args.path, "on": not args.off, "broken": snap["broken"],
            "note": f"{'已断裂' if not args.off else '已恢复继承'}: {args.path}"}


def cmd_order(a, args):
    order = [p.strip() for p in args.order.split(",") if p.strip()]
    snap = a.set_order(args.person, args.snapshot, order)
    a.save()
    return {"kind": "order", "person": args.person, "snapshot": args.snapshot,
            "order": snap["order"], "note": "展示顺序已更新"}


def cmd_tree(a, args):
    return {**a.tree(args.person), "kind": "tree"}


def cmd_links(a, args):
    return {"kind": "links", "person": args.person, "links": a.list_links(args.person)}


def cmd_add_link(a, args):
    lid = a.add_link(
        args.person, args.from_, args.to, args.type, args.note or "",
        from_path=args.from_path, to_path=args.to_path,
    )
    a.save()
    return {"kind": "link", "link_id": lid, "person": args.person,
            "from": args.from_, "from_path": args.from_path,
            "to": args.to, "to_path": args.to_path,
            "type": args.type, "note": args.note or ""}


def cmd_rm_link(a, args):
    removed = a.rm_link(args.person, args.link)
    a.save()
    return {"kind": "link", "removed": removed, "note": "删除链接不级联删除快照"}


def cmd_collect(a, args):
    try:
        if args.collector == "openai-compatible":
            cfg = load_config()
            if not cfg.get("base_url") or not cfg.get("model"):
                raise ArchiveError(
                    "尚未配置模型：请先填写 data/config.json（base_url/model/api_key），"
                    "或在 Web 端『AI 采集 → 模型设置』保存"
                )
            collector = get_collector(args.collector, cfg)
        else:
            collector = get_collector(args.collector)
    except ValueError as e:
        raise ArchiveError(str(e))
    context = {
        "person": args.person,
        "snapshot": args.snapshot,
        "resolved": a.resolved_leaves(args.person, args.snapshot),
    }
    updates = collector.collect(args.prompt, context)
    if not isinstance(updates, dict):
        raise ArchiveError("collector 返回必须为 {path: value} 字典")
    applied, errors = {}, []
    for path, value in updates.items():
        try:
            applied[path] = a.set_value(args.person, args.snapshot, path, value)
        except ArchiveError as e:
            errors.append({"path": path, "error": str(e)})
    if applied:
        a.save()
    return {"kind": "collect", "person": args.person, "snapshot": args.snapshot,
            "collector": args.collector, "applied": applied, "errors": errors,
            "note": None if (applied or errors) else "模型未抽取到任何字段"}


# ---------- parser ----------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="personal-profile",
        description="个人档案系统 CLI（python -m personal_profile <command>）",
    )

    # 共享参数：挂在每个子命令上，使 --data/--pretty 放在命令前后均可
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--data", default=DATA_PATH,
        help="archive.json 路径（默认项目根 data/archive.json，可用环境变量 PP_DATA 覆盖）",
    )
    common.add_argument("--pretty", action="store_true", help="人类可读输出（默认 JSON，供 AI 解析）")

    sub = parser.add_subparsers(dest="command", required=True)

    def _p(name, help_, func):
        sp = sub.add_parser(name, help=help_, parents=[common])
        sp.set_defaults(func=func)
        return sp

    p = _p("add-person", "新增人物", cmd_add_person)
    p.add_argument("--name", required=True, help="人物名")
    p.add_argument("--id", help="identity_id（默认自动生成 p_xxx）")

    _p("list-persons", "列出所有人物", cmd_list_persons)

    p = _p("export-person", "导出人物为 JSON 文件（--out 指定路径，缺省打印到标准输出）", cmd_export_person)
    p.add_argument("--person", required=True, help="identity_id")
    p.add_argument("--out", help="导出文件路径（如 张三.json）；缺省打印 JSON 到标准输出")

    p = _p("import-person", "从 JSON 文件导入一整个人物（含全部快照与链接）", cmd_import_person)
    p.add_argument("--file", required=True, help="导出 JSON 文件路径")

    p = _p("rename-person", "重命名人物", cmd_rename_person)
    p.add_argument("--person", required=True, help="identity_id")
    p.add_argument("--name", required=True, help="新名称")

    p = _p("del-person", "删除人物（含全部快照与链接，不可恢复）", cmd_del_person)
    p.add_argument("--person", required=True, help="identity_id")
    p.add_argument("--yes", action="store_true", help="跳过交互确认（危险操作）")

    p = _p("add-snapshot", "新增时间快照（默认继承时间轴上一个；--inherits-from 指定父态，--break 显式建为独立根态）", cmd_add_snapshot)
    p.add_argument("--person", required=True, help="identity_id")
    p.add_argument("--timestamp", required=True, help="ISO 日期 YYYY-MM-DD")
    p.add_argument("--label", required=True, help="该时间态标签（如 '20岁的张三'）")
    p.add_argument("--inherits-from", help="父快照 id（默认自动继承上一个；不再接受 none，建独立根态请用 --break）")
    p.add_argument("--break", dest="break_chain", action="store_true", help="显式建为独立根态（不继承任何快照）")
    p.add_argument("--id", help="snapshot_id（默认自动生成 s_xxx）")

    p = _p("set-inherits", "给已存在的快照设置/修改/清除继承关系（--parent none 清除）", cmd_set_inherits)
    p.add_argument("--person", required=True, help="identity_id")
    p.add_argument("--snapshot", required=True, help="要修改的快照 id")
    p.add_argument("--parent", required=True, help="父快照 id；传 none 表示清除继承（改为独立根态）")

    p = _p("del-snapshot", "删除时间快照（含相关链接，继承链自动衔接，不可恢复）", cmd_del_snapshot)
    p.add_argument("--person", required=True, help="identity_id")
    p.add_argument("--snapshot", required=True, help="要删除的快照 id")
    p.add_argument("--yes", action="store_true", help="跳过交互确认（危险操作）")

    p = _p("rename-snapshot", "修改快照标签（仅展示名，不影响 id/继承链/链接）", cmd_rename_snapshot)
    p.add_argument("--person", required=True, help="identity_id")
    p.add_argument("--snapshot", required=True, help="快照 id")
    p.add_argument("--label", required=True, help="新标签")

    p = _p("set", "写值（copy-on-write，只写本态 overrides；path 可为模板外自由维度）", cmd_set)
    p.add_argument("--person", required=True)
    p.add_argument("--snapshot", required=True)
    p.add_argument("--path", required=True, help="维度路径，如 physical.body_shape.height")
    p.add_argument("--value", required=True, help='标量或 JSON 列表（如 \'["a","b"]\'）')
    p.add_argument("--unit", help="单位（可选）")
    p.add_argument("--name", help="展示名（可选；默认取模板名或 path 末段）")

    p = _p("get", "取值（沿 inherits_from 链合并解析）", cmd_get)
    p.add_argument("--person", required=True)
    p.add_argument("--snapshot", required=True)
    p.add_argument("--path", required=True)

    p = _p("del-value", "删本态 overrides 的值（父态值重新生效）", cmd_del_value)
    p.add_argument("--person", required=True)
    p.add_argument("--snapshot", required=True)
    p.add_argument("--path", required=True)

    p = _p("break", "属性级断裂：在本态标记某属性不再继承（--off 取消，恢复继承）", cmd_break)
    p.add_argument("--person", required=True, help="identity_id")
    p.add_argument("--snapshot", required=True, help="快照 id")
    p.add_argument("--path", required=True, help="维度路径，如 physical.body_shape.height")
    p.add_argument("--off", action="store_true", help="取消断裂（恢复继承）")

    p = _p("order", "设置某快照卡项内属性值的展示顺序（逗号分隔的 path 列表）", cmd_order)
    p.add_argument("--person", required=True, help="identity_id")
    p.add_argument("--snapshot", required=True, help="快照 id")
    p.add_argument("--order", required=True, help="path 列表，逗号分隔，如 a.b,c.d（仅影响显示排序）")

    p = _p("tree", "时间轴视图（默认视图：快照按时间排列 + 合并叶子 + 链接）", cmd_tree)
    p.add_argument("--person", required=True)

    p = _p("links", "列出某人的连贯性链接", cmd_links)
    p.add_argument("--person", required=True)

    p = _p("add-link", "新增连贯性链接（属性级：快照A的某属性 ↔ 快照B的某属性）", cmd_add_link)
    p.add_argument("--person", required=True)
    p.add_argument("--from", dest="from_", required=True, help="起始快照 id")
    p.add_argument("--from-path", required=True, help="起始属性维度路径，如 mental.tendency.preferences")
    p.add_argument("--to", required=True, help="目标快照 id")
    p.add_argument("--to-path", required=True, help="目标属性维度路径")
    p.add_argument("--type", required=True, help=f"链接类型：{'/'.join(LINK_TYPES)}")
    p.add_argument("--note", help="说明（可选）")

    p = _p("rm-link", "删除连贯性链接（不级联删快照）", cmd_rm_link)
    p.add_argument("--person", required=True)
    p.add_argument("--link", required=True, help="link_id")

    p = _p("collect", "AI 采集：prompt → {path:value} 落库", cmd_collect)
    p.add_argument("--person", required=True)
    p.add_argument("--snapshot", required=True)
    p.add_argument("--prompt", required=True)
    p.add_argument("--collector", default="stub", help="采集器（stub / openai-compatible）")

    return parser


# ---------- --pretty 渲染 ----------

def _fmt_leaf(leaf: dict) -> str:
    unit = f" {leaf['unit']}" if leaf.get("unit") else ""
    return f"{leaf['value']}{unit}"


def render_text(payload: dict) -> str:
    """--pretty 人类可读渲染；未专门处理的 kind 回退 JSON。"""
    kind = payload.get("kind")
    if kind == "tree":
        lines = [f"{payload['person']['name']} ({payload['person']['identity_id']})", "-" * 46]
        for s in payload["snapshots"]:
            inh = s["inherits_from"] or "独立根态"
            lines.append(
                f"[{s['timestamp']}] {s['label']}  ({s['id']}, 继承自: {inh}, 本态覆盖 {s['own_overrides']} 项)"
            )
            for path, leaf in sorted(s["resolved"].items()):
                lines.append(f"    {path} = {_fmt_leaf(leaf)}")
            lines.append("")
        lines.append("连贯性链接:")
        for lk in payload["continuity_links"]:
            note = f"  {lk['note']}" if lk.get("note") else ""
            lines.append(f"  {lk['link_id']}  {lk['from']} → {lk['to']}  [{lk['type']}]{note}")
        return "\n".join(lines)
    if kind == "value":
        return f"{payload['path']} = {_fmt_leaf(payload['leaf'])}"
    if kind == "deleted":
        return f"已删除 {payload['path']}（原值: {payload['removed']['value']}）；{payload['note']}"
    if kind == "inherits":
        return f"{payload['snapshot']} 的继承关系: {payload['inherits_from'] or '独立根态'}（{payload['note']}）"
    if kind == "snapshot":
        if payload.get("cancelled"):
            return f"已取消删除 {payload.get('snapshot_id', '')}"
        note = payload.get("note", "")
        return f"{note} {payload.get('label', '')} ({payload.get('snapshot_id', '')})".strip()
    if kind == "person":
        note = payload.get("note", "")
        return f"{note} {payload.get('name', '')} ({payload.get('identity_id', '')})".strip()
    if kind == "persons":
        lines = [
            f"{p['identity_id']}  {p['name']}  (快照 {p['snapshot_count']}, 链接 {p['link_count']})"
            for p in payload["persons"]
        ]
        return "\n".join(lines) or "(无人物)"
    if kind == "export":
        return (f"{payload['note']}\n"
                f"人物: {payload['name']} ({payload['person']})\n"
                f"快照 {payload['snapshot_count']} 个，链接 {payload['link_count']} 条")
    if kind == "import":
        suffix = "（id 冲突，已自动重映射并更名）" if payload.get("renamed") else ""
        return (f"已导入人物: {payload['name']} ({payload['identity_id']}){suffix}\n"
                f"快照 {payload['snapshot_count']} 个，链接 {payload['link_count']} 条")
    if kind == "links":
        lines = [
            f"{lk['link_id']}  {lk['from']}.{lk.get('from_path', '')} → {lk['to']}.{lk.get('to_path', '')}  [{lk['type']}]"
            + (f"  {lk['note']}" if lk.get("note") else "")
            for lk in payload["links"]
        ]
        return "\n".join(lines) or "(无链接)"
    if kind == "break":
        return f"{payload['note']}（当前 broken: {', '.join(payload['broken']) or '无'}）"
    if kind == "order":
        return f"{payload['note']}（顺序: {', '.join(payload['order']) or '默认'}）"
    return json.dumps(payload, ensure_ascii=False, indent=2)

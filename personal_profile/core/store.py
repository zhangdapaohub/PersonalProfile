"""PersonalProfile 核心存储层。

唯一的读写入口：所有端（CLI / Web / 未来新端）都经过 Archive 操作数据，
保证增量解析、path 派生与持久化逻辑一致。

数据模型（定稿见 docs/data-model.md）：
  Person → Snapshot(inherits_from + overrides 扁平 path→叶子) + continuity_links
  - 读取沿 inherits_from 链合并（子覆盖父）
  - 写入 copy-on-write：只写本态 overrides，绝不回写父态
  - path 不落库，由 key 链按 `.` 切分派生（本态直查天然 O(1)）
"""

from __future__ import annotations

import copy
import datetime
import json
import os
import tempfile
import uuid
from typing import Any, Optional

from personal_profile.paths import SCHEMA_PATH

# 连贯性链接语义（属性级关系；扩展时只需在此追加）。
# 注意：「断裂」不再是链接类型——它是「属性级中断继承」动作（见 Snapshot.broken），
# 标记记录在属性当前所在的快照上：本态仍显示，从下一个快照起不再继承显示。
LINK_TYPES = ("继承", "因果", "主动重塑")

# 需要 to 态确实继承自 from 态的链接类型
INHERIT_REQUIRED_LINKS = ("继承", "因果")

EMPTY_DB: dict = {"persons": {}}

# 叶子 value 允许的类型：标量 + 标量列表（暂不嵌套对象）
_SCALARS = (str, int, float, bool)


class ArchiveError(Exception):
    """业务错误：消息可直接展示给调用方（CLI/AI）。"""


def _gen_id(prefix: str, existing: set) -> str:
    """短码 id 自动生成 + 冲突重试。"""
    for _ in range(16):
        new_id = f"{prefix}_{uuid.uuid4().hex[:8]}"
        if new_id not in existing:
            return new_id
    raise ArchiveError("自动生成 id 失败（冲突过多），请用 --id 手动指定")


def _validate_path(path: str) -> str:
    if not path or not isinstance(path, str):
        raise ArchiveError("path 不能为空")
    if any(not seg for seg in path.split(".")):
        raise ArchiveError(f"path 格式非法（存在空段）: {path}")
    return path


def _validate_value(value: Any) -> Any:
    if value is None:
        raise ArchiveError("value 不能为 null（未设置即无值）")
    if isinstance(value, list):
        if not value:
            raise ArchiveError("列表 value 不能为空")
        if not all(isinstance(v, _SCALARS) for v in value):
            raise ArchiveError("列表 value 只能包含标量元素")
        return value
    if isinstance(value, _SCALARS):
        return value
    raise ArchiveError(f"value 类型不支持: {type(value).__name__}（支持标量与标量列表）")


class Archive:
    """档案库：加载/保存 + 全部业务操作。所有端共用。"""

    def __init__(self, data_path: str):
        self.data_path = data_path
        self.db: dict = copy.deepcopy(EMPTY_DB)
        self._template: Optional[dict] = None

    # ================= 持久化 =================

    def load(self) -> "Archive":
        if os.path.exists(self.data_path):
            with open(self.data_path, "r", encoding="utf-8") as f:
                self.db = json.load(f)
            self.db.setdefault("persons", {})
        else:
            self.db = copy.deepcopy(EMPTY_DB)
        self._migrate()
        return self

    def _migrate(self) -> None:
        """向后兼容迁移（幂等，仅在确有变化时落盘）：
        - 为旧快照补齐 broken / order 字段；
        - 旧版「断裂」类型链接 → 属性级断裂：在 to 态的 to_path 上标记 broken，
          并移除该链接（断裂本就不是一种关联）。
        """
        import shutil

        dirty = False
        # 迁移前先判断是否存在旧版「断裂」链接（用于决定是否备份真实数据）
        has_legacy_break = any(
            lk.get("type") == "断裂"
            for p in self.db.get("persons", {}).values()
            for lk in p.get("continuity_links", [])
        )
        for p in self.db.get("persons", {}).values():
            for s in p.get("snapshots", {}).values():
                if "broken" not in s:
                    s["broken"] = []
                    dirty = True
                if "order" not in s:
                    s["order"] = []
                    dirty = True
            # 旧版「断裂」链接 → 属性级断裂（记录在属性当前所在的 from 快照，
            # 效果：from 的下一个快照起不再继承显示）
            old_links = p.get("continuity_links", [])
            new_links = []
            for lk in old_links:
                if lk.get("type") == "断裂":
                    frm_id, frm_path = lk.get("from"), lk.get("from_path")
                    snap = p.get("snapshots", {}).get(frm_id)
                    if snap and frm_path:
                        broken = snap.setdefault("broken", [])
                        if frm_path not in broken:
                            broken.append(frm_path)
                        dirty = True
                    # 该链接不再作为关联存在
                else:
                    new_links.append(lk)
            if len(new_links) != len(old_links):
                p["continuity_links"] = new_links
                dirty = True
        if dirty:
            # 迁移前先备份一次真实数据（仅当确有旧断裂链接要转换时）
            bak = self.data_path + ".pre-break-migrate.bak"
            if has_legacy_break and not os.path.exists(bak):
                try:
                    shutil.copy2(self.data_path, bak)
                except OSError:
                    pass
            self.save()

    def save(self) -> None:
        """原子写：先写临时文件再 replace，避免写坏数据。"""
        dir_ = os.path.dirname(os.path.abspath(self.data_path))
        os.makedirs(dir_, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.db, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.data_path)
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    # ================= 内部工具 =================

    def _person(self, person_id: str) -> dict:
        p = self.db["persons"].get(person_id)
        if p is None:
            raise ArchiveError(f"人物不存在: {person_id}")
        return p

    def _snapshot(self, person_id: str, snapshot_id: str) -> dict:
        p = self._person(person_id)
        s = p["snapshots"].get(snapshot_id)
        if s is None:
            raise ArchiveError(f"快照不存在: {snapshot_id}（person={person_id}）")
        return s

    def _chain(self, person: dict, snapshot_id: str) -> list:
        """从 snapshot_id 沿 inherits_from 上溯到根，返回 [本态...根态]（成环报错）。"""
        chain: list = []
        seen: set = set()
        sid: Optional[str] = snapshot_id
        while sid is not None:
            if sid in seen:
                raise ArchiveError(f"inherits_from 链成环: {snapshot_id}")
            seen.add(sid)
            s = person["snapshots"].get(sid)
            if s is None:
                break
            chain.append(s)
            sid = s["inherits_from"]
        return chain

    def _template_name(self, path: str) -> Optional[str]:
        """从维度模板取 path 对应展示名；模板缺失或自由维度返回 None。"""
        if self._template is None:
            try:
                with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
                    self._template = json.load(f)
            except OSError:
                self._template = {}
        node: Any = None
        children: Any = self._template  # 模板顶层键即第一段维度，之后逐层 children
        for seg in path.split("."):
            if not isinstance(children, dict) or seg not in children:
                return None
            node = children[seg]
            children = node.get("children") if isinstance(node, dict) else None
        name = node.get("name") if isinstance(node, dict) else None
        return name if isinstance(name, str) else None

    # ================= Person =================

    def add_person(self, name: str, identity_id: Optional[str] = None) -> str:
        if not name:
            raise ArchiveError("name 不能为空")
        if identity_id is None:
            identity_id = _gen_id("p", self.db["persons"])
        if identity_id in self.db["persons"]:
            raise ArchiveError(f"identity_id 已存在: {identity_id}")
        self.db["persons"][identity_id] = {
            "identity_id": identity_id,
            "name": name,
            "snapshots": {},
            "continuity_links": [],
        }
        return identity_id

    def list_persons(self) -> list:
        return [
            {
                "identity_id": p["identity_id"],
                "name": p["name"],
                "snapshot_count": len(p["snapshots"]),
                "link_count": len(p["continuity_links"]),
            }
            for p in self.db["persons"].values()
        ]

    def get_person(self, person_id: str) -> dict:
        return self._person(person_id)

    def rename_person(self, person_id: str, name: str) -> dict:
        p = self._person(person_id)
        if not name:
            raise ArchiveError("name 不能为空")
        p["name"] = name
        return p

    def rename_snapshot(self, person_id: str, snapshot_id: str, label: str) -> dict:
        """修改快照标签（仅展示名，不影响 id / 继承链 / 链接端点）。"""
        snap = self._snapshot(person_id, snapshot_id)
        if not label or not label.strip():
            raise ArchiveError("label 不能为空")
        snap["label"] = label.strip()
        return snap

    def delete_person(self, person_id: str) -> dict:
        """删除人物及其全部快照与连贯性链接（不可恢复）。"""
        p = self._person(person_id)
        del self.db["persons"][person_id]
        return p

    def export_person(self, person_id: str) -> dict:
        """导出整个人物（含全部快照与链接）为自包含 JSON，便于备份 / 迁移 / 跨端导入。"""
        p = self._person(person_id)
        return {
            "format": "personal-profile/person",
            "version": 1,
            "person": {
                "identity_id": p["identity_id"],
                "name": p["name"],
                "snapshots": [
                    {
                        "id": s["id"],
                        "timestamp": s["timestamp"],
                        "label": s["label"],
                        "inherits_from": s["inherits_from"],
                        "overrides": copy.deepcopy(s["overrides"]),
                        "broken": copy.deepcopy(s.get("broken", [])),
                        "order": copy.deepcopy(s.get("order", [])),
                    }
                    for s in p["snapshots"].values()
                ],
            },
            "links": copy.deepcopy(p["continuity_links"]),
        }

    def import_person(self, data: dict) -> dict:
        """从导出 JSON 导入一整个人物（含全部快照与链接）。

        与现有人物 identity_id 冲突时，自动重新生成 id（人物 + 全部快照 + 链接端点统一重映射），
        并将名称追加「 (导入)」以示区分，避免覆盖已有数据。返回导入结果摘要。
        """
        if not isinstance(data, dict):
            raise ArchiveError("导入数据必须是 JSON 对象")
        person = data.get("person")
        if not isinstance(person, dict) or not person.get("name"):
            raise ArchiveError("导入数据缺少 person.name")
        snapshots = person.get("snapshots")
        if not isinstance(snapshots, list) or not snapshots:
            raise ArchiveError("导入数据必须包含至少一个快照（person.snapshots）")

        desired_id = person.get("identity_id")
        remap = bool(desired_id and desired_id in self.db["persons"])
        pid = desired_id if (desired_id and not remap) else _gen_id("p", self.db["persons"])
        name = person["name"]
        if remap:
            name = f"{name} (导入)"

        # 快照 id 重映射：old -> new（仅冲突时整体重映射，避免继承链断裂）
        mapping: dict = {}
        new_snaps: dict = {}
        for s in snapshots:
            if not isinstance(s, dict) or not s.get("id"):
                raise ArchiveError("快照缺少 id 字段")
            try:
                datetime.date.fromisoformat(s["timestamp"])
            except (TypeError, ValueError):
                raise ArchiveError(f"快照 timestamp 非法: {s.get('timestamp')}")
            old_id = s["id"]
            new_id = old_id if not remap else _gen_id("s", set(new_snaps))
            mapping[old_id] = new_id
            new_snaps[new_id] = {
                "id": new_id,
                "timestamp": s["timestamp"],
                "label": s.get("label") or "",
                "inherits_from": None,  # 稍后按映射表回填
                "overrides": copy.deepcopy(s.get("overrides") or {}),
                "broken": copy.deepcopy(s.get("broken") or []),
                "order": copy.deepcopy(s.get("order") or []),
            }
        # 回填 inherits_from（继承链保持原结构）
        for s in snapshots:
            parent = s.get("inherits_from")
            new_snaps[mapping[s["id"]]]["inherits_from"] = mapping.get(parent) if parent else None

        # 链接端点重映射（端点缺失则跳过该链接）
        new_links = []
        seen_lids: set = set()
        for lk in (data.get("links") or []):
            if not isinstance(lk, dict):
                continue
            # 旧版「断裂」链接在导入时同样转为属性级断裂（记录在 from 快照，不再作为关联）
            if lk.get("type") == "断裂":
                frm = mapping.get(lk.get("from"))
                frm_path = lk.get("from_path")
                if frm and frm_path:
                    broken = new_snaps[frm].setdefault("broken", [])
                    if frm_path not in broken:
                        broken.append(frm_path)
                continue
            frm = mapping.get(lk.get("from"))
            to = mapping.get(lk.get("to"))
            if not frm or not to:
                continue
            link_id = lk.get("link_id")
            if not link_id or link_id in seen_lids or remap:
                link_id = _gen_id("l", seen_lids)
            seen_lids.add(link_id)
            new_links.append({
                "link_id": link_id,
                "from": frm, "from_path": lk.get("from_path", ""),
                "to": to, "to_path": lk.get("to_path", ""),
                "type": lk.get("type", "继承"),
                "note": lk.get("note", ""),
            })

        self.db["persons"][pid] = {
            "identity_id": pid,
            "name": name,
            "snapshots": new_snaps,
            "continuity_links": new_links,
        }
        return {
            "identity_id": pid, "name": name, "renamed": remap,
            "snapshot_count": len(new_snaps), "link_count": len(new_links),
        }

    # ================= Snapshot =================

    def add_snapshot(
        self,
        person_id: str,
        timestamp: str,
        label: str,
        inherits_from: Optional[str] = None,
        snapshot_id: Optional[str] = None,
        break_chain: bool = False,
    ) -> str:
        """新增时间快照。

        继承关系规则（默认「自动继承上一个」，兼顾可覆盖/可断开）：
        - inherits_from 显式给定 → 以该快照为父（校验存在）；
        - 否则 break_chain=True → 显式建为独立根态（inherits_from=None）；
        - 否则（默认）→ 自动继承该人物时间轴上 timestamp 紧邻且小于当前的最大快照，
          若无更早快照则成为根态。
        插入后若处于两个已有快照之间，会把原本继承「本态前驱」的紧邻下一个快照改挂到
        本态，使「继承上一个」在时间轴变动后仍成立（显式指定其他父态的快照不被改动）。
        """
        p = self._person(person_id)
        try:
            datetime.date.fromisoformat(timestamp)
        except (TypeError, ValueError):
            raise ArchiveError(f"timestamp 需为 ISO 日期 YYYY-MM-DD: {timestamp}")
        if not label:
            raise ArchiveError("label 不能为空")
        if inherits_from is None and not break_chain:
            # 默认：自动继承时间轴上紧邻的上一个（timestamp 严格小于当前的最大值）
            prev = None
            for s in p["snapshots"].values():
                if s["timestamp"] < timestamp:
                    if prev is None or s["timestamp"] > prev["timestamp"]:
                        prev = s
            inherits_from = prev["id"] if prev else None
        if inherits_from is not None and inherits_from not in p["snapshots"]:
            raise ArchiveError(f"父快照不存在: {inherits_from}")
        if snapshot_id is None:
            snapshot_id = _gen_id("s", p["snapshots"])
        if snapshot_id in p["snapshots"]:
            raise ArchiveError(f"snapshot_id 已存在: {snapshot_id}")
        p["snapshots"][snapshot_id] = {
            "id": snapshot_id,
            "timestamp": timestamp,
            "label": label,
            "inherits_from": inherits_from,
            "overrides": {},
            "broken": [],
            "order": [],
        }
        # 插入「中间」快照时，维持「每个快照继承时间轴上紧邻的上一个」这一语义：
        # 若紧邻下一个快照 N 当前正继承自本快照的前驱，则把它改挂到本快照。
        # 显式指定了其他父态（N.inherits_from != 前驱）的快照不受影响。
        prev_by_time = None
        nxt = None
        for s in p["snapshots"].values():
            if s["id"] == snapshot_id:
                continue
            if s["timestamp"] < timestamp:
                if prev_by_time is None or s["timestamp"] > prev_by_time["timestamp"]:
                    prev_by_time = s
            elif s["timestamp"] > timestamp:
                if nxt is None or s["timestamp"] < nxt["timestamp"]:
                    nxt = s
        if (prev_by_time is not None and nxt is not None
                and nxt["inherits_from"] == prev_by_time["id"]):
            nxt["inherits_from"] = snapshot_id
        return snapshot_id

    def set_inherits(self, person_id: str, snapshot_id: str, parent_id: Optional[str]) -> dict:
        """给已存在的快照设置 / 修改 / 清除继承关系（parent_id=None 改为独立根态）。

        校验：父快照存在、不能继承自身、不能形成环（父态祖先链含自身即拒绝）。
        """
        p = self._person(person_id)
        snap = self._snapshot(person_id, snapshot_id)
        if parent_id is not None:
            if parent_id == snapshot_id:
                raise ArchiveError(f"快照不能继承自身: {snapshot_id}")
            self._snapshot(person_id, parent_id)  # 父必须存在
            sid: Optional[str] = parent_id
            while sid is not None:
                if sid == snapshot_id:
                    raise ArchiveError(
                        f"设置继承将成环: {parent_id} 的祖先链已包含 {snapshot_id}"
                    )
                s = p["snapshots"].get(sid)
                if s is None:
                    break
                sid = s["inherits_from"]
        snap["inherits_from"] = parent_id
        return snap

    def get_snapshot(self, person_id: str, snapshot_id: str) -> dict:
        return self._snapshot(person_id, snapshot_id)

    def list_snapshots(self, person_id: str) -> list:
        """时间轴视图（默认视图）：按 timestamp 升序。"""
        p = self._person(person_id)
        return sorted(p["snapshots"].values(), key=lambda s: s["timestamp"])

    def delete_snapshot(self, person_id: str, snapshot_id: str) -> dict:
        """删除快照（时间轴节点）及其相关链接；继承链自动衔接（原本继承自它的子态改挂到它的父态）。

        不可恢复。
        """
        p = self._person(person_id)
        snap = self._snapshot(person_id, snapshot_id)
        parent = snap.get("inherits_from")
        del p["snapshots"][snapshot_id]
        # 级联删除引用该快照的连贯性链接
        p["continuity_links"] = [
            lk for lk in p["continuity_links"]
            if lk["from"] != snapshot_id and lk["to"] != snapshot_id
        ]
        # 继承链衔接：原本继承自它的子态改挂到它的父态（无父则成为独立根态）
        for s in p["snapshots"].values():
            if s.get("inherits_from") == snapshot_id:
                s["inherits_from"] = parent
        return snap

    # ================= 值操作（增量解析核心） =================

    def resolve_value(self, person_id: str, snapshot_id: str, path: str) -> Optional[dict]:
        """沿 inherits_from 链合并解析：本态 overrides 命中即返回，否则逐级查父态。
        祖先快照（非本态）若对该 path 标记了 broken，则视为不再继承（返回 None）。
        本态自身的 broken 不影响本态显示（断裂=从下一个快照起不再继承）。"""
        _validate_path(path)
        p = self._person(person_id)
        for i, snap in enumerate(self._chain(p, snapshot_id)):  # [本态...根态]
            if i > 0 and path in snap.get("broken", []):
                return None
            leaf = snap["overrides"].get(path)
            if leaf is not None:
                return leaf
        return None

    def set_value(
        self,
        person_id: str,
        snapshot_id: str,
        path: str,
        value: Any,
        unit: Optional[str] = None,
        name: Optional[str] = None,
    ) -> dict:
        """copy-on-write：只写本态 overrides，绝不回写父态。允许模板外自由维度。"""
        _validate_path(path)
        value = _validate_value(value)
        snap = self._snapshot(person_id, snapshot_id)
        if name is None:
            name = self._template_name(path) or path.split(".")[-1]
        leaf: dict = {"name": name, "value": value}
        if unit is not None:
            leaf["unit"] = unit
        snap["overrides"][path] = leaf
        return leaf

    def del_value(self, person_id: str, snapshot_id: str, path: str) -> dict:
        """只删本态 overrides；继承链不受影响（父态值将重新生效）。"""
        _validate_path(path)
        snap = self._snapshot(person_id, snapshot_id)
        if path not in snap["overrides"]:
            raise ArchiveError(f"本态 overrides 中不存在该 path: {path}")
        return snap["overrides"].pop(path)

    def set_break(self, person_id: str, snapshot_id: str, path: str, on: bool) -> dict:
        """属性级「断裂」（中断继承）开关。断裂标记记录在当前快照上。

        on=True：在本态标记 path 为 broken —— 本态自身仍正常显示该属性，
        从本态的下一个快照起不再继承显示（即使祖先有定义），直至后代显式覆盖重新引入。
        on=False：取消标记，恢复后代继承。
        与「删本态覆盖」不同：删覆盖后祖先值在本态会重新生效且后代仍继承；断裂则专门阻断向后代传递。
        """
        _validate_path(path)
        snap = self._snapshot(person_id, snapshot_id)
        broken = snap.setdefault("broken", [])
        if on:
            if path not in broken:
                broken.append(path)
        else:
            snap["broken"] = [x for x in broken if x != path]
        return snap

    def set_order(self, person_id: str, snapshot_id: str, order: list) -> dict:
        """设置本态卡项内属性值的展示顺序（仅影响显示排序，不影响继承语义）。
        order 为 path 字符串数组。"""
        if not isinstance(order, list) or not all(isinstance(x, str) for x in order):
            raise ArchiveError("order 必须为字符串路径数组")
        snap = self._snapshot(person_id, snapshot_id)
        snap["order"] = list(order)
        return snap

    def resolved_leaves(self, person_id: str, snapshot_id: str) -> dict:
        """某快照的完整合并视图：{path: leaf}（本态 + 全部继承）。
        祖先快照对该 path 标记 broken → 本态及全部后代不再显示/继承；
        本态自身标记的 broken 不影响本态显示（断裂=从下一个快照起不再继承）。"""
        p = self._person(person_id)
        self._snapshot(person_id, snapshot_id)
        chain = self._chain(p, snapshot_id)  # [本态...根态]
        merged: dict = {}
        for i, s in enumerate(reversed(chain)):  # 根态先写入，子态覆盖；最后一个为本态
            merged.update(s.get("overrides", {}))
            if i < len(chain) - 1:  # 跳过本态自身的 broken
                for path in s.get("broken", []):
                    merged.pop(path, None)
        return merged

    def resolve_trace(self, person_id: str, snapshot_id: str) -> dict:
        """合并视图 + 值来源标注：{path: {"leaf": leaf, "source": snapshot_id}}。
        source=本态 id 表示本态覆盖，否则为继承来源快照。供 Web 可视化标注。
        被祖先 broken 的属性不会出现在结果中（本态自身的 broken 不隐藏本态显示）。"""
        p = self._person(person_id)
        self._snapshot(person_id, snapshot_id)
        chain = self._chain(p, snapshot_id)
        traced: dict = {}
        for i, s in enumerate(reversed(chain)):
            for path, leaf in s.get("overrides", {}).items():
                traced[path] = {"leaf": leaf, "source": s["id"]}
            if i < len(chain) - 1:  # 跳过本态自身的 broken
                for path in s.get("broken", []):
                    traced.pop(path, None)
        return traced

    # ================= 连贯性链接 =================

    def add_link(
        self,
        person_id: str,
        from_id: str,
        to_id: str,
        link_type: str,
        note: str = "",
        from_path: Optional[str] = None,
        to_path: Optional[str] = None,
    ) -> str:
        """连贯性链接：属性级关系——from 快照的某属性 ↔ to 快照的某属性。

        from_path/to_path 为维度路径（如 mental.tendency.preferences），
        必须能在对应快照的合并视图中解析到值（沿继承链）。
        """
        p = self._person(person_id)
        if link_type not in LINK_TYPES:
            raise ArchiveError(f"link type 必须是 {'/'.join(LINK_TYPES)} 之一: {link_type}")
        self._snapshot(person_id, from_id)
        self._snapshot(person_id, to_id)
        if not from_path or not to_path:
            raise ArchiveError("属性级链接必须指定 from_path 与 to_path（维度路径）")
        _validate_path(from_path)
        _validate_path(to_path)
        # 两端属性都必须已存在（沿各自继承链合并视图可解析）
        if self.resolve_value(person_id, from_id, from_path) is None:
            raise ArchiveError(f"起始属性不存在: {from_id} 的 {from_path}")
        if self.resolve_value(person_id, to_id, to_path) is None:
            raise ArchiveError(f"目标属性不存在: {to_id} 的 {to_path}")
        # 存储与语义一致：继承/因果 要求 to 态确实继承自 from
        if link_type in INHERIT_REQUIRED_LINKS and p["snapshots"][to_id]["inherits_from"] != from_id:
            raise ArchiveError(
                f"{link_type} 链接要求 {to_id} 的 inherits_from 指向 {from_id}，"
                f"当前为 {p['snapshots'][to_id]['inherits_from']}"
                f"（可先调用 set-inherits 建立继承关系，或添加链接时勾选『同步建立继承』）"
            )
        for lk in p["continuity_links"]:
            if (lk["from"] == from_id and lk["from_path"] == from_path
                    and lk["to"] == to_id and lk["to_path"] == to_path
                    and lk["type"] == link_type):
                raise ArchiveError(
                    f"链接已存在: {from_id}.{from_path} -> {to_id}.{to_path} ({link_type})"
                )
        link_id = _gen_id("l", {lk["link_id"] for lk in p["continuity_links"]})
        p["continuity_links"].append(
            {
                "link_id": link_id,
                "from": from_id, "from_path": from_path,
                "to": to_id, "to_path": to_path,
                "type": link_type, "note": note,
            }
        )
        return link_id

    def rm_link(self, person_id: str, link_id: str) -> dict:
        """删链接不级联删快照。"""
        p = self._person(person_id)
        for i, lk in enumerate(p["continuity_links"]):
            if lk["link_id"] == link_id:
                return p["continuity_links"].pop(i)
        raise ArchiveError(f"链接不存在: {link_id}")

    def list_links(self, person_id: str) -> list:
        return self._person(person_id)["continuity_links"]

    # ================= 视图 =================

    def tree(self, person_id: str) -> dict:
        """时间轴视图（默认视图）：按时间排列快照 + 合并后叶子 + 链接。"""
        p = self._person(person_id)
        snapshots = []
        for s in self.list_snapshots(person_id):
            snapshots.append(
                {
                    "id": s["id"],
                    "timestamp": s["timestamp"],
                    "label": s["label"],
                    "inherits_from": s["inherits_from"],
                    "resolved": self.resolved_leaves(person_id, s["id"]),
                    "own_overrides": len(s["overrides"]),
                    "order": s.get("order", []),
                }
            )
        return {
            "person": {"identity_id": p["identity_id"], "name": p["name"]},
            "snapshots": snapshots,
            "continuity_links": p["continuity_links"],
        }

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

# 连贯性链接语义（已定稿；扩展时只需在此追加）
LINK_TYPES = ("继承", "因果", "断裂", "主动重塑")

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
        return self

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

    # ================= Snapshot =================

    def add_snapshot(
        self,
        person_id: str,
        timestamp: str,
        label: str,
        inherits_from: Optional[str] = None,
        snapshot_id: Optional[str] = None,
    ) -> str:
        p = self._person(person_id)
        try:
            datetime.date.fromisoformat(timestamp)
        except (TypeError, ValueError):
            raise ArchiveError(f"timestamp 需为 ISO 日期 YYYY-MM-DD: {timestamp}")
        if not label:
            raise ArchiveError("label 不能为空")
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
        }
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

    # ================= 值操作（增量解析核心） =================

    def resolve_value(self, person_id: str, snapshot_id: str, path: str) -> Optional[dict]:
        """沿 inherits_from 链合并解析：本态 overrides 命中即返回，否则逐级查父态。"""
        _validate_path(path)
        p = self._person(person_id)
        for snap in self._chain(p, snapshot_id):
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

    def resolved_leaves(self, person_id: str, snapshot_id: str) -> dict:
        """某快照的完整合并视图：{path: leaf}（本态 + 全部继承）。"""
        p = self._person(person_id)
        self._snapshot(person_id, snapshot_id)
        merged: dict = {}
        for s in reversed(self._chain(p, snapshot_id)):  # 根态先写入，子态覆盖
            merged.update(s["overrides"])
        return merged

    def resolve_trace(self, person_id: str, snapshot_id: str) -> dict:
        """合并视图 + 值来源标注：{path: {"leaf": leaf, "source": snapshot_id}}。
        source=本态 id 表示本态覆盖，否则为继承来源快照。供 Web 可视化标注。"""
        p = self._person(person_id)
        self._snapshot(person_id, snapshot_id)
        traced: dict = {}
        for s in reversed(self._chain(p, snapshot_id)):
            for path, leaf in s["overrides"].items():
                traced[path] = {"leaf": leaf, "source": s["id"]}
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
                }
            )
        return {
            "person": {"identity_id": p["identity_id"], "name": p["name"]},
            "snapshots": snapshots,
            "continuity_links": p["continuity_links"],
        }

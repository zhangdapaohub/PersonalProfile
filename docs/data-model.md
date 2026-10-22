# 数据存储结构定稿（PersonalProfile）

> 状态：设计定稿 · **未实现**（待明确「实现」后按此落地）
> 本文档是数据结构的最终定义。结构变更以本文为准。

---

## 0. 设计目标

1. **时间轴切分人格**：每个时间节点的"他"相对独立，仿佛不是同一个人。
2. **跨时间连贯性**：显式链接把各态串回"同一个人"，断裂也要能如实标记。
3. **树状、可逐级切分**：维度从大维度 → 中维度 → 细致字段层层下钻。
4. **查询友好**：给定维度路径（如 `physical.body_shape.height`）直接解析定位，不靠遍历。
5. **零依赖、本地 JSON**：Python 标准库即可读写。
6. **紧凑存储（增量）**：继承态**不存全量副本**，用「引用父态 + 差异(override)」模型，避免数据膨胀。

---

## 1. 整体层级

```
Person(根身份, identity_id)
 ├─ snapshots: { [snapshot_id]: Snapshot }   ← 每个时间点的"他"，彼此独立
 └─ continuity_links: [ Link ]               ← 属性级语义关系（继承/因果/断裂/主动重塑）
                                                Link = {from, from_path, to, to_path, type, note}
                                                （快照A的某属性 ↔ 快照B的某属性）
```

- **"不是同一个人"** → 每个 `Snapshot` 是独立状态实体；除非显式 `inherits_from`，否则不共享数据。
- **"连贯性"** → `continuity_link` 显式记录关联类型与说明（支持断裂）。

---

## 2. 叶子与路径

- **维度路径即 key 链**：`physical.body_shape.height` = 依次取键。
- **path 不落库**，由 key 链在查询时派生；查询按 `.` 切分逐级索引。
- **叶子载荷**（存于 `overrides`）：

```json
{ "name": "身高", "value": 175, "unit": "cm" }
```

  - `name`：展示名（自由维度必填；模板维度可省，回退模板名）。
  - `value`：标量或列表（如偏好多值 `["极简","理想"]`）。
  - `unit`：可选单位。

---

## 3. 快照模型（增量 / 继承）

```json
{
  "id": "s_2026",
  "timestamp": "2026-01-01",
  "label": "26岁的张三",
  "inherits_from": "s_2023",
  "overrides": {
    "physical.body_shape.height": { "value": 178, "unit": "cm" }
  }
}
```

- **`inherits_from`**：存储指针（`null` = 独立根态）；继承态指向父态，**不抄数据**。
- **`overrides`**：扁平 `path → 叶子` 字典，只存「本态设置 / 相对父态变化」的部分。
  - 根态（`inherits_from=null`）：`overrides` 含该态全部值。
  - 继承态：`overrides` 仅含差异（甚至为空 = 纯继承）。
- **读取沿 `inherits_from` 链合并**（子覆盖父，类似原型链）：
  ```
  resolve(snapshot, path):
      if path in snapshot.overrides: return snapshot.overrides[path]
      if snapshot.inherits_from:     return resolve(父态, path)
      return None
  ```
- **写入走 copy-on-write**：改继承来的字段只落在本态 `overrides`，不回写父态。

---

## 4. 连贯性链接（语义）

```json
{ "link_id": "l1", "from": "s_2020", "to": "s_2023", "type": "因果", "note": "..." }
```

- `type ∈ { 继承, 因果, 断裂, 主动重塑 }`。
- **继承 / 因果**：`to` 态的 `inherits_from` 应等于 `from`（存储与语义一致）。
- **断裂 / 主动重塑**：`to` 态 `inherits_from` 通常为 `null`（不继承前态），链接仅作语义记录。

---

## 5. 完整示例（覆盖各场景）

覆盖：多人物、根态、因果(差异)、继承(空 overrides)、断裂(独立)、主动重塑(差异+模板外自由维度)、多值列表、单位。

```json
{
  "persons": {
    "p_zhangsan": {
      "identity_id": "p_zhangsan",
      "name": "张三",
      "snapshots": {
        "s_2020": {
          "id": "s_2020",
          "timestamp": "2020-01-01",
          "label": "20岁的张三",
          "inherits_from": null,
          "overrides": {
            "physical.body_shape.height": {"name": "身高", "value": 175, "unit": "cm"},
            "physical.body_shape.weight": {"name": "体重", "value": 60, "unit": "kg"},
            "mental.cognitive.thoughts": {"name": "思想", "value": "理想主义"},
            "mental.tendency.preferences": {"name": "偏好", "value": ["极简", "理想"]},
            "timeline.life_stage": {"name": "人生阶段", "value": "青年"},
            "timeline.role": {"name": "角色", "value": "学生"}
          }
        },
        "s_2023": {
          "id": "s_2023",
          "timestamp": "2023-01-01",
          "label": "23岁的张三",
          "inherits_from": "s_2020",
          "overrides": {
            "mental.cognitive.thoughts": {"name": "思想", "value": "务实转向中"},
            "physical.body_shape.weight": {"name": "体重", "value": 68, "unit": "kg"},
            "timeline.role": {"name": "角色", "value": "职场新人"}
          }
        },
        "s_2026": {
          "id": "s_2026",
          "timestamp": "2026-01-01",
          "label": "26岁的张三",
          "inherits_from": "s_2023",
          "overrides": {}
        },
        "s_2028": {
          "id": "s_2028",
          "timestamp": "2028-01-01",
          "label": "28岁的张三（断裂）",
          "inherits_from": null,
          "overrides": {
            "physical.body_shape.height": {"name": "身高", "value": 178, "unit": "cm"},
            "physical.body_shape.weight": {"name": "体重", "value": 75, "unit": "kg"},
            "mental.cognitive.thoughts": {"name": "思想", "value": "彻底重构"},
            "mental.tendency.preferences": {"name": "偏好", "value": ["效率", "务实"]},
            "timeline.life_stage": {"name": "人生阶段", "value": "青年后期"},
            "timeline.role": {"name": "角色", "value": "创业者"}
          }
        },
        "s_2030": {
          "id": "s_2030",
          "timestamp": "2030-01-01",
          "label": "30岁的张三（主动重塑）",
          "inherits_from": "s_2028",
          "overrides": {
            "mental.cognitive.beliefs": {"name": "信念", "value": ["独立", "长期主义"]},
            "timeline.role": {"name": "角色", "value": "创始人"}
          }
        }
      },
      "continuity_links": [
        {"link_id": "l1", "from": "s_2020", "from_path": "mental.tendency.preferences", "to": "s_2023", "to_path": "mental.tendency.preferences", "type": "因果", "note": "偏好由理想主义演变而来"},
        {"link_id": "l2", "from": "s_2023", "from_path": "physical.body_shape.height", "to": "s_2026", "to_path": "physical.body_shape.height", "type": "继承", "note": "身高稳态延续"},
        {"link_id": "l3", "from": "s_2026", "from_path": "mental.cognitive.thoughts", "to": "s_2028", "to_path": "mental.cognitive.thoughts", "type": "断裂", "note": "思想断裂式重构，不继承前态"},
        {"link_id": "l4", "from": "s_2028", "from_path": "mental.cognitive.beliefs", "to": "s_2030", "to_path": "mental.cognitive.beliefs", "type": "主动重塑", "note": "信念体系主动重建"}
      ]
    },
    "p_lisi": {
      "identity_id": "p_lisi",
      "name": "李四",
      "snapshots": {
        "s_l1": {
          "id": "s_l1",
          "timestamp": "2025-01-01",
          "label": "李四",
          "inherits_from": null,
          "overrides": {
            "physical.body_shape.height": {"name": "身高", "value": 180, "unit": "cm"},
            "mental.tendency.preferences": {"name": "偏好", "value": ["安静"]}
          }
        }
      },
      "continuity_links": []
    }
  }
}
```

**场景对照**
- `s_2020`：根态，全量 `overrides`（含多值 `preferences`、单位）。
- `s_2023`（因果）：`inherits_from=s_2020`，只存 3 处差异。
- `s_2026`（继承）：`inherits_from=s_2023`，`overrides={}` 空，纯继承。
- `s_2028`（断裂）：`inherits_from=null`，全量独立（不共享前态）。
- `s_2030`（主动重塑）：`inherits_from=s_2028`，差异 + 模板外自由维度 `beliefs`。
- `p_lisi`：第二个人物，证明多人物隔离。

---

## 6. 查询模型

### 6.1 按路径定位（主路径）
```
segments = path.split(".")
沿当前快照 overrides 查 segments；未命中则沿 inherits_from 链向上查父态 overrides。
```
- 不遍历、不手维护 path；深度浅，性能足够。

### 6.2 快照与时间轴
- 按 `snapshot.timestamp` 排序得到时间轴。
- 沿 `continuity_links` 可回溯/前推某态关系与类型（继承/因果/断裂/主动重塑）。

---

## 7. 存储落点

- 单文件 JSON：`data/archive.json`（运行时生成，不参与版本管理）。
- 顶层结构：`{ "persons": { [identity_id]: Person } }`。
- 维度模板：`src/schema/dimensions.json`（系统预设大维度骨架，仅 `name/children/unit`，无 value）；用于展示骨架与自由维度回退名。

---

## 8. 与"树状浅层级"的关系

- 此前"≤3 层"为暂定，已放宽为**先粗粒度、大概即可、别太深**。
- 主轴 `Person → Snapshot(增量树) → 维度/字段` 满足可逐级切分；维度内部深度按需增长，不强求上限。

---

## 9. 已确认（实现前拍板，详见 `implementation.md` §8.1）

1. 连贯性链接语义：继承/因果/断裂/主动重塑（4 类足够）。
2. 时间粒度：节点式，`timestamp` 用 ISO 日期串 `YYYY-MM-DD`。
3. 默认视图：时间轴（看全貌）。

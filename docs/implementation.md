# 技术实现方案（PersonalProfile）

> 状态：实现方案定稿 · **未实现**（待明确「实现」后按此落地）
> 前置：数据结构见 `docs/data-model.md`。本文只定「怎么搭」，不含源码。
> 范围决策：**先只做 CLI 端**（第一阶段）；Web 端暂缓至第二阶段，待 CLI 验证后再定。

---

## 1. 总体约束（已定）

- **语言**：Python 3，仅用标准库（json / argparse / http.server / urllib），**零第三方依赖**。
- **存储**：单文件 JSON `data/archive.json`，顶层 `{ "persons": { [identity_id]: Person } }`。
- **双通道**：
  - Web 界面（给人）：`http.server` 起 localhost，原生 HTML+JS 前端。
  - CLI（给 AI）：`argparse` 命令行，供 AI 程序化调用采集/操作。
- **AI 采集**：抽象接口 + stub，后续接腾讯混元 / OpenAI 兼容（用 `urllib` 发请求，仍零依赖）。

---

## 2. 目录结构与职责

```
PersonalProfile/
├── README.md
├── docs/
│   ├── data-model.md       # 数据结构定稿
│   └── implementation.md   # 本文
├── src/
│   ├── schema/
│   │   └── dimensions.json # 维度模板（仅结构，无 value）
│   ├── core/
│   │   └── store.py         # 存储 / 查询 / 索引 / 连贯性链接
│   ├── ai/
│   │   └── collector.py     # AI 采集抽象接口 + stub + 真实实现占位
│   ├── web/
│   │   ├── app.py           # localhost HTTP 服务（API + 静态页）
│   │   └── index.html       # 前端：树浏览 / 表单上报 / AI 采集入口
│   └── cli/
│       └── main.py          # 命令行入口（argparse 子命令）
├── data/
│   └── archive.json         # 运行时数据（首次运行自动初始化为空）
└── requirements.txt         # 注明「仅 Python 标准库，无需安装」
```

---

## 3. 核心层 `core/store.py`

单一数据访问对象，所有读写都经过它，保证 path 派生与持久化一致。

### 3.1 关键方法（签名级）
```
load(path) -> dict                      # 读 archive.json
save(path, db)                         # 写回（原子：先写临时再 rename）
add_person(name, identity_id=None) -> id
add_snapshot(person_id, timestamp, label, inherits_from=None) -> snapshot_id   # 增量：默认空 overrides
get_person(person_id) -> Person
list_persons() -> [Person 摘要]
get_snapshot(person_id, snapshot_id) -> Snapshot
resolve_value(person_id, snapshot_id, path) -> leaf|None   # 沿 inherits_from 链合并解析（见 data-model §3）
set_value(person_id, snapshot_id, path, value, unit=None, name=None)  # 写本态 overrides（copy-on-write）
del_value(person_id, snapshot_id, path)                   # 删本态 overrides 中的 path
add_link(person_id, from_id, to_id, type, note)           # 连贯性链接
rm_link(person_id, link_id)                               # 删链接（不级联删快照）
list_links(person_id) -> [link]
```

### 3.2 增量解析（核心）
- 快照存储为 `inherits_from` + `overrides`（扁平 `path → 叶子`），不再存整棵嵌套树（见 data-model §3）。
- `resolve_value`：先查本态 `overrides[path]`，未命中则沿 `inherits_from` 链向上查父态，直至命中或根（链合并）。
- `set_value`：只写**本态** `overrides[path]`（copy-on-write），绝不回写父态；支持标量与列表值。
- `del_value`：删本态 `overrides` 中该 path（不影响继承来的父态值）。

### 3.3 维度模板
- `schema/dimensions.json` 仅描述骨架（`name`/`children`/`unit`），无 value；用于展示骨架与自由维度回退名。
- `add_snapshot` 不再深拷贝整棵树：新建快照仅含 `inherits_from` + 空 `overrides`；值经 `set` 逐步写入（继承态则指向父态复用）。
- `set` 允许按 path 新建模板外自由维度（值对象带 `name`）。

---

## 4. 维度模板 `src/schema/dimensions.json`

```json
{
  "physical": { "name": "物理维度", "children": {
    "body_shape": { "name": "体型", "children": {
      "height": { "name": "身高", "unit": "cm" },
      "weight": { "name": "体重", "unit": "kg" }
    }}
  }},
  "mental": { "name": "精神维度", "children": {
    "cognitive": { "name": "认知", "children": { "thoughts": { "name": "思想" } }},
    "tendency": { "name": "倾向", "children": { "preferences": { "name": "偏好" } }}
  }},
  "timeline": { "name": "时间线维度", "children": {
    "life_stage": { "name": "人生阶段" },
    "role": { "name": "角色" },
    "milestone": { "name": "里程碑" }
  }}
}
```
> 先粗粒度（大维度→字段 2 级）；要细分时往 `children` 加即可，path 自然变长。

---

## 5. AI 采集层 `src/ai/collector.py`

抽象接口，与存储解耦；真实模型后接，不改 store。

```
class Collector(ABC):
    @abstractmethod
    def collect(self, prompt: str, context: dict) -> dict:
        """返回 { path: value } 形式的字段更新，由 store.set_value 落库。
           context 含当前 person/snapshot、已有维度值、时间上下文。"""

class StubCollector(Collector):          # 占位：原样返回或空，便于先跑通链路
    def collect(self, prompt, context): return {}

class HunyuanCollector(Collector):      # 腾讯混元：urllib 调 API，读 env 密钥
class OpenAICompatibleCollector(Collector):  # OpenAI 兼容 / 本地 Ollama
```
- Web 的 `POST /api/collect` 与 CLI 的 `collect` 子命令都调用 `Collector.collect`，拿到 `{path:value}` 后批量 `set_value`。
- 时间上下文：采集时携带 `snapshot_id` / `timestamp`，确保填到正确时间态。

---

## 6. Web 层 `src/web/app.py` + `index.html`

### 6.1 服务（零依赖）
- `http.server.ThreadingHTTPServer` + `BaseHTTPRequestHandler`，纯路径分发，无框架。
- 启动：`python src/web/app.py`，监听 `http://localhost:8000`。

### 6.2 API（JSON）
| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/persons` | 列出所有人 |
| GET | `/api/persons/<id>` | 某人 + 其快照摘要 + 连贯性链接 |
| GET | `/api/persons/<id>/snapshots/<sid>` | 某快照完整维度树 |
| GET | `/api/value?person=&snapshot=&path=` | 按 path 取/定位值 |
| POST | `/api/snapshots` | 新增快照（body: timestamp,label） |
| POST | `/api/value` | 写值（body: person,snapshot,path,value） |
| POST | `/api/links` | 加连贯性链接 |
| POST | `/api/collect` | AI 采集（body: person,snapshot,prompt） |

### 6.3 前端 `index.html`
- 原生 HTML + vanilla JS（`fetch` 调 API），无构建工具。
- 能力：选 Person → 沿时间轴选 Snapshot → 树状展示/逐级下钻 → 按 path 查看或编辑值 → 维护连贯性链接 → AI 采集输入框。
- 默认视图：时间轴（已定，见 §8.1）。

---

## 7. CLI 层 `src/cli/main.py`

`argparse` 子命令，供 AI/脚本调用：
```
python src/cli/main.py add-person  --name 张三
python src/cli/main.py add-snapshot --person p_zhangsan --timestamp 2020-01-01 --label "20岁的张三"
python src/cli/main.py add-snapshot --person p_zhangsan --timestamp 2023-01-01 --label "23岁的张三" --inherits-from s_2020
python src/cli/main.py set  --person p_zhangsan --snapshot s_2020 --path physical.body_shape.height --value 175
python src/cli/main.py get  --person p_zhangsan --snapshot s_2023 --path physical.body_shape.height
python src/cli/main.py del-value --person p_zhangsan --snapshot s_2020 --path physical.body_shape.height
python src/cli/main.py tree --person p_zhangsan
python src/cli/main.py links --person p_zhangsan
python src/cli/main.py add-link --person p_zhangsan --from s_2020 --to s_2023 --type 因果 --note "..."
python src/cli/main.py rm-link  --person p_zhangsan --link l3
python src/cli/main.py collect --person p_zhangsan --snapshot s_2020 --prompt "..."
```

---

## 8. 决策状态

### 8.1 已确认（3 项，全部采用建议值）
| 项 | 已定值 | 备注 |
| --- | --- | --- |
| 连贯性链接语义 | 继承 / 因果 / 断裂 / 主动重塑 | 4 类足够，扩展另行评估 |
| 时间粒度 | 节点式，`timestamp` 用 ISO 日期串 `YYYY-MM-DD` | 不限年/事件，自由填 |
| 默认视图 | 时间轴（看全貌） | CLI `tree` 按时间轴列出快照 |

### 8.2 已定默认值（CLI 第一阶段，用户已认同）
| 项 | 默认值 |
| --- | --- |
| identity_id / snapshot_id | 自动生成（`p_`+短 uuid / `s_`+时间戳短码），允许 `--id` 手动指定 |
| 维度严格性 | 实例**不必**死守模板；模板仅为初始骨架；`set` 允许按 path 新建自由维度 |
| 值类型 | 叶子 value 支持标量 + 列表（如 `preferences` 多值）；暂不嵌套对象 |
| CLI 输出 | 默认 JSON（供 AI 解析）；`--pretty` 切换人类可读 |
| timestamp 格式 | ISO 日期串 `YYYY-MM-DD`，可排序 |
| 删除操作 | 提供 `del-value`、`rm-link`；删除链接不级联删快照 |
| 多人物 | 支持多人（`persons` 为 dict） |
| Web 技术 | 严格零依赖：`http.server` + 原生 JS（第二阶段） |
| 数据初始化 | 首次运行 `archive.json` 为空 `{"persons":{}}`，不预置样例 |

### 8.3 下一步待确认：CLI 实现逻辑与暴露能力（实现前）
- CLI 子命令全集与参数签名：`add-person` / `add-snapshot` / `set` / `get` / `del-value` / `tree` / `links` / `add-link` / `rm-link` / `collect`。
- 各命令暴露能力边界：返回值结构、错误码、JSON 输出字段定义。
- 增量解析在 CLI 上的映射：`set` 写本态 `overrides`、`get` 沿 `inherits_from` 链合并、`del-value` 仅删本态。
- 输出规范：默认 JSON（供 AI 解析）与 `--pretty` 人类可读的样式、错误输出格式。
- 自动生成 id 的短码规则与碰撞处理（`p_`+短 uuid / `s_`+时间戳短码）。
- `collector` 真实接入时机（Hunyuan / OpenAI 兼容）与 `StubCollector` 验证范围。

---

## 9. 落地顺序（实现阶段，待授权）

### 第一阶段：仅 CLI 端（当前范围）
1. `schema/dimensions.json`：维度模板（仅结构，无值）。
2. `core/store.py`：存储/查询/path 解析/连贯性链接（load/save、add_person/add_snapshot、resolve_value/set_value、add_link 等）。
3. `cli/main.py`：argparse 子命令（add-person / add-snapshot / set / get / del-value / tree / links / add-link / rm-link / collect），打通 CLI 全链路。
4. `requirements.txt` 与 README 运行说明。

### 第二阶段（暂缓，待定）：Web 端
- `web/app.py` + `index.html`：localhost 原生 JS 页面，树浏览 / 表单上报 / AI 采集。
- 视 CLI 验证情况与需求再启动，不进入第一阶段。

> 第一阶段不创建 `src/web/`，也不做前端；AI 采集先用 `StubCollector`，`collect` 子命令验证链路。

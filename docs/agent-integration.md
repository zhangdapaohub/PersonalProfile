# AI Agent 接入设计：让任何 AI 都用上个人档案

> 版本 v2（P0 已实现，2026-10-25） · 2026-10-25
> 定位：PersonalProfile 从「人看的档案系统」升级为「AI 的单一事实源（Single Source of Truth）」——
> 任何 agent 在做任何个性化需求时，都从这里取数、也向这里沉淀。

**P0 实现现状**（`personal_profile/mcp/`，与 web/cli/ai 三模块互不依赖，仅依赖 core）：

| 文件 | 职责 |
|---|---|
| `mcp/protocol.py` | stdio JSON-RPC 编解码 + 错误码（不掺业务） |
| `mcp/tools.py` | 6 个只读工具（源码级禁写：只调 Archive 读方法，每次调用重新 load 保证对 Web/CLI 写入实时可见） |
| `mcp/server.py` | 工具 schema 注册表 + 分发 + 主循环；日志落 `logs/mcp.log`（绝不污染 stdout） |
| `mcp/AGENT_PROMPT.md` | 提示词片段（贴进任意 agent 的系统提示/自定义指令） |
| `tests/test_mcp.py` | 端到端测试：模块独立性静态检查 + 子进程真协议 19 项（含「跑完全部工具数据文件零写入」只读回归） |

宿主配置（WorkBuddy `~/.workbuddy/mcp.json`）：
```json
{ "mcpServers": { "personal-profile": {
    "command": "python", "args": ["-m", "personal_profile.mcp"],
    "cwd": "E:/doc/workbuddy/PersonalProfile" } } }
```
> 写入后需在连接器管理页对该 server 点「信任」才生效。

---

## 1. 目标与设计原则

| 原则 | 含义 |
|---|---|
| 单一事实源 | 个性化 ≠ AI 猜。称呼、偏好、健康数据、技能、关系……一律查档案，不靠会话记忆或系统提示词硬编码 |
| 读广写严 | 读：任何 agent 任意查询；写：走受控通道，快照推进（新建时间态）必须用户显式确认 |
| 时间语义 | AI 默认拿「最新 resolved 态」；历史任务可指定快照 id。档案的时间轴对 AI 透明 |
| 零依赖不变 | MCP stdio 协议是纯 JSON-RPC over stdio，手写实现，不引入 SDK |
| 展示零耦合 | 接入层只消费 core/store.py 与 core/qbank.py，不碰 web 展示层 |

---

## 2. 四种接入形态

| 形态 | 适用 agent | 优点 | 缺点 | 定位 |
|---|---|---|---|---|
| **MCP Server（stdio）** | 一切支持 MCP 的 agent（WorkBuddy / Claude / Cursor / CodeBuddy…） | 标准协议、即插即用、工具发现自动完成 | 需实现协议层 | **P0 主通道** |
| **HTTP API** | 已有 REST 调用能力的 agent / 远程部署 | 现成（web/server.py 已有），零新代码 | 需服务常驻、无工具自描述 | 已有，保持 |
| **CLI** | 只有 shell 能力的 agent | 现成（cli 已有 11 子命令） | 无结构化 schema 发现 | 已有，保持 |
| **直读 archive.json** | 兜底：任何能读文件的 agent | 绝对可达 | 破坏增量语义（AI 可能误改 overrides 链） | 只读兜底，文档标注勿直写 |

**结论：P0 只做 MCP Server**，其余三个形态已天然存在，写一份《接入指南》说明即可。

---

## 3. MCP Server 设计（P0 核心）

### 3.1 形态
- 独立进程 `mcp/server.py`，stdio 传输，`python -m personal_profile.mcp` 启动。
- 手写 JSON-RPC：`initialize` / `tools/list` / `tools/call` / `notifications/initialized`，协议量小（~200 行）。
- 复用 `core/store.py` 的 Archive（原子读），**只读**——不持有写盘路径，杜绝双写者问题（CLI/服务/MCP 三方并发写风险归零）。

### 3.2 工具清单（首批 6 个）

| 工具 | 入参 | 返回 | 对应场景 |
|---|---|---|---|
| `pp_list_persons` | — | 人物列表（id/名称/快照数/最新时间） | 先知道「档案里有谁」 |
| `pp_get_profile` | `person`，可选 `snapshot_id`（缺省=最新） | 该时间态**全量 resolved 扁平值**（path→{value,unit,name,source}） | 个性化主查询：一次拿全 |
| `pp_query_path` | `person`，`paths[]`（支持前缀，如 `inbody.`） | 指定子树/路径的 resolved 值 | 精准取数，省 token |
| `pp_timeline` | `person` | 快照时间轴 + 链接类型概览 | 需要「他在某时期是什么样」 |
| `pp_search` | `person`，`keyword` | 命中 path/展示名/值的行 | 模糊找指标（如「体重」「高考」） |
| `pp_qbank_progress` | `person` | 各领域已答/未答统计 | AI 引导用户补全档案（「还有 12 项健康指标没答」） |

### 3.3 宿主配置示例（WorkBuddy `~/.workbuddy/mcp.json`）

```json
{
  "mcpServers": {
    "personal-profile": {
      "command": "python",
      "args": ["-m", "personal_profile.mcp"],
      "cwd": "E:/doc/workbuddy/PersonalProfile"
    }
  }
}
```
> 注意：按现有约定，写入 `mcp.json` 后需在连接器管理页对该 server 点「信任」才生效。

### 3.4 输出约定
- 默认返回紧凑 JSON（与 CLI 的 `--pretty` 相反，MCP 面向 token 效率）。
- 值行附 `source`（本态/继承自哪个快照），AI 可自行判断「这是现在的他还是过去的他」。
- `broken`（已断裂）路径不出现在最新态结果中，语义与 web 端一致。

---

## 4. 触发机制：让 AI「想到用」

工具存在 ≠ AI 会用。三管齐下：

### 4.1 提示词片段（随 MCP 一起分发，`mcp/AGENT_PROMPT.md`）
一段 ~200 字的固定指令，用户贴进各 agent 的系统提示/自定义指令即可：

> 你可以访问用户的个人档案（MCP: personal-profile）。凡涉及以下内容，**必须先查档案再回答**：
> 称呼与自称、写作风格与语气偏好、健康与体检数据、作息与习惯、技能与经历、重要他人与关系、
> 设备与资产、目标与计划。档案中没有的事实不要编造；发现用户在对话中透露了档案外的新事实，
> 在征得同意后建议补录（pp 建议走提问库 /qbank）。

### 4.2 触发场景清单（写进提示词片段的判定表）

| 场景类型 | 例 | 查什么 |
|---|---|---|
| 称呼/身份 | 「帮我写自我介绍」 | basic / identity |
| 健康类 | 「给我配食谱/运动建议」 | inbody.*（53 项） |
| 偏好类 | 「推荐一部电影/写周报」 | mental.tendency.preferences |
| 能力类 | 「帮我改简历」 | skills / experience |
| 关系类 | 「给家人挑礼物」 | relations |
| 时间对比 | 「我变了哪些」 | pp_timeline + 链接 |

### 4.3 WorkBuddy Skill 封装（可选，P1）
一个薄 skill：触发词（个人档案/我的档案/profile）→ 指导调用 MCP 工具 + 读写礼仪。让 WorkBuddy 场景不依赖用户手贴提示词。

---

## 5. 写通道设计（P1，本期不做实现，只定边界）

1. **对话沉淀**：agent 发现新事实 → 调 `pp_suggest_fact`（P1 工具，入参 path/value/依据）→ **不直接落库**，返回建议 + 提示用户到 /qbank 或确认后由 agent 调写接口。
2. **快照推进**是用户动作：agent 永远不自动建快照；volatile 指标（体检等）由 qbank 的既有逻辑处理。
3. **并发安全**：写仍统一走 web API（单写者），MCP 永远只读——双写者问题不再扩大。

---

## 6. 隐私与安全（P2）

- 维度注册表（dimensions.json）加可选 `"sensitive": true`（如 health 段）；`pp_get_profile` 默认对 sensitive 段只返回 `{有值, 条数}` 摘要，`pp_query_path` 显式指名才给全值。
- 审计：MCP 每次调用记入 `logs/mcp.log`（复用 core/logutil.py 轮转），查谁、查了什么 path。
- 该仓库已公开（GitHub）→ **data/ 与 logs/ 必须确保在 .gitignore 中**（实现前核查），敏感指标脱敏也是给「万一误提交」上的双保险。

---

## 7. 分阶段实施计划

| 阶段 | 内容 | 产物 |
|---|---|---|
| **P0（本次授权范围）** | MCP stdio server（6 只读工具）+ `mcp/AGENT_PROMPT.md` 提示词片段 + 《接入指南》章节（HTTP/CLI/直读三形态用法）+ .gitignore 核查 | `mcp/`、`docs/agent-integration.md` 补全、可配置进任意 MCP 宿主 |
| P1 | 写通道（pp_suggest_fact + 确认流）、WorkBuddy skill 封装 | 建议落库闭环 |
| P2 | 敏感度分级脱敏、mcp.log 审计、多 agent 使用统计 | 安全加固 |

**P0 预估**：mcp/server.py（协议层 ~200 行）+ tools.py（6 工具 ~150 行）+ 提示词与文档。零第三方依赖不变，测试沿用 node/脚本端到端套路。

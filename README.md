# 个人档案（PersonalProfile）

> **让任何 AI 都懂你：本地个人档案系统，AI 个性化协作的单一事实源。**
> 零第三方依赖（仅 Python 标准库）· 纯本地运行 · 数据自持（单文件 JSON）

AI 每次对话都从零认识你一遍——称呼靠猜、偏好靠编、健康数据不敢给。PersonalProfile 把「你是谁」沉淀成本地档案，任何支持 MCP 的 AI（WorkBuddy / Claude / Cursor…）在做**任何个性化需求**时都从这里取数：称呼、偏好、健康体检、技能经历、重要关系、目标计划。**档案里没有的事实，AI 不编造。**

## 核心理念

1. **时间轴切分人格**：每个时间节点的「他」互相独立（快照），历史任务可精确回溯某时期。
2. **跨时间连贯性**：属性级连贯性链接（继承/因果/主动重塑）把不同时期的属性显式串回同一个人。
3. **增量存储**：快照 = 继承指针 + 仅存差异（overrides）；读沿链合并，写 copy-on-write，永不重复录入。
4. **AI 单一事实源**：读广写严——AI 可任意查询（MCP 只读），写统一走受控通道，快照推进永远由你确认。

## 功能全景

| 能力 | 入口 | 说明 |
|---|---|---|
| **Web 可视化** | `pp.bat` 双击 / `python -m personal_profile.web.server` | 时间轴 + 属性级关联图谱 + 树状详情（拖拽排序/悬浮卡片/整节点删除），http://127.0.0.1:8765 |
| **提问库 /qbank** | Web 页顶栏「📝 提问库」 | P0 85 指标 10 领域，逐题采集答题直接转快照；volatile 指标（体检等）自动建新时间态 |
| **MCP Server（AI 接入）** | `python -m personal_profile.mcp` | 6 个只读工具，任何 MCP 宿主即插即用，**AI 个性化协作的主通道** |
| **CLI** | `python -m personal_profile` | 11+ 子命令，输出 JSON（供 AI 解析），`--pretty` 人读 |
| **AI 采集** | Web「✦ AI 采集」/ CLI `collect` | OpenAI 兼容模型（混元/DeepSeek/Ollama）自然语言直录档案 |
| **一键脚本** | 项目根 `pp.bat` | start（双击即启+开浏览器）/ stop / restart / status |
| **运行日志** | `logs/{web,cli,mcp}.log` | 自动轮转，请求留痕，MCP 调用审计 |

## AI 个性化协作（重点）

### 接入：三步让 AI 用上你的档案

```jsonc
// 1. 宿主 MCP 配置（如 ~/.workbuddy/mcp.json）
{ "mcpServers": { "personal-profile": {
    "command": "python", "args": ["-m", "personal_profile.mcp"],
    "cwd": "<项目根>" } } }
```
2. 连接器管理页对该 server 点「信任」；
3. 把 `personal_profile/mcp/AGENT_PROMPT.md` 的规则贴进 agent 系统提示/自定义指令——这是让 AI「想到用」的关键。

### 6 个只读工具

| 工具 | 用途 |
|---|---|
| `pp_list_persons` | 档案里有谁（含最新时间态） |
| `pp_get_profile` | **个性化主查询**：某时间态全量档案值（合并继承，含值来源标注） |
| `pp_query_path` | 前缀精准取数（`"inbody"` 命中整个健康子树），省 token |
| `pp_timeline` | 时间轴概览：「他在某时期是什么样」 |
| `pp_search` | 关键词模糊找指标 |
| `pp_qbank_progress` | 答题进度 + 缺口样例：AI 主动引导你补全档案 |

### 触发规则（AGENT_PROMPT.md 摘要）

凡任务涉及**称呼身份 / 健康建议 / 写作风格偏好 / 简历技能 / 送礼沟通 / 目标计划**，AI 必须先查档案再作答；档案没有的明确说没有并引导你去 /qbank 补录；对话中发现新事实**不直接写库**（MCP 源码级禁写），由你在 Web 页确认落库——写永远走 Web API 单写者，杜绝并发写坏数据。

### 时间语义

AI 默认拿「最新 resolved 态」；问「过去的你」时经 `pp_timeline` 选快照、带 `snapshot_id` 精确回溯。每项值的 `source` 字段标注来自哪个快照（本态 or 继承自历史态）。

## 快速开始

```bash
# ① 双击 pp.bat（Windows）→ 自动启动 Web + 开浏览器
#    或手动：
python -m personal_profile.web.server          # Web 端
python -m personal_profile.mcp                 # MCP stdio server（宿主拉起，勿手动常驻）

# ② 不想从零建数据？一键载入完全虚构的演示人物「陈亦航」（92 项值 / 3 快照 / 断裂+三类链接 / InBody）：
PP_DATA=docs/demo-archive.json python -m personal_profile.web.server
#    Windows PowerShell：$env:PP_DATA="docs/demo-archive.json"; python -m personal_profile.web.server

# ③ CLI 全流程
python -m personal_profile add-person --name 张三
python -m personal_profile add-snapshot --person p_xxx --timestamp 2020-01-01 --label "20岁的张三"
python -m personal_profile set --person p_xxx --snapshot s_xxx --path physical.body_shape.height --value 175 --unit cm
python -m personal_profile tree --person p_xxx --pretty
```
- 数据：`data/archive.json`（自动创建；`PP_DATA` / `PP_PORT` 环境变量可覆盖）。
- 演示数据：`docs/demo-archive.json`（全虚构，不含任何真人信息），同时是数据模型全特性的参考样例。

## 架构与工程化

```
PersonalProfile/
├── pp.bat                       # 一键服务脚本
├── data/                        # archive.json / config.json（gitignore，不外泄）
├── logs/                        # web/cli/mcp 轮转日志（gitignore）
├── docs/                        # 设计文档（数据模型/实现/提问库/AI接入）
├── tests/
│   └── test_mcp.py              # 端到端 19 项（协议/工具/只读回归/隔离检查）
└── personal_profile/            # 主包
    ├── paths.py                 # 路径单一事实来源
    ├── core/                    # ★ 主模块：store.py（Archive 唯一读写入口）+ qbank.py + logutil.py
    ├── web/                     # 展示模块：server.py + qbank_api.py + 原生 ES Module 前端
    ├── mcp/                     # AI 接入模块：protocol.py + tools.py + server.py + AGENT_PROMPT.md
    ├── cli/  ├── ai/            # 命令行 / AI 采集器（OpenAI 兼容，即插即用）
    └── assets/                  # dimensions.json（维度模板）+ question_bank.json（题库唯一权威）
```

**三模块独立性是工程红线（测试强制）**：`core`（主模块）/ `web`（展示）/ `mcp`（AI 接入）互不依赖，只准依赖 core——`tests/test_mcp.py` 静态扫描 import 强制，违规即失败。MCP 源码级禁写（只调 Archive 读方法，每次调用重新加载，对 Web/CLI 写入实时可见）。

## 文档索引
- `docs/data-model.md` —— 数据结构定稿
- `docs/implementation.md` —— 技术实现方案
- `docs/question-bank.md` —— 提问库设计（指标预命名 / 答题转快照）
- `docs/agent-integration.md` —— AI Agent 接入设计（四形态对比 / MCP P0 实现现状）
- `docs/sample-archive.json` —— 覆盖各场景的完整数据样例

## Roadmap
- **P1** 写通道 `pp_suggest_fact`（AI 建议落库 + 确认流）、WorkBuddy skill 封装、题库扩至 ~600 题
- **P2** 敏感维度分级脱敏、MCP 审计增强、跨人物全局视图 / 雷达图

---

*License：见仓库 LICENSE · 数据 100% 本地，档案即主权。*

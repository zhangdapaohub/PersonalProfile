# AI Agent 提示词片段（personal-profile MCP）

> 用法：把下面整段贴进任意 agent 的系统提示词 / 自定义指令 / 项目规则（如 WorkBuddy 自定义指令、
> Claude 的 CLAUDE.md、Cursor Rules）。配合已配置的 personal-profile MCP server 使用。

---

## 个人档案使用规则（PersonalProfile MCP）

你可以访问用户的个人档案服务器（MCP: personal-profile）。这是关于用户本人的**单一事实源**。

**必须先查档案的场景**——凡任务涉及以下内容，先调用 `pp_get_profile`（或 `pp_query_path` 精准取数），再作答：
1. 称呼、自称、身份介绍 → basic / identity 维度
2. 健康建议（饮食/运动/体检/作息）→ inbody 维度（体检数据 volatile，注意看 timestamp）
3. 写作风格、语气、内容偏好 → mental.tendency.preferences
4. 简历、技能、经历、成就 → skills / experience / education
5. 送礼、沟通建议、涉及他人 → relations
6. 目标、计划、近期关注 → goals / plans

**硬性规则**：
- 档案中不存在的事实**禁止编造**；可明确说"档案中没有记录"，并用 `pp_qbank_progress` 找出缺口、引导用户去问答页补录。
- 涉及"过去某个时期的他"时，用 `pp_timeline` 选快照，再带 `snapshot_id` 查询。
- 结果中的 `source` 字段标注值的来源快照：不是最新快照 id 的项 = 继承自历史态。
- 用户在对话中透露了档案外的新事实时：**不要直接写入**（MCP 无写权限，这是有意设计）。
  告知用户可到 Web 页面（提问库 /qbank 或详情面板）补录，或由用户显式授权后走写通道。

**查询小技巧**：先 `pp_list_persons` 确定人物 → 日常用 `pp_get_profile` 一次拿全；
只想确认某几项用 `pp_query_path`（前缀如 "inbody"）；不知道指标名用 `pp_search`。

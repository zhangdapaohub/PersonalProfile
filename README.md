# 个人档案（PersonalProfile）

> 状态：**CLI 端 + Web 端均已实现**（零第三方依赖，仅 Python 标准库）

## 项目定位
**本地个人 AI 档案系统**：在本地管理「个人档案」类信息（人物卡、身体/精神/时间线数据等）。
- 运行：纯本地个人使用，不部署、无登录、零第三方依赖（仅 Python 标准库）。
- 核心诉求：时间轴切分人格（每时间节点的"他"互相独立）+ 跨时间连贯性（显式链接串回同一人）。

## 快速开始
```bash
# 前提：Python 3.10+，无需 pip install；在项目根目录执行
python -m personal_profile --help

# Web 端（可视化时间轴 + 关联关系图谱）
python -m personal_profile.web.server    # 打开 http://127.0.0.1:8765

# 建人 → 建时间快照 → 按维度路径写值 → 时间轴查看
python -m personal_profile add-person --name 张三
python -m personal_profile add-snapshot --person p_xxx --timestamp 2020-01-01 --label "20岁的张三"
python -m personal_profile set --person p_xxx --snapshot s_xxx --path physical.body_shape.height --value 175 --unit cm
python -m personal_profile get --person p_xxx --snapshot s_xxx --path physical.body_shape.height
python -m personal_profile tree --person p_xxx --pretty
```
- 输出默认 JSON（供 AI 解析），`--pretty` 切人类可读。
- 数据文件：`data/archive.json`（运行时自动创建；可用 `--data` 或环境变量 `PP_DATA` 换路径）。

## 命令一览
| 命令 | 作用 |
| --- | --- |
| `add-person` / `list-persons` | 新增 / 列出人物 |
| `add-snapshot` | 新增时间快照（`--inherits-from` 指向父态 = 增量继承；不传 = 独立根态） |
| `set-inherits` | 给**已存在**的快照设置/修改/清除继承关系（`--parent none` 清除；含成环防护） |
| `set` | 写值（copy-on-write 只写本态 overrides；支持模板外自由维度） |
| `get` | 取值（沿继承链合并解析） |
| `del-value` | 删本态覆盖（父态值重新生效） |
| `tree` | 时间轴视图（默认视图）：快照按时间排列 + 合并后叶子 + 链接 |
| `links` / `add-link` / `rm-link` | 连贯性链接（**属性级**：快照A的某属性 ↔ 快照B的某属性；`add-link --from-path/--to-path`） |
| `collect` | AI 采集（`--collector openai-compatible`，配置见下节） |

## 架构（1 核心 + 2 端，可拓展）
```
PersonalProfile/
├── data/                        # 运行时数据（archive.json / config.json，自动生成）
├── docs/                        # 设计文档
└── personal_profile/            # 主包（python -m personal_profile）
    ├── paths.py                 # 路径单一事实来源（ROOT/DATA/CONFIG/SCHEMA）
    ├── __main__.py              # python -m personal_profile → CLI
    ├── core/
    │   ├── store.py             # 唯一读写入口 Archive：增量解析/path/链接/持久化
    │   └── config.py            # 模型配置读写（data/config.json）
    ├── ai/
    │   └── collector.py         # 采集器抽象 + 注册表（新增模型实现即插即用）
    ├── cli/
    │   ├── main.py              # CLI 入口：参数解析 + 统一 JSON 错误输出
    │   └── commands.py          # 子命令定义（新增命令 = 1 个 handler + 1 段注册）
    ├── web/
    │   ├── server.py            # HTTP 服务 + JSON API（零依赖 ThreadingHTTPServer）
    │   ├── templates/index.html # 页面骨架 + 模态
    │   └── static/
    │       ├── css/style.css    # 浅色现代风格
    │       └── js/              # 前端按职责拆分（ES Module，无构建工具）
    │           ├── main.js      # 入口：初始化 + window 处理器挂载
    │           ├── state.js     # 全局状态 + 链接样式
    │           ├── api.js       # HTTP 封装
    │           ├── util.js      # 工具（转义/toast/弹窗开关）
    │           ├── view.js      # 人物切换/加载
    │           ├── timeline.js  # 时间轴渲染 + SVG 关联连线 + 快照选择
    │           ├── detail.js    # 详情面板（值来源标注）
    │           ├── actions.js   # 写操作（人物/快照/链接/值/采集/配置）
    │           └── modals.js    # 模态动态填充
    └── assets/
        └── dimensions.json      # 维度模板（仅结构，无值；扩展维度改这里）
```
Web 端可视化要点：
- **时间轴视图**：快照按时间排列为节点卡片，显示合并后值预览（展示名优先）与覆盖数。
- **关联关系图谱**：快照属性间的 `continuity_link`（`from+from_path → to+to_path`）绘制为 SVG 曲线，四类语义四色区分（继承蓝/因果绿/断裂红虚线/主动重塑紫点线），连线中点标注属性，悬停显示完整说明。
- **值来源标注**：详情面板每个值标注「本态」或「← 继承自某快照」，直观呈现增量模型；分组标题用维度中文名。
- **全操作在线**：建人物/快照/链接（可勾选"同步建立继承关系"）、设置继承、写值（覆盖即编辑）、删本态覆盖、AI 采集，均可页面完成。
设计要点（详见 `docs/`）：
- **增量存储**：快照 = `inherits_from`（父态指针）+ `overrides`（扁平 path→叶子，仅存差异）；读沿链合并、写 copy-on-write。
- **path 即寻址**：path 不落库，按 `.` 切分派生；本态直查天然 O(1)。
- **模块化**：新端只需复用 `core/store.py`；新采集器只需实现 `Collector` 接口；前端新模块按职责加文件并在 `main.js` 挂载。

## 文档
- `docs/data-model.md` —— 数据结构定稿
- `docs/implementation.md` —— 技术实现方案定稿（§8.3 为 CLI 暴露能力确认清单）
- `docs/sample-archive.json` —— 覆盖各场景的完整数据样例

## AI 采集模型配置
- **页面配置**：打开「✦ AI 采集」弹窗 → 展开「模型设置」→ 填 Base URL / API Key / 模型名 → 保存配置（密钥明文存 `data/config.json`，勿提交版本库；页面不回传完整密钥）。
- **CLI 配置**：直接编辑 `data/config.json`（字段 base_url / api_key / model），然后：
  `python -m personal_profile collect --person p_xxx --snapshot s_xxx --prompt "..." --collector openai-compatible`
- 兼容端点（任选其一）：腾讯混元 `https://api.hunyuan.cloud.tencent.com/v1` · DeepSeek `https://api.deepseek.com/v1` · 本地 Ollama `http://127.0.0.1:11434/v1`（无需 key）。

## 下一步
- 可视化增强可选方向：跨人物全局视图、维度雷达图、数据导入导出。

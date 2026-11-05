# 架构

ohmypm 是一个模块化单体：一套 Python Core，三个薄接口层，一个可选的 React 前端。

```text
src/ohmypm/
├── config.py            路径（XDG / OHMYPM_*）与 config.toml
├── storage/             SQLite 引擎、ORM 模型、文件工具、Alembic 迁移
├── core/                业务逻辑（只在这里实现一次）
│   ├── projects.py      注册、路径识别（最长匹配）、重定位、取消注册
│   ├── entries.py       记录、序号分配、修订历史、筛选
│   ├── summaries.py     项目摘要、Markdown 分节解析/渲染、修订
│   ├── context.py       ContextBuilder（确定性、带 token 预算）
│   ├── search.py        FTS5 trigram 全文检索 + 短词 LIKE 兜底
│   ├── assets.py        图片/附件：类型识别、SVG 校验、去重、清理
│   ├── export.py        Markdown 导出、备份、恢复
│   ├── service.py       MemoryService：三个接口共用的高层操作
│   ├── schemas.py       Pydantic 输入/输出模型
│   └── errors.py        统一错误类型（code / 退出码 / HTTP 状态）
├── cli/                 Typer 命令（参数解析与输出）
├── mcp/server.py        MCPServer 工具（stdio）
├── api/                 FastAPI 应用、本地安全中间件、静态前端
├── agents/              全局 Agent 指令的安装/更新/卸载
└── webui/dist/          构建后的前端（由 frontend/ 生成）
frontend/                React + TypeScript + Vite + Tailwind + shadcn/ui
```

## 设计要点

**统一核心。** CLI、MCP、HTTP 都只调用 `MemoryService`；它为每个操作打开一个事务，返回 Pydantic 模型。错误类型 `OhmypmError` 带有稳定的 `code`，各接口把它映射为退出码、MCP 错误 JSON 或 HTTP 状态码。

**项目识别。** 注册时保存 `realpath` 规范化后的根目录。查询时取路径（以及其规范化形式）的所有祖先目录，在活跃项目中查找，取路径组件最多的那个（嵌套项目最长匹配）。比较以目录组件为单位，`/a/robot2` 不会匹配 `/a/robot`。未注册目录明确返回 `registered: false`，从不自动注册。Service 层要求显式的项目引用或路径，不会用进程自身的 CWD 猜测——MCP 服务器因此总是要求 `workspace_path` 或 `project`。

**零侵入。** 核心代码只写 ohmypm 的数据目录和配置目录；导出、备份的默认位置也在数据目录中，而不是当前目录（当前目录可能就是被注册的项目）。`ohmypm agents` 只修改 Agent 的**全局**配置文件中带标记的区块。测试用目录快照（含 mtime）和 `git status --ignored` 验证这一点。

**并发。** SQLite 使用 WAL、`busy_timeout=15s`、外键约束。写事务以 `BEGIN IMMEDIATE` 开始，多个进程的写入被串行化；序号由 `projects.next_sequence` 原子递增分配（删除后不复用），并有 `UNIQUE(project_id, sequence)` 兜底。测试中 6 个进程并发写入 150 条记录，序号连续且唯一。

**修订而非覆盖。** 记录默认追加；编辑和删除前把旧版本写入 `entry_revisions`，摘要被覆盖前写入 `summary_revisions`。可以通过 `log history / log restore / log deleted`、`summary history / summary restore` 找回。

**ContextBuilder。** 不调用任何 AI。按固定优先级分配 token 预算（下一步 > 当前状态 > 概述 > 已知问题 > 未解决 issue > 近期重要记录 > 架构/决策 > 索引），再按阅读顺序渲染；长文本在行边界截断、补齐未闭合的代码块并标注省略；最后严格检查渲染结果不超预算。记录元数据中 `confidence: hypothesis` 或 `verified: false` 会标为 *unverified*，开头的说明提醒 Agent：记录是历史笔记，不是已确认事实。

**全文搜索。** FTS5 `trigram` 分词器支持任意 ≥3 字符的子串（中文、`cv::Mat` 之类的标识符都可以）；1–2 字符的词（如“相机”）用 LIKE 在同一张索引表上兜底。索引由触发器维护，覆盖记录、摘要和项目名称/描述。

**附件。** 文件按内容（魔数）识别类型，只接受 PNG/JPEG/WebP/GIF/SVG 和 UTF-8 文本；SVG 拒绝脚本、事件属性、外部引用、DOCTYPE/ENTITY；文件名清洗、存储路径只由 ID 生成并经过 `safe_child` 校验；同一项目内按 SHA-256 去重；事务失败时删除已写入的文件；`assets gc` 清理无引用文件（引用包括记录、摘要和保留的修订）。

**Web 安全。** 只监听回环地址；访问令牌（Cookie 或 Bearer）防止本机其他用户读取；Host 白名单防 DNS rebinding；写请求校验 Origin / `Sec-Fetch-Site` 防 CSRF；请求体大小限制；CSP 等安全响应头；SVG 以沙箱 CSP 提供，文本附件一律 `text/plain`；Markdown 渲染不解释原始 HTML，URL 只允许 http(s)/mailto/相对地址/`ohmypm-asset:`。

**富文本编辑。** MDXEditor 负责所见即所得；自定义数学插件让 `$…$`、`$$…$$` 无损往返（原版会把 TeX 中的 `_`、`*` 转义）。打开记录时先做一次“往返探测”，如果富文本模式会改写原始 Markdown（超出无意义的格式差异），编辑器自动切换到 Markdown 源码模式并说明原因；未修改的记录不会被规范化后写回。

## 依赖

Python：SQLAlchemy 2、Alembic、Pydantic 2、Typer、FastAPI、Uvicorn、python-multipart、mcp 2。
前端：React 19、React Router、TanStack Query、MDXEditor、react-markdown + remark-gfm + remark-math + rehype-katex + rehype-highlight、Mermaid（按需加载）、Tailwind CSS 4、shadcn/ui（Radix）。

# 开发

## 仓库结构

```text
pyproject.toml        Python 包（hatchling），依赖与工具配置
src/ohmypm/           Python 包（见 architecture.md）
tests/                pytest（全部使用临时 HOME / 数据目录 / Agent 配置目录）
frontend/             React 前端；构建输出到 src/ohmypm/webui/dist
scripts/
  build-frontend.sh   构建前端
  build.sh            前端 + wheel/sdist
  check.sh            全部自动化检查
  acceptance.py       从 wheel 安装后跑 7 个验收场景（--web 含浏览器测试）
  verify_agents.py    实测各 Agent 加载全局指令
  seed_demo.py        向临时数据目录写入演示数据
docs/                 文档
```

## 常用命令

```bash
uv sync                              # Python 依赖（含 dev 组：pytest、httpx、ruff）
uv run pytest -q                     # 后端测试
uv run ruff check src tests && uv run ruff format src tests

cd frontend
pnpm install
pnpm test                            # vitest
pnpm exec tsc -b                     # 类型检查
pnpm lint                            # oxlint
pnpm build                           # → ../src/ohmypm/webui/dist
pnpm dev                             # Vite 开发服务器（/api 代理到 127.0.0.1:8737）
```

前后端联调：

```bash
export OHMYPM_DATA_DIR=/tmp/ohmypm-dev/data OHMYPM_CONFIG_DIR=/tmp/ohmypm-dev/config
uv run python scripts/seed_demo.py /tmp/ohmypm-dev/projects
uv run ohmypm web --dev-origin http://localhost:5173      # 记下打印的 token 链接
cd frontend && pnpm dev                                  # 打开 http://localhost:5173/?token=…
```

浏览器测试（需要 Chromium，默认 `/usr/bin/chromium`）：

```bash
node frontend/scripts/ui-smoke.mjs "<token-url>" /tmp/shots     # 截图 + 渲染检查
node frontend/scripts/e2e-web.mjs "<token-url>" some.png         # 创建/编辑/上传/删除全流程
```

## 测试覆盖

| 范围 | 文件 |
|---|---|
| 注册、重复注册、子目录、规范化、符号链接、嵌套最长匹配、相似前缀、重定位、取消注册与恢复、清除、不修改项目目录 | `tests/test_projects.py` |
| 创建/修改/删除、类型、扩展类型、校验、时间线排序与筛选、序号唯一与不复用、中文 Markdown、超长文本、6 进程并发写入、修订与恢复、乐观并发 | `tests/test_entries.py` |
| 摘要读写/合并/替换/历史、Markdown 分节解析（中英文标题、未知标题、代码块） | `tests/test_summaries.py` |
| brief/standard/full、预算严格不超、截断与代码块闭合、大量记录、空项目、分页、未验证标记 | `tests/test_context.py` |
| 中文（≥3 字与 2 字）、标识符、短语、项目范围、过滤、索引随更新/删除同步、归档项目 | `tests/test_search.py` |
| 上传、引用关联、类型识别与拒绝、大小限制、SVG 攻击样本、路径遍历、篡改的存储路径、缺失资源、垃圾回收、失败事务回滚文件 | `tests/test_assets.py` |
| 迁移版本、文件权限、PRAGMA、外键 | `tests/test_storage.py` |
| CLI 全部主要命令、stdin、JSON、退出码、项目隔离、导出/备份/恢复、真实子进程 | `tests/test_cli.py` |
| MCP 全部工具、Schema、错误格式、stdio 子进程 | `tests/test_mcp.py` |
| HTTP 安全（令牌、Host、Origin、大小）、CRUD、分页、过滤、附件头、不能访问源码 | `tests/test_api.py` |
| Agent 指令安装/重复安装/更新/卸载/保留用户内容/未检测到/override 文件/符号链接/损坏标记/dry-run/不修改项目 | `tests/test_agents.py` |
| 编辑器往返（含数学插件）、Markdown 渲染与安全、工具函数、API 客户端 | `frontend/src/test/*.test.tsx` |

## 约定

- 业务逻辑只写在 `core/`，接口层只做参数解析和展示。
- Schema 变更必须通过 Alembic 迁移，并更新 `SCHEMA_HEAD`。
- 测试不得接触真实 HOME：`tests/conftest.py` 的自动 fixture 会重定向 HOME、XDG、OHMYPM_* 和所有 Agent 配置变量。
- 不在用户注册的项目中写入任何文件（包括导出/备份的默认位置）。
- 开发进度与交接信息记录在 `docs/PROGRESS.md`。

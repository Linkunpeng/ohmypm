# ohmypm — Oh My Project Memory

ohmypm 是一个**本地优先、零项目侵入**的开发记录与项目记忆工具。它让 AI Agent（Codex、Claude Code、Pi、DSH……）在开发过程中把有长期价值的信息——里程碑、问题排查、技术决策、工程知识、产物说明——记录下来，并在下一次会话开始时快速恢复项目上下文。

- **零侵入**：注册项目只在 ohmypm 自己的数据库里建立关联，不在你的源码目录里写任何文件，不改 Git 配置和项目级 Agent 指令。
- **本地独立**：SQLite + 本地文件系统，数据只在本机（`~/.local/share/ohmypm/`），每台设备的记录互相独立，不依赖任何云服务或 AI API。
- **极简模型**：Project（项目）、Entry（记录，按类型区分）、Summary（项目摘要）。
- **三种入口，一个核心**：CLI（Agent 主要入口，支持 `--json`）、MCP Server（stdio）、Web UI（浏览、搜索、富文本编辑），共用同一套 Python Core。
- **Agent 友好**：`ohmypm agents install` 把使用规范写入各 Agent 的全局指令（只追加一个带标记的区块，可更新、可卸载）。

```text
           ┌──────────── ohmypm CLI (Typer) ────────────┐
Agents ───►│                                            │
           │  MCP Server (MCPServer, stdio)               ├──► Python Core ──► SQLite (WAL, FTS5)
Browser ──►│  HTTP API (FastAPI) + Web UI (React)       │    (projects, entries,   + assets/ 目录
           └────────────────────────────────────────────┘     summaries, context, search)
```

## 安装

需要 Python ≥ 3.12 与 [uv](https://docs.astral.sh/uv/)（或 pip）。构建 Web UI 需要 Node ≥ 20 与 pnpm。

```bash
git clone <this repo> ohmypm && cd ohmypm
./scripts/build.sh                 # 构建前端 + wheel（dist/ohmypm-0.1.0-py3-none-any.whl）
uv tool install dist/ohmypm-0.1.0-py3-none-any.whl
ohmypm doctor                      # 检查路径、数据库、FTS5、Web UI、Agent 配置
```

开发方式运行：`uv sync && uv run ohmypm --help`。详见 [docs/installation.md](docs/installation.md)。

## 快速开始

```bash
cd ~/Projects/Robot_WS
ohmypm register                    # 注册当前目录（目录内容不会改变）
ohmypm status                      # 在任意子目录中都能识别项目

ohmypm log add --type milestone --title "完成相机驱动" \
  --content "已实现 V4L2 图像采集，编译测试通过。"
cat issue.md | ohmypm log add --type issue --title "OpenCV 链接失败" --stdin
ohmypm log list
ohmypm log show 2

ohmypm summary set --file summary.md   # 以 "## Overview" 等二级标题划分小节
ohmypm summary show

ohmypm context                     # 给 Agent 的项目上下文（brief / standard / full）
ohmypm search "链接失败"            # 全文检索，支持中文
```

记录类型：`note`、`milestone`、`issue`（默认状态 open）、`decision`、`knowledge`、`artifact`；可在 `config.toml` 中扩展。所有命令支持 `--json`，错误输出到 stderr 并使用明确的退出码。完整命令见 [docs/cli.md](docs/cli.md)。

## 让 Agent 使用 ohmypm

```bash
ohmypm agents install      # 写入 Claude Code / Codex / Pi / DSH 的全局指令
ohmypm agents status       # 查看每个 Agent 读取哪个文件、是否已安装
ohmypm agents update       # 修改 ~/.config/ohmypm/agent-instructions.md 后同步
ohmypm agents remove       # 只移除 ohmypm 区块，保留你的其他内容
```

| Agent | 全局指令文件 | 方式 |
|---|---|---|
| Claude Code | `~/.claude/CLAUDE.md`（`$CLAUDE_CONFIG_DIR`） | `@~/.config/ohmypm/agent-instructions.md` 导入 |
| Codex | `~/.codex/AGENTS.override.md` 或 `AGENTS.md`（`$CODEX_HOME`） | 内联区块 |
| Pi | `~/.pi/agent/` 下的 `AGENTS.md` 等（`$PI_CODING_AGENT_DIR`） | 内联区块 |
| DSH | `~/.dsh/AGENTS.md`（`$DSH_HOME`） | 内联区块 |

以上位置已在本机安装的版本上实测验证（`scripts/verify_agents.py`）。细节见 [docs/agents.md](docs/agents.md)。

## MCP

```bash
claude mcp add --scope user ohmypm -- ohmypm mcp      # Claude Code
```

```toml
# ~/.codex/config.toml
[mcp_servers.ohmypm]
command = "ohmypm"
args = ["mcp"]
```

工具：`pm_get_status`、`pm_list_projects`、`pm_get_project`、`pm_get_context`、`pm_get_summary`、`pm_update_summary`、`pm_add_entry`、`pm_list_entries`、`pm_get_entry`、`pm_update_entry`、`pm_search`、`pm_register_asset`。MCP 进程的工作目录不代表 Agent 的工作区，因此项目相关工具都要求传入 `workspace_path`（绝对路径）或 `project`。见 [docs/mcp.md](docs/mcp.md)。

## Web UI

```bash
ohmypm web            # http://127.0.0.1:8737/?token=...（打开一次即登录）
ohmypm web --open     # 同时打开浏览器
```

总览、项目时间线（按类型/状态/关键词/时间筛选）、记录详情与编辑（富文本 + Markdown 源码模式，图片拖拽/粘贴上传）、Mermaid、KaTeX、代码高亮、项目摘要编辑、全文搜索、Agent 上下文预览；支持浅色/深色主题。只监听 127.0.0.1，并带有访问令牌、Host/Origin 校验等保护。见 [docs/api.md](docs/api.md)。

## 数据位置

| 内容 | 默认位置 | 覆盖方式 |
|---|---|---|
| 数据库、附件、备份、导出 | `~/.local/share/ohmypm/`（`ohmypm.db`、`assets/`、`backups/`、`exports/`） | `OHMYPM_DATA_DIR` 或 `XDG_DATA_HOME` |
| 配置、Agent 指令 | `~/.config/ohmypm/`（`config.toml`、`agent-instructions.md`） | `OHMYPM_CONFIG_DIR` 或 `XDG_CONFIG_HOME` |

目录权限为 0700，数据库与附件为 0600。图片在 Markdown 中以 `ohmypm-asset://<id>` 引用，项目目录移动后不会失效（`ohmypm project relink /new/path`）。

## 备份与恢复

```bash
ohmypm backup                        # → ~/.local/share/ohmypm/backups/ohmypm-backup-<时间>.tar.gz
ohmypm export --all                  # → ~/.local/share/ohmypm/exports/…（纯 Markdown + 附件）
ohmypm restore <backup.tar.gz> --yes # 当前数据先移到 pre-restore-<时间>/，再恢复
```

## 测试

```bash
./scripts/check.sh                   # ruff + pytest（Python）+ tsc + vitest（前端）
python3 scripts/acceptance.py --web  # 从 wheel 安装，在临时 HOME 中跑完 7 个验收场景
python3 scripts/verify_agents.py     # 实测各 Agent 是否加载了 ohmypm 指令（不调用真实 API）
```

## 文档

[架构](docs/architecture.md) · [安装](docs/installation.md) · [数据库](docs/database.md) · [CLI](docs/cli.md) · [MCP](docs/mcp.md) · [Agent 指令](docs/agents.md) · [HTTP API 与 Web](docs/api.md) · [开发](docs/development.md) · [故障排查](docs/troubleshooting.md) · [开发进度](docs/PROGRESS.md)

## 许可证

[Apache-2.0](LICENSE)

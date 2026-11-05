# 开发计划与进度

供后续开发者 / Agent 接力使用。最后更新：2026-11-04（v0.1.0）。

## 阶段状态

| 阶段 | 内容 | 状态 | 验证 |
|---|---|---|---|
| 1 Python Core | 工程、SQLite（WAL / BEGIN IMMEDIATE）、Alembic、Project / Entry / Summary、修订、附件、FTS5 | 完成 | pytest |
| 2 CLI 与 Context | Typer CLI、自动识别、JSON、退出码、ContextBuilder、搜索 | 完成 | pytest（CliRunner + 子进程） |
| 3 MCP 与 Agent | MCPServer stdio 12 个工具、全局指令管理（Claude Code / Codex / Pi / DSH） | 完成 | pytest；`scripts/verify_agents.py` 对四个 Agent 实测通过 |
| 4 Web 与富文本 | FastAPI + 安全中间件；React UI（总览、时间线、详情、编辑器、摘要、搜索、上下文预览） | 完成 | pytest、vitest、Playwright（`frontend/scripts/e2e-web.mjs`） |
| 5 交付 | 备份 / 恢复 / Markdown 导出、文档、构建脚本、验收脚本 | 完成 | `scripts/acceptance.py --web`：23 项检查 + 8 个浏览器步骤通过 |

## 关键决策

- **MCPServer**：使用官方 `mcp` SDK 2.x 的 `MCPServer`，提供 stdio 服务。
- **全文检索**：FTS5 `trigram` + 短词 LIKE 兜底，不引入中文分词依赖。
- **序号**：`projects.next_sequence` 原子递增，删除后不复用，`#12` 始终指向同一条记录。
- **取消注册**：默认归档（保留数据，可在原路径重新注册恢复）；`--purge --yes` 才真正删除。
- **摘要写入**：默认只更新输入中出现的小节，`--replace` 才清空其他小节；所有覆盖都有修订记录。
- **Web 认证**：令牌 + HttpOnly Cookie，令牌保存在数据目录；Host / Origin 校验。
- **富文本**：MDXEditor + 自定义数学插件；“往返探测”在可能改写语法时自动切换源码模式。
- **Claude Code 用 import，其他 Agent 内联**：Codex、Pi、DSH 没有文件导入机制（已核对源码）。
- **默认端口 8737**（避免与本机已有服务 8765 冲突）。

## 已知限制 / 后续可做

- 只在 Linux 上开发与测试（`fcntl` 文件锁）；macOS 应可用但未验证，Windows 不支持。
- 富文本模式会规范化部分格式（表格对齐空格、`<` 转义、列表符号），语义不变；含原始 HTML 等内容时使用 Markdown 模式。
- 前端主包约 1.2 MB（gzip 约 360 KB），编辑器与 Mermaid 已按需加载。
- 搜索结果的排序只对 ≥3 字符的词使用 bm25；纯短词查询按时间排序。
- 尚未实现：记录之间的链接/标签体系、多设备同步（按设计不做）、附件以外的二进制格式（PDF 等）。

## 交接提示

- 运行全部检查：`./scripts/check.sh`；完整验收：`./scripts/build.sh && python3 scripts/acceptance.py --web`。
- 新增 Schema 变更：见 `docs/database.md` 的“迁移”。
- Agent 升级后若指令加载方式变化：更新 `src/ohmypm/agents/manager.py` 中的 `AGENTS` 表，并用 `scripts/verify_agents.py` 验证。

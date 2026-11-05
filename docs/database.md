# 数据库与存储

权威存储是 `~/.local/share/ohmypm/ohmypm.db`（SQLite）。二进制附件保存在 `assets/<project_id>/<asset_id>.<ext>`，数据库只记录元数据。

## 连接设置

| 设置 | 值 | 作用 |
|---|---|---|
| `journal_mode` | WAL | 读写并发；读不阻塞写 |
| `busy_timeout` | 15000 ms | 多进程写入时等待而不是立即失败 |
| `foreign_keys` | ON | 级联删除与引用完整性 |
| `synchronous` | NORMAL | WAL 下的常用折中 |
| 写事务 | `BEGIN IMMEDIATE` | 一开始就拿写锁，读-改-写（如分配序号）安全 |

## 表

| 表 | 说明 |
|---|---|
| `projects` | `id`(UUID)、`name`、`root_path`（realpath）、`description`、`archived_at`（取消注册时间）、`created_at`、`updated_at`、`last_activity_at`、`next_sequence`、`metadata`(JSON) |
| `entries` | `id`、`project_id`→projects（CASCADE）、`sequence`（项目内唯一、递增、不复用）、`type`、`title`、`content`(Markdown)、`status`(open/resolved/obsolete/NULL)、`author`、`source`(cli/mcp/web)、`revision`、`created_at`、`updated_at`、`metadata`(JSON) |
| `entry_revisions` | 每次编辑/删除前的快照（`reason`=edit/delete、`changed_by`）。不对 entries 设外键，因此删除的记录可以恢复；随项目一起删除 |
| `project_summaries` | 每个项目一行：`overview`、`architecture`、`current_state`、`important_decisions`、`known_issues`、`next_steps`、`revision`、`updated_by` |
| `summary_revisions` | 摘要被覆盖前的快照（JSON） |
| `assets` | `id`、`project_id`（CASCADE）、`entry_id`（SET NULL）、`filename`、`mime_type`、`size`、`sha256`、`storage_path`（相对路径）、`created_at` |
| `search_map` / `search_index` | 全文索引：`search_index` 是 FTS5（`tokenize='trigram'`），`search_map` 给每个文档稳定的整数 rowid；由 entries / project_summaries / projects 上的触发器维护 |
| `alembic_version` | Schema 版本 |

## 索引

- `projects.root_path`；活跃项目上的部分唯一索引 `uq_projects_active_root_path (root_path) WHERE archived_at IS NULL`（取消注册的项目保留原路径，便于重新注册时恢复）
- `projects.last_activity_at`
- `entries (project_id, sequence)` 唯一；`(project_id, created_at)`、`(project_id, type)`、`(project_id, status)`、`created_at`
- `assets.project_id`、`assets.entry_id`、`entry_revisions.project_id`

## 删除语义

- `ohmypm unregister`：只设置 `archived_at`，目录不再匹配，记录全部保留；在同一目录再次 `register` 会恢复。
- `ohmypm unregister --purge --yes`：删除项目及其记录、摘要、修订、附件（事务提交后再删除附件文件）。
- 删除记录：先写入删除快照，再删除；附件的 `entry_id` 置空，若不再被引用，可用 `ohmypm assets gc --apply` 清理（默认保留 1 小时内的新上传）。

## 迁移

迁移脚本在 `src/ohmypm/storage/migrations/versions/`，随包发布，首次打开数据库时自动执行。新增迁移：

```bash
uv run alembic revision -m "describe change"     # 使用仓库根目录的 alembic.ini（./dev.db）
# 编辑生成的脚本，然后更新 storage/database.py 中的 SCHEMA_HEAD
uv run pytest tests/test_storage.py              # 会检查 SCHEMA_HEAD 与 Alembic head 一致
```

## 备份、导出、恢复

- `ohmypm backup`：用 SQLite 在线备份 API 生成一致的快照，与 `assets/` 和 `manifest.json` 一起打包为 `.tar.gz`（0600）。可以在 Agent 正在写入时执行。
- `ohmypm export [--all]`：每个项目一个目录：`README.md`（时间线）、`summary.md`、`entries/0001-标题.md`（带 front matter）、`assets/`，Markdown 中的 `ohmypm-asset://` 链接被改写为相对路径。
- `ohmypm restore <archive> --yes`：校验归档后，把当前数据库与附件移到 `pre-restore-<时间>/`，再放入备份内容并迁移到最新 Schema。恢复前请停止 `ohmypm web` 和 MCP 进程。

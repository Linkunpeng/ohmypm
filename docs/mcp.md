# MCP Server

`ohmypm mcp`（或 `ohmypm-mcp`）以 **stdio** 方式运行基于 MCPServer 的 MCP 服务器，调用与 CLI 相同的 Python Core，不需要网络、Web 服务或外部 AI。

> MCP 服务器进程的工作目录不等于 Agent 的工作区。所有与项目相关的工具都要求传入 `workspace_path`（Agent 当前工作区的**绝对路径**，可以是项目内任意子目录）或 `project`（项目 id、id 前缀或名称）；服务器从不根据自己的 CWD 猜测项目。

## 客户端配置

如果本机已有名为 `ohmypm` 的其他 MCP 服务器，换一个名字（例如 `ohmypm-memory`）即可，工具名会以服务器名作为命名空间。

**Claude Code**

```bash
claude mcp add --scope user ohmypm -- ohmypm mcp
```

**Codex**（`~/.codex/config.toml`）

```toml
[mcp_servers.ohmypm]
command = "ohmypm"
args = ["mcp"]
```

**Pi**（`~/.pi/agent/mcp.json`，或 `pi mcp add ohmypm -- ohmypm mcp`）

```json
{
  "mcpServers": {
    "ohmypm": { "command": "ohmypm", "args": ["mcp"] }
  }
}
```

**DSH**（`~/.dsh/cordis.patch.yml`）

```yaml
- insert:
    - id: mcp-ohmypm
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: ohmypm
        transport: stdio
        command: ohmypm
        args: ['mcp']
```

**通用 JSON 格式（Cursor、Claude Desktop 等）**

```json
{ "mcpServers": { "ohmypm": { "command": "ohmypm", "args": ["mcp"] } } }
```

如果 `ohmypm` 不在客户端的 PATH 中，使用绝对路径（`which ohmypm`）。使用自定义数据目录时通过 `env` 传入 `OHMYPM_DATA_DIR` / `OHMYPM_CONFIG_DIR`。

## 工具

| 工具 | 作用 | 关键参数 |
|---|---|---|
| `pm_get_status` | 工作区是否属于已注册项目（先调用） | `workspace_path`（必填） |
| `pm_list_projects` | 列出项目 | `include_archived` |
| `pm_get_project` | 项目详情 | `project` / `workspace_path` |
| `pm_get_context` | 确定性的项目上下文 | `mode`=brief/standard/full、`max_tokens`、`page`、`page_size`、`output`=markdown/json |
| `pm_get_summary` | 摘要（各小节 + 等价 Markdown） | |
| `pm_update_summary` | 更新摘要（只改提供的小节；`replace` 清空其他） | `markdown` 或 `overview`…`next_steps`、`author` |
| `pm_add_entry` | 新增记录 | `title`（必填）、`type`、`content`、`status`、`author`、`metadata` |
| `pm_list_entries` | 列出记录（默认最新在前，带摘录） | `types`、`statuses`、`query`、`since`、`until`、`order`、`limit`、`offset`、`include_content` |
| `pm_get_entry` | 单条记录全文 | `entry`（序号或 id） |
| `pm_update_entry` | 编辑记录（保留修订） | `title`、`type`、`content` 或 `append_content`、`status`、`metadata`（合并） |
| `pm_search` | 全文检索 | `query`、`all_projects`、`types`、`kinds`、`limit` |
| `pm_register_asset` | 保存图片/文本附件，返回 Markdown 引用 | `file_path`（绝对路径）或 `content_base64` + `filename`、`entry` |

MCP 写入的记录 `source` 为 `mcp`。删除记录、取消注册等破坏性操作不通过 MCP 提供，请使用 CLI 或 Web。

## 错误格式

工具出错时返回 MCP 错误结果（`isError: true`），文本内容是 JSON：

```json
{"error": {"code": "project_not_registered", "message": "No registered ohmypm project contains /tmp/x", "details": {"path": "/tmp/x", "hint": "Run `ohmypm register` in the project root to register it."}}}
```

`code` 取值：`validation_error`、`not_found`、`project_not_registered`、`conflict`、`ambiguous_reference`。参数不符合 Schema（例如 `mode: "huge"`）也以同样格式返回 `validation_error`。

## 测试

`tests/test_mcp.py` 使用 MCPServer 内存客户端覆盖全部工具，并以子进程方式启动 `ohmypm mcp`（工作目录设为 `/`）验证 stdio 传输。

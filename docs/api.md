# HTTP API 与 Web UI

`ohmypm web` 启动本地 FastAPI 服务（默认 `127.0.0.1:8737`），同时提供 JSON API 和编译好的 Web UI。OpenAPI 文档：`/api/docs`、`/api/openapi.json`。

## 访问控制

| 保护 | 说明 |
|---|---|
| 只监听回环地址 | 非回环地址需要显式 `--allow-remote`（此时不再检查 Host，务必另加防护） |
| 访问令牌 | 首次启动生成 `~/.local/share/ohmypm/web-token`（0600）。终端打印的 `/?token=…` 链接会设置 HttpOnly、SameSite=Strict 的 Cookie 并跳转；脚本可用 `Authorization: Bearer <token>`。`/api/health` 无需令牌。`--no-auth` 关闭（仅限单用户机器） |
| Host 白名单 | 只接受 `127.0.0.1`、`localhost`、`[::1]`（防 DNS rebinding，返回 421） |
| 写请求来源检查 | POST/PUT/PATCH/DELETE 带有非本站 `Origin` 或 `Sec-Fetch-Site: cross-site` 时返回 403；默认不开放 CORS，`--dev-origin` 只用于前端开发 |
| 请求体大小 | JSON 16 MiB；上传为 `max_upload_mb`（默认 20 MiB）+ 1 MiB，超出返回 413 |
| 响应头 | `Content-Security-Policy`、`X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy: no-referrer` |
| 附件 | 只能按 ID 读取 ohmypm 数据目录中的文件；SVG 带沙箱 CSP，文本附件一律 `text/plain`；不存在访问项目源码文件的接口 |

## 错误格式

```json
{"error": {"code": "not_found", "message": "Entry not found: …", "details": {}}}
```

| HTTP | code |
|---|---|
| 401 | `unauthorized` |
| 403 | `bad_origin` |
| 404 | `not_found`、`project_not_registered` |
| 409 | `conflict`（`expected_revision` 不匹配、路径已被占用） |
| 413 | `too_large` |
| 421 | `bad_host` |
| 422 | `validation_error`（`details.errors` 列出字段） |

## 端点

| 方法与路径 | 说明 |
|---|---|
| `GET /api/health` | `{"status":"ok","version","schema"}` |
| `GET /api/meta` | 记录类型、状态、上传上限、默认作者 |
| `GET /api/dashboard` | 项目、最近记录、最近更新的摘要、类型统计 |
| `GET /api/projects?include_archived=` | 项目列表 |
| `POST /api/projects` | `{"path","name?","description?"}` 注册本机目录（只读取目录是否存在） |
| `GET /api/projects/{id}` | 项目详情（`id` 也可以是名称或 id 前缀） |
| `PATCH /api/projects/{id}` | `{"name?","description?","root_path?"}`（`root_path` 即 relink） |
| `DELETE /api/projects/{id}?purge=false` | 取消注册（保留数据）；`purge=true` 永久删除 |
| `GET /api/projects/{id}/summary` | 摘要 |
| `PUT /api/projects/{id}/summary` | `{"overview?",…,"replace?","expected_revision?","author?"}` |
| `GET /api/projects/{id}/summary/history` | 摘要修订 |
| `GET /api/projects/{id}/context?mode=&max_tokens=&page=&page_size=` | ContextBuilder 结果（含 `markdown`） |
| `GET /api/entries` | 参数：`project_id`（缺省为全部项目）、`type`（可重复）、`status`（可重复，含 `none`）、`q`、`since`、`until`、`author`、`order`=asc/desc、`sort`=sequence/created_at/updated_at、`limit`（≤500）、`offset`、`include_content` |
| `POST /api/entries` | `{"project_id","type","title","content","status?","author?","metadata?"}`，`source` 记为 `web` |
| `GET /api/entries/{id}` | 单条记录（含全文） |
| `PATCH /api/entries/{id}` | `{"title?","type?","content?","status?","clear_status?","metadata?","expected_revision?","author?"}` |
| `DELETE /api/entries/{id}` | 删除（保留可恢复的快照） |
| `GET /api/entries/{id}/revisions` | 修订列表 |
| `POST /api/entries/{id}/restore` | `{"revision"}` |
| `GET /api/search?q=&project_id=&kind=&type=&since=&until=&limit=&offset=` | 全文检索 |
| `POST /api/assets` | multipart：`file`、`project_id`、`entry_id?`；返回 `{id, uri, markdown, url, …}` |
| `GET /api/assets?project_id=&entry_id=` | 附件列表 |
| `GET /api/assets/{id}[?download=1]` | 文件内容 |
| `GET /api/assets/{id}/meta` | 附件元数据 |

示例：

```bash
TOKEN=$(cat ~/.local/share/ohmypm/web-token)
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8737/api/projects | jq
curl -s -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"project_id":"Robot_WS","type":"note","title":"来自 API"}' http://127.0.0.1:8737/api/entries
```

## Web UI

| 页面 | 内容 |
|---|---|
| 总览 `/` | 最近记录、最近活跃的项目、按类型的记录数、最近更新的摘要 |
| 项目 `/projects/:id` | 名称、目录、简介（可编辑）、摘要（当前状态与下一步）、时间线（序号、时间、类型、状态、作者、摘录、图片缩略图），按类型/状态/关键词/日期筛选，正序/倒序 |
| 记录 `/projects/:id/entries/:entryId` | 完整 Markdown 渲染（GFM 表格与任务列表、代码高亮、Mermaid、KaTeX、图片放大）、元数据、附件、修订历史与恢复、标记已解决、删除 |
| 编辑 `…/edit`、`…/entries/new` | 标题、类型、状态；富文本（MDXEditor）与 Markdown 源码 + 实时预览两种模式；图片可拖拽、粘贴或选择上传；按类型提供模板；离开页面前提示未保存修改；并发修改检测 |
| 摘要 `/projects/:id/summary` | 六个小节分别阅读与编辑 |
| Agent 上下文 `/projects/:id/context` | 预览 `ohmypm context` 的输出，可复制 |
| 搜索 `/search` | 全部或单个项目、按对象类型筛选，高亮命中词 |

富文本模式使用自定义数学插件保证 `$…$`、`$$…$$` 无损；打开记录时会检测富文本模式是否会改写原始 Markdown（例如 HTML 片段），若会则自动使用 Markdown 模式并给出提示。浅色/深色主题可在侧栏切换（默认跟随系统）。

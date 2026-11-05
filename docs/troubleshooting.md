# 故障排查

先运行 `ohmypm doctor`：它会显示版本、数据与配置路径、Schema 版本、FTS5 trigram 是否可用、Web UI 是否已构建以及各 Agent 的安装状态。

**`Error: No registered ohmypm project contains …`（退出码 3）**
当前目录不在任何已注册项目中。在项目根目录运行 `ohmypm register`，或用 `--project <名称>` 指定。用 `ohmypm list --all` 查看包括已取消注册在内的项目。

**项目目录移动后找不到项目**
`cd /new/path && ohmypm project relink /new/path --project <名称或 id>`。附件不受影响。

**`which ohmypm` 指向别的程序 / `uv tool install` 报冲突**
PATH 中有同名命令。`which -a ohmypm` 查看；确认可以替换后 `uv tool install --force …`，或者用绝对路径调用本工具（`~/.local/share/uv/tools/ohmypm/bin/ohmypm`）。

**`database is locked`**
写操作会等待最多 15 秒。若持续出现，检查是否有进程长时间持有写事务（例如被挂起的脚本），或数据目录是否在不支持文件锁的网络文件系统上。

**搜索不到 1–2 个字符的词**
1–2 字符的词走 LIKE 匹配，仍然可以搜索；如果结果过多，增加更长的词。`doctor` 中 `fts5_trigram: False` 表示 SQLite 太旧（需 ≥ 3.34），请升级 Python/SQLite。

**Web 页面显示 “Open the link from your terminal”**
浏览器没有访问 Cookie。打开 `ohmypm web` 打印的带 `?token=` 的链接，或把令牌（`~/.local/share/ohmypm/web-token`）粘贴到页面中。

**Web 页面返回 503 `web_ui_missing`**
安装包中不含前端。运行 `./scripts/build.sh` 后重新安装 wheel，或开发模式下 `./scripts/build-frontend.sh`。

**请求返回 421 / 403**
421：通过非 localhost 主机名访问（例如局域网 IP）；403：跨站写请求。这是有意的保护，见 [api.md](api.md)。

**编辑器打开后自动切到 Markdown 模式**
记录中有富文本编辑器会改写的语法（例如原始 HTML、行内 `$$…$$`）。为避免丢失内容，编辑器改用源码模式。在浏览器控制台执行 `localStorage.setItem("ohmypm-debug","1")` 后刷新，可以看到具体差异。

**Mermaid 图表显示 “could not be rendered”**
图表语法错误，提示中包含 Mermaid 的错误信息和源码。

**Agent 没有使用 ohmypm**
`ohmypm agents status` 确认状态为 `installed` 且目标文件是该 Agent 实际读取的文件；`inactive` 表示需要重新 `install`。Codex 存在 `AGENTS.override.md` 时只读取它。可用 `python3 scripts/verify_agents.py <agent>` 实测。

**恢复误删的记录或旧版本**
`ohmypm log deleted` 列出已删除记录（内容保存在修订表中）；`ohmypm log history <n>` / `ohmypm log restore <n> --revision <r>` 恢复旧版本；摘要用 `ohmypm summary history` / `restore`。整个数据库可以用 `ohmypm restore <backup>` 恢复，恢复前的数据保存在 `pre-restore-<时间>/`。

**附件占用空间**
`ohmypm assets gc` 列出无引用的附件，确认后 `--apply` 删除。

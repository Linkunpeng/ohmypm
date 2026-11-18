# CLI 参考

所有命令都不需要 Web 服务，在无图形环境下工作。`ohmypm <命令> --help` 查看完整帮助。

## 通用约定

- **项目识别**：默认根据当前目录（含子目录，嵌套项目取最长匹配）识别；`--project/-p <id|id前缀|名称>`（或环境变量 `OHMYPM_PROJECT`）显式指定；`--cwd/-C <dir>` 以其他目录为准。
- **`--json`**：stdout 只输出可解析的 JSON；出错时 stdout 为空，stderr 输出 `{"error": {"code", "message", "details"}}`。
- **输入**：正文可来自 `--content/-c`、`--file/-f <path>`（`-` 表示 stdin）或 `--stdin`，三者只能选一。UTF-8，支持很长的文本（单条上限 200 万字符）。
- **作者**：`--author` 或 `OHMYPM_AUTHOR`，或 `config.toml` 中的 `[ohmypm] author`。
- **时间参数**：`2026-11-01`、`2026-11-01T10:00`、`today`、`yesterday`、`30m`、`12h`、`7d`、`2w`；`--until` 只给日期时包含当天。
- **记录引用**：序号 `12` 或 `#12`（在当前项目中），或记录 ID / ID 前缀。

| 退出码 | 含义 |
|---|---|
| 0 | 成功（`status` 对未注册目录也返回 0，看 `registered` 字段） |
| 1 | 其他错误 |
| 2 | 用法错误（参数缺失等） |
| 3 | 当前目录不属于任何已注册项目 |
| 4 | 找不到（记录、项目、附件） |
| 5 | 校验失败（类型错误、空标题、需要 `--yes` 确认等） |
| 6 | 冲突（路径已被其他项目使用、并发修改） |
| 7 | 数据库由更新版本的 ohmypm 迁移过，当前版本无法打开（重新安装新版本，或恢复本版本做的备份） |

## 项目

```bash
ohmypm register [PATH] [--name N] [--description D]   # 默认当前目录；重复执行返回已有项目
ohmypm status                                         # 是否属于已注册项目、相对路径、记录数、未解决 issue（含久未更新数）
ohmypm list [--all]                                   # --all 包含已取消注册的项目
ohmypm project info
ohmypm project relink /new/path [--project P]         # 项目目录移动/重新克隆后
ohmypm project rename "Robot WS"
ohmypm project describe "ROS 2 巡检机器人" | --file f | --stdin
ohmypm project settings                               # 查看本项目生效的上下文预算与久未更新阈值
ohmypm project settings --brief-tokens 5000 --stale-days 14   # 项目级覆盖；token 设为 0 恢复默认
ohmypm project settings --stale-days 0                # 不再区分久未更新的 issue
ohmypm project settings --reset                       # 清除全部项目级覆盖
ohmypm unregister                                     # 保留历史，重新 register 可恢复
ohmypm unregister --purge --yes                       # 永久删除该项目的全部 ohmypm 数据
```

## 记录（log）

```bash
ohmypm log add --type milestone --title "完成相机驱动" --content "…" [--status open] [--author codex] \
               [--meta confidence=hypothesis --meta 'files=["a.c"]']
ohmypm log add -T issue -t "OpenCV 链接失败" --file issue.md
cat issue.md | ohmypm log add -T issue -t "OpenCV 链接失败" --stdin

ohmypm log list                        # 最近 30 条，按时间正序显示
ohmypm log list -r -n 10               # 最新在前
ohmypm log list -T issue -s open       # 按类型/状态（状态可用 none）
ohmypm log list -q "链接" --since 7d --until today --by codex
ohmypm log list --all-projects --json --full

ohmypm log show 12 [--raw]             # --raw 只输出 Markdown 正文
ohmypm log edit 12 --status resolved --append -c "修复：调整链接顺序"
ohmypm log edit 12 --title "…" --type decision --file new.md
ohmypm log edit 12 --editor            # 用 $EDITOR 编辑正文
ohmypm log edit 12 --clear-status
ohmypm log delete 12 --yes
ohmypm log history 12                  # 修订历史
ohmypm log restore 12 --revision 1     # 恢复旧版本（产生新修订）
ohmypm log deleted                     # 已删除但可找回的记录
```

类型：`note`、`milestone`、`issue`、`decision`、`knowledge`、`artifact`（以及 `config.toml` 中的扩展类型）。状态：`open`、`resolved`、`obsolete`；`issue` 默认 `open`，`obsolete` 的记录不进入上下文。

### 标签与关联

```bash
ohmypm log add -T issue -t "相册缩略图慢" --tag lvgl --tag device:a0ac1sn14a00013 -c "…"
ohmypm log add -T milestone -t "缩略图预加载" --fixes 12 --relates 8 -c "…"   # #12 标为 resolved
ohmypm log add -T knowledge -t "新部署流程" --supersedes 5 -c "…"             # #5 标为 obsolete
ohmypm log edit 12 --tag gallery --untag lvgl
ohmypm log edit 20 --relates 15 --unlink 8   # --unlink 只删除显式关联，不改状态
ohmypm log list --tag lvgl --tag gallery     # 同时带有全部标签
ohmypm search 缩略图 --tag lvgl
ohmypm context --tag lvgl                     # 只看带该标签的记录，摘要不过滤
ohmypm tags [--all]                           # 使用中的标签及记录数
```

- **标签**：统一转为小写，不能包含空格；可用字母（含中文）、数字和 `_ - . : /  +`，以字母或数字开头，最长 64 个字符，每条记录最多 20 个。可以用 `key:value` 表示维度，例如 `device:…`、`v3.6.0`。标签修改会产生修订，`log restore` 时一并恢复。
- **关联**：只能指向同一项目的记录。`--fixes N` 要求 N 是 issue，并在它处于 open 时标为 resolved；`--supersedes N` 把 N 标为 obsolete。这两种状态变化都是正常编辑，会保留修订。`--relates N` 只建立关联。
- **自动提及**：正文中的 `#N`（代码块和行内代码除外）会自动关联到第 N 条记录，正文修改后重新计算。升级数据库时会为已有记录补建这类关联。
- `log show` 显示双向关联（如 `fixes: #12`、`fixed by: #20`、`mentioned in: #31`）。context 在每条记录下列出 `_Links: …_`，并在开头列出使用中的标签。
- 关联本身不产生修订；删除任一端的记录时，关联一并删除。

### 作者名

写入时作者名会去掉首尾空白、转为小写，再按别名表映射。内置别名：`claude` / `claude code` → `claude-code`，`antigravity` → `agy`。可以在 `config.toml` 的 `[ohmypm] author_aliases` 中补充。已有记录可以批量整理：

```bash
ohmypm log authors [--all-projects]           # 各作者名的记录数，以及将改成的名称
ohmypm log authors --all-projects --apply     # 原地改写：不产生修订，不改变更新时间
```

## 摘要（summary）

摘要文档用二级标题划分小节，标题可用英文或中文别名：

| 小节 | 可用标题示例 |
|---|---|
| overview | Overview、项目简介、概述、目标 |
| architecture | Architecture、技术架构、架构 |
| current_state | Current State、当前状态、进展 |
| important_decisions | Important Decisions、重要决策、技术决策 |
| known_issues | Known Issues、已知问题、未解决问题 |
| next_steps | Next Steps、下一步、后续计划 |

```bash
ohmypm summary show                    # 输出可直接回写的 Markdown（修订信息在 stderr）
ohmypm summary show --section next_steps
ohmypm summary set --file summary.md   # 只更新文件中出现的小节
ohmypm summary set --file summary.md --replace   # 未出现的小节清空
ohmypm summary set --section "Known Issues" --content "- 偶发丢帧"
ohmypm summary history
ohmypm summary restore 3
```

不认识的二级标题会连同内容保留在前一个小节中，代码块中的 `##` 不会被当作标题。

## 上下文（context）

```bash
ohmypm context                          # brief，默认 3000 token
ohmypm context --mode standard          # 默认 8000 token：更多近期记录、决策、知识、产物
ohmypm context --mode full --page 2 --page-size 20   # 摘要 + 全部记录（最新在前）分页
ohmypm context --max-tokens 1500 --json
```

- 默认预算按优先级取值：`--max-tokens` → 项目设置（`ohmypm project settings`）→ `config.toml` 的 `[context]` → 内置默认（3000 / 8000 / 20000）。
- 超过阈值（默认 7 天）未更新的 open issue 不再展开正文，而是在“Stale Open Issues”小节中逐条列出序号、标题、打开日期和距上次更新的天数，并提示 Agent 核实后关闭或追加新发现。追加内容或修改状态都会刷新更新时间。JSON 中该小节的 `entries` 不含正文，`stats` 增加 `stale_open_issues` 与 `stale_issue_days`。
- 摘要更新后若又有新记录或新提交，头部会多一行“Since the summary: N commit(s) on HEAD … and M new record(s)”，提醒 Agent 核对并更新摘要。`stats` 中对应 `summary_commits_behind` 与 `records_since_summary`，`ohmypm status --json` 也包含这两项及 `summary_git`。

## Git 提交标记

项目根目录是 Git 仓库时，新记录的 `metadata.git` 和每次实际变更的摘要都会记下当时的 HEAD：`{"commit": "<完整 SHA>", "branch": "<分支名，分离 HEAD 时为 null>"}`。只执行只读的 `git rev-parse` / `symbolic-ref` / `rev-list`（3 秒超时，不加锁），失败时不记录，绝不阻塞写入。

- 记录的是写入时所在的提交；Agent 往往在提交前记录，所以它表示“基于哪个提交完成的工作”，不保证包含该工作本身。
- 调用方在 `metadata` 中自带 `git` 时不会被覆盖；编辑记录不会更新标记。
- `log show` 显示为 `git: cf637fb (master)`，context 中每条记录的元信息行显示 `at cf637fb`。
- 提交被 rebase 或 gc 丢弃后，落后提交数无法计算，只显示新增记录数。
- 在 `config.toml` 中设置 `[git] stamps = false` 可整体关闭。

## 搜索

```bash
ohmypm search "链接失败"                # 当前项目；不在项目中时自动搜索全部
ohmypm search "OpenCV 链接" --all       # 多个词全部匹配
ohmypm search '"undefined reference"' -T issue --since 30d
ohmypm search 相机 -k entry -n 50
```

## 附件

```bash
ohmypm assets add screenshot.png [--entry 12]   # 输出可粘贴进记录的 Markdown 引用
ohmypm assets list [--entry 12]
ohmypm assets path <asset-id>
ohmypm assets gc [--apply] [--all-projects] [--grace-hours 1]
```

## Agent、服务、数据

```bash
ohmypm agents install|update|remove|status [--agent claude|codex|pi|dsh|all] [--dry-run] [--force]
ohmypm agents update --reset-instructions   # 恢复内置的默认指令
ohmypm agents instructions [--path]

ohmypm web [--host 127.0.0.1] [--port 8737] [--open] [--no-auth] [--dev-origin URL]
ohmypm mcp                                  # stdio MCP 服务器（也可用 ohmypm-mcp）

ohmypm export [--all] [--output DIR]
ohmypm backup [--output FILE]
ohmypm restore FILE --yes
ohmypm doctor [--json]
```

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

## 项目

```bash
ohmypm register [PATH] [--name N] [--description D]   # 默认当前目录；重复执行返回已有项目
ohmypm status                                         # 是否属于已注册项目、相对路径、记录数、未解决 issue
ohmypm list [--all]                                   # --all 包含已取消注册的项目
ohmypm project info
ohmypm project relink /new/path [--project P]         # 项目目录移动/重新克隆后
ohmypm project rename "Robot WS"
ohmypm project describe "ROS 2 巡检机器人" | --file f | --stdin
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

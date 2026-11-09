# ohmypm 面板（Quickshell）

在桌面上快速查看项目记忆。窗口分为标题栏、左侧栏（总览 + 已注册项目）和主区域：

- **总览**：记录数、未解决的问题、近 7 天新增；近 14 天按类型堆叠的每日记录（悬停某天看明细）；所有项目的未解决问题和最新动态；每个项目一张卡片，带近 14 天的活动迷你图。
- **项目**：名称、路径、记录数 / 活跃天数 / 最近更新，下面四个标签页：
  - **概览**：项目摘要（现状，加最近里程碑 ✓ 和未解决问题 ○ 的标签）、下一步清单、未解决的问题、最近记录；
  - **时间线**：最近 200 条记录按天分组，可按类型筛选；
  - **总结**：摘要的六个小节；
  - **搜索**：边输入边全文搜索记录和摘要。

面板是普通窗口，由 Hyprland 和其他窗口一起平铺，不会遮挡它们。外观沿用 ohmyhypr 状态栏（半透明黑底、15px 圆角、强调色底边、JetBrainsMono Nerd Font），颜色跟随 `omh theme apply` 写入的主题。

数据只通过公开的 `ohmypm … --json` 命令读取，面板不直接访问数据库。

## 使用

```bash
quickshell/scripts/toggle.sh          # 显示 / 隐藏 / 移到当前工作区（未运行时先启动）
quickshell/scripts/toggle.sh start    # 只启动，不显示（开机自启用）
qs -p quickshell ipc call ohmypm select Robot_WS   # 切换到某个项目
```

`SUPER + I`：面板隐藏时在当前工作区平铺显示；面板有焦点时隐藏；在别的工作区或没有焦点时移到当前工作区。

显示时会自动选中当前聚焦窗口所在的项目（例如终端里 shell 的工作目录），找不到时保留上次的视图（默认是总览）。

键盘只保留 vim 风格的移动，其余操作都用鼠标：

| 按键 | 作用 |
|---|---|
| `j` / `k` | 侧栏下一项 / 上一项（总览和各项目） |
| `h` / `l` | 上一个 / 下一个标签页（概览、时间线、总结、搜索） |

用 `l` 切到搜索页不会占用键盘；点击搜索标签或标题栏的搜索按钮才会把光标放进输入框，在输入框里按 `Esc` 交还 hjkl。终端、复制上下文、Web UI、刷新都在界面上的按钮里，隐藏面板用 `SUPER + I`。

点击一条记录可展开完整正文。

标题栏的 **A+ / A−** 按 10% 调整整个面板的字号（100%–200%），侧栏、记录正文、Markdown 和搜索输入框同步变化。点击中间的百分比可恢复 100%。设置自动保存，重启后保留；按钮、标签和卡片布局会随字号调整，窄窗口中自动换行。

字号偏好保存在 `${OHMYPM_CONFIG_DIR:-${XDG_CONFIG_HOME:-~/.config}/ohmypm}/quickshell.ini`。

## Hyprland 绑定

ohmyhypr 的机器本地配置 `hypr/lua/omh/local.lua`（`setup` 中）：

```lua
local ohmypm_panel = os.getenv("HOME") .. "/workspace/ohmypm/quickshell/scripts/toggle.sh"
hl.bind(s.mod .. " + I", hl.dsp.exec_cmd(ohmypm_panel), { description = "[group:桌面] 项目记忆面板 (ohmypm)" })
hl.on("hyprland.start", function() hl.exec_cmd(ohmypm_panel .. " start") end)
```

## 环境变量

| 变量 | 作用 |
|---|---|
| `OHMYPM_BIN` | ohmypm 可执行文件（默认在 `PATH` 中查找；`toggle.sh` 会补上 `~/.local/bin`） |
| `OHMYPM_DATA_DIR` / `OHMYPM_CONFIG_DIR` | 与 CLI 相同，例如用 `scripts/seed_demo.py` 的演示数据调试 |
| `OHMYPM_WEB_PORT` | Web UI 端口（默认 8737） |
| `TERMINAL` | “终端”按钮使用的终端 |

## 文件

```text
shell.qml              入口：面板 + IPC（toggle / open / close / select / refresh / ping）
Panel.qml              平铺窗口（FloatingWindow，标题“ohmypm 项目面板”）、布局与键盘操作
components/            Sidebar、Dashboard（总览）、ProjectView 与 OverviewTab / TimelineTab / SummaryTab / SearchTab、
                       ActivityChart、EntryRow、Card、Box（状态栏样式的外框）…
services/Memory.qml    调用 ohmypm CLI（list / log list / context / search），缓存项目详情
services/Style.qml     状态栏尺寸与配色、ohmyhypr 主题、记录类型图标
scripts/               toggle.sh、focused-cwds.sh（聚焦窗口的工作目录）、open-web.sh
```

修改 QML 后重启：`qs -p quickshell kill && quickshell/scripts/toggle.sh start`。

# Agent 全局指令

ohmypm 把一份简洁的使用规范放在 `~/.config/ohmypm/agent-instructions.md`，`ohmypm agents install` 再把它接入各 Agent 的**全局**指令文件，让 Agent 在任何目录启动时都知道如何使用 ohmypm。被注册项目里的 `AGENTS.md`、`CLAUDE.md` 等项目级文件永远不会被修改。

## 各 Agent 的接入方式

以下位置在 2026-11-04 针对本机安装的版本核对过源码/文档，并用 `scripts/verify_agents.py` 实测：在临时 HOME 中安装后，让每个 Agent 把一次请求发到本地“抓包”服务器（运行在只有回环网卡的网络命名空间中，不会访问真实 API），确认系统提示中确实包含 ohmypm 指令。

| Agent（验证版本） | 目标文件 | 选择规则 | 方式 |
|---|---|---|---|
| Claude Code 2.1.303 | `$CLAUDE_CONFIG_DIR/CLAUDE.md`，默认 `~/.claude/CLAUDE.md` | 固定 | 写入一行 `@~/.config/ohmypm/agent-instructions.md`（Claude Code 的 import 语法，实测会被展开） |
| Codex CLI 0.166.0 | `$CODEX_HOME`，默认 `~/.codex` | 存在 `AGENTS.override.md` 时写它，否则写 `AGENTS.md`（与 Codex 的读取顺序一致） | 内联复制 |
| Pi 1.1.0 | `$PI_CODING_AGENT_DIR`，默认 `~/.pi/agent` | 按 Pi 的顺序取第一个存在的：`AGENTS.override.md`、`AGENTS.md`、`AGENTS.MD`、`CLAUDE.md`、`CLAUDE.MD`；都不存在则新建 `AGENTS.md` | 内联复制 |
| DSH 0.2.0-rc.2 | `$DSH_HOME/AGENTS.md`，默认 `~/.dsh/AGENTS.md` | 固定 | 内联复制 |

`ohmypm agents status` 会显示每个 Agent 实际读取的文件、安装状态和“verified with”说明。如果某个 Agent 升级后改变了加载规则，请用 `scripts/verify_agents.py` 重新验证。

## 管理区块

ohmypm 只增删如下区块，文件中的其他内容保持原样：

```markdown
<!-- ohmypm:start managed by `ohmypm agents`; edit ~/.config/ohmypm/agent-instructions.md and run `ohmypm agents update` instead of editing this block. sha=1a2b3c4d5e6f -->
…ohmypm 指令…
<!-- ohmypm:end -->
```

- **install**：创建共享指令文件（已存在则不覆盖，保留你的修改）；对检测到的 Agent（配置目录存在或命令在 PATH 中）追加区块，已存在则就地更新；重复执行结果为 `unchanged`。未检测到的 Agent 会被跳过并说明原因，`--force` 可强制安装。
- **update**：在修改共享指令后同步内联区块；只处理已经安装过的 Agent。`--reset-instructions` 恢复内置默认内容（旧文件备份为 `agent-instructions.md.<时间>.bak`）。
- **remove**：只删除区块和 ohmypm 添加的空行；如果文件只剩该区块（即文件是 ohmypm 创建的），整个文件会被删除。
- **status**：`installed` / `outdated`（需要 update）/ `not_installed` / `not_detected` / `inactive`（区块在一个 Agent 不读取的文件里，例如后来新建了 `AGENTS.override.md`，再次 install 会迁移）/ `broken`（标记不成对，ohmypm 不会自动修改，请手动处理）。
- 每次写入前，原文件备份到 `~/.local/share/ohmypm/agent-backups/<agent>/`（每个文件保留最近 10 份）。
- 符号链接（例如 dotfiles 管理的配置）会写入链接目标，链接本身保持不变。
- `--dry-run` 只显示将要发生的变化。

## 指令内容

默认指令要求 Agent：

1. **开始时**：运行 `ohmypm status --json`；已注册则运行 `ohmypm context`；未注册就正常工作，不要自行注册项目。
2. **过程中**：只记录有长期价值的信息——重要架构选择、阶段成果、复杂问题与解决方法、有代表性的失败尝试、工程知识、重要产物的用法；不记录简单命令、普通文件读取、临时调试输出、重复中间信息，以及任何密码、Token、密钥。未验证的推测用 `--meta confidence=hypothesis` 标注。
3. **阶段结束时**：保存重要结果、未解决的问题及排查过程、下一步建议；必要时更新项目摘要。
4. 记录要准确、简洁，使用用户的语言，不要干扰正常开发。

完整内容：`ohmypm agents instructions`。可以直接编辑 `~/.config/ohmypm/agent-instructions.md`，然后 `ohmypm agents update`（Claude Code 通过 import 读取，无需更新）。

## 推荐的记录格式

```bash
ohmypm log add --type issue --title "OpenCV 链接失败：undefined reference to TIFFReadDirectory" \
  --author codex --stdin <<'EOF'
## 错误表现
…
## 相关文件
…
## 已尝试
- …（包括失败的方法）
## 已确认
…
## 下一步
…
EOF
```

# 安装

## 环境要求

- Linux（使用了 `fcntl` 与 XDG 目录约定；macOS 理论可用但未验证）
- Python ≥ 3.12（已在 3.12 与 3.14 上运行全部测试）
- SQLite ≥ 3.34（需要 FTS5 `trigram`；Python 自带的 sqlite3 一般满足，`ohmypm doctor` 会检查）
- [uv](https://docs.astral.sh/uv/)（推荐）或 pip
- 构建 Web UI：Node ≥ 20、pnpm

## 从源码构建并安装

```bash
git clone <repo-url> ohmypm && cd ohmypm
./scripts/build.sh                                   # 前端 → src/ohmypm/webui/dist，然后 uv build
uv tool install dist/ohmypm-0.1.0-py3-none-any.whl   # 安装 `ohmypm` 与 `ohmypm-mcp` 命令
ohmypm doctor
```

也可以 `pip install dist/ohmypm-0.1.0-py3-none-any.whl`（建议在虚拟环境或 `pipx` 中）。

不需要 Web UI 时可以跳过前端构建：`uv tool install .`。此时 `ohmypm web` 只提供 API（`/api/docs`），访问页面会提示 UI 未构建。

> 如果 PATH 中已经有别的 `ohmypm` 命令（例如同名的旧工具），`uv tool install` 会提示冲突；确认可以替换后再加 `--force`。用 `which -a ohmypm` 查看。

## 开发模式

```bash
uv sync                      # 创建 .venv，安装依赖与开发依赖
uv run ohmypm --help
cd frontend && pnpm install && pnpm dev   # 前端开发服务器，/api 代理到 127.0.0.1:8737
```

前端开发时另开终端运行 `uv run ohmypm web --dev-origin http://localhost:5173`。

## 初始化

不需要单独初始化：第一次运行任意命令时自动创建数据目录（0700）和数据库（0600），并执行 Alembic 迁移到最新版本。升级 ohmypm 后同样会自动迁移；迁移过程有文件锁保护，多个进程同时启动是安全的。

## 配置文件（可选）

`~/.config/ohmypm/config.toml`：

```toml
[ohmypm]
author = "lkp"                 # Web/CLI 记录的默认作者（CLI 也可用 --author 或 OHMYPM_AUTHOR）

[web]
host = "127.0.0.1"
port = 8737

[assets]
max_upload_mb = 20

[entries]
extra_types = ["experiment"]   # 在 6 种内置类型之外追加的记录类型
```

文件中不认识的键会被忽略，ohmypm 从不改写已有的配置文件。环境变量见 `.env.example`。

## 卸载

```bash
ohmypm agents remove          # 先移除各 Agent 全局指令中的 ohmypm 区块
uv tool uninstall ohmypm
# 数据仍保留在 ~/.local/share/ohmypm 与 ~/.config/ohmypm，确认不再需要后手动删除
```

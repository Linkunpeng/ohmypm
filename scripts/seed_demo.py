#!/usr/bin/env python3
"""Fill a (temporary!) ohmypm data directory with realistic demo records.

Usage::

    OHMYPM_DATA_DIR=/tmp/ohmypm-demo/data OHMYPM_CONFIG_DIR=/tmp/ohmypm-demo/config \\
        uv run python scripts/seed_demo.py /tmp/ohmypm-demo/projects

Creates two project directories under the given path (they stay empty apart
from a README) and registers them. Refuses to run against the default data
directory so real data is never mixed with demo content.
"""

from __future__ import annotations

import os
import struct
import sys
import zlib
from pathlib import Path

from ohmypm.config import load_settings
from ohmypm.core.schemas import EntryCreate, SummaryUpdate
from ohmypm.core.service import MemoryService


def png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    row = b"\x00" + bytes(rgb) * width
    raw = b"".join(
        b"\x00" + b"".join(bytes(rgb) if (x // 8 + y // 8) % 2 else b"\xee\xf2\xf0" for x in range(width))
        for y in range(height)
    )
    del row
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


RICH = """\
## 完成内容

相机节点现在通过 **V4L2** 以 30 fps 采集 1280×720 图像，并发布到 `/camera/image_raw`。

```cpp
// src/camera/v4l2_capture.cpp
bool Capture::start() {
  if (ioctl(fd_, VIDIOC_STREAMON, &type_) < 0) return false;
  running_ = true;
  return true;
}
```

| 指标 | 目标 | 实测 |
|---|---|---|
| 帧率 | 30 fps | 29.8 fps |
| 延迟 | < 50 ms | 38 ms |
| CPU | < 15 % | 11 % |

```mermaid
flowchart LR
  cam[V4L2 camera] --> node[camera_node]
  node -->|image_raw| perception
  perception --> planner
```

曝光补偿使用 $E_v = \\log_2 \\frac{N^2}{t}$，标定误差：

$$
e = \\frac{1}{n} \\sum_{i=1}^{n} \\lVert p_i - \\hat{p}_i \\rVert_2
$$

- [x] 驱动编译通过
- [x] `colcon test` 通过
- [ ] 长时间稳定性测试

{image}

> 下一步：接入相机标定与时间同步。
"""


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    settings = load_settings()
    default = Path.home() / ".local" / "share" / "ohmypm"
    if not os.environ.get("OHMYPM_DATA_DIR") or settings.data_dir == default:
        sys.exit("Set OHMYPM_DATA_DIR to a temporary directory first.")
    base = Path(sys.argv[1]).expanduser()
    robot = base / "Robot_WS"
    web = base / "lab-dashboard"
    for d in (robot / "src" / "camera", web):
        d.mkdir(parents=True, exist_ok=True)
    (robot / "README.md").write_text("# Robot_WS\n")

    svc = MemoryService(settings)
    p, _ = svc.register(
        robot, description="ROS 2 workspace for the inspection robot: camera, perception and planning."
    )
    w, _ = svc.register(web)

    image = svc.add_asset("camera-test.png", png(160, 96, (47, 111, 143)), project=p.id)

    svc.set_summary(
        SummaryUpdate(
            overview="Robot_WS 是巡检机器人的 ROS 2 工作空间，包含相机驱动、感知和路径规划。",
            architecture="- `camera_node`：V4L2 采集\n- `perception`：OpenCV + ONNX Runtime\n- `planner`：A* 全局规划",
            current_state="相机驱动已完成并通过测试；感知模块的 OpenCV 链接问题尚未解决。",
            important_decisions="- 使用 V4L2 直接采集，而不是 GStreamer（延迟更低）。",
            known_issues="- OpenCV 4.10 与系统 libtiff 版本冲突导致链接失败。",
            next_steps="1. 解决 OpenCV 链接问题\n2. 完成相机标定\n3. 接入 planner",
        ),
        project=p.id,
        changed_by="codex",
    )
    records = [
        (
            "decision",
            "相机采集使用 V4L2 而不是 GStreamer",
            "GStreamer 管线在 Jetson 上增加约 20 ms 延迟。V4L2 直接采集更简单。",
            "claude",
            None,
        ),
        ("milestone", "完成相机驱动", RICH.replace("{image}", image.markdown), "codex", None),
        (
            "issue",
            "OpenCV 链接失败：undefined reference to TIFFReadDirectory",
            "## 错误表现\n\n```text\n/usr/bin/ld: libopencv_imgcodecs.so.410: undefined reference to `TIFFReadDirectory@LIBTIFF_4.0'\n```\n\n"
            "## 已尝试\n\n- 重新安装 `libtiff-dev`：无效\n- 设置 `-DBUILD_TIFF=ON` 重新编译 OpenCV：未完成\n\n"
            "## 已确认\n\nConda 环境中的 libtiff 4.6 覆盖了系统版本。\n\n## 下一步\n\n检查 `LD_LIBRARY_PATH`。",
            "claude",
            None,
        ),
        (
            "knowledge",
            "colcon 构建时必须先 source 安装目录",
            "`source install/setup.bash` 之后再运行 `ros2 run`。",
            "codex",
            None,
        ),
        (
            "artifact",
            "标定脚本 calibrate.py",
            "位置：`tools/calibrate.py`\n\n```bash\npython tools/calibrate.py --board 9x6 --square 0.025\n```",
            "codex",
            None,
        ),
        (
            "note",
            "带宽可能不足（待验证）",
            "两路相机同时开启时偶发丢帧，怀疑 USB 2.0 带宽不足。",
            "claude",
            {"confidence": "hypothesis"},
        ),
    ]
    for type_, title, content, author, meta in records:
        svc.add_entry(
            EntryCreate(
                type=type_, title=title, content=content, author=author, source="cli", metadata=meta or {}
            ),
            project=p.id,
        )
    svc.add_entry(
        EntryCreate(
            type="milestone",
            title="Dashboard skeleton with React Router",
            content="Routes for overview and runs.",
            author="pi",
        ),
        project=w.id,
    )
    print(f"Seeded {p.name} ({p.id}) and {w.name} ({w.id}) into {settings.data_dir}")


if __name__ == "__main__":
    main()

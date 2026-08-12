"""生成 Phase 3 本地视频源测试文件。

该脚本只生成本地 MP4 测试素材，不代表真实摄像头已接入。
"""

import subprocess
from pathlib import Path


def generate(path: Path, color: str) -> None:
    """使用 FFmpeg 生成短 MP4 文件。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=320x180:r=25",
            "-t",
            "2",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )


def main() -> None:
    """生成 site_config.json 默认引用的 overview_A/B 测试源。"""

    generate(Path("data/test/overview_A.mp4"), "blue")
    generate(Path("data/test/overview_B.mp4"), "green")
    print("generated data/test/overview_A.mp4 and data/test/overview_B.mp4")


if __name__ == "__main__":
    main()

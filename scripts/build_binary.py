#!/usr/bin/env python3
"""构建单文件可执行程序（PyInstaller），产物名与 installer.asset_name() 一致。

用法：
    python -m pip install pyinstaller
    python scripts/build_binary.py

产物：dist/binaries/<asset_name> 与同名 .sha256 校验文件。
CI 的 release.yml 会在 Windows / macOS / Linux 各跑一次本脚本，
把产物作为 GitHub Release 附件发布，安装脚本据此实现「无需 Python」。

构建机需要 Python，但**运行产物不需要**——PyInstaller 会把解释器一起打包。
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agys import __version__, installer  # noqa: E402

ENTRY = """\
import sys
from agys.cli import main
sys.exit(main())
"""


def main():
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        sys.exit("需要 PyInstaller：python -m pip install pyinstaller")

    name = installer.asset_name()
    if not name:
        sys.exit(f"不支持的平台/架构：{sys.platform} / "
                 f"{__import__('platform').machine()}（跳过二进制构建）")
    out_dir = ROOT / "dist" / "binaries"
    out_dir.mkdir(parents=True, exist_ok=True)
    is_exe = name.endswith(".exe")
    built_name = "agys.exe" if is_exe else "agys"
    print(f"==> 构建 {name}（agys {__version__}，{sys.platform}）")

    with tempfile.TemporaryDirectory(prefix="agys-build-") as td:
        tmp = Path(td)
        entry = tmp / "agys_entry.py"
        entry.write_text(ENTRY, encoding="utf-8")
        # 凭据后端按平台运行时导入，静态分析看不到 → 全量收集 agys 子模块
        hidden = ["--collect-submodules", "agys"]
        # msvcrt / fcntl 是条件导入（SwitchLock），只加当前平台存在的那个
        hidden += ["--hidden-import", "msvcrt" if sys.platform.startswith("win")
                   else "fcntl"]
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--onefile", "--clean", "--noconfirm",
            "--name", "agys",
            "--distpath", str(out_dir),
            "--workpath", str(tmp / "work"),
            "--specpath", str(tmp / "spec"),
            "--paths", str(ROOT / "src"),
            *hidden,
            str(entry),
        ]
        subprocess.check_call(cmd, cwd=str(ROOT))

    built = out_dir / built_name
    if not built.is_file():
        sys.exit(f"构建完成但找不到产物：{built}")
    target = out_dir / name
    if target.exists():
        target.unlink()
    shutil.move(str(built), str(target))
    if not is_exe:
        os.chmod(target, 0o755)

    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (out_dir / f"{name}.sha256").write_text(f"{digest}  {name}\n", encoding="utf-8")
    size = target.stat().st_size / 1024 / 1024
    print(f"==> 完成：{target}（{size:.1f} MiB）")
    print(f"    SHA-256: {digest}")

    # 冒烟：不依赖外部 agy，也不碰真实凭据 / 用户 home
    with tempfile.TemporaryDirectory(prefix="agys-smoke-") as home:
        env = dict(os.environ, AGYS_BACKEND="memory",
                   AGYS_HOME=os.path.join(home, "accounts"),
                   AGYS_GEMINI_HOME=os.path.join(home, "gemini"),
                   AGYS_MEMORY_FILE=os.path.join(home, "accounts", "mem.json"),
                   AGYS_PROCESS_NAMES="")
        subprocess.check_call([str(target), "version"], env=env)
    print("==> 冒烟通过：version")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

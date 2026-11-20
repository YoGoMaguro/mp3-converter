"""建立 release 套件。

在 Windows 產生免安裝 zip（含 FFmpeg），並產生一份原始碼 zip。
Linux 執行檔必須在 Linux 上執行這支腳本才會產生。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import convert_to_mp3_gui as app  # noqa: E402

VERSION = app.APP_VERSION
APP_NAME = "mp3-converter"
RELEASE_DIR = ROOT / "release"
BUILD_DIR = ROOT / "build"
DIST_DIR = BUILD_DIR / "dist"
SOURCE_PREFIX = f"{APP_NAME}-{VERSION}"
WINDOWS_DIR_NAME = f"{APP_NAME}-{VERSION}-windows-x64"


def main() -> None:
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    source_zip = RELEASE_DIR / f"{SOURCE_PREFIX}-source.zip"
    write_source_zip(source_zip)
    print(f"原始碼套件：{source_zip}")

    if sys.platform == "win32":
        windows_zip = RELEASE_DIR / f"{WINDOWS_DIR_NAME}.zip"
        build_windows_zip(windows_zip)
        print(f"Windows 套件：{windows_zip}")
        return

    if sys.platform.startswith("linux"):
        linux_name = f"{APP_NAME}-{VERSION}-linux-{machine_name()}"
        linux_zip = RELEASE_DIR / f"{linux_name}.zip"
        build_frozen_zip(linux_zip, linux_name, ffmpeg_bundle_name="ffmpeg")
        print(f"Linux 套件：{linux_zip}")
        return

    print("這個系統只建立原始碼套件。Windows 與 Linux 執行檔請在對應的系統上打包。")


def machine_name() -> str:
    machine = os.uname().machine if hasattr(os, "uname") else "unknown"
    return {"x86_64": "x64", "aarch64": "arm64", "AMD64": "x64"}.get(machine, machine)


def write_source_zip(destination: Path) -> None:
    excluded_dirs = {".git", "build", "dist", "release", "__pycache__", ".venv", "venv"}
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(ROOT)
            if any(part in excluded_dirs for part in relative.parts):
                continue
            if path.suffix.lower() == ".pyc":
                continue
            archive.write(path, arcname=Path(SOURCE_PREFIX) / relative)


def build_windows_zip(destination: Path) -> None:
    build_frozen_zip(destination, WINDOWS_DIR_NAME, ffmpeg_bundle_name="ffmpeg.exe")


def build_frozen_zip(destination: Path, folder_name: str, ffmpeg_bundle_name: str) -> None:
    run_pyinstaller()
    frozen_dir = DIST_DIR / APP_NAME
    if not frozen_dir.is_dir():
        raise SystemExit(f"找不到打包結果：{frozen_dir}")

    stage_root = BUILD_DIR / "stage"
    stage = stage_root / folder_name
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(frozen_dir, stage)

    ffmpeg = app.find_ffmpeg()
    if not ffmpeg:
        raise SystemExit("找不到 FFmpeg，無法做成免安裝套件。")
    shutil.copy2(ffmpeg, stage / ffmpeg_bundle_name)
    if os.name != "nt":
        os.chmod(stage / ffmpeg_bundle_name, 0o755)
    copy_ffmpeg_notices(Path(ffmpeg).resolve().parent.parent, stage)
    (stage / "使用說明.txt").write_text(user_guide(folder_name), encoding="utf-8")

    if destination.exists():
        destination.unlink()
    zip_directory(stage, destination)


def run_pyinstaller() -> None:
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        APP_NAME,
        "--collect-all",
        "customtkinter",
        "--collect-all",
        "tkinterdnd2",
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR / "work"),
        "--specpath",
        str(BUILD_DIR),
        str(ROOT / "convert_to_mp3_gui.py"),
    ]
    subprocess.run(command, cwd=ROOT, check=True)


def copy_ffmpeg_notices(ffmpeg_root: Path, stage: Path) -> None:
    """FFmpeg 官方 Windows 套件的授權放在 bin 的上一層。"""
    candidates = [ffmpeg_root, ffmpeg_root / "bin", Path(ffmpeg_root).parent]
    for folder in candidates:
        license_file = folder / "LICENSE"
        readme = folder / "README.txt"
        if license_file.is_file():
            shutil.copy2(license_file, stage / "FFmpeg-LICENSE.txt")
        if readme.is_file():
            shutil.copy2(readme, stage / "FFmpeg-README.txt")
        if (stage / "FFmpeg-LICENSE.txt").is_file():
            return


def user_guide(folder_name: str) -> str:
    executable = "mp3-converter.exe" if os.name == "nt" else "mp3-converter"
    return f"""MP3 轉檔 {VERSION}

套件資料夾：{folder_name}

1. 解壓縮後保留整個資料夾，不要只把 {executable} 拿到別處。
2. 開啟 {executable}。
3. 這個套件已附上 FFmpeg，不需要另外安裝 Python。

把音訊或影片拖進視窗，確認輸出路徑，然後按「開始轉換」。

隨附的 FFmpeg 採用 GPL v3。授權全文在 FFmpeg-LICENSE.txt，版本與原始碼位置在 FFmpeg-README.txt。
本工具以獨立程式呼叫 FFmpeg。工具本身的原始碼在 mp3-converter-{VERSION}-source.zip。
"""


def zip_directory(source: Path, destination: Path) -> None:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in source.rglob("*"):
            if path.is_file():
                archive.write(path, arcname=Path(source.name) / path.relative_to(source))


if __name__ == "__main__":
    main()

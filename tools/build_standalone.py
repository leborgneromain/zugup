import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = "zugup/web"
STOCKFISH_NOTICES = ROOT / "third_party" / "stockfish"


def stage_stockfish(binary, stage):
    folder = stage / "stockfish"
    folder.mkdir(parents=True)
    target = folder / ("stockfish.exe" if sys.platform == "win32" else "stockfish")
    shutil.copy2(binary, target)
    target.chmod(0o755)
    for notice in sorted(STOCKFISH_NOTICES.iterdir()):
        shutil.copy2(notice, folder / notice.name)
    return folder


def pyinstaller_args(stage, work):
    sep = os.pathsep
    args = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--name", "ZugUp",
        "--distpath", str(ROOT / "dist"), "--workpath", str(work / "build"), "--specpath", str(work),
        "--paths", str(ROOT / "src"),
        "--add-data", f"{ROOT / 'src' / WEB / 'templates'}{sep}{WEB}/templates",
        "--add-data", f"{ROOT / 'src' / WEB / 'static'}{sep}{WEB}/static",
        "--add-data", f"{stage / 'stockfish'}{sep}stockfish",
        "--add-data", f"{ROOT / 'LICENSE'}{sep}.",
        "--add-data", f"{ROOT / 'third_party'}{sep}licenses",
    ]
    args += ["--windowed"] if sys.platform in ("darwin", "win32") else []
    return args + [str(ROOT / "tools" / "standalone_entry.py")]


def package():
    dist = ROOT / "dist"
    arch = platform.machine().lower()
    if sys.platform == "darwin":
        archive = dist / f"ZugUp-macos-{arch}.zip"
        archive.unlink(missing_ok=True)
        subprocess.run(["ditto", "-c", "-k", "--keepParent", str(dist / "ZugUp.app"), str(archive)], check=True)
        return archive
    system = "windows" if sys.platform == "win32" else sys.platform
    return Path(shutil.make_archive(str(dist / f"ZugUp-{system}-{arch}"), "zip", dist, "ZugUp"))


def main():
    parser = argparse.ArgumentParser(description="Build the ZugUp standalone application for this operating system.")
    parser.add_argument("--stockfish", required=True, type=Path, help="Stockfish binary for this operating system and CPU")
    args = parser.parse_args()
    if not args.stockfish.is_file():
        sys.exit(f"Stockfish binary not found: {args.stockfish}")
    work = ROOT / "build"
    shutil.rmtree(work, ignore_errors=True)
    stage = work / "stage"
    stage_stockfish(args.stockfish, stage)
    subprocess.run(pyinstaller_args(stage, work), check=True)
    print(f"Archive: {package()}")


if __name__ == "__main__":
    main()

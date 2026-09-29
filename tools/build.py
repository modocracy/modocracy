"""일반판과 분석판을 각각 독립적인 단일 exe로 빌드한다."""
from pathlib import Path
import hashlib
import os
import subprocess
import sys

from PyInstaller.archive.readers import CArchiveReader

ROOT = Path(__file__).resolve().parent.parent


def main():
    # 캐시·임시 파일도 저장소의 빌드 폴더 안에 둔다.
    temp = ROOT / "build" / "tmp"
    temp.mkdir(parents=True, exist_ok=True)
    cache = ROOT / "build" / "pyinstaller-cache"
    assert temp.resolve().is_relative_to(ROOT) and cache.resolve().is_relative_to(ROOT)
    # 개발 도구가 PATH에 넣은 동명 DLL(예: Poppler의 ICU)을 잘못 묶지 않는다.
    system = Path(os.environ["SystemRoot"])
    search_path = os.pathsep.join(str(p) for p in (Path(sys.executable).parent, Path(sys.base_prefix),
                                                  system / "System32", system))
    env = dict(os.environ, TEMP=str(temp), TMP=str(temp), PATH=search_path,
               PYINSTALLER_CONFIG_DIR=str(cache))
    # DLL 검색 경로가 바뀌어도 예전 분석 결과를 재사용하지 않게 한다. 캐시는 위 저장소 내부로 제한한다.
    common = ["--noconfirm", "--clean", "--onefile", "--windowed", "--noupx",
              "--icon", str(ROOT / "assets/icon.ico"),
              "--add-data", f"{ROOT / 'assets/icon.ico'};assets",
              "--add-data", f"{ROOT / 'hd2mm/web'};hd2mm/web",
              "--add-data", f"{ROOT / 'hd2mm/ui_text.json'};hd2mm",
              "--add-data", f"{ROOT / 'hd2mm/licenses.txt'};hd2mm",
              "--exclude-module", "webview",
              "--distpath", str(ROOT / "dist"), "--specpath", str(ROOT / "build")]
    lines = []
    for name, entry in (("Modocracy", "launcher.py"), ("Modocracy-diagnostic", "launcher_diagnostic.py")):
        version = (ROOT / "assets/version_info.txt").read_text(encoding="utf-8")
        if name.endswith("-diagnostic"):
            version = version.replace("Modocracy.exe", name + ".exe").replace(
                "Modocracy - Helldivers 2 mod manager", "Modocracy Diagnostic - Helldivers 2 mod manager")
        version_path = ROOT / "build" / (name + "-version.txt")
        version_path.write_text(version, encoding="utf-8")
        subprocess.run([sys.executable, "-m", "PyInstaller", *common, "--name", name,
                        "--version-file", str(version_path),
                        "--workpath", str(ROOT / "build" / name), str(ROOT / entry)],
                       cwd=ROOT, env=env, check=True)
        artifact = ROOT / "dist" / (name + ".exe")
        payload = CArchiveReader(str(artifact))
        names = {n.replace("\\", "/").lower() for n in payload.toc}
        # Qt 6.10은 Windows 내장 ICU를 사용한다. PATH의 다른 ICU를 묶으면 시작부터 실패한다.
        if any(n.rsplit("/", 1)[-1] == "icuuc.dll" for n in names):
            raise RuntimeError("Unexpected bundled ICU DLL; check the build environment")
        if not any(n.endswith("/qwindows.dll") for n in names) or not any(n.endswith("/qt6widgets.dll") for n in names):
            raise RuntimeError("Qt Widgets runtime or Windows platform plugin is missing")
        lines.append(f"{hashlib.sha256(artifact.read_bytes()).hexdigest()}  {artifact.name}")
        print(f"Built {artifact} ({artifact.stat().st_size:,} bytes)", flush=True)
    (ROOT / "dist/SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()

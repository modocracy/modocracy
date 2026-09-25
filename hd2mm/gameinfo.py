"""게임 폴더 확인, 게임 버전·실행 여부, 외부 프로그램(7-Zip, Edge) 찾기."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

STEAM_APP_ID = 553850
GAME_EXE = "helldivers2.exe"
DEFAULT_GAME_PATH = r"C:\Program Files (x86)\Steam\steamapps\common\Helldivers 2"
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def normalize_game_path(raw: str | os.PathLike | None) -> Path | None:
    """사용자가 data 또는 bin 폴더를 골라도 게임 최상위 폴더로 맞춰 준다."""
    if not raw:
        return None
    path = Path(str(raw).strip().strip('"')).expanduser()
    if path.name.lower() in ("data", "bin") and (path.parent / "data").is_dir():
        path = path.parent
    return path


def check_game_path(raw) -> tuple[Path | None, str | None]:
    """(게임 폴더, 문제 설명) 을 돌려준다. 문제가 없으면 설명은 None."""
    path = normalize_game_path(raw)
    if path is None:
        return None, "게임 폴더가 아직 설정되지 않았어요."
    if not path.is_dir():
        return path, "설정된 게임 폴더가 존재하지 않아요."
    if not (path / "data").is_dir():
        return path, "Helldivers 2 폴더가 아닌 것 같아요 (data 폴더가 없어요)."
    return path, None


_version_cache: dict[str, tuple[float, str | None]] = {}


def exe_version(game_path: Path) -> str | None:
    """bin/helldivers2.exe 의 파일 버전(예: 1.8.46015.0)."""
    exe = game_path / "bin" / GAME_EXE
    try:
        mtime = exe.stat().st_mtime
    except OSError:
        return None
    cached = _version_cache.get(str(exe))
    if cached and cached[0] == mtime:
        return cached[1]
    version = _read_file_version(exe)
    _version_cache[str(exe)] = (mtime, version)
    return version


def _read_file_version(path: Path) -> str | None:
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    try:
        ver = ctypes.WinDLL("version")
        size = ver.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(str(path), 0, size, buf):
            return None
        ptr = ctypes.c_void_p()
        length = wintypes.UINT()
        if not ver.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(length)):
            return None
        fields = ctypes.cast(ptr, ctypes.POINTER(wintypes.DWORD * 4))
        ms, ls = fields.contents[2], fields.contents[3]  # dwFileVersionMS / LS
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except OSError:
        return None


_running_cache: tuple[float, bool] = (0.0, False)


def is_game_running() -> bool:
    global _running_cache
    now = time.monotonic()
    if now - _running_cache[0] < 2:
        return _running_cache[1]
    running = False
    if sys.platform == "win32":
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {GAME_EXE}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, errors="ignore", timeout=5,
                creationflags=CREATE_NO_WINDOW,
            ).stdout
            running = GAME_EXE in out.lower()
        except (OSError, subprocess.SubprocessError):
            running = False
    _running_cache = (now, running)
    return running


def detect_game_path() -> str | None:
    """Steam 라이브러리를 뒤져 Helldivers 2 설치 폴더를 찾는다."""
    candidates = [Path(DEFAULT_GAME_PATH)]
    for steam in _steam_roots():
        candidates.append(steam / "steamapps" / "common" / "Helldivers 2")
        vdf = steam / "steamapps" / "libraryfolders.vdf"
        try:
            text = vdf.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lib in re.findall(r'"path"\s+"([^"]+)"', text):
            lib_path = Path(lib.replace("\\\\", "\\"))
            candidates.append(lib_path / "steamapps" / "common" / "Helldivers 2")
    for path in candidates:
        if check_game_path(path)[1] is None:
            return str(path)
    return None


def _steam_roots() -> list[Path]:
    roots = []
    if sys.platform != "win32":
        return roots
    import winreg

    keys = [
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
    ]
    for hive, key, value in keys:
        try:
            with winreg.OpenKey(hive, key) as handle:
                roots.append(Path(winreg.QueryValueEx(handle, value)[0]))
        except OSError:
            continue
    return roots


def find_7zip() -> str | None:
    found = shutil.which("7z") or shutil.which("7za")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramW6432")):
        if base and (Path(base) / "7-Zip" / "7z.exe").is_file():
            return str(Path(base) / "7-Zip" / "7z.exe")
    if sys.platform == "win32":
        import winreg

        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\7-Zip") as handle:
                    exe = Path(winreg.QueryValueEx(handle, "Path")[0]) / "7z.exe"
                    if exe.is_file():
                        return str(exe)
            except OSError:
                continue
    return None


WEBVIEW2_RUNTIME_KEY = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def has_webview2() -> bool:
    """전용 앱 창을 그리는 Microsoft Edge WebView2 런타임이 설치돼 있는지 (Windows 11에는 기본 포함)."""
    if sys.platform != "win32":
        return False
    import winreg

    keys = [
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_RUNTIME_KEY}"),
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_RUNTIME_KEY}"),
        (winreg.HKEY_CURRENT_USER, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_RUNTIME_KEY}"),
    ]
    for hive, key in keys:
        try:
            with winreg.OpenKey(hive, key) as handle:
                version = str(winreg.QueryValueEx(handle, "pv")[0])
        except OSError:
            continue
        if version and version != "0.0.0.0":
            return True
    return False


def find_edge() -> str | None:
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            exe = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if exe.is_file():
                return str(exe)
    return shutil.which("msedge")

"""프로그램 시작점: 서버를 띄우고 Modocracy 전용 창을 연다.

기본 화면은 PySide6 Qt Widgets로 그린다. --browser는 이전 웹 화면을 여는 개발용 옵션이다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import APP_NAME, LEGACY_APP_NAME, __version__, gameinfo, i18n, updater
from .i18n import t
from .core import SETTINGS_FILE, Library, read_json, write_json
from .paths import log_path
from .server import AppServer

PREFERRED_PORT = 47815
log = logging.getLogger("hd2mm")
_mutex_handles = []


def acquire_instance_mutex(data_dir: Path) -> bool:
    if sys.platform != "win32":
        return True
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    normalized = os.path.normpath(str(data_dir.resolve())).lower()
    name = f"Local\\{APP_NAME}-" + hashlib.sha1(normalized.encode("utf-8")).hexdigest()
    handle = kernel32.CreateMutexW(None, False, name)
    error = ctypes.get_last_error()
    if not handle:
        raise ctypes.WinError(error)
    if error == 183:
        kernel32.CloseHandle(handle)
        return False
    _mutex_handles.append(handle)  # 프로세스가 끝날 때까지 핸들을 유지한다.
    return True


def web_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "hd2mm" / "web"


def default_data_dir() -> Path:
    """exe 옆에 ModocracyData 폴더가 있으면 그곳(휴대용), 아니면 %LOCALAPPDATA%\\Modocracy."""
    exe_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None
    if exe_dir and (exe_dir / "ModocracyData").is_dir():
        return exe_dir / "ModocracyData"
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_NAME


def migrate_legacy_data(data_dir: Path) -> bool:
    """이름을 바꾸기 전 보관 폴더(%LOCALAPPDATA%\\HD2ModManager)가 있으면 새 위치로 옮긴다.

    옮길 필요가 없거나 옮겼으면 True, 옛 폴더가 사용 중이라 옮기지 못했으면 False.
    """
    legacy = data_dir.parent / LEGACY_APP_NAME
    if data_dir.exists() or not (legacy / SETTINGS_FILE).is_file():
        return True
    try:
        settings = json.loads((legacy / SETTINGS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    if not isinstance(settings, dict) or "mods" not in settings or "gamePath" not in settings:
        return True  # 이름이 같은 다른 프로그램의 폴더일 수 있으니 건드리지 않는다
    try:
        os.replace(legacy, data_dir)
    except OSError:
        return False
    return True


def setup_logging(verbose: bool, *, diagnostic: bool = False) -> None:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose or diagnostic else logging.INFO)
    if diagnostic:
        handler = RotatingFileHandler(log_path(), maxBytes=1_000_000, backupCount=1, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
    else:
        root.addHandler(logging.NullHandler())
    if sys.stderr is not None:
        root.addHandler(logging.StreamHandler())


def open_window(url: str) -> None:
    edge = gameinfo.find_edge()
    if edge:
        try:
            subprocess.Popen(
                [edge, f"--app={url}", "--no-first-run", "--no-default-browser-check"],
                creationflags=gameinfo.CREATE_NO_WINDOW,
            )
            return
        except OSError:
            log.exception("Edge 실행 실패, 기본 브라우저로 엽니다.")
    webbrowser.open(url)


def icon_path() -> Path | None:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    path = base / "assets" / "icon.ico"
    return path if path.is_file() else None


def show_existing(url: str) -> None:
    """이미 실행 중인 매니저의 창을 앞으로 가져온다. 전용 창이 아니면(Edge 창 모드) 창을 하나 더 연다."""
    try:
        with urllib.request.urlopen(url + "api/focus", timeout=3) as res:
            if json.loads(res.read().decode("utf-8")).get("focused"):
                return
    except (OSError, ValueError):
        pass
    open_window(url + "?app=1")


def running_instance(data_dir: Path) -> str | None:
    """이미 실행 중인 매니저가 있으면 그 주소를 돌려준다."""
    try:
        info = json.loads((data_dir / "instance.json").read_text(encoding="utf-8"))
        url = f"http://127.0.0.1:{int(info['port'])}/"
        with urllib.request.urlopen(url + "api/ping", timeout=1.5) as res:
            ping = json.loads(res.read().decode("utf-8"))
        if ping.get("app") == "hd2mm" and ping.get("dataDir") == str(data_dir):
            return url
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def create_server(library: Library, port: int, auto_exit: bool) -> AppServer:
    for candidate in (port, 0) if port else (0,):
        try:
            return AppServer(("127.0.0.1", candidate), library, web_dir(), auto_exit=auto_exit)
        except OSError:
            continue
    raise OSError(t("startup.no_port"))


def saved_language(data_dir: Path) -> str | None:
    """설정 파일에서 언어만 읽는다. 보관함을 열기 전에 뜨는 오류 창도 사용자가 고른 언어로 띄우기 위해."""
    try:
        value = read_json(data_dir / SETTINGS_FILE).get("language")
    except (OSError, ValueError, AttributeError):
        return None
    return value if isinstance(value, str) else None


def show_error(message: str) -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10)
    else:
        print(message, file=sys.stderr)


def main(argv: list[str] | None = None, *, diagnostic: bool = False) -> int:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} - Helldivers 2 모드 매니저")
    parser.add_argument("--data-dir", help=f"모드 보관 폴더 (기본: %%LOCALAPPDATA%%\\{APP_NAME})")
    parser.add_argument("--port", type=int, default=PREFERRED_PORT)
    parser.add_argument("--no-window", action="store_true", help="창을 열지 않고 서버만 실행 (개발용)")
    parser.add_argument("--browser", action="store_true", help="전용 창 대신 Edge 앱 창(또는 기본 브라우저)으로 열기")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--diagnostic", action="store_true", help="분석용 로그를 exe 옆에 기록")
    args = parser.parse_args(argv)
    diagnostic = diagnostic or args.diagnostic
    updater.ASSET_NAME = f"{APP_NAME}-diagnostic.exe" if diagnostic else f"{APP_NAME}.exe"

    custom_dir = args.data_dir or os.environ.get("HD2MM_DATA_DIR")
    data_dir = Path(custom_dir or default_data_dir()).resolve()
    i18n.set_language(i18n.resolve(saved_language(data_dir)))  # 설정이 "auto"거나 없으면 Windows 언어
    try:
        acquired = acquire_instance_mutex(data_dir)
    except OSError as exc:
        show_error(t("startup.check_failed", detail=exc))
        return 1
    if not acquired:
        if diagnostic:
            from .ui_text import tr
            show_error(tr("native.close_other"))
            return 1
        if args.no_window:
            log.error("같은 보관함의 모드 매니저가 이미 실행 중이에요.")
            return 1
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            existing = running_instance(data_dir)
            if existing:
                show_existing(existing)
                return 0
            time.sleep(0.2)
        show_error(t("startup.not_responding"))
        return 1
    if not custom_dir and not migrate_legacy_data(data_dir):
        show_error(t("startup.legacy_running"))
        return 1
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        show_error(t("startup.data_dir_failed", path=data_dir, detail=exc))
        return 1
    try:
        setup_logging(args.verbose, diagnostic=diagnostic)
    except OSError as exc:
        show_error(t("startup.log_failed", path=log_path(), detail=exc))
        return 1

    existing = running_instance(data_dir)
    if existing:
        if args.no_window:
            log.error("같은 보관함의 모드 매니저가 이미 실행 중이에요.")
            return 1
        show_existing(existing)
        return 0

    # 업데이트 후 다시 켤 때도 같은 보관 폴더·창 방식으로 켜지도록 넘길 옵션
    updater.RESTART_ARGS[:] = (["--data-dir", str(data_dir)] if args.data_dir else []) + (["--browser"] if args.browser else []) + (["--diagnostic"] if diagnostic else [])
    try:
        library = Library(data_dir)
        if not library.game_path:
            library.set_game_path(gameinfo.detect_game_path())
        # 전용 창이면 창이 닫힐 때 끝나므로, 연결이 끊기면 스스로 끝나는 기능은 Edge 창 모드에서만 쓴다
        server = create_server(library, args.port, auto_exit=args.browser and not args.no_window)
    except Exception as exc:  # noqa: BLE001 - 창 없이 실행되므로 메시지 상자로 알림
        log.exception("시작 실패")
        show_error(t("startup.failed", detail=exc))
        return 1

    # 화면이 처음 제대로 뜨면 지난 업데이트가 남긴 옛 exe를 지운다 (교체 작업은 이것으로 성공을 확인한다)
    server.on_ready = updater.cleanup_leftovers if args.browser else None
    url = f"http://127.0.0.1:{server.port}/"
    instance_file = data_dir / "instance.json"
    write_json(instance_file, {"port": server.port, "pid": os.getpid()})
    log.info("%s %s 시작: %s (보관 폴더 %s)", APP_NAME, __version__, url, data_dir)
    try:
        if not args.no_window and not args.browser:
            from .native_ui import run_window
            return run_window(server, icon_path(), diagnostic=diagnostic)
        if not args.no_window:
            open_window(url + "?app=1")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        log.exception("창 시작 실패")
        show_error(t("startup.failed", detail=exc))
        return 1
    finally:
        server.server_close()
        instance_file.unlink(missing_ok=True)
    return 0

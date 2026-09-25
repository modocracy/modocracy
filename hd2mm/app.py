"""프로그램 시작점: 서버를 띄우고 Modocracy 전용 창을 연다.

전용 창은 Windows의 WebView2 부품으로 화면을 그린다. 쓸 수 없으면 Edge 앱 창(없으면 기본 브라우저)으로 연다.
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

from . import APP_NAME, LEGACY_APP_NAME, __version__, gameinfo
from .core import Library, write_json
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
    if data_dir.exists() or not (legacy / "settings.json").is_file():
        return True
    try:
        settings = json.loads((legacy / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    if not isinstance(settings, dict) or "mods" not in settings or "gamePath" not in settings:
        return True  # 이름이 같은 다른 프로그램의 폴더일 수 있으니 건드리지 않는다
    try:
        os.replace(legacy, data_dir)
    except OSError:
        return False
    return True


def setup_logging(data_dir: Path, verbose: bool) -> None:
    handler = RotatingFileHandler(data_dir / "log.txt", maxBytes=1_000_000, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.addHandler(handler)
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


def load_webview():
    """전용 창을 만드는 pywebview. 쓸 수 없으면 None (그때는 Edge 앱 창이나 기본 브라우저로 연다)."""
    if not gameinfo.has_webview2():
        log.info("WebView2가 없어 Edge 앱 창으로 엽니다.")
        return None
    try:
        import webview
    except Exception:  # noqa: BLE001 - 설치 안 됨, .NET 초기화 실패 등
        log.exception("전용 창을 쓸 수 없어 Edge 앱 창으로 엽니다.")
        return None
    return webview


def run_app_window(webview, server: AppServer, url: str) -> bool:
    """전용 창을 띄우고 닫힐 때까지 기다린다 (서버는 뒤에서 돈다).

    창이 한 번도 뜨지 못했으면 False를 돌려준다. 이때 서버는 멈추기만 하고 다시 쓸 수 있다.
    """
    window = webview.create_window(
        APP_NAME, url, width=1280, height=840, min_size=(760, 560),
        background_color="#0B0D10", text_select=True,
    )
    shown = threading.Event()
    minimized = threading.Event()
    window.events.shown += lambda *_: shown.set()
    window.events.minimized += lambda *_: minimized.set()
    window.events.restored += lambda *_: minimized.clear()
    window.events.maximized += lambda *_: minimized.clear()

    def pick_folder(initial: str | None) -> str | None:
        chosen = window.create_file_dialog(webview.FileDialog.FOLDER, directory=initial or "")
        return chosen[0] if chosen else None

    def bring_to_front() -> None:
        if minimized.is_set():
            window.restore()
        window.show()
        window.on_top = True  # 다른 창 뒤에 가려져 있으면 앞으로 올린다
        window.on_top = False

    server.folder_picker = pick_folder
    server.on_focus = bring_to_front
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    icon = icon_path()
    try:
        webview.start(gui="edgechromium", icon=str(icon) if icon else None)
    except Exception:  # noqa: BLE001 - 창 부품 오류는 기록하고 아래에서 처리
        log.exception("전용 창 오류")
    if not shown.is_set():
        server.folder_picker = server.on_focus = None
        server.shutdown()
        thread.join(5)
        return False
    # 적용하는 중에 창을 닫았으면 그 작업이 끝날 때까지 기다린 뒤 끝낸다
    if not server.finish_operations(timeout=300):
        log.warning("진행 중인 작업을 기다리다 시간이 지나 종료합니다.")
    server.shutdown()
    thread.join(5)
    return True


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
    raise OSError("사용할 수 있는 포트가 없어요.")


def show_error(message: str) -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10)
    else:
        print(message, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} - Helldivers 2 모드 매니저")
    parser.add_argument("--data-dir", help=f"모드 보관 폴더 (기본: %%LOCALAPPDATA%%\\{APP_NAME})")
    parser.add_argument("--port", type=int, default=PREFERRED_PORT)
    parser.add_argument("--no-window", action="store_true", help="창을 열지 않고 서버만 실행 (개발용)")
    parser.add_argument("--browser", action="store_true", help="전용 창 대신 Edge 앱 창(또는 기본 브라우저)으로 열기")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    custom_dir = args.data_dir or os.environ.get("HD2MM_DATA_DIR")
    data_dir = Path(custom_dir or default_data_dir()).resolve()
    try:
        acquired = acquire_instance_mutex(data_dir)
    except OSError as exc:
        show_error(f"실행 중인 모드 매니저를 확인하지 못했어요.\n\n{exc}")
        return 1
    if not acquired:
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
        show_error("실행 중인 모드 매니저가 응답하지 않아요. 잠시 후 다시 실행해 주세요.")
        return 1
    if not custom_dir and not migrate_legacy_data(data_dir):
        show_error("이전 버전(HD2ModManager)이 실행 중이라 설정을 옮기지 못했어요.\n이전 버전 창을 닫고 다시 실행해 주세요.")
        return 1
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        setup_logging(data_dir, args.verbose)
    except OSError as exc:
        show_error(f"모드 보관 폴더를 만들 수 없어요:\n{data_dir}\n\n{exc}")
        return 1

    existing = running_instance(data_dir)
    if existing:
        if args.no_window:
            log.error("같은 보관함의 모드 매니저가 이미 실행 중이에요.")
            return 1
        show_existing(existing)
        return 0

    webview = None if args.no_window or args.browser else load_webview()
    try:
        library = Library(data_dir)
        if not library.game_path:
            library.set_game_path(gameinfo.detect_game_path())
        # 전용 창이면 창이 닫힐 때 끝나므로, 연결이 끊기면 스스로 끝나는 기능은 Edge 창 모드에서만 쓴다
        server = create_server(library, args.port, auto_exit=not args.no_window and webview is None)
    except Exception as exc:  # noqa: BLE001 - 창 없이 실행되므로 메시지 상자로 알림
        log.exception("시작 실패")
        show_error(f"모드 매니저를 시작하지 못했어요.\n\n{exc}")
        return 1

    url = f"http://127.0.0.1:{server.port}/"
    instance_file = data_dir / "instance.json"
    write_json(instance_file, {"port": server.port, "pid": os.getpid()})
    log.info("%s %s 시작: %s (보관 폴더 %s)", APP_NAME, __version__, url, data_dir)
    try:
        if webview is not None:
            if run_app_window(webview, server, url):
                return 0
            log.warning("전용 창을 열지 못해 Edge 앱 창으로 엽니다.")
            server.start_auto_exit()
        if not args.no_window:
            open_window(url + "?app=1")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        instance_file.unlink(missing_ok=True)
    return 0

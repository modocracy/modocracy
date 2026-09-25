"""화면(웹 페이지)과 모드 로직을 잇는 로컬 HTTP 서버. 127.0.0.1 에서만 열린다."""
from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

from . import __version__, gameinfo, i18n, updater
from .i18n import t
from .core import Library, ModError, NeedsConfirm, analyze, mtime_ns, safe_join

log = logging.getLogger(__name__)

STATIC_FILES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/app.js": "app.js",
    "/i18n.js": "i18n.js",
    "/style.css": "style.css",
    "/icon.svg": "icon.svg",
}
MAX_JSON_BYTES = 1024 * 1024
# 보관함을 건드리지 않는 요청. 폴더 선택 창처럼 오래 걸려도 다른 요청을 막지 않도록 잠금 없이 처리한다.
# 업데이트 설치도 보관함을 건드리지 않는다 (내려받는 동안 화면이 멈추지 않도록)
LOCK_FREE_POSTS = {"/api/pick-folder", "/api/detect-game", "/api/update/install", "/api/update/check"}
UPDATE_CHECK_SECONDS = 30 * 60  # 새 버전 확인 결과를 다시 쓰는 시간
RASTER_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
}


class AppServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, library: Library, web_dir: Path, auto_exit: bool = True):
        super().__init__(address, Handler)
        self.library = library
        self.web_dir = web_dir
        self.token = secrets.token_urlsafe(24)
        self.lock = threading.RLock()     # 보관함·게임 폴더 작업은 한 번에 하나씩
        self.dialog_lock = threading.Lock()
        self.clients = 0
        self.active_operations = 0
        self.stopping = False
        self.ever_connected = False
        self.last_change = time.monotonic()
        self.client_lock = threading.Lock()
        # 전용 앱 창으로 실행할 때 app.py가 채운다: 창에 딸린 폴더 선택 창, 창을 앞으로 가져오기
        self.folder_picker = None
        self.on_focus = None
        self.on_exit = None  # 전용 창이면 창을 닫는 함수 (업데이트 후 다시 켤 때 쓴다)
        self.on_ready = None  # 화면이 처음 제대로 뜨면 한 번 부른다 (업데이트 뒤 옛 exe 정리)
        self.updating = False  # 새 버전을 받는 중: 다른 변경 작업은 받지 않는다
        self.update_cache: tuple[float, updater.Release] | None = None
        if auto_exit:
            self.start_auto_exit()

    def start_auto_exit(self) -> None:
        """Edge 앱 창·브라우저로 열었을 때: 창이 모두 닫히면(연결이 끊기면) 스스로 끝난다."""
        with self.client_lock:
            self.last_change = time.monotonic()
        threading.Thread(target=self._watch_clients, daemon=True).start()

    @property
    def port(self) -> int:
        return self.server_address[1]

    def client_delta(self, delta: int) -> None:
        with self.client_lock:
            self.clients += delta
            self.ever_connected = True
            self.last_change = time.monotonic()

    def _watch_clients(self) -> None:
        """창이 모두 닫히면(연결이 끊기면) 프로그램을 끝낸다."""
        while True:
            time.sleep(1)
            with self.client_lock:
                idle = self.clients == 0 and self.active_operations == 0
                since = time.monotonic() - self.last_change
                ever = self.ever_connected
                stop = idle and since > (5 if ever else 120)
                if stop:
                    self.stopping = True
            if stop:
                log.info("열린 창이 없어 종료합니다.")
                self.shutdown()
                return

    def begin_operation(self) -> bool:
        with self.client_lock:
            if self.stopping or self.updating:
                return False
            self.active_operations += 1
            return True

    def end_operation(self) -> None:
        with self.client_lock:
            self.active_operations -= 1
            self.last_change = time.monotonic()

    def request_exit(self) -> None:
        """프로그램을 끝낸다 (업데이트한 새 버전으로 다시 켜기 위해)."""
        if self.on_exit:
            self.on_exit()  # 창이 닫히면 app.py가 진행 중인 작업을 기다렸다가 끝낸다
            return

        def stop() -> None:
            self.finish_operations(timeout=300)
            self.shutdown()

        threading.Thread(target=stop, daemon=True).start()

    def finish_operations(self, timeout: float) -> bool:
        """새 작업은 받지 않고, 진행 중인 작업(적용 등)이 끝날 때까지 기다린다. 끝났으면 True."""
        deadline = time.monotonic() + timeout
        with self.client_lock:
            self.stopping = True
        while True:
            with self.client_lock:
                if self.active_operations == 0:
                    return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.1)


class Handler(BaseHTTPRequestHandler):
    server: AppServer
    server_version = f"Modocracy/{__version__}"

    def log_message(self, fmt, *args):
        log.debug("%s - %s", self.address_string(), fmt % args)

    # ---- 공통

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        return host in (f"127.0.0.1:{self.server.port}", f"localhost:{self.server.port}")

    def _send_json(self, data, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, status: int = 400, **extra) -> None:
        self._send_json({"error": message, **extra}, status)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_JSON_BYTES:
            raise ModError(t("err.request_too_large"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            raise ModError(t("err.bad_request")) from None
        if not isinstance(data, dict):
            raise ModError(t("err.bad_request"))
        return data

    # ---- GET

    def do_GET(self):
        if not self._host_ok():
            return self._error("forbidden", 403)
        url = urlsplit(self.path)
        path, query = url.path, parse_qs(url.query)
        try:
            if path in STATIC_FILES:
                return self._static(STATIC_FILES[path])
            if path == "/api/ping":
                return self._send_json({"app": "hd2mm", "version": __version__, "dataDir": str(self.server.library.data_dir)})
            if path == "/api/state":
                with self.server.lock:
                    self._send_json(build_state(self.server.library))
                ready, self.server.on_ready = self.server.on_ready, None
                if ready:
                    ready()
                return
            if path == "/api/events":
                return self._events()
            if path == "/api/update":
                return self._send_json(update_info(self.server))  # 다시 묻기(force)는 토큰이 필요한 POST로만
            if path == "/api/focus":
                # 두 번째로 실행했을 때 이미 열린 창을 앞으로 가져온다 (창을 보여 주는 것 말고는 하는 일이 없다)
                focus = self.server.on_focus
                if focus:
                    focus()
                return self._send_json({"focused": focus is not None})
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[:2] == ["api", "mods"] and parts[3] == "file":
                return self._mod_file(unquote(parts[2]), query.get("path", [""])[0])
            if len(parts) == 4 and parts[:2] == ["api", "mods"] and parts[3] == "readme":
                with self.server.lock:
                    return self._send_json({"readme": self.server.library.readme(unquote(parts[2]))})
            self._error("not found", 404)
        except ModError as exc:
            self._error(str(exc))
        except (ConnectionError, TimeoutError):
            pass
        except Exception:  # noqa: BLE001 - 화면에 알리고 기록
            log.exception("GET %s 실패", self.path)
            self._error(t("err.unknown"), 500)

    def _static(self, name: str) -> None:
        file = self.server.web_dir / name
        data = file.read_bytes()
        if name == "index.html":
            data = data.replace(b"__HD2MM_TOKEN__", self.server.token.encode())
            data = data.replace(b"__HD2MM_VERSION__", __version__.encode())
            data = data.replace(b"__HD2MM_LANG__", i18n.current().encode())
        ctype = {
            ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml",
        }.get(file.suffix, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _mod_file(self, mod_id: str, rel: str) -> None:
        with self.server.lock:
            root = self.server.library.mod_dir(mod_id)
        target = safe_join(root, rel)
        if target is None or not target.is_file():
            return self._error("not found", 404)
        ctype = RASTER_TYPES.get(target.suffix.lower())
        if ctype is None:
            return self._error("not found", 404)
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=86400")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "sandbox; default-src 'none'")
        self.end_headers()
        self.wfile.write(data)

    def _events(self) -> None:
        """창이 열려 있는 동안 유지되는 연결. 끊기면 창이 닫힌 것으로 본다."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.server.client_delta(+1)
        try:
            self.wfile.write(b"retry: 1000\n\n")
            self.wfile.flush()
            while True:
                time.sleep(2)
                self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except OSError:
            pass
        finally:
            self.server.client_delta(-1)

    # ---- POST

    def do_POST(self):
        if not self._host_ok() or self.headers.get("X-HD2MM-Token") != self.server.token:
            return self._error("forbidden", 403)
        if not self.server.begin_operation():
            if self.server.updating:
                return self._error(t("err.updating"), 503)
            return self._error(t("err.shutting_down"), 503)
        try:
            self._handle_post()
        finally:
            self.server.end_operation()

    def _handle_post(self):
        url = urlsplit(self.path)
        path, query = url.path, parse_qs(url.query)
        try:
            if path == "/api/import":
                return self._import(query.get("name", [""])[0])
            body = self._read_json()
            if path in LOCK_FREE_POSTS:
                result = self._post(path, body)
            else:
                with self.server.lock:
                    result = self._post(path, body)
            if result is None:
                return self._error("not found", 404)
            self._send_json(result)
        except NeedsConfirm as exc:
            self._error(t("err.needs_confirm"), 409, needsConfirm="unmanaged", unmanaged=exc.unmanaged)
        except ModError as exc:
            self._error(str(exc))
        except (ConnectionError, TimeoutError):
            pass
        except Exception:  # noqa: BLE001
            log.exception("POST %s 실패", self.path)
            self._error(t("err.unknown"), 500)

    def _post(self, path: str, body: dict):
        lib = self.server.library
        parts = path.strip("/").split("/")
        if path == "/api/order":
            ids = body.get("ids")
            if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
                raise ModError(t("err.bad_request"))
            lib.reorder(ids)
            return {"ok": True}
        if len(parts) == 3 and parts[:2] == ["api", "mods"]:
            lib.update(parts[2], body)
            return {"ok": True}
        if len(parts) == 4 and parts[:2] == ["api", "mods"] and parts[3] == "delete":
            lib.remove(parts[2])
            return {"ok": True}
        if path in ("/api/deploy", "/api/purge"):
            game = _require_game(lib)
            if gameinfo.is_game_running():
                raise ModError(t("err.game_running"))
            mode = body.get("unmanaged", "ask")
            if mode not in ("ask", "move", "keep") or (path == "/api/deploy" and mode == "keep"):
                raise ModError(t("err.bad_request"))
            action = lib.deploy if path == "/api/deploy" else lib.purge
            result = action(game, mode)
            log.info("%s 완료: %s", path, result)
            return result
        if path == "/api/settings":
            if "language" in body and body["language"] not in i18n.SETTINGS:
                raise ModError(t("err.bad_request"))
            if "gamePath" in body:
                game, problem = gameinfo.check_game_path(body.get("gamePath"))
                if problem and game is not None and not body.get("force"):
                    raise ModError(problem)
                lib.set_game_path(str(game) if game else None)
            if "language" in body:
                lib.settings["language"] = body["language"]
                lib.save()
                i18n.set_language(i18n.resolve(body["language"]))
            if "checkUpdates" in body:
                lib.settings["checkUpdates"] = bool(body["checkUpdates"])
                lib.save()
            return {"ok": True}
        if path == "/api/update/install":
            return _install_update(self.server)
        if path == "/api/update/check":
            return update_info(self.server, force=True)
        if path == "/api/detect-game":
            return {"path": gameinfo.detect_game_path()}
        if path == "/api/pick-folder":
            return {"path": _pick_folder(self.server, lib.game_path)}
        if path == "/api/open":
            return _open_target(lib, body)
        if path == "/api/launch-game":
            os.startfile(f"steam://rungameid/{gameinfo.STEAM_APP_ID}")  # noqa: S606 - Steam 실행
            return {"ok": True}
        return None

    def _import(self, name: str) -> None:
        name = Path(name.replace("\\", "/")).name
        if not name:
            return self._error(t("err.no_file_name"))
        lib = self.server.library
        length = int(self.headers.get("Content-Length") or 0)
        upload = lib.tmp_dir / f"upload-{uuid.uuid4().hex}{Path(name).suffix.lower()}"
        try:
            with open(upload, "wb") as out:
                remaining = length
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, 1024 * 1024))
                    if not chunk:
                        break
                    out.write(chunk)
                    remaining -= len(chunk)
            if remaining:
                return self._error(t("err.upload_incomplete"))
            with self.server.lock:
                result = lib.import_archive(upload, name)
            log.info("모드 추가: %s -> %s", name, result)
            self._send_json(result)
        except ModError as exc:
            self._error(str(exc))
        finally:
            upload.unlink(missing_ok=True)


def _require_game(lib: Library) -> Path:
    game, problem = gameinfo.check_game_path(lib.game_path)
    if problem:
        raise ModError(t("err.set_game_folder", problem=problem))
    return game


def _pick_folder(server: AppServer, initial: str | None) -> str | None:
    if not server.dialog_lock.acquire(blocking=False):
        raise ModError(t("err.dialog_open"))
    try:
        start = initial if initial and Path(initial).is_dir() else None
        if server.folder_picker:  # 전용 앱 창: 창에 딸린 Windows 폴더 선택 창
            chosen = server.folder_picker(start)
            return str(Path(chosen)) if chosen else None
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            chosen = filedialog.askdirectory(
                parent=root, title=t("dialog.pick_game_folder"), mustexist=True, initialdir=start,
            )
        finally:
            root.destroy()
        return str(Path(chosen)) if chosen else None
    finally:
        server.dialog_lock.release()


def _open_target(lib: Library, body: dict) -> dict:
    target = body.get("target")
    if target == "mod":
        path = lib.mod_dir(str(body.get("id")))
    elif target == "library":
        path = lib.data_dir
    elif target == "backups":
        path = lib.backups_dir
    elif target in ("game", "data"):
        path = _require_game(lib)
        path = path / "data" if target == "data" else path
    elif target == "log":
        path = lib.data_dir / "log.txt"
    elif target == "release":
        os.startfile(updater.RELEASES_PAGE)  # noqa: S606 - 정해진 릴리즈 페이지만 연다
        return {"ok": True}
    else:
        raise ModError(t("err.bad_request"))
    if not path.exists():
        raise ModError(t("err.folder_missing"))
    os.startfile(str(path))  # noqa: S606 - 탐색기로 열기
    return {"ok": True}


def update_info(server: AppServer, force: bool = False) -> dict:
    """새 버전이 있는지. GitHub에 너무 자주 묻지 않도록 결과를 잠시 기억해 둔다."""
    now = time.monotonic()
    cached = server.update_cache
    if force or cached is None or now - cached[0] > UPDATE_CHECK_SECONDS:
        cached = (now, updater.fetch_latest())
        server.update_cache = cached
    release = cached[1]
    newer = updater.is_newer(release.version)
    problem = updater.install_problem(release) if newer else None
    return {
        "current": __version__, "latest": release.version, "newer": newer,
        "url": release.url, "notes": release.notes, "canInstall": newer and problem is None, "problem": problem,
    }


def _install_update(server: AppServer) -> dict:
    """새 버전을 받아 검사하고, 이 프로그램이 끝나면 바꿔 끼워 다시 켜지도록 한다."""
    with server.client_lock:
        if server.updating:
            raise ModError(t("err.already_updating"))
        if server.active_operations > 1:  # 이 요청 말고 진행 중인 작업(적용 등)
            raise ModError(t("err.busy_try_later"))
        server.updating = True  # 여기서부터 다른 변경 작업은 받지 않는다
    scheduled = False
    try:
        release = updater.fetch_latest()
        if not updater.is_newer(release.version):
            raise ModError(t("err.already_latest"))
        problem = updater.install_problem(release)
        if problem:
            raise ModError(problem)
        exe = updater.current_exe()
        new_file = updater.download(release, exe)
        if server.stopping:  # 받는 동안 창을 닫았으면 업데이트하지 않는다
            new_file.unlink(missing_ok=True)
            raise ModError(t("err.update_cancelled"))
        updater.schedule_swap(exe, new_file)
        scheduled = True
    finally:
        if not scheduled:
            with server.client_lock:
                server.updating = False
    log.info("업데이트 준비 완료: %s -> %s", __version__, release.version)
    threading.Timer(1.0, server.request_exit).start()  # 응답을 보낸 뒤 끝낸다
    return {"restarting": True, "version": release.version}


def build_state(lib: Library) -> dict:
    game, problem = gameinfo.check_game_path(lib.game_path)
    version = gameinfo.exe_version(game) if game and not problem else None
    snapshot = lib.snapshot()
    issues = analyze(snapshot, version)
    records = lib.load_records()  # 설치 기록은 한 번만 읽어서 함께 쓴다
    status = lib.status(game, snapshot, records) if game and not problem else {"state": "nogame", "unmanaged": []}
    status["otherDeployments"] = lib.other_deployments(game if game and not problem else None, records)
    targets = status.pop("planTargets", {})
    mods = []
    for snap in snapshot:
        entry = snap.entry
        mod = {
            "id": snap.id,
            "enabled": bool(entry.get("enabled")),
            "sourceName": entry.get("sourceName"),
            "addedAt": entry.get("addedAt"),
            "updatedAt": entry.get("updatedAt"),
            "error": snap.error,
            "issues": issues.get(snap.id, []),
        }
        if snap.info:
            info = snap.info
            root = info.root

            def url(rel):
                # v=그림 파일 수정 시각: 그림이 바뀌면 주소가 바뀌어 브라우저가 새로 받는다
                if not rel or Path(rel).suffix.lower() not in RASTER_TYPES:
                    return None
                return f"/api/mods/{quote(snap.id)}/file?path={quote(rel)}&v={_revision(root / rel) or 0}"

            extra = info.extra or {}
            mod.update({
                "name": info.name,
                "description": info.description,
                "version": extra.get("version") or None,
                "gameVersion": extra.get("exeVersion") or None,
                "requires": extra.get("requires", []),
                "guid": info.guid,
                "icon": url(info.icon),
                "kind": info.kind,
                "mode": info.mode,
                "options": [
                    {
                        "name": o.name, "description": o.description, "image": url(o.image),
                        "subs": [{"name": s.name, "description": s.description, "image": url(s.image)} for s in o.subs],
                    }
                    for o in info.options
                ],
                "state": snap.state,
                "files": [
                    {
                        "source": ps.main.relative_to(root.resolve()).as_posix()
                        if root.resolve() in ps.main.parents else ps.main.name,
                        "size": _size(ps.main),
                        "target": targets.get(f"{snap.id}|{ps.main}"),
                    }
                    for ps in snap.sets
                ],
                # README 본문은 펼칠 때 /api/mods/<id>/readme 로 가져온다. readmeRev가 바뀌면 다시 받는다.
                "hasReadme": info.readme_file is not None,
                "readmeRev": _revision(root / info.readme_file) if info.readme_file else None,
            })
        else:
            mod["name"] = entry.get("fallbackName") or entry.get("sourceName") or snap.id
        mods.append(mod)
    return {
        "appVersion": __version__,
        "checkUpdates": lib.settings.get("checkUpdates", True),
        "language": lib.settings.get("language", "auto"),  # 설정값: auto / ko / en
        "lang": i18n.current(),  # 지금 쓰는 언어
        "game": {
            "path": str(game) if game else None,
            "problem": problem,
            "version": version,
            "running": gameinfo.is_game_running() if game and not problem else False,
        },
        "status": status,
        "mods": mods,
        "paths": {"library": str(lib.data_dir), "backups": str(lib.backups_dir)},
        "sevenZip": gameinfo.find_7zip() is not None,
    }


def _revision(path: Path) -> str | None:
    """파일 수정 시각(ns)을 문자열로. 숫자로 보내면 브라우저에서 정밀도가 깎인다."""
    value = mtime_ns(path)
    return str(value) if value is not None else None


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0

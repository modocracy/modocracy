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

from . import __version__, gameinfo
from .core import Library, ModError, NeedsConfirm, analyze, mtime_ns, safe_join

log = logging.getLogger(__name__)

STATIC_FILES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/app.js": "app.js",
    "/style.css": "style.css",
    "/icon.svg": "icon.svg",
}
MAX_JSON_BYTES = 1024 * 1024
# 보관함을 건드리지 않는 요청. 폴더 선택 창처럼 오래 걸려도 다른 요청을 막지 않도록 잠금 없이 처리한다.
LOCK_FREE_POSTS = {"/api/pick-folder", "/api/detect-game"}
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
        if auto_exit:
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
            if self.stopping:
                return False
            self.active_operations += 1
            return True

    def end_operation(self) -> None:
        with self.client_lock:
            self.active_operations -= 1
            self.last_change = time.monotonic()


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
            raise ModError("요청이 너무 커요.")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            raise ModError("잘못된 요청이에요.") from None
        if not isinstance(data, dict):
            raise ModError("잘못된 요청이에요.")
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
                    return self._send_json(build_state(self.server.library))
            if path == "/api/events":
                return self._events()
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
            self._error("알 수 없는 오류가 났어요. 로그 파일을 확인해 주세요.", 500)

    def _static(self, name: str) -> None:
        file = self.server.web_dir / name
        data = file.read_bytes()
        if name == "index.html":
            data = data.replace(b"__HD2MM_TOKEN__", self.server.token.encode())
            data = data.replace(b"__HD2MM_VERSION__", __version__.encode())
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
            return self._error("프로그램이 종료 중이에요. 다시 실행해 주세요.", 503)
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
            self._error("확인이 필요해요.", 409, needsConfirm="unmanaged", unmanaged=exc.unmanaged)
        except ModError as exc:
            self._error(str(exc))
        except (ConnectionError, TimeoutError):
            pass
        except Exception:  # noqa: BLE001
            log.exception("POST %s 실패", self.path)
            self._error("알 수 없는 오류가 났어요. 로그 파일을 확인해 주세요.", 500)

    def _post(self, path: str, body: dict):
        lib = self.server.library
        parts = path.strip("/").split("/")
        if path == "/api/order":
            ids = body.get("ids")
            if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
                raise ModError("잘못된 요청이에요.")
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
                raise ModError("게임이 실행 중이에요. 게임을 완전히 끈 뒤 다시 시도해 주세요.")
            mode = body.get("unmanaged", "ask")
            if mode not in ("ask", "move", "keep") or (path == "/api/deploy" and mode == "keep"):
                raise ModError("잘못된 요청이에요.")
            action = lib.deploy if path == "/api/deploy" else lib.purge
            result = action(game, mode)
            log.info("%s 완료: %s", path, result)
            return result
        if path == "/api/settings":
            raw = body.get("gamePath")
            game, problem = gameinfo.check_game_path(raw)
            if problem and game is not None and not body.get("force"):
                raise ModError(problem)
            lib.set_game_path(str(game) if game else None)
            return {"ok": True}
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
            return self._error("파일 이름이 없어요.")
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
                return self._error("파일을 끝까지 받지 못했어요. 다시 시도해 주세요.")
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
        raise ModError(problem + " 설정에서 게임 폴더를 지정해 주세요.")
    return game


def _pick_folder(server: AppServer, initial: str | None) -> str | None:
    if not server.dialog_lock.acquire(blocking=False):
        raise ModError("폴더 선택 창이 이미 열려 있어요.")
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            chosen = filedialog.askdirectory(
                parent=root, title="Helldivers 2 설치 폴더 선택", mustexist=True,
                initialdir=initial if initial and Path(initial).is_dir() else None,
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
    else:
        raise ModError("잘못된 요청이에요.")
    if not path.exists():
        raise ModError("열 폴더가 없어요.")
    os.startfile(str(path))  # noqa: S606 - 탐색기로 열기
    return {"ok": True}


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
            stamp = int(root.stat().st_mtime)

            def url(rel):
                return f"/api/mods/{quote(snap.id)}/file?path={quote(rel)}&v={stamp}" if rel and Path(rel).suffix.lower() in RASTER_TYPES else None

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

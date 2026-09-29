"""로컬 서버(화면과 로직 연결) 테스트. 가짜 게임 폴더만 사용한다."""
from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from hd2mm import app, gameinfo, i18n, paths
from hd2mm.app import web_dir
from hd2mm.core import Library
from hd2mm.server import AppServer, Handler, RASTER_TYPES
from tests.test_core import ARCHIVE, make_zip

ROOT = Path(__file__).resolve().parent.parent
LOADER_ZIP = ROOT / "Bingus-Shared-Loader-v17.zip"


class ServerCase(unittest.TestCase):
    """가짜 게임 폴더와 실제 로컬 서버를 띄우는 준비 과정 (다른 테스트 파일에서도 쓴다)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hd2mm-srv-"))
        self.game = self.tmp / "game"
        (self.game / "data").mkdir(parents=True)
        self.lib = Library(self.tmp / "data")
        self.lib.set_game_path(str(self.game))
        self.server = AppServer(("127.0.0.1", 0), self.lib, web_dir(), auto_exit=False)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.port}"
        patcher = mock.patch.object(gameinfo, "is_game_running", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def request(self, path, body=None, data=None, token=True, headers=None):
        hdrs = dict(headers or {})
        if token:
            hdrs["X-HD2MM-Token"] = self.server.token
        if body is not None:
            data = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, headers=hdrs, method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                return res.status, json.loads(res.read() or b"{}")
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read() or b"{}")


class ServerTests(ServerCase):
    def test_open_log_uses_application_folder_instead_of_library(self):
        expected = self.tmp / "log.txt"
        expected.write_text("application log", encoding="utf-8")
        (self.lib.data_dir / "log.txt").write_text("old log", encoding="utf-8")
        with mock.patch("hd2mm.server.log_path", return_value=expected), \
                mock.patch("hd2mm.server.os.startfile", create=True) as open_file:
            self.assertEqual(self.request("/api/open", body={"target": "log"})[0], 200)
        open_file.assert_called_once_with(str(expected))

    def test_ui_diagnostics_require_token_and_validate_body(self):
        body = {"event": "error", "detail": "resource: /i18n.js"}
        self.assertEqual(self.request("/api/ui-diagnostics", body=body, token=False)[0], 403)
        for body in ({"event": "other"}, {"event": "error", "detail": []}):
            with self.subTest(body=body):
                self.assertEqual(self.request("/api/ui-diagnostics", body=body)[0], 400)
        self.assertEqual(self.server.ui_reports, 0)

    def test_ui_diagnostics_log_resource_failure_and_readiness(self):
        with self.assertLogs("hd2mm.server", "INFO") as logs:
            self.assertEqual(self.request("/api/ui-diagnostics", body={"event": "error", "detail": "resource: /i18n.js"})[0], 200)
            self.assertEqual(self.request("/api/ui-diagnostics", body={"event": "ready", "detail": "test runtime"})[0], 200)
        self.assertIn('UI error: "resource: /i18n.js"', logs.output[0])
        self.assertIn('UI ready: "test runtime"', logs.output[1])

    def test_ui_diagnostics_bound_and_escape_log_messages(self):
        with self.assertLogs("hd2mm.server", "WARNING") as logs:
            self.request("/api/ui-diagnostics", body={"event": "error", "detail": "bad\n" + "x" * 3000})
        self.assertNotIn("\n", logs.output[0])
        self.assertIn("bad\\n", logs.output[0])
        self.assertLess(len(logs.output[0]), 2100)
        self.server.ui_reports = 100
        with self.assertNoLogs("hd2mm.server", "WARNING"):
            self.assertEqual(self.request("/api/ui-diagnostics", body={"event": "error", "detail": "repeated"})[0], 200)

    def test_index_contains_token(self):
        with urllib.request.urlopen(self.base + "/", timeout=5) as res:
            html = res.read().decode()
        self.assertIn(self.server.token, html)
        self.assertNotIn("__HD2MM_TOKEN__", html)

    def test_post_requires_token_and_host(self):
        status, _ = self.request("/api/order", body={"ids": []}, token=False)
        self.assertEqual(status, 403)
        status, _ = self.request("/api/state", headers={"Host": "evil.example:80"})
        self.assertEqual(status, 403)

    def test_state_without_mods(self):
        status, state = self.request("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(state["status"]["state"], "empty")
        self.assertIsNone(state["game"]["problem"])

    @unittest.skipUnless(LOADER_ZIP.exists(), "예시 모드 zip이 없음")
    def test_import_and_deploy_over_http(self):
        status, result = self.request(f"/api/import?name={LOADER_ZIP.name}", data=LOADER_ZIP.read_bytes())
        self.assertEqual(status, 200, result)
        mod_id = result["id"]

        status, state = self.request("/api/state")
        mod = state["mods"][0]
        self.assertEqual(mod["name"], "Bingus Shared Loader - v17")
        self.assertEqual(mod["files"][0]["target"], "9ba626afa44a3aa3.patch_0")
        self.assertEqual(state["status"]["state"], "pending")
        with urllib.request.urlopen(self.base + mod["icon"], timeout=5) as res:
            self.assertEqual(res.headers["Content-Type"], "image/png")

        (self.game / "data" / "9ba626afa44a3aa3.patch_5").write_bytes(b"other")
        status, result = self.request("/api/deploy", body={"unmanaged": "ask"})
        self.assertEqual(status, 409)
        self.assertEqual(result["needsConfirm"], "unmanaged")
        status, result = self.request("/api/deploy", body={"unmanaged": "move"})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["modCount"], 1)
        _, state = self.request("/api/state")
        self.assertEqual(state["status"]["state"], "ok")

        status, _ = self.request(f"/api/mods/{mod_id}", body={"enabled": False})
        self.assertEqual(status, 200)
        _, state = self.request("/api/state")
        self.assertEqual(state["status"]["state"], "dirty")

    def test_readme_is_served_separately(self):
        archive = make_zip(self.tmp / "mod.zip", {"readme.txt": "사용법 설명", f"{ARCHIVE}.patch_0": "p"})
        status, result = self.request("/api/import?name=mod.zip", data=archive.read_bytes())
        self.assertEqual(status, 200, result)
        _, state = self.request("/api/state")
        mod = state["mods"][0]
        self.assertTrue(mod["hasReadme"])
        self.assertNotIn("readme", mod)
        status, body = self.request(f"/api/mods/{result['id']}/readme")
        self.assertEqual((status, body), (200, {"readme": "사용법 설명"}))
        status, _ = self.request("/api/mods/unknown/readme")
        self.assertEqual(status, 400)

    def test_readme_revision_changes_on_update(self):
        def upload(text):
            archive = make_zip(self.tmp / "mod.zip", {
                "manifest.json": json.dumps({"Guid": "11111111-2222-3333-4444-555555555555", "Name": "M"}),
                "readme.txt": text, f"{ARCHIVE}.patch_0": "p",
            })
            status, result = self.request("/api/import?name=mod.zip", data=archive.read_bytes())
            self.assertEqual(status, 200, result)
            _, state = self.request("/api/state")
            return state["mods"][0]["readmeRev"]

        first = upload("첫 번째")
        second = upload("두 번째")
        self.assertIsNotNone(first)
        self.assertNotEqual(first, second)
        _, body = self.request("/api/mods/11111111-2222-3333-4444-555555555555/readme")
        self.assertEqual(body["readme"], "두 번째")

    def test_thumbnail_url_changes_when_image_changes(self):
        archive = make_zip(self.tmp / "mod.zip", {
            "manifest.json": json.dumps({"Name": "M", "IconPath": "thumb.png"}),
            "thumb.png": "old", f"{ARCHIVE}.patch_0": "p",
        })
        status, result = self.request("/api/import?name=mod.zip", data=archive.read_bytes())
        self.assertEqual(status, 200, result)
        _, state = self.request("/api/state")
        before = state["mods"][0]["icon"]
        image = self.lib.mods_dir / result["id"] / "thumb.png"
        image.write_bytes(b"new picture")
        stat = image.stat()
        os.utime(image, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
        _, state = self.request("/api/state")
        self.assertNotEqual(state["mods"][0]["icon"], before)

    def test_state_reads_deploy_records_once(self):
        with mock.patch.object(self.lib, "load_records", wraps=self.lib.load_records) as load:
            status, _ = self.request("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(load.call_count, 1)

    def test_folder_dialog_does_not_block_other_requests(self):
        opened, release = threading.Event(), threading.Event()

        def slow_dialog(server, initial):
            opened.set()
            release.wait(10)
            return None

        with mock.patch("hd2mm.server._pick_folder", side_effect=slow_dialog):
            worker = threading.Thread(target=self.request, args=("/api/pick-folder",), kwargs={"body": {}})
            worker.start()
            self.assertTrue(opened.wait(5))
            try:
                status, state = self.request("/api/state")  # 폴더 선택 창이 열려 있어도 응답해야 함
                self.assertEqual(status, 200)
                self.assertEqual(state["status"]["otherDeployments"], [])
                status, _ = self.request("/api/order", body={"ids": []})
                self.assertEqual(status, 200)
            finally:
                release.set()
                worker.join(5)

    def test_mod_file_cannot_escape_mod_folder(self):
        status, _ = self.request("/api/mods/unknown/file?path=../settings.json")
        self.assertEqual(status, 400)

    def test_bad_game_path_is_rejected(self):
        not_game = self.tmp / "not-a-game"
        not_game.mkdir()
        status, result = self.request("/api/settings", body={"gamePath": str(not_game)})
        self.assertEqual(status, 400)
        self.assertIn("data 폴더", result["error"])
        status, _ = self.request("/api/settings", body={"gamePath": str(self.game / "data")})
        self.assertEqual(status, 200)
        self.assertEqual(self.lib.game_path, str(self.game))

    def test_mod_images_allow_only_raster_and_have_security_headers(self):
        files = {f"{ARCHIVE}.patch_0": "patch", "icon.svg": "<svg/>", "page.html": "<html/>"}
        for ext in RASTER_TYPES:
            files["image" + ext.upper()] = b"image"
        files["manifest.json"] = json.dumps({
            "IconPath": "icon.svg",
            "Options": [{"Name": "옵션", "Image": "icon.svg", "Include": ["."], "SubOptions": [
                {"Name": "벡터", "Image": "icon.svg"},
                {"Name": "그림", "Image": "image.PNG"},
            ]}],
        })
        archive = make_zip(self.tmp / "images.zip", files)
        mod_id = self.lib.import_archive(archive, archive.name)["id"]
        prefix = f"/api/mods/{mod_id}/file?path="
        for name in ("icon.svg", "page.html"):
            self.assertEqual(self.request(prefix + name)[0], 404)
        for ext, ctype in RASTER_TYPES.items():
            with self.subTest(ext=ext):
                with urllib.request.urlopen(self.base + prefix + "image" + ext.upper(), timeout=5) as res:
                    self.assertEqual(res.headers["Content-Type"], ctype)
                    self.assertEqual(res.headers["X-Content-Type-Options"], "nosniff")
                    self.assertEqual(res.headers["Content-Security-Policy"], "sandbox; default-src 'none'")
        _, state = self.request("/api/state")
        mod = state["mods"][0]
        self.assertIsNone(mod["icon"])
        self.assertIsNone(mod["options"][0]["image"])
        self.assertIsNone(mod["options"][0]["subs"][0]["image"])
        self.assertIn("image.PNG", mod["options"][0]["subs"][1]["image"])

    def test_post_operations_count_success_failure_and_import(self):
        def request_finished(path, payload):
            status, _ = self.request(path, data=payload)
            # 응답 직후에도 서버의 finally가 실행 중일 수 있다.
            deadline = time.monotonic() + 2
            while self.server.active_operations and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(self.server.active_operations, 0)
            return status

        def handle(handler, *args):
            self.assertEqual(self.server.active_operations, 1)
            if handler.path.startswith("/api/import"):
                handler._send_json({"ok": True})
                return
            return {"ok": True}

        for path, method, payload in (("/api/order", "_post", b"{}"), ("/api/import?name=a.zip", "_import", b"zip")):
            with self.subTest(path=path):
                with mock.patch.object(Handler, method, autospec=True, side_effect=handle):
                    self.assertEqual(request_finished(path, payload), 200)
                with mock.patch.object(Handler, method, side_effect=ValueError("실패")):
                    self.assertEqual(request_finished(path, payload), 500)
        self.assertEqual(request_finished("/api/order", b"invalid"), 400)

    def test_watcher_waits_for_operations_and_new_grace_period(self):
        server = self.server
        for connected in (False, True):
            with self.subTest(connected=connected):
                server.stopping = False
                server.ever_connected = connected
                server.last_change = 0
                self.assertTrue(server.begin_operation())
                self.assertTrue(server.begin_operation())
                now = [200.0]
                ticks = [0]

                def tick(_):
                    ticks[0] += 1
                    now[0] += 1
                    if ticks[0] == 2:
                        server.end_operation()
                    if ticks[0] == 3:
                        server.end_operation()
                    if ticks[0] > 130:
                        self.fail("종료 감시가 끝나지 않음")

                with mock.patch("hd2mm.server.time.monotonic", side_effect=lambda: now[0]), \
                        mock.patch("hd2mm.server.time.sleep", side_effect=tick), \
                        mock.patch.object(server, "shutdown") as shutdown:
                    server._watch_clients()
                shutdown.assert_called_once()
                self.assertEqual(ticks[0], 9 if connected else 124)
                self.assertFalse(server.begin_operation())


class LoggingTests(unittest.TestCase):
    def test_log_is_written_beside_exe_or_source_not_extraction_directory(self):
        with tempfile.TemporaryDirectory(prefix="hd2mm-log-") as tmp:
            root = Path(tmp)
            for frozen in (True, False):
                with self.subTest(frozen=frozen):
                    folder = root / ("app" if frozen else "source")
                    folder.mkdir()
                    logger = logging.Logger("log-test")
                    with mock.patch.object(paths.sys, "frozen", frozen, create=True), \
                            mock.patch.object(paths.sys, "executable", str(folder / "Modocracy.exe")), \
                            mock.patch.object(paths.sys, "_MEIPASS", str(root / "extracted"), create=True), \
                            mock.patch.object(paths, "__file__", str(folder / "hd2mm" / "paths.py")), \
                            mock.patch.object(app.logging, "getLogger", return_value=logger), \
                            mock.patch.object(app.sys, "stderr", None):
                        try:
                            app.setup_logging(False)
                            logger.info("로그 위치 확인")
                        finally:
                            for handler in logger.handlers:
                                handler.close()
                    self.assertIn("로그 위치 확인", (folder / "log.txt").read_text(encoding="utf-8"))
            self.assertFalse((root / "extracted" / "log.txt").exists())

    def test_unwritable_log_reports_log_path(self):
        self.addCleanup(i18n.set_language, i18n.current())
        with tempfile.TemporaryDirectory(prefix="hd2mm-log-") as tmp, \
                mock.patch.object(app, "acquire_instance_mutex", return_value=True), \
                mock.patch.object(app, "setup_logging", side_effect=PermissionError("denied")), \
                mock.patch.object(app, "log_path", return_value=Path(tmp) / "app" / "log.txt"), \
                mock.patch.object(app, "show_error") as error, \
                mock.patch.object(app, "Library") as library:
            self.assertEqual(app.main(["--data-dir", tmp, "--no-window"]), 1)
            self.assertIn(str(Path(tmp) / "app" / "log.txt"), error.call_args.args[0])
            library.assert_not_called()


class InstanceTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(i18n.set_language, i18n.current())  # main()이 Windows 언어로 바꾼다

    def test_mutex_name_handle_and_existing_instance(self):
        import ctypes

        kernel = mock.Mock()
        kernel.CreateMutexW.return_value = 123
        with tempfile.TemporaryDirectory(prefix="hd2mm-mutex-") as tmp, \
                mock.patch.object(app.sys, "platform", "win32"), \
                mock.patch.object(ctypes, "WinDLL", return_value=kernel, create=True), \
                mock.patch.object(ctypes, "get_last_error", return_value=0, create=True) as error, \
                mock.patch.object(app, "_mutex_handles", []) as handles:
            path = Path(tmp) / "Data"
            self.assertTrue(app.acquire_instance_mutex(path))
            self.assertEqual(handles, [123])
            name = kernel.CreateMutexW.call_args.args[2]
            self.assertTrue(name.startswith("Local\\Modocracy-"))
            self.assertEqual(len(name.rsplit("-", 1)[1]), 40)
            error.return_value = 183
            self.assertFalse(app.acquire_instance_mutex(Path(tmp) / "data" / "."))
            self.assertEqual(kernel.CreateMutexW.call_args.args[2], name)
            kernel.CloseHandle.assert_called_once_with(123)
            self.assertEqual(handles, [123])

    def test_mutex_non_windows(self):
        with mock.patch.object(app.sys, "platform", "linux"):
            self.assertTrue(app.acquire_instance_mutex(Path("unused")))

    def test_duplicate_launch_waits_without_creating_library(self):
        with tempfile.TemporaryDirectory(prefix="hd2mm-launch-") as tmp, \
                mock.patch.object(app, "acquire_instance_mutex", return_value=False), \
                mock.patch.object(app, "Library") as library, \
                mock.patch.object(app, "running_instance", side_effect=[None, "http://127.0.0.1:1234/"]) as running, \
                mock.patch.object(app, "open_window") as window, \
                mock.patch.object(app.time, "sleep"):
            self.assertEqual(app.main(["--data-dir", tmp]), 0)
            self.assertEqual(running.call_count, 2)
            window.assert_called_once_with("http://127.0.0.1:1234/?app=1")
            library.assert_not_called()

    def test_duplicate_launch_timeout_and_no_window(self):
        with tempfile.TemporaryDirectory(prefix="hd2mm-launch-") as tmp, \
                mock.patch.object(app, "acquire_instance_mutex", return_value=False), \
                mock.patch.object(app, "Library") as library, \
                mock.patch.object(app, "running_instance", return_value=None) as running, \
                mock.patch.object(app, "open_window") as window, \
                mock.patch.object(app, "show_error") as error, \
                mock.patch.object(app.time, "monotonic", side_effect=[0, 0, 11]), \
                mock.patch.object(app.time, "sleep"):
            self.assertEqual(app.main(["--data-dir", tmp]), 1)
            error.assert_called_once()
            running.assert_called_once()
            running.reset_mock()
            self.assertEqual(app.main(["--data-dir", tmp, "--no-window"]), 1)
            running.assert_not_called()
            window.assert_not_called()
            library.assert_not_called()



class LifecycleTests(unittest.TestCase):
    def test_server_stops_after_last_window_closes(self):
        tmp = Path(tempfile.mkdtemp(prefix="hd2mm-life-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        server = AppServer(("127.0.0.1", 0), Library(tmp / "data"), web_dir(), auto_exit=True)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        # 창 하나가 열려 있는 상황: 이벤트 연결 유지
        sock = socket.create_connection(("127.0.0.1", server.port))
        sock.sendall(f"GET /api/events HTTP/1.1\r\nHost: 127.0.0.1:{server.port}\r\n\r\n".encode())
        self.assertIn(b"text/event-stream", sock.recv(4096))
        time.sleep(7)
        self.assertTrue(thread.is_alive(), "창이 열려 있는 동안에는 꺼지면 안 됨")

        sock.close()  # 창 닫힘
        thread.join(timeout=20)
        self.assertFalse(thread.is_alive(), "창이 닫히면 스스로 종료해야 함")


class FakeEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self):
        for handler in self.handlers:
            handler()


class FakeWebview:
    """pywebview 대신 쓰는 가짜. start()가 창이 떠 있는 동안을 흉내 낸다."""

    class FileDialog:
        FOLDER = 20

    def __init__(self, show=True, fail=False, while_open=None):
        self.show, self.fail, self.while_open = show, fail, while_open
        self.window = None

    def create_window(self, title, url, **kwargs):
        events = {name: FakeEvent() for name in ("shown", "minimized", "restored", "maximized")}
        self.window = mock.Mock(events=mock.Mock(**events), title=title, url=url, kwargs=kwargs)
        self.window.create_file_dialog.return_value = ("D:\\Games\\Helldivers 2",)
        return self.window

    def start(self, **kwargs):
        if self.fail:
            raise RuntimeError("WebView2 초기화 실패")
        if self.show:
            self.window.events.shown.fire()
        if self.while_open:
            self.while_open()


class FakeControlAdded:
    """WinForms 이벤트처럼 += / -= 로 처리기를 붙이고 뗀다."""

    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def __isub__(self, handler):
        self.handlers.remove(handler)
        return self


def fake_edge_module(attach=True):
    """pywebview edgechromium 모듈 흉내. EdgeChrome이 옵션을 정하고, 창에 붙이고, 켠다."""

    class EdgeChrome:
        def __init__(self, form, window, cache_dir):
            self.webview = mock.Mock()
            self.webview.CreationProperties.AdditionalBrowserArguments = "--disable-features=ElasticOverscroll"
            if attach:
                for handler in list(form.ControlAdded.handlers):
                    handler(form, mock.Mock())
            self.started_with = self.webview.CreationProperties.AdditionalBrowserArguments  # 켜는 순간의 옵션

        def on_webview_ready(self, sender, event):
            self.initialized = event.IsSuccess

        def on_navigation_completed(self, sender, event):
            self.navigated = event.IsSuccess

    return mock.Mock(EdgeChrome=EdgeChrome)


class AppWindowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hd2mm-win-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.enterContext(mock.patch.dict(os.environ))  # 창을 띄우며 바꾼 환경 변수를 테스트가 끝나면 되돌린다
        self.edge = fake_edge_module()
        self.enterContext(mock.patch.object(app, "load_edge_chrome", return_value=self.edge))
        self.server = AppServer(("127.0.0.1", 0), Library(self.tmp / "data"), web_dir(), auto_exit=False)
        self.addCleanup(self.server.server_close)
        self.base = f"http://127.0.0.1:{self.server.port}/"

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as res:
            return json.loads(res.read())

    def test_window_runs_until_closed_and_uses_window_dialogs(self):
        seen = {}

        def while_open():
            seen["ping"] = self.get("api/ping")["app"]
            seen["focus"] = self.get("api/focus")
            seen["folder"] = self.server.folder_picker("C:\\")

        fake = FakeWebview(while_open=while_open)
        self.assertTrue(app.run_app_window(fake, self.server, self.base))
        self.assertEqual(seen["ping"], "hd2mm")
        self.assertEqual(seen["focus"], {"focused": True})
        self.assertEqual(seen["folder"], "D:\\Games\\Helldivers 2")
        fake.window.show.assert_called()
        self.assertEqual(fake.window.title, "Modocracy")
        self.assertTrue(fake.window.kwargs["text_select"])
        self.assertTrue(self.server.stopping)  # 창을 닫은 뒤에는 새 작업을 받지 않는다

    def test_window_that_never_opens_leaves_server_reusable(self):
        self.assertFalse(app.run_app_window(FakeWebview(fail=True), self.server, self.base))
        self.assertFalse(self.server.stopping)
        self.assertIsNone(self.server.on_focus)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        try:
            self.assertEqual(self.get("api/focus"), {"focused": False})
        finally:
            self.server.shutdown()
            thread.join(5)

    def test_closing_window_waits_for_running_operation(self):
        self.assertTrue(self.server.begin_operation())
        threading.Timer(0.5, self.server.end_operation).start()
        started = time.monotonic()
        self.assertTrue(self.server.finish_operations(timeout=5))
        self.assertGreaterEqual(time.monotonic() - started, 0.4)
        self.assertFalse(self.server.begin_operation())  # 끝내는 중에는 새 작업 거절
        self.assertTrue(self.server.stopping)

    def test_finish_operations_times_out(self):
        self.assertTrue(self.server.begin_operation())
        self.assertFalse(self.server.finish_operations(timeout=0.3))

    def test_second_launch_brings_existing_window_forward(self):
        focused = []
        self.server.on_focus = lambda: focused.append(True)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        try:
            with mock.patch.object(app, "open_window") as window:
                app.show_existing(self.base)
                window.assert_not_called()
                self.assertEqual(focused, [True])
                self.server.on_focus = None  # Edge 창 모드로 떠 있는 매니저면 창을 하나 더 연다
                app.show_existing(self.base)
                window.assert_called_once_with(self.base + "?app=1")
        finally:
            self.server.shutdown()
            thread.join(5)

    def test_window_draws_without_gpu(self):
        name = app.BROWSER_ARGS_ENV
        os.environ[name] = "--lang=ko"
        seen = {}
        fake = FakeWebview(while_open=lambda: seen.setdefault("args", os.environ[name]))
        self.assertTrue(app.run_app_window(fake, self.server, self.base))
        self.assertEqual(seen["args"], "--lang=ko --disable-gpu")  # 창을 띄울 때 이미 들어가 있다
        app.disable_webview_gpu()
        self.assertEqual(os.environ[name], "--lang=ko --disable-gpu")  # 두 번 붙이지 않는다

    def test_gpu_flag_is_also_set_in_code_for_elevated_runs(self):
        form = mock.Mock(ControlAdded=FakeControlAdded())
        app.disable_webview_gpu()
        app.disable_webview_gpu()  # 두 번 불러도 한 번만 감싼다
        browser = self.edge.EdgeChrome(form, None, "cache")
        self.assertEqual(browser.started_with, "--disable-features=ElasticOverscroll --disable-gpu")
        self.assertEqual(form.ControlAdded.handlers, [])  # 다 만든 뒤에는 처리기를 뗀다

    def test_gpu_flag_hook_failure_is_logged_not_fatal(self):
        edge = fake_edge_module(attach=False)  # pywebview 구조가 바뀌어 신호가 오지 않는 경우
        app.patch_edge_chrome(edge)
        form = mock.Mock(ControlAdded=FakeControlAdded())
        with self.assertLogs("hd2mm", "WARNING"):
            browser = edge.EdgeChrome(form, None, "cache")
        self.assertEqual(browser.started_with, "--disable-features=ElasticOverscroll")
        self.assertEqual(form.ControlAdded.handlers, [])

    def test_webview_runtime_navigation_and_process_failures_are_logged(self):
        app.patch_edge_chrome(self.edge)
        browser = self.edge.EdgeChrome(mock.Mock(ControlAdded=FakeControlAdded()), None, "cache")
        core = mock.Mock(ProcessFailed=FakeControlAdded())
        core.Environment.BrowserVersionString = "123.0.0.0"
        sender = mock.Mock(CoreWebView2=core)
        with self.assertLogs("hd2mm", "INFO") as logs:
            browser.on_webview_ready(sender, mock.Mock(IsSuccess=True))
            browser.on_navigation_completed(sender, mock.Mock(IsSuccess=False, WebErrorStatus="ConnectionAborted"))
            core.ProcessFailed.handlers[0](core, mock.Mock(ProcessFailedKind="RenderProcessExited", Reason="Crashed", ExitCode=5))
        self.assertTrue(browser.initialized)
        self.assertFalse(browser.navigated)
        self.assertIn("123.0.0.0", logs.output[0])
        self.assertIn("ConnectionAborted", logs.output[1])
        self.assertIn("kind=RenderProcessExited reason=Crashed exit=5", logs.output[2])

    def test_webview_initialization_error_is_logged(self):
        app.patch_edge_chrome(self.edge)
        browser = self.edge.EdgeChrome(mock.Mock(ControlAdded=FakeControlAdded()), None, "cache")
        with self.assertLogs("hd2mm", "ERROR") as logs:
            browser.on_webview_ready(None, mock.Mock(IsSuccess=False, InitializationException="runtime unavailable"))
        self.assertFalse(browser.initialized)
        self.assertIn("runtime unavailable", logs.output[0])

    def test_diagnostic_hook_failure_does_not_interrupt_initialization(self):
        app.patch_edge_chrome(self.edge)
        browser = self.edge.EdgeChrome(mock.Mock(ControlAdded=FakeControlAdded()), None, "cache")
        with self.assertLogs("hd2mm", "ERROR"):
            browser.on_webview_ready(mock.Mock(CoreWebView2=None), mock.Mock(IsSuccess=True))
        self.assertTrue(browser.initialized)

    def test_with_flag_keeps_existing_arguments(self):
        self.assertEqual(app.with_flag(None, "--disable-gpu"), "--disable-gpu")
        self.assertEqual(app.with_flag("", "--disable-gpu"), "--disable-gpu")
        self.assertEqual(app.with_flag("--disable-gpu", "--disable-gpu"), "--disable-gpu")
        quoted = '--log-file="C:\\Logs\\GPU  Trace.log"'
        self.assertEqual(app.with_flag(quoted, "--disable-gpu"), quoted + " --disable-gpu")  # 공백 두 칸 유지

    def test_no_webview_without_webview2(self):
        with mock.patch.object(gameinfo, "has_webview2", return_value=False):
            self.assertIsNone(app.load_webview())


class LegacyDataTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="hd2mm-legacy-"))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.legacy = self.base / "HD2ModManager"
        self.new = self.base / "Modocracy"

    def write_legacy(self, settings):
        (self.legacy / "mods" / "abc").mkdir(parents=True)
        (self.legacy / "settings.json").write_text(json.dumps(settings), encoding="utf-8")

    def test_moves_old_library_to_new_name(self):
        self.write_legacy({"version": 1, "gamePath": "C:\\game", "mods": [{"id": "abc", "enabled": True}]})
        self.assertTrue(app.migrate_legacy_data(self.new))
        self.assertFalse(self.legacy.exists())
        self.assertTrue((self.new / "mods" / "abc").is_dir())

    def test_leaves_other_programs_folder_alone(self):
        self.write_legacy({"Mods": [], "Profile": "x"})
        self.assertTrue(app.migrate_legacy_data(self.new))
        self.assertTrue((self.legacy / "settings.json").exists())
        self.assertFalse(self.new.exists())

    def test_keeps_existing_new_library(self):
        self.write_legacy({"version": 1, "gamePath": None, "mods": []})
        self.new.mkdir()
        self.assertTrue(app.migrate_legacy_data(self.new))
        self.assertTrue(self.legacy.exists())

    def test_reports_when_old_folder_is_in_use(self):
        self.write_legacy({"version": 1, "gamePath": None, "mods": []})
        with mock.patch.object(app.os, "replace", side_effect=PermissionError("in use")):
            self.assertFalse(app.migrate_legacy_data(self.new))
        self.assertTrue(self.legacy.exists())


if __name__ == "__main__":
    unittest.main()

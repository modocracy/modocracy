"""앱 자체 업데이트 테스트. 인터넷에 접속하지 않고 가짜 응답을 쓴다."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from hd2mm import __version__, updater
from hd2mm.app import web_dir
from hd2mm.core import Library, ModError
from hd2mm.server import AppServer

REAL_URLOPEN = urllib.request.urlopen  # 가짜로 바꿔도 테스트가 서버를 부를 때는 진짜를 쓴다
NEW_EXE = b"MZ" + b"new version" * 100
DIGEST = hashlib.sha256(NEW_EXE).hexdigest()


def release_json(tag="v9.9.9", digest=f"sha256:{DIGEST}", url=None, size=len(NEW_EXE)):
    return {
        "tag_name": tag,
        "html_url": "https://github.com/JJ-dot-eng/modocracy/releases/tag/" + tag,
        "body": "변경 내용",
        "assets": [{
            "name": "Modocracy.exe", "size": size, "digest": digest,
            "browser_download_url": url or f"{updater.DOWNLOAD_PREFIX}{tag}/Modocracy.exe",
        }],
    }


def fake_urlopen(api_data, file_bytes=NEW_EXE):
    def opener(request, timeout=None):
        url = request.full_url if isinstance(request, urllib.request.Request) else request
        if url == updater.LATEST_API:
            return io.BytesIO(json.dumps(api_data).encode())
        return io.BytesIO(file_bytes)
    return opener


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hd2mm-upd-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.exe = self.tmp / "Modocracy.exe"
        self.exe.write_bytes(b"MZ old")

    def test_reads_latest_release(self):
        with mock.patch("hd2mm.updater.urllib.request.urlopen", side_effect=fake_urlopen(release_json())):
            release = updater.fetch_latest()
        self.assertEqual(release.version, "9.9.9")
        self.assertEqual(release.sha256, DIGEST)
        self.assertTrue(release.asset_url.startswith(updater.DOWNLOAD_PREFIX))
        self.assertTrue(updater.is_newer(release.version))
        self.assertFalse(updater.is_newer(__version__))

    def test_ignores_files_from_other_places(self):
        data = release_json(url="https://example.com/Modocracy.exe")
        with mock.patch("hd2mm.updater.urllib.request.urlopen", side_effect=fake_urlopen(data)):
            release = updater.fetch_latest()
        self.assertIsNone(release.asset_url)
        with mock.patch.object(updater, "current_exe", return_value=self.exe):
            self.assertIsNotNone(updater.install_problem(release))

    def test_offline_gives_friendly_error(self):
        with mock.patch("hd2mm.updater.urllib.request.urlopen", side_effect=OSError("offline")):
            with self.assertRaises(ModError):
                updater.fetch_latest()

    def test_download_checks_fingerprint(self):
        with mock.patch("hd2mm.updater.urllib.request.urlopen", side_effect=fake_urlopen(release_json())):
            release = updater.fetch_latest()
            path = updater.download(release, self.exe)
        self.assertEqual(path.read_bytes(), NEW_EXE)
        self.assertEqual(path.name, "Modocracy.exe.download")

        with mock.patch("hd2mm.updater.urllib.request.urlopen", side_effect=fake_urlopen(release_json(), b"MZ tampered")):
            with self.assertRaises(ModError):
                updater.download(release, self.exe)
        self.assertFalse((self.tmp / "Modocracy.exe.download").exists())
        self.assertEqual(self.exe.read_bytes(), b"MZ old")  # 원래 exe는 그대로

    def test_swap_job_waits_for_this_process_then_replaces(self):
        folder = self.tmp / "it's here"
        folder.mkdir()
        exe = folder / "Modocracy.exe"
        with mock.patch("hd2mm.updater.subprocess.Popen") as popen:
            updater.schedule_swap(exe, folder / "Modocracy.exe.download")
        command = popen.call_args.args[0]
        self.assertEqual(command[0], "powershell.exe")
        script = base64.b64decode(command[-1]).decode("utf-16-le")
        self.assertIn(f"Wait-Process -Id {__import__('os').getpid()}", script)
        self.assertIn(str(folder).replace("'", "''") + "\\Modocracy.old.exe", script)
        self.assertIn("Start-Process -FilePath $exe", script)
        self.assertIn("Move-Item -LiteralPath $old -Destination $exe", script)  # 실패하면 되돌림

    def test_swap_job_gets_clean_environment(self):
        fake_env = {"PATH": "C:\\Temp\\_MEI123;C:\\Windows", "_PYI_APPLICATION_HOME_DIR": "C:\\Temp\\_MEI123",
                    "_MEIPASS2": "C:\\Temp\\_MEI123", "HD2MM_DATA_DIR": "D:\\data"}
        with mock.patch.dict("os.environ", fake_env, clear=True), \
                mock.patch.object(updater.sys, "_MEIPASS", "C:\\Temp\\_MEI123", create=True), \
                mock.patch("hd2mm.updater.subprocess.Popen") as popen:
            updater.schedule_swap(self.exe, self.tmp / "Modocracy.exe.download")
        env = popen.call_args.kwargs["env"]
        self.assertNotIn("_PYI_APPLICATION_HOME_DIR", env)
        self.assertNotIn("_MEIPASS2", env)
        self.assertEqual(env["PATH"], "C:\\Windows")
        self.assertEqual(env["PYINSTALLER_RESET_ENVIRONMENT"], "1")
        self.assertEqual(env["HD2MM_DATA_DIR"], "D:\\data")  # 다른 설정은 그대로 넘긴다

    def test_cleanup_leftovers(self):
        (self.tmp / "Modocracy.old.exe").write_bytes(b"old")
        (self.tmp / "Modocracy.exe.download").write_bytes(b"partial")
        with mock.patch.object(updater, "current_exe", return_value=self.exe):
            updater.cleanup_leftovers()
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["Modocracy.exe"])


class UpdateServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hd2mm-updsrv-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.lib = Library(self.tmp / "data")
        self.server = AppServer(("127.0.0.1", 0), self.lib, web_dir(), auto_exit=False)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.port}"
        self.exe = self.tmp / "Modocracy.exe"
        self.exe.write_bytes(b"MZ old")

    def call(self, path, body=None):
        headers = {"X-HD2MM-Token": self.server.token}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method="POST" if data else "GET")
        try:
            with REAL_URLOPEN(req, timeout=10) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read())

    def test_check_reports_new_version_and_caches(self):
        with mock.patch.object(updater, "fetch_latest", return_value=updater.Release("9.9.9", "u", "n", None, 0, None)) as fetch:
            status, info = self.call("/api/update")
            self.call("/api/update")
        self.assertEqual(status, 200)
        self.assertTrue(info["newer"])
        self.assertFalse(info["canInstall"])  # 소스로 실행 중이라 자동 설치는 안 됨
        self.assertEqual(fetch.call_count, 1)  # 두 번째는 기억해 둔 결과

    def test_install_downloads_schedules_swap_and_exits(self):
        release = updater.Release("9.9.9", "u", "n", updater.DOWNLOAD_PREFIX + "v9.9.9/Modocracy.exe", len(NEW_EXE), DIGEST)
        exited = threading.Event()
        self.server.on_exit = exited.set
        with mock.patch.object(updater, "fetch_latest", return_value=release), \
                mock.patch.object(updater, "current_exe", return_value=self.exe), \
                mock.patch("hd2mm.updater.urllib.request.urlopen", side_effect=fake_urlopen({}, NEW_EXE)), \
                mock.patch.object(updater, "schedule_swap") as swap:
            status, result = self.call("/api/update/install", body={})
            self.assertEqual((status, result), (200, {"restarting": True, "version": "9.9.9"}))
            swap.assert_called_once_with(self.exe, self.tmp / "Modocracy.exe.download")
            self.assertTrue(exited.wait(5))

    def test_install_refused_when_running_from_source(self):
        release = updater.Release("9.9.9", "u", "n", updater.DOWNLOAD_PREFIX + "x", 1, "ab")
        with mock.patch.object(updater, "fetch_latest", return_value=release):
            status, result = self.call("/api/update/install", body={})
        self.assertEqual(status, 400)
        self.assertIn("exe로 실행할 때만", result["error"])

    def test_install_refused_while_other_work_runs(self):
        self.assertTrue(self.server.begin_operation())
        try:
            status, result = self.call("/api/update/install", body={})
        finally:
            self.server.end_operation()
        self.assertEqual(status, 400)
        self.assertIn("다른 작업", result["error"])

    def test_update_check_setting(self):
        status, _ = self.call("/api/settings", body={"checkUpdates": False})
        self.assertEqual(status, 200)
        _, state = self.call("/api/state")
        self.assertFalse(state["checkUpdates"])
        self.assertFalse(Library(self.tmp / "data").settings["checkUpdates"])


if __name__ == "__main__":
    unittest.main()

"""앱 자체 업데이트 테스트. 인터넷에 접속하지 않고 가짜 응답을 쓴다."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
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
        self.assertIn(f"Get-Process -Id {os.getpid()}", script)
        self.assertIn("$ErrorActionPreference = 'Stop'", script)  # 파일 작업이 실패하면 catch로 넘어가야 되돌릴 수 있다
        self.assertIn(str(folder).replace("'", "''") + "\\Modocracy.old.exe", script)
        self.assertIn("Move-Item -LiteralPath $old -Destination $exe", script)  # 실패하면 되돌림

    def test_restart_keeps_launch_options(self):
        with mock.patch.object(updater, "RESTART_ARGS", ["--data-dir", "D:\\My Mods", "--browser"]), \
                mock.patch("hd2mm.updater.subprocess.Popen") as popen:
            updater.schedule_swap(self.exe, self.tmp / "Modocracy.exe.download")
        script = base64.b64decode(popen.call_args.args[0][-1]).decode("utf-16-le")
        self.assertIn("$arguments = '--data-dir \"D:\\My Mods\" --browser'", script)

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

    def test_manual_check_asks_again(self):
        with mock.patch.object(updater, "fetch_latest", return_value=updater.Release("9.9.9", "u", "n", None, 0, None)) as fetch:
            self.call("/api/update")
            self.call("/api/update?force=1")  # GET으로는 다시 묻지 않는다 (아무 웹페이지나 부를 수 있으므로)
            self.assertEqual(fetch.call_count, 1)
            status, _ = self.call("/api/update/check", body={})
            self.assertEqual(status, 200)
            self.assertEqual(fetch.call_count, 2)

    def test_after_install_other_changes_are_refused(self):
        release = updater.Release("9.9.9", "u", "n", updater.DOWNLOAD_PREFIX + "v9.9.9/Modocracy.exe", len(NEW_EXE), DIGEST)
        self.server.on_exit = lambda: None
        with mock.patch.object(updater, "fetch_latest", return_value=release), \
                mock.patch.object(updater, "current_exe", return_value=self.exe), \
                mock.patch("hd2mm.updater.urllib.request.urlopen", side_effect=fake_urlopen({}, NEW_EXE)), \
                mock.patch.object(updater, "schedule_swap") as swap:
            self.assertEqual(self.call("/api/update/install", body={})[0], 200)
            status, result = self.call("/api/update/install", body={})
            self.assertEqual(status, 503)
            self.assertIn("업데이트하는 중", result["error"])
            self.assertEqual(self.call("/api/order", body={"ids": []})[0], 503)
        swap.assert_called_once()

    def test_closing_window_during_download_cancels_update(self):
        release = updater.Release("9.9.9", "u", "n", updater.DOWNLOAD_PREFIX + "v9.9.9/Modocracy.exe", len(NEW_EXE), DIGEST)
        downloaded = self.tmp / "Modocracy.exe.download"

        def download(rel, exe):
            downloaded.write_bytes(NEW_EXE)
            self.server.stopping = True  # 받는 동안 사용자가 창을 닫음
            return downloaded

        with mock.patch.object(updater, "fetch_latest", return_value=release), \
                mock.patch.object(updater, "current_exe", return_value=self.exe), \
                mock.patch.object(updater, "download", side_effect=download), \
                mock.patch.object(updater, "schedule_swap") as swap:
            status, result = self.call("/api/update/install", body={})
        self.assertEqual(status, 400)
        self.assertIn("취소", result["error"])
        swap.assert_not_called()
        self.assertFalse(downloaded.exists())
        self.assertFalse(self.server.updating)

    def test_ready_hook_runs_once_after_first_state(self):
        calls = []
        self.server.on_ready = lambda: calls.append(1)
        self.call("/api/state")
        self.call("/api/state")
        self.assertEqual(calls, [1])

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


@unittest.skipUnless(sys.platform == "win32", "Windows 전용 (PowerShell)")
class SwapScriptTests(unittest.TestCase):
    """교체 작업(PowerShell)을 실제로 돌려 본다. 창 없이 바로 끝나는 rundll32.exe를 가짜 앱으로 쓴다."""

    def setUp(self):
        base = Path(tempfile.mkdtemp(prefix="hd2mm-swap-"))
        self.addCleanup(shutil.rmtree, base, True)
        self.dir = base / "it's 모드 폴더"  # 빈칸·작은따옴표·한글이 든 경로
        self.dir.mkdir()
        self.exe = self.dir / "Modocracy.exe"
        self.new = self.dir / "Modocracy.exe.download"
        self.old = self.dir / "Modocracy.old.exe"
        stub = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "rundll32.exe"
        self.old_bytes = stub.read_bytes()
        self.new_bytes = self.old_bytes + b"new-version"  # 뒤에 덧붙여도 실행은 된다
        self.exe.write_bytes(self.old_bytes)
        self.new.write_bytes(self.new_bytes)

    def finished_pid(self) -> int:
        proc = subprocess.Popen(["cmd.exe", "/c", "exit 0"], creationflags=updater.CREATE_NO_WINDOW)
        proc.wait()
        return proc.pid

    def run_script(self, pid, wait=3, verify=4, retries=100, new_version_starts=False):
        script = updater.build_swap_script(self.exe, self.new, pid, wait_seconds=wait, verify_seconds=verify, retries=retries)
        proc = subprocess.Popen(updater.powershell_command(script), creationflags=updater.CREATE_NO_WINDOW)
        if new_version_starts:  # 새 버전이 화면까지 떴을 때처럼 .old.exe를 지운다
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    if self.old.exists() and self.exe.read_bytes() == self.new_bytes:
                        self.old.unlink()
                        break
                except OSError:
                    pass
                time.sleep(0.02)
        return proc.wait(timeout=90)

    def test_swaps_after_exit_and_keeps_new_version(self):
        self.assertEqual(self.run_script(self.finished_pid(), new_version_starts=True), 0)
        self.assertEqual(self.exe.read_bytes(), self.new_bytes)
        self.assertFalse(self.new.exists())
        self.assertFalse(self.old.exists())

    def test_rolls_back_when_new_version_quits_at_start(self):
        self.assertEqual(self.run_script(self.finished_pid()), 3)
        self.assertEqual(self.exe.read_bytes(), self.old_bytes)
        self.assertFalse(self.old.exists())
        self.assertFalse((self.dir / "Modocracy.failed.exe").exists())

    def test_does_nothing_while_app_is_still_running(self):
        self.assertEqual(self.run_script(os.getpid(), wait=2), 1)
        self.assertEqual(self.exe.read_bytes(), self.old_bytes)
        self.assertTrue(self.new.exists())
        self.assertFalse(self.old.exists())

    def test_failed_swap_restores_old_exe(self):
        self.new.unlink()  # 새 파일을 옮길 수 없는 상황
        self.assertEqual(self.run_script(self.finished_pid(), retries=3), 2)
        self.assertEqual(self.exe.read_bytes(), self.old_bytes)
        self.assertFalse(self.old.exists())


if __name__ == "__main__":
    unittest.main()

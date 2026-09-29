"""실제 Qt 위젯과 백그라운드 작업으로 사용자 흐름을 검증한다. 게임은 임시 폴더만 사용한다."""
import json
import logging
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QButtonGroup, QCheckBox, QComboBox, QPushButton, QRadioButton

from hd2mm import app, i18n, updater
from hd2mm.core import Library, ModError, NeedsConfirm
from hd2mm.native_ui import MainWindow, SettingsDialog, configure_qt
from hd2mm.server import AppServer
from hd2mm.ui_text import CATALOG, tr
from tests.test_core import ARCHIVE, make_zip
from tests.test_updater import fake_urlopen, release_json


class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])
        configure_qt(cls.qt)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hd2mm-qt-")
        self.root = Path(self.temp.name)
        self.lib = Library(self.root / "library")
        self.game = self.root / "game"
        (self.game / "data").mkdir(parents=True)
        self.lib.update_settings({"gamePath": str(self.game), "checkUpdates": False, "language": "ko"})
        self.old_lang = i18n.current()
        i18n.set_language("ko")
        self.running_patch = mock.patch("hd2mm.server.gameinfo.is_game_running", return_value=False)
        self.running_patch.start()
        self.server = AppServer(("127.0.0.1", 0), self.lib, app.web_dir(), auto_exit=False)
        self.window = MainWindow(self.server)
        self.window.show()
        self.wait(lambda: self.window.rendered and not self.window.busy)

    def tearDown(self):
        self.wait(lambda: not self.window.busy)
        self.window.close()
        self.window._executor.shutdown(wait=True)
        self.window.deleteLater()
        self.qt.processEvents()
        self.server.server_close()
        self.running_patch.stop()
        i18n.set_language(self.old_lang)
        self.temp.cleanup()

    def wait(self, condition, timeout=6):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.qt.processEvents()
            time.sleep(0.01)
        self.qt.processEvents()
        self.assertTrue(condition(), "Qt 작업이 시간 안에 끝나지 않았습니다")

    def make_mod(self, name="Pack"):
        manifest = {"Version": 1, "Name": name, "Options": [
            {"Name": "Alpha", "Include": ["a"], "SubOptions": [
                {"Name": "One", "Include": ["a"]}, {"Name": "Two", "Include": ["b"]}]},
            {"Name": "Beta", "Include": ["b"]},
        ]}
        files = {"manifest.json": json.dumps(manifest),
                 f"a/{ARCHIVE}.patch_0": "a", f"b/{ARCHIVE}.patch_0": "b", "README.txt": "<script>plain text</script>"}
        return make_zip(self.root / (name + ".zip"), files)

    def import_mod(self, name="Pack"):
        self.window.import_paths([str(self.make_mod(name))])
        self.wait(lambda: not self.window.busy and len(self.window.state["mods"]) > 0)
        return self.window.selected_mod()

    def test_empty_window_is_ready_and_can_retry_read_failure(self):
        self.assertTrue(self.window.empty_button.isVisible())
        self.assertTrue(self.window.deploy_button.isEnabled())
        with mock.patch.object(self.window.backend, "state", side_effect=ModError("disk failure")):
            self.window.refresh()
            self.wait(lambda: not self.window.busy)
        self.assertTrue(self.window.retry_button.isVisible())
        self.window.retry_button.click()
        self.wait(lambda: not self.window.busy)
        self.assertFalse(self.window.retry_button.isVisible())
        self.assertNotEqual(self.window.status_title.text(), tr("native.load_failed"))

    def test_import_toggle_options_order_deploy_and_purge(self):
        mod = self.import_mod()
        self.assertEqual(self.window.mod_list.count(), 1)
        self.assertFalse(self.window.empty_button.isVisible())
        combo = self.window.detail_scroll.findChild(QComboBox)
        combo.setCurrentIndex(1)
        self.wait(lambda: not self.window.busy)
        self.assertEqual(self.lib.snapshot()[0].state["selectedSubs"][0], 1)
        checks = self.window.detail_scroll.findChildren(QCheckBox)
        beta = next(c for c in checks if c.text() == "Beta")
        beta.click()
        self.wait(lambda: not self.window.busy)
        self.assertFalse(self.lib.snapshot()[0].state["enabledOptions"][1])
        self.window.mod_list.item(0).setCheckState(Qt.CheckState.Unchecked)
        self.wait(lambda: not self.window.busy)
        self.assertFalse(self.lib.snapshot()[0].enabled)
        self.window.mod_list.item(0).setCheckState(Qt.CheckState.Checked)
        self.wait(lambda: not self.window.busy)
        self.import_mod("Second")
        self.window.move_mod(mod["id"], None)
        self.wait(lambda: not self.window.busy)
        self.assertEqual(self.lib.snapshot()[-1].id, mod["id"])
        self.window.game_action("deploy")
        self.wait(lambda: not self.window.busy)
        self.assertEqual(self.window.state["status"]["state"], "ok")
        self.assertTrue(list((self.game / "data").glob("*.patch_*")))
        with mock.patch.object(self.window, "choose", return_value=True):
            self.window.game_action("purge")
        self.wait(lambda: not self.window.busy)
        self.assertFalse(list((self.game / "data").iterdir()))
        self.assertEqual(len(self.lib.snapshot()), 2)

    def test_unmanaged_cancel_preserves_files_then_move_backs_up(self):
        self.import_mod()
        original = self.game / "data" / (ARCHIVE + ".patch_7")
        original.write_text("other manager")
        with mock.patch.object(self.window, "choose", return_value=None):
            self.window.game_action("deploy")
            self.wait(lambda: not self.window.busy)
        self.assertEqual(original.read_text(), "other manager")
        with mock.patch.object(self.window, "choose", return_value="move"):
            self.window.game_action("deploy")
            self.wait(lambda: not self.window.busy)
        self.assertFalse(original.exists())
        backups = list(self.lib.backups_dir.rglob(original.name))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "other manager")

    def test_delete_requires_confirmation(self):
        mod = self.import_mod()
        with mock.patch.object(self.window, "choose", return_value=False):
            self.window.delete_mod(mod)
        self.assertEqual(len(self.lib.snapshot()), 1)
        with mock.patch.object(self.window, "choose", return_value=True):
            self.window.delete_mod(mod)
        self.wait(lambda: not self.window.busy)
        self.assertEqual(self.window.mod_list.count(), 0)
        self.assertTrue(self.window.empty_button.isVisible())

    def test_legacy_single_choice_is_exclusive_and_changes_files(self):
        archive = make_zip(self.root / "legacy.zip", {
            "manifest.json": json.dumps({"Name": "Legacy", "Options": ["a", "b"]}),
            f"a/{ARCHIVE}.patch_0": "a", f"b/{ARCHIVE}.patch_0": "b",
        })
        self.window.import_paths([str(archive)])
        self.wait(lambda: not self.window.busy)
        choices = self.window.detail_scroll.findChildren(QRadioButton)
        self.assertEqual([c.isChecked() for c in choices], [True, False])
        choices[1].click()
        self.wait(lambda: not self.window.busy)
        self.assertEqual(self.lib.snapshot()[0].state["choice"], 1)
        # 선택 묶음은 상세 화면과 함께 지워진다 (다시 그릴 때마다 쌓이지 않게)
        self.assertFalse([c for c in self.window.detail_scroll.children() if isinstance(c, QButtonGroup)])
        self.assertTrue(self.window.selected_mod()["files"][0]["source"].startswith("b/"))

    def test_folder_picker_is_a_native_dialog_and_cancel_preserves_path(self):
        dialog = SettingsDialog(self.window)
        with mock.patch("hd2mm.native_ui.QFileDialog.getExistingDirectory", return_value=""):
            dialog.browse()
        self.assertEqual(dialog.path.text(), str(self.game))
        with mock.patch("hd2mm.native_ui.QFileDialog.getExistingDirectory", return_value=str(self.game / "data")):
            dialog.browse()
        self.assertEqual(dialog.path.text(), str(self.game / "data"))
        dialog.deleteLater()

    def test_game_running_disables_apply_and_backend_rejects_stale_click(self):
        self.import_mod()
        with mock.patch("hd2mm.server.gameinfo.is_game_running", return_value=True):
            self.window.refresh()
            self.wait(lambda: not self.window.busy)
            self.assertFalse(self.window.deploy_button.isEnabled())
            with self.assertRaises(ModError):
                self.window.backend.command("/api/deploy")
        self.assertFalse(list((self.game / "data").iterdir()))

    def test_settings_change_language_and_persist_only_changed_values(self):
        dialog = SettingsDialog(self.window)
        dialog.show()
        dialog.language.setCurrentIndex(dialog.language.findData("en"))
        dialog.save()
        self.wait(lambda: not self.window.busy)
        self.assertEqual(self.lib.settings["language"], "en")
        self.assertEqual(self.window.settings_button.text(), "Settings")
        self.assertEqual(self.lib.game_path, str(self.game))
        self.assertFalse(dialog.isVisible())
        dialog.deleteLater()

    def test_normal_settings_do_not_offer_log(self):
        dialog = SettingsDialog(self.window)
        self.assertNotIn(tr("settings.view_log"), [b.text() for b in dialog.findChildren(QPushButton)])
        dialog.deleteLater()
        self.window.diagnostic = True
        dialog = SettingsDialog(self.window)
        self.assertIn(tr("settings.view_log"), [b.text() for b in dialog.findChildren(QPushButton)])
        dialog.deleteLater()

    def test_ui_stays_responsive_and_close_waits_for_operation(self):
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        worker_thread = []
        def slow_work():
            worker_thread.append(threading.get_ident())
            started.set()
            release.wait(5)
            self.lib.update_settings({"language": "en"})
        self.window.run_task(slow_work, refresh=True)
        self.wait(started.is_set)
        self.assertNotEqual(worker_thread, [threading.get_ident()])
        self.assertFalse(self.window.deploy_button.isEnabled())
        self.window.close()
        self.assertTrue(self.window.isVisible())
        release.set()
        self.wait(lambda: not self.window.isVisible())
        self.assertEqual(self.lib.settings["language"], "en")

    def test_failed_command_restores_controls_and_operation_count(self):
        with mock.patch.object(self.window, "show_error") as error:
            self.window.command("/api/mods/missing", {"enabled": True})
            self.wait(lambda: not self.window.busy)
        error.assert_called_once()
        self.assertEqual(self.server.active_operations, 0)
        self.assertTrue(self.window.deploy_button.isEnabled())

    def quiet_gate(self):
        """뒤에서 조용히 도는 작업(15초 새로고침 등)을 흉내 낸다. 돌려준 이벤트를 set하면 끝난다."""
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def slow():
            started.set()
            release.wait(5)
        self.assertTrue(self.window.run_task(slow, quiet=True))
        self.wait(started.is_set)
        return release

    def test_changes_during_quiet_task_use_latest_state(self):
        manifest = {"Version": 1, "Name": "Three", "Options": [
            {"Name": name, "Include": [folder]} for name, folder in (("A", "a"), ("B", "b"), ("C", "c"))]}
        archive = make_zip(self.root / "three.zip", {"manifest.json": json.dumps(manifest), f"a/{ARCHIVE}.patch_0": "a",
                                                    f"b/{ARCHIVE}.patch_0": "b", f"c/{ARCHIVE}.patch_0": "c"})
        self.window.import_paths([str(archive)])
        self.wait(lambda: not self.window.busy and len(self.window.state["mods"]) > 0)
        mod = self.window.selected_mod()
        self.assertEqual(mod["state"]["enabledOptions"], [True, True, True])
        release = self.quiet_gate()
        self.assertTrue(self.window.detail_scroll.isEnabled())  # 조용한 작업 중에도 화면을 막지 않는다
        # 두 번 모두 옛 화면(mod) 기준으로 누른다. 앞의 변경이 뒤의 변경에 덮어쓰이면 안 된다
        self.window.change_array(mod, "enabledOptions", 0, False)
        self.window.change_array(mod, "enabledOptions", 1, False)
        self.window.move_mod(mod["id"], None)
        self.assertEqual(len(self.window._pending), 3)
        release.set()
        self.wait(lambda: not self.window.busy and not self.window._pending)
        self.assertEqual(self.lib.snapshot()[0].state["enabledOptions"], [False, False, True])

    def test_close_during_quiet_task_saves_pending_change(self):
        mod = self.import_mod()
        release = self.quiet_gate()
        self.window.change_mod(mod["id"], {"enabled": False})
        self.window.close()
        self.assertTrue(self.window.isVisible())  # 받아 둔 변경을 저장하기 전에는 닫지 않는다
        release.set()
        self.wait(lambda: not self.window.isVisible())
        self.assertFalse(self.lib.snapshot()[0].enabled)

    def test_space_key_toggles_selected_mod(self):
        self.import_mod()
        self.window.mod_list.setCurrentRow(0)
        QApplication.sendEvent(self.window.mod_list, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space,
                                                               Qt.KeyboardModifier.NoModifier, " "))
        self.wait(lambda: not self.window.busy)
        self.assertFalse(self.lib.snapshot()[0].enabled)

    def test_unrelated_state_change_keeps_detail_widgets(self):
        self.import_mod()
        self.window.detail_scroll.widget().setProperty("marker", "kept")
        with mock.patch("hd2mm.server.gameinfo.is_game_running", return_value=True):
            self.window.refresh(quiet=True)
            self.wait(lambda: not self.window.busy)
        self.assertTrue(self.window.state["game"]["running"])
        # 게임 실행 여부만 바뀌었으니 펼쳐 둔 선택 상자·포커스가 있는 상세 화면은 그대로 둔다
        self.assertEqual(self.window.detail_scroll.widget().property("marker"), "kept")

    def test_readme_is_loaded_as_plain_text(self):
        mod = self.import_mod()
        with mock.patch.object(self.window, "text_dialog") as dialog:
            self.window.show_readme(mod)
            self.wait(lambda: not self.window.busy)
        self.assertIn("<script>", dialog.call_args.args[1])


class BuildVariantTests(unittest.TestCase):
    def test_normal_build_never_creates_log_handler(self):
        logger = logging.Logger("normal-test")
        with mock.patch.object(app.logging, "getLogger", return_value=logger), \
                mock.patch.object(app, "RotatingFileHandler") as file_handler, \
                mock.patch.object(app.sys, "stderr", None):
            app.setup_logging(True)
        file_handler.assert_not_called()
        self.assertIsInstance(logger.handlers[0], logging.NullHandler)

    def test_diagnostic_log_hides_user_folder(self):
        formatter = app.PrivacyFormatter(app.LOG_FORMAT, homes=[r"C:\Users\Jane Doe"], siblings=[])
        record = logging.LogRecord("hd2mm", logging.INFO, __file__, 1, "%s | %s | %s | %s", (
            r"C:\Users\Jane Doe\AppData\Local\Modocracy",
            {"backup": r"c:\users\jane doe\Games\backup"},  # dict는 \가 두 번 찍힌다
            "C:/Users/Jane Doe/Downloads/mod.zip",
            r"C:\Users\Jane Doe2\keep",  # 다른 사용자 폴더는 건드리지 않는다
        ), None)
        try:
            raise OSError(r"cannot open C:\Users\Jane Doe\x.txt")
        except OSError:
            record.exc_info = sys.exc_info()
        text = formatter.format(record)
        self.assertNotIn("Jane Doe\\", text.replace("Jane Doe2", ""))
        self.assertNotIn("jane doe", text.lower().replace("jane doe2", ""))
        self.assertIn(r"%USERPROFILE%\AppData\Local\Modocracy", text)
        self.assertIn("%USERPROFILE%\\\\Games", text)
        self.assertIn("%USERPROFILE%/Downloads", text)
        self.assertIn(r"C:\Users\Jane Doe2\keep", text)
        self.assertIn(r"cannot open %USERPROFILE%\x.txt", text)

    def test_diagnostic_log_hides_short_path_but_not_other_users(self):
        formatter = app.PrivacyFormatter(app.LOG_FORMAT, homes=[r"C:\Users\Jane Doe", r"C:\Users\JANEDO~1"],
                                         siblings=["Jane Doe Smith"])
        text = formatter.mask(r"_MEI C:\Users\JANEDO~1\AppData\Local\Temp\_MEI1 | C:\Users\Jane Doe Smith\x | "
                              r"at C:\Users\Jane Doe and C:\Users\Jane Doe\y")
        self.assertIn(r"%USERPROFILE%\AppData\Local\Temp\_MEI1", text)
        self.assertIn(r"C:\Users\Jane Doe Smith\x", text)  # 이름이 겹치는 다른 사용자 폴더
        self.assertEqual(text.count("%USERPROFILE%"), 3)

    def test_diagnostic_start_scrubs_old_logs(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / "log.txt"
            log.write_text("old C:\\Users\\Jane Doe\\AppData x\n", encoding="utf-8")
            log.with_name("log.txt.1").write_text("older 'C:\\\\Users\\\\Jane Doe\\\\a'\n", encoding="utf-8")
            formatter = app.PrivacyFormatter(app.LOG_FORMAT, homes=[r"C:\Users\Jane Doe"], siblings=[])
            app.scrub_old_logs(log, formatter)
            for file in (log, log.with_name("log.txt.1")):
                self.assertNotIn("Jane Doe", file.read_text(encoding="utf-8"))
            app.scrub_old_logs(Path(folder) / "missing.txt", formatter)  # 파일이 없어도 괜찮다

    def test_diagnostic_log_file_uses_privacy_formatter(self):
        logger = logging.Logger("diagnostic-test")
        with mock.patch.object(app.logging, "getLogger", return_value=logger), \
                mock.patch.object(app, "RotatingFileHandler") as file_handler, \
                mock.patch.object(app, "scrub_old_logs") as scrub, \
                mock.patch.object(app.sys, "stderr", None):
            app.setup_logging(False, diagnostic=True)
        formatter = file_handler.return_value.setFormatter.call_args.args[0]
        self.assertIsInstance(formatter, app.PrivacyFormatter)
        scrub.assert_called_once()  # 새 기록을 이어 쓰기 전에 옛 로그를 먼저 가린다

    def test_diagnostic_updater_chooses_diagnostic_asset_only(self):
        data = release_json()
        data["assets"].append({**data["assets"][0], "name": "Modocracy-diagnostic.exe",
                               "browser_download_url": updater.DOWNLOAD_PREFIX + "v9.9.9/Modocracy-diagnostic.exe"})
        with mock.patch.object(updater, "ASSET_NAME", "Modocracy-diagnostic.exe"), \
                mock.patch.object(updater.urllib.request, "urlopen", side_effect=fake_urlopen(data)):
            self.assertTrue(updater.fetch_latest().asset_url.endswith("/Modocracy-diagnostic.exe"))
            data["assets"].pop()
            self.assertIsNone(updater.fetch_latest().asset_url)

    def test_native_translation_keys_exist(self):
        import re
        source = (Path(__file__).resolve().parent.parent / "hd2mm/native_ui.py").read_text(encoding="utf-8")
        keys = set(re.findall(r'\btr\("([\w.]+)"', source))
        self.assertFalse({k for k in keys if not k.endswith(".")} - CATALOG["ko"].keys())

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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QPushButton, QRadioButton

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
        formatter = app.PrivacyFormatter(app.LOG_FORMAT, home=r"C:\Users\Jane Doe")
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

    def test_diagnostic_log_file_uses_privacy_formatter(self):
        logger = logging.Logger("diagnostic-test")
        with mock.patch.object(app.logging, "getLogger", return_value=logger), \
                mock.patch.object(app, "RotatingFileHandler") as file_handler, \
                mock.patch.object(app.sys, "stderr", None):
            app.setup_logging(False, diagnostic=True)
        formatter = file_handler.return_value.setFormatter.call_args.args[0]
        self.assertIsInstance(formatter, app.PrivacyFormatter)

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

"""한국어·영어 문구 사전과 언어 설정 테스트."""
from __future__ import annotations

import json
import re
import shutil
import string
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from hd2mm import app, gameinfo, i18n
from hd2mm.core import Library, analyze
from hd2mm.server import build_state
from tests.test_core import make_zip
from tests.test_server import ServerCase

WEB = app.web_dir()


def fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def js_catalog() -> dict[str, dict[str, str]]:
    source = (WEB / "i18n.js").read_text(encoding="utf-8")
    body = source.split("const I18N = ", 1)[1].rstrip().rstrip(";")
    return json.loads(body)


class LanguageCase(unittest.TestCase):
    def setUp(self):
        self.addCleanup(i18n.set_language, i18n.current())


class CatalogTests(unittest.TestCase):
    def assert_same_shape(self, catalog):
        ko, en = catalog["ko"], catalog["en"]
        self.assertEqual(set(ko), set(en))
        for key in ko:
            self.assertEqual(fields(ko[key]), fields(en[key]), key)
            self.assertTrue(en[key].strip(), key)
            self.assertIsNone(re.search("[가-힣]", en[key]), f"영어 문구에 한글: {key}")

    def test_python_catalog_matches(self):
        self.assert_same_shape(i18n.MESSAGES)

    def test_web_catalog_matches(self):
        self.assert_same_shape(js_catalog())

    def test_web_uses_only_known_keys(self):
        known = set(js_catalog()["ko"])
        script = (WEB / "app.js").read_text(encoding="utf-8")
        used = set(re.findall(r"\bt\('([\w.]+)'", script))
        html = (WEB / "index.html").read_text(encoding="utf-8")
        used |= set(re.findall(r'data-i18n(?:-title|-aria)?="([\w.]+)"', html))
        self.assertGreater(len(used), 100)
        self.assertEqual(used - known, set())
        # 사전에 있는데 아무 데서도 안 쓰는 문구가 쌓이지 않게
        self.assertEqual(known - used - {"app.title"}, set())

    def test_web_has_no_hardcoded_korean(self):
        script = (WEB / "app.js").read_text(encoding="utf-8")
        code = [line for line in script.splitlines() if not line.strip().startswith("//")]
        leftovers = [line for line in code if re.search("[가-힣]", line.split("//")[0]) and "'한국어'" not in line]
        self.assertEqual(leftovers, [])


class TranslateTests(LanguageCase):
    def test_translate_and_fallback(self):
        i18n.set_language("en")
        self.assertEqual(i18n.t("option.default", n=2), "Option 2")
        with mock.patch.dict(i18n.MESSAGES["en"], clear=True):
            self.assertEqual(i18n.t("option.default", n=2), "옵션 2")  # 영어가 없으면 한국어로
        i18n.set_language("fr")
        self.assertEqual(i18n.current(), "ko")

    def test_resolve_setting(self):
        with mock.patch.object(i18n, "system_language", return_value="en"):
            self.assertEqual(i18n.resolve("auto"), "en")
            self.assertEqual(i18n.resolve(None), "en")
            self.assertEqual(i18n.resolve("ko"), "ko")
        with mock.patch.object(i18n, "system_language", return_value="ko"):
            self.assertEqual(i18n.resolve("auto"), "ko")
            self.assertEqual(i18n.resolve("en"), "en")

    def test_system_language_from_windows(self):
        import ctypes

        kernel = mock.Mock()
        fake = mock.Mock(kernel32=kernel)
        with mock.patch.object(i18n.sys, "platform", "win32"), mock.patch.object(ctypes, "windll", fake, create=True):
            kernel.GetUserDefaultUILanguage.return_value = 0x0412  # ko-KR
            self.assertEqual(i18n.system_language(), "ko")
            kernel.GetUserDefaultUILanguage.return_value = 0x0409  # en-US
            self.assertEqual(i18n.system_language(), "en")


class EnglishCoreTests(LanguageCase):
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp(prefix="hd2mm-i18n-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.lib = Library(self.tmp / "data")

    def import_pack(self) -> str:
        manifest = {"Version": 1, "Name": "Pack", "Options": [
            {"Include": ["a"], "SubOptions": [{"Include": ["a"]}, {"Name": "Named", "Include": ["a"]}]},
            {"Include": ["b"]},
        ]}
        archive = make_zip(self.tmp / "pack.zip", {
            "manifest.json": json.dumps(manifest),
            "a/1111111111111111.patch_0": "a",
            "b/2222222222222222.patch_0": "b",
        })
        return self.lib.import_archive(archive, "pack.zip")["id"]

    def test_default_option_names_follow_language(self):
        self.import_pack()

        def names():
            options = build_state(self.lib)["mods"][0]["options"]
            return [o["name"] for o in options], [s["name"] for s in options[0]["subs"]]

        i18n.set_language("ko")
        self.assertEqual(names(), (["옵션 1", "옵션 2"], ["선택 1", "Named"]))
        i18n.set_language("en")
        self.assertEqual(names(), (["Option 1", "Option 2"], ["Choice 1", "Named"]))
        # 모드 정보 자체(기억해 두는 값)에는 언어별 이름을 넣지 않는다
        self.assertEqual([o.name for o in self.lib.snapshot()[0].info.options], ["", ""])

    def test_issue_text_in_english(self):
        mod_id = self.import_pack()
        self.lib.update(mod_id, {"enabledOptions": [False, False]})  # 켜져 있지만 설치할 파일이 없음
        i18n.set_language("en")
        issues = analyze(self.lib.snapshot(), None)[mod_id]
        self.assertEqual([i["text"] for i in issues], [i18n.MESSAGES["en"]["issue.no_files"]])

    def test_check_game_path_in_english(self):
        i18n.set_language("en")
        _, problem = gameinfo.check_game_path(self.tmp / "missing")
        self.assertEqual(problem, i18n.MESSAGES["en"]["game.missing"])


class EnglishServerTests(ServerCase):
    def setUp(self):
        self.addCleanup(i18n.set_language, i18n.current())
        super().setUp()

    def index_lang(self) -> str:
        with urllib.request.urlopen(self.base + "/", timeout=5) as res:
            html = res.read().decode()
        self.assertNotIn("__HD2MM_LANG__", html)
        return re.search(r'<html lang="(\w+)">', html).group(1)

    def test_language_setting_switches_server_and_page(self):
        i18n.set_language("ko")
        self.assertEqual(self.index_lang(), "ko")
        status, state = self.request("/api/state")
        self.assertEqual((state["language"], state["lang"]), ("auto", "ko"))

        status, _ = self.request("/api/settings", body={"language": "en"})
        self.assertEqual(status, 200)
        self.assertEqual(self.index_lang(), "en")
        status, state = self.request("/api/state")
        self.assertEqual((state["language"], state["lang"]), ("en", "en"))
        self.assertEqual(Library(self.lib.data_dir).settings["language"], "en")  # 파일에도 저장

        status, result = self.request("/api/settings", body={"gamePath": str(self.tmp / "nope")})
        self.assertEqual(status, 400)
        self.assertEqual(result["error"], i18n.MESSAGES["en"]["game.missing"])

    def test_bad_language_changes_nothing(self):
        before = self.lib.game_path
        status, result = self.request("/api/settings", body={"language": "fr", "gamePath": str(self.tmp)})
        self.assertEqual(status, 400)
        self.assertEqual(self.lib.game_path, before)
        self.assertNotIn("language", self.lib.settings)

    def test_language_can_change_while_game_folder_is_missing(self):
        shutil.rmtree(self.game)  # 게임을 옮기거나 지워서 저장된 경로가 틀어진 상태
        status, _ = self.request("/api/settings", body={"language": "en"})
        self.assertEqual(status, 200)
        self.assertEqual(self.lib.settings["language"], "en")

    def test_settings_are_saved_once_and_not_at_all_on_error(self):
        with mock.patch.object(self.lib, "save", wraps=self.lib.save) as save:
            body = {"language": "ko", "checkUpdates": False, "gamePath": str(self.game)}
            status, _ = self.request("/api/settings", body=body)
            self.assertEqual((status, save.call_count), (200, 1))
            status, _ = self.request("/api/settings", body={"language": "en", "gamePath": str(self.tmp / "nope")})
            self.assertEqual((status, save.call_count), (400, 1))
        self.assertEqual(self.lib.settings["language"], "ko")
        self.assertEqual(i18n.current(), "ko")

    def test_failed_settings_save_changes_nothing(self):
        i18n.set_language("ko")
        with mock.patch("hd2mm.core.write_json", side_effect=OSError("disk full")):
            status, result = self.request("/api/settings", body={"language": "en", "checkUpdates": False})
        self.assertEqual(status, 400)
        self.assertIn("disk full", result["error"])
        self.assertNotIn("language", self.lib.settings)  # 화면에 저장된 것처럼 보이지 않게 되돌린다
        self.assertNotIn("checkUpdates", self.lib.settings)
        self.assertEqual(i18n.current(), "ko")

    def test_i18n_script_is_served(self):
        with urllib.request.urlopen(self.base + "/i18n.js", timeout=5) as res:
            self.assertIn("javascript", res.headers["Content-Type"])
            self.assertIn(b"const I18N", res.read())


class StartupLanguageTests(LanguageCase):
    def test_saved_language_reads_only_valid_text(self):
        with tempfile.TemporaryDirectory(prefix="hd2mm-lang-") as tmp:
            data_dir = Path(tmp)
            self.assertIsNone(app.saved_language(data_dir))  # 설정 파일이 아직 없음
            cases = [("{broken", None), ('["en"]', None), ('{"language": 3}', None), ('{"language": "en"}', "en")]
            for content, expected in cases:
                (data_dir / "settings.json").write_text(content, encoding="utf-8")
                self.assertEqual(app.saved_language(data_dir), expected, content)

    def test_startup_errors_use_saved_language(self):
        with tempfile.TemporaryDirectory(prefix="hd2mm-lang-") as tmp,                 mock.patch.object(i18n, "system_language", return_value="ko"),                 mock.patch.object(app, "acquire_instance_mutex", return_value=False),                 mock.patch.object(app, "running_instance", return_value=None),                 mock.patch.object(app, "show_error") as error,                 mock.patch.object(app.time, "monotonic", side_effect=[0, 0, 11]),                 mock.patch.object(app.time, "sleep"):
            (Path(tmp) / "settings.json").write_text(json.dumps({"language": "en"}), encoding="utf-8")
            self.assertEqual(app.main(["--data-dir", tmp]), 1)
            error.assert_called_once_with(i18n.MESSAGES["en"]["startup.not_responding"])
            self.assertEqual(i18n.current(), "en")

    def test_startup_uses_windows_language_when_auto(self):
        with tempfile.TemporaryDirectory(prefix="hd2mm-lang-") as tmp,                 mock.patch.object(i18n, "system_language", return_value="en"),                 mock.patch.object(app, "acquire_instance_mutex", return_value=False):
            (Path(tmp) / "settings.json").write_text(json.dumps({"language": "auto"}), encoding="utf-8")
            self.assertEqual(app.main(["--data-dir", tmp, "--no-window"]), 1)
            self.assertEqual(i18n.current(), "en")


if __name__ == "__main__":
    unittest.main()

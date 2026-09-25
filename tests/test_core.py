"""핵심 로직 테스트. 실제 게임 폴더는 건드리지 않고 임시 폴더에 가짜 게임 폴더를 만든다."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from hd2mm.core import (
    MAX_README_BYTES, PATCH_RE, Library, ModError, NeedsConfirm, analyze, build_plan, clean_guid,
    legacy_plan_signature, parse_mod, read_readme, read_text, safe_join,
)

ROOT = Path(__file__).resolve().parent.parent
LOADER_ZIP = ROOT / "Bingus-Shared-Loader-v17.zip"
ECS_ZIP = ROOT / "Enemy-Collision-Synchronized-v2.9.zip"
LOADER_ID = "612eaf70-d682-43c7-9efd-16dcc695f977"
ECS_ID = "1f58c710-8822-4bd9-9c52-6fa0ed9277ef"
ARCHIVE = "9ba626afa44a3aa3"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_zip(path: Path, files: dict[str, bytes | str]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data.encode() if isinstance(data, str) else data)
    return path


class TempCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hd2mm-test-"))
        self.lib = Library(self.tmp / "data")
        self.game = self.tmp / "game"
        (self.game / "data").mkdir(parents=True)
        (self.game / "bin").mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def game_files(self) -> list[str]:
        return sorted(p.name for p in (self.game / "data").iterdir())


@unittest.skipUnless(LOADER_ZIP.exists() and ECS_ZIP.exists(), "예시 모드 zip이 없음")
class SampleModTests(TempCase):
    def import_samples(self):
        self.lib.import_archive(ECS_ZIP, ECS_ZIP.name)
        self.lib.import_archive(LOADER_ZIP, LOADER_ZIP.name)

    def test_import_reads_manifest(self):
        result = self.lib.import_archive(LOADER_ZIP, LOADER_ZIP.name)
        self.assertEqual(result, {"id": LOADER_ID, "name": "Bingus Shared Loader - v17", "updated": False, "previousName": None})
        snap = self.lib.snapshot()[0]
        self.assertEqual(snap.info.mode, "fixed")
        self.assertEqual(snap.info.icon, "thumbnail.png")
        self.assertEqual(snap.info.extra["version"], "v17")
        self.assertIn("shared_loader_api", snap.info.extra["provides"])
        self.assertEqual([(s.archive, s.index) for s in snap.sets], [(ARCHIVE, 0)])
        self.assertIn("Bingus Shared Loader", read_readme(snap.info))

    def test_reimport_same_guid_updates_in_place(self):
        self.import_samples()
        self.lib.update(ECS_ID, {"enabled": False})
        result = self.lib.import_archive(ECS_ZIP, "Enemy-Collision-Synchronized-v3.0.zip")
        self.assertTrue(result["updated"])
        self.assertEqual(result["previousName"], "Enemy Collision Synchronized - v2.9")
        ids = [m["id"] for m in self.lib.settings["mods"]]
        self.assertEqual(ids, [ECS_ID, LOADER_ID])
        self.assertFalse(self.lib.settings["mods"][0]["enabled"])
        self.assertEqual(self.lib.settings["mods"][0]["sourceName"], "Enemy-Collision-Synchronized-v3.0.zip")

    def test_deploy_numbers_patches_in_list_order(self):
        self.import_samples()
        result = self.lib.deploy(self.game)
        self.assertEqual(result["modCount"], 2)
        self.assertEqual(result["fileCount"], 6)
        data = self.game / "data"
        ecs_src = self.lib.mods_dir / ECS_ID / "data" / f"{ARCHIVE}.patch_0"
        loader_src = self.lib.mods_dir / LOADER_ID / "data" / f"{ARCHIVE}.patch_0"
        # 위에 있는 ECS가 0번, 맨 아래 로더가 1번(가장 높은 우선순위)
        self.assertEqual(sha(data / f"{ARCHIVE}.patch_0"), sha(ecs_src))
        self.assertEqual(sha(data / f"{ARCHIVE}.patch_1"), sha(loader_src))
        self.assertEqual((data / f"{ARCHIVE}.patch_1.stream").stat().st_size, 0)
        self.assertEqual(self.lib.status(self.game, self.lib.snapshot())["state"], "ok")

        self.lib.reorder([LOADER_ID, ECS_ID])
        self.assertEqual(self.lib.status(self.game, self.lib.snapshot())["state"], "dirty")
        self.lib.deploy(self.game)
        self.assertEqual(sha(data / f"{ARCHIVE}.patch_0"), sha(loader_src))
        self.assertEqual(sha(data / f"{ARCHIVE}.patch_1"), sha(ecs_src))

    def test_disabling_mod_removes_its_files_on_next_deploy(self):
        self.import_samples()
        self.lib.deploy(self.game)
        self.lib.update(ECS_ID, {"enabled": False})
        self.lib.deploy(self.game)
        self.assertEqual(self.game_files(), [f"{ARCHIVE}.patch_0", f"{ARCHIVE}.patch_0.gpu_resources", f"{ARCHIVE}.patch_0.stream"])

    def test_unmanaged_files_need_confirmation_and_are_backed_up(self):
        self.import_samples()
        data = self.game / "data"
        ecs_bytes = (self.lib.mods_dir / ECS_ID / "data" / f"{ARCHIVE}.patch_0").read_bytes()
        (data / f"{ARCHIVE}.patch_0").write_bytes(ecs_bytes)
        (data / f"{ARCHIVE}.patch_0.stream").write_bytes(b"")
        (data / f"{ARCHIVE}.patch_1").write_bytes(b"unknown mod")
        (data / "bundles.00.nxa").write_bytes(b"game data")  # 게임 원본 파일은 건드리면 안 됨

        with self.assertRaises(NeedsConfirm) as ctx:
            self.lib.deploy(self.game)
        groups = {g["name"]: g for g in ctx.exception.unmanaged}
        self.assertEqual(groups[f"{ARCHIVE}.patch_0"]["match"], "Enemy Collision Synchronized - v2.9")
        self.assertEqual(len(groups[f"{ARCHIVE}.patch_0"]["files"]), 2)
        self.assertIsNone(groups[f"{ARCHIVE}.patch_1"]["match"])
        self.assertIn(f"{ARCHIVE}.patch_1", self.game_files())  # 확인 전에는 아무것도 바뀌지 않음

        result = self.lib.deploy(self.game, "move")
        backup = Path(result["backup"])
        self.assertEqual((backup / f"{ARCHIVE}.patch_1").read_bytes(), b"unknown mod")
        self.assertTrue((data / "bundles.00.nxa").exists())
        self.assertEqual(self.lib.status(self.game, self.lib.snapshot())["unmanaged"], [])

    def test_purge_keeps_or_moves_unmanaged(self):
        self.import_samples()
        self.lib.deploy(self.game)
        data = self.game / "data"
        (data / "0123456789abcdef.patch_0").write_bytes(b"x")
        with self.assertRaises(NeedsConfirm):
            self.lib.purge(self.game)
        result = self.lib.purge(self.game, "keep")
        self.assertEqual(result["removed"], 6)
        self.assertEqual(self.game_files(), ["0123456789abcdef.patch_0"])
        self.assertEqual(self.lib.status(self.game, self.lib.snapshot())["state"], "pending")

    def test_missing_files_are_reported(self):
        self.import_samples()
        self.lib.deploy(self.game)
        (self.game / "data" / f"{ARCHIVE}.patch_1").unlink()
        self.assertEqual(self.lib.status(self.game, self.lib.snapshot())["state"], "broken")

    def test_new_mod_goes_above_loader_at_bottom(self):
        self.lib.import_archive(LOADER_ZIP, LOADER_ZIP.name)
        self.lib.import_archive(ECS_ZIP, ECS_ZIP.name)
        self.assertEqual([m["id"] for m in self.lib.settings["mods"]], [ECS_ID, LOADER_ID])

    def test_analyze_dependency_and_loader_position(self):
        self.lib.import_archive(ECS_ZIP, ECS_ZIP.name)
        issues = analyze(self.lib.snapshot(), "1.8.46015.0")[ECS_ID]
        self.assertTrue(any(i["level"] == "error" and "Bingus Shared Loader" in i["text"] for i in issues))
        self.assertTrue(any(i["level"] == "info" and "1.8.45317.0" in i["text"] for i in issues))

        self.lib.import_archive(LOADER_ZIP, LOADER_ZIP.name)
        self.assertFalse(any(i["level"] == "error" for i in analyze(self.lib.snapshot(), None)[ECS_ID]))

        self.lib.reorder([LOADER_ID, ECS_ID])
        loader_issues = analyze(self.lib.snapshot(), None)[LOADER_ID]
        self.assertTrue(any(i.get("fix") == "bottom" for i in loader_issues))

        self.lib.update(LOADER_ID, {"enabled": False})
        issues = analyze(self.lib.snapshot(), None)[ECS_ID]
        self.assertTrue(any("꺼져 있어요" in i["text"] for i in issues))


class SyntheticModTests(TempCase):
    def test_v1_options_and_suboptions(self):
        manifest = {
            "Version": 1, "Guid": "{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}", "Name": "Color Pack",
            "Options": [
                {"Name": "Base", "Include": ["base"]},
                {"Name": "Color", "Include": [], "SubOptions": [
                    {"Name": "Red", "Include": ["red"]}, {"Name": "Blue", "Include": ["blue"]}]},
            ],
        }
        archive = make_zip(self.tmp / "color.zip", {
            "manifest.json": json.dumps(manifest),
            "base/1111111111111111.patch_0": "b",
            "red/2222222222222222.patch_0": "r",
            "blue/2222222222222222.patch_0": "bl",
        })
        result = self.lib.import_archive(archive, "color.zip")
        mod_id = result["id"]
        self.assertEqual(mod_id, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        snap = self.lib.snapshot()[0]
        self.assertEqual(snap.info.mode, "multi")
        self.assertEqual(sorted(s.main.parent.name for s in snap.sets), ["base", "red"])

        self.lib.update(mod_id, {"selectedSubs": [0, 1]})
        self.lib.deploy(self.game)
        self.assertEqual((self.game / "data" / "2222222222222222.patch_0").read_text(), "bl")

        self.lib.update(mod_id, {"enabledOptions": [True, False]})
        self.lib.deploy(self.game)
        self.assertNotIn("2222222222222222.patch_0", self.game_files())
        self.assertIn("1111111111111111.patch_0", self.game_files())

    def test_legacy_manifest_single_choice(self):
        archive = make_zip(self.tmp / "legacy.zip", {
            "manifest.json": json.dumps({"Guid": "11111111-2222-3333-4444-555555555555", "Name": "Legacy", "Options": ["A", "B"]}),
            "A/3333333333333333.patch_0": "a",
            "B/3333333333333333.patch_0": "b",
        })
        mod_id = self.lib.import_archive(archive, "legacy.zip")["id"]
        self.assertEqual(self.lib.snapshot()[0].info.mode, "single")
        self.lib.update(mod_id, {"choice": 1})
        self.lib.deploy(self.game)
        self.assertEqual((self.game / "data" / "3333333333333333.patch_0").read_text(), "b")

    def test_no_manifest_with_wrapper_folder(self):
        archive = make_zip(self.tmp / "My Cool Mod v2.zip", {
            "My Cool Mod/readme.txt": "hello",
            "My Cool Mod/4444444444444444.patch_0": "p",
            "My Cool Mod/4444444444444444.patch_0.gpu_resources": "g",
        })
        result = self.lib.import_archive(archive, "My Cool Mod v2.zip")
        self.assertEqual(result["name"], "My Cool Mod v2")
        snap = self.lib.snapshot()[0]
        self.assertEqual(read_readme(snap.info), "hello")
        self.lib.deploy(self.game)
        self.assertEqual((self.game / "data" / "4444444444444444.patch_0.gpu_resources").read_text(), "g")
        self.assertEqual((self.game / "data" / "4444444444444444.patch_0.stream").read_bytes(), b"")

    def test_same_archive_across_mods_and_multiple_patches_in_one_mod(self):
        make_zip(self.tmp / "a.zip", {"5555555555555555.patch_0": "a0", "5555555555555555.patch_1": "a1"})
        make_zip(self.tmp / "b.zip", {"5555555555555555.patch_0": "b0", "6666666666666666.patch_0": "b6"})
        self.lib.import_archive(self.tmp / "a.zip", "a.zip")
        self.lib.import_archive(self.tmp / "b.zip", "b.zip")
        self.lib.deploy(self.game)
        data = self.game / "data"
        self.assertEqual([(data / f"5555555555555555.patch_{i}").read_text() for i in range(3)], ["a0", "a1", "b0"])
        self.assertEqual((data / "6666666666666666.patch_0").read_text(), "b6")

    def test_rejects_archive_without_patch_files(self):
        archive = make_zip(self.tmp / "nothing.zip", {"readme.txt": "no mod here"})
        with self.assertRaises(ModError):
            self.lib.import_archive(archive, "nothing.zip")
        self.assertEqual(self.lib.settings["mods"], [])

    def test_zip_slip_entries_are_ignored(self):
        archive = make_zip(self.tmp / "evil.zip", {
            "../../evil.txt": "x",
            "7777777777777777.patch_0": "ok",
        })
        self.lib.import_archive(archive, "evil.zip")
        self.assertFalse((self.tmp / "evil.txt").exists())
        self.assertFalse((self.lib.data_dir / "evil.txt").exists())

    def test_include_outside_mod_folder_is_ignored(self):
        root = self.tmp / "mod"
        root.mkdir()
        (root / "manifest.json").write_text(json.dumps({"Version": 1, "Name": "x", "Options": [
            {"Name": "bad", "Include": ["../../game/data"]}, {"Name": "good", "Include": ["."]}]}))
        self.assertIsNone(safe_join(root, "../../game/data"))
        info = parse_mod(root)
        self.assertEqual(info.options[0].include, ["../../game/data"])

    def test_broken_manifest_reports_error(self):
        archive = make_zip(self.tmp / "broken.zip", {"manifest.json": "{not json", "8888888888888888.patch_0": "x"})
        with self.assertRaises(ModError):
            self.lib.import_archive(archive, "broken.zip")

    def test_remove_mod(self):
        make_zip(self.tmp / "a.zip", {"5555555555555555.patch_0": "a0"})
        mod_id = self.lib.import_archive(self.tmp / "a.zip", "a.zip")["id"]
        self.lib.remove(mod_id)
        self.assertEqual(self.lib.settings["mods"], [])
        self.assertFalse((self.lib.mods_dir / mod_id).exists())

    def test_settings_survive_reload(self):
        make_zip(self.tmp / "a.zip", {"5555555555555555.patch_0": "a0"})
        mod_id = self.lib.import_archive(self.tmp / "a.zip", "a.zip")["id"]
        self.lib.set_game_path(str(self.game))
        reloaded = Library(self.lib.data_dir)
        self.assertEqual(reloaded.game_path, str(self.game))
        self.assertEqual([m["id"] for m in reloaded.settings["mods"]], [mod_id])


class ReviewRegressionTests(TempCase):
    def import_patch(self, guid=None):
        files = {f"{ARCHIVE}.patch_0": "original"}
        if guid:
            files["manifest.json"] = json.dumps({"Guid": guid})
        archive = make_zip(self.tmp / "mod.zip", files)
        return self.lib.import_archive(archive, archive.name)

    def test_changed_deployed_file_requires_confirmation_and_backup(self):
        self.import_patch()
        for action in (self.lib.deploy, self.lib.purge):
            for content in (b"modified", b"different size"):
                with self.subTest(action=action.__name__, content=content):
                    self.lib.deploy(self.game)
                    target = self.game / "data" / f"{ARCHIVE}.patch_0"
                    old = target.stat()
                    target.write_bytes(content)
                    os.utime(target, ns=(old.st_atime_ns, old.st_mtime_ns + 2_000_000_000))
                    status = self.lib.status(self.game, self.lib.snapshot())
                    self.assertEqual(status["state"], "broken")
                    self.assertIn(target.name, status["unmanaged"])
                    with self.assertRaises(NeedsConfirm) as caught:
                        action(self.game)
                    self.assertIn(target.name, caught.exception.unmanaged[0]["files"])
                    self.assertEqual(target.read_bytes(), content)
                    result = action(self.game, "move")
                    self.assertEqual((Path(result["backup"]) / target.name).read_bytes(), content)

    def test_purge_keeps_changed_file(self):
        self.import_patch()
        self.lib.deploy(self.game)
        target = self.game / "data" / f"{ARCHIVE}.patch_0"
        target.write_bytes(b"external replacement")
        result = self.lib.purge(self.game, "keep")
        self.assertEqual(result["removed"], 2)
        self.assertEqual(self.game_files(), [target.name])
        self.assertEqual(target.read_bytes(), b"external replacement")

    def test_old_record_uses_size_and_missing_file_is_broken(self):
        self.import_patch()
        self.lib.deploy(self.game)
        record = self.lib._load_record(self.game)
        for item in record["files"]:
            self.assertIsInstance(item.pop("mtime"), int)
        self.lib._write_record(self.game, record)
        target = self.game / "data" / f"{ARCHIVE}.patch_0"
        target.write_bytes(b"modified")
        self.assertEqual(self.lib.status(self.game, self.lib.snapshot())["state"], "ok")
        target.unlink()
        status = self.lib.status(self.game, self.lib.snapshot())
        self.assertEqual(status["state"], "broken")
        self.assertIn(target.name, status["missing"])
        self.assertNotIn(target.name, status["unmanaged"])

    def test_partial_copy_leaves_no_patch_or_temp(self):
        self.import_patch()

        def fail_copy(src, dst):
            self.assertIsNone(PATCH_RE.match(dst.name))
            dst.write_bytes(b"partial")
            raise OSError("복사 실패")

        with mock.patch("hd2mm.core.shutil.copyfile", side_effect=fail_copy):
            with self.assertRaises(ModError):
                self.lib.deploy(self.game)
        self.assertEqual(self.game_files(), [])
        self.assertIsNone(self.lib._load_record(self.game))  # 파일이 없는 기록은 남기지 않음
        self.lib.deploy(self.game)
        self.assertEqual(self.lib.status(self.game, self.lib.snapshot())["state"], "ok")

    def test_replace_failure_cleans_temp(self):
        self.import_patch()
        replace = os.replace

        def fail_replace(src, dst):
            if str(src).endswith(".hd2mm-tmp"):
                raise OSError("교체 실패")
            return replace(src, dst)

        with mock.patch("hd2mm.core.os.replace", side_effect=fail_replace):
            with self.assertRaises(ModError):
                self.lib.deploy(self.game)
        self.assertEqual(self.game_files(), [])

    def test_deploy_and_purge_clean_abandoned_temp(self):
        for action in (self.lib.deploy, self.lib.purge):
            with self.subTest(action=action.__name__):
                target = self.game / "data" / f"{ARCHIVE}.patch_0.hd2mm-tmp"
                target.write_bytes(b"partial")
                action(self.game)
                self.assertFalse(target.exists())

    def test_guid_formats_update_existing_folder(self):
        self.assertEqual(clean_guid("{" + LOADER_ID.replace("-", "").upper() + "}"), LOADER_ID)
        self.assertIsNone(clean_guid("invalid"))
        self.assertIsNone(clean_guid(None))
        result = self.import_patch(LOADER_ID.replace("-", ""))
        self.assertEqual(result["id"], LOADER_ID)
        result = self.import_patch(LOADER_ID.upper())
        self.assertTrue(result["updated"])
        entry = self.lib.settings["mods"][0]
        old_id = LOADER_ID.replace("-", "")
        (self.lib.mods_dir / LOADER_ID).rename(self.lib.mods_dir / old_id)
        entry["id"] = old_id
        self.lib.update(old_id, {"enabled": False})
        result = self.import_patch(LOADER_ID)
        self.assertTrue(result["updated"])
        self.assertEqual(result["id"], old_id)
        self.assertEqual(len(self.lib.settings["mods"]), 1)
        self.assertFalse(entry["enabled"])
        self.assertEqual([p.name for p in self.lib.mods_dir.iterdir()], [old_id])


class SecondReviewTests(TempCase):
    def import_patch(self):
        archive = make_zip(self.tmp / "mod.zip", {f"{ARCHIVE}.patch_0": "p"})
        return self.lib.import_archive(archive, archive.name)["id"]

    def test_moving_library_keeps_applied_state(self):
        self.import_patch()
        self.lib.deploy(self.game)
        moved = self.tmp / "moved-library"
        os.replace(self.lib.data_dir, moved)  # 예: HD2ModManager → Modocracy 폴더 이동
        reopened = Library(moved)
        self.assertEqual(reopened.status(self.game, reopened.snapshot())["state"], "ok")

    def test_records_are_kept_per_game_folder(self):
        self.import_patch()
        other = self.tmp / "game2"
        (other / "data").mkdir(parents=True)
        self.lib.deploy(self.game)
        self.lib.deploy(other)
        self.assertEqual(self.lib.other_deployments(other), [{"gamePath": str(self.game), "files": 3}])
        self.assertEqual(self.lib.status(self.game, self.lib.snapshot())["state"], "ok")
        self.assertEqual(self.lib.purge(self.game)["removed"], 3)
        self.assertEqual(self.game_files(), [])
        self.assertEqual(self.lib.other_deployments(other), [])
        self.assertEqual(self.lib.status(other, self.lib.snapshot())["state"], "ok")

    def test_mod_info_is_cached_until_folder_changes(self):
        mod_id = self.import_patch()
        self.lib.snapshot()
        with mock.patch("hd2mm.core.parse_mod", wraps=parse_mod) as parse:
            self.lib.snapshot()
            self.lib.snapshot()
            self.assertEqual(parse.call_count, 0)  # 폴더가 그대로면 전에 읽은 결과를 씀
            (self.lib.mods_dir / mod_id / "manifest.json").write_text('{"Name": "Renamed"}', encoding="utf-8")
            self.assertEqual(self.lib.snapshot()[0].info.name, "Renamed")
            self.assertEqual(parse.call_count, 1)

    def test_cache_notices_new_patch_folder_inside_subfolder(self):
        archive = make_zip(self.tmp / "pack.zip", {
            "Pack/Red/1111111111111111.patch_0": "r",
            "Pack/Blue/1111111111111111.patch_0": "b",
        })
        mod_id = self.lib.import_archive(archive, archive.name)["id"]
        self.assertEqual(len(self.lib.snapshot()[0].info.options), 2)
        extra = self.lib.mods_dir / mod_id / "Red" / "Extra"
        extra.mkdir()
        (extra / "2222222222222222.patch_0").write_text("x")
        self.assertEqual(len(self.lib.snapshot()[0].info.options), 3)

    def test_cache_notices_edited_extra_manifest(self):
        archive = make_zip(self.tmp / "mod.zip", {
            "Mod-manifest.json": json.dumps({"name": "Mod", "display_version": "v1"}),
            f"{ARCHIVE}.patch_0": "p",
        })
        mod_id = self.lib.import_archive(archive, archive.name)["id"]
        self.assertEqual(self.lib.snapshot()[0].info.extra["version"], "v1")
        extra = self.lib.mods_dir / mod_id / "Mod-manifest.json"
        extra.write_text(json.dumps({"name": "Mod", "display_version": "v2"}), encoding="utf-8")
        stat = extra.stat()
        os.utime(extra, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
        self.assertEqual(self.lib.snapshot()[0].info.extra["version"], "v2")

    def test_readme_reads_only_the_limit_and_keeps_korean_intact(self):
        path = self.tmp / "readme.txt"
        path.write_bytes(("가" * 10).encode("utf-8"))  # 한 글자 3바이트
        self.assertEqual(read_text(path, 7), "가가")      # 7바이트에서 잘린 세 번째 글자는 버림
        big = self.tmp / "big.txt"
        big.write_bytes(b"a" * (MAX_README_BYTES * 5))
        self.assertEqual(len(read_text(big, MAX_README_BYTES)), MAX_README_BYTES)

    def test_v1_signature_is_accepted_and_upgraded(self):
        self.import_patch()
        self.lib.deploy(self.game)
        record = self.lib._load_record(self.game)
        plan = build_plan(self.lib.snapshot())
        record["signature"] = legacy_plan_signature(plan)  # v1.0.0이 남긴 기록
        self.lib._write_record(self.game, record)
        self.assertEqual(self.lib.status(self.game, self.lib.snapshot())["state"], "ok")
        self.assertNotEqual(self.lib._load_record(self.game)["signature"], legacy_plan_signature(plan))

    def test_empty_records_are_not_kept(self):
        self.import_patch()
        self.lib.deploy(self.game)
        self.lib.purge(self.game)
        self.assertEqual(self.lib.load_records(), {})

    def test_locked_old_mod_folder_gives_clear_error(self):
        archive = make_zip(self.tmp / "mod.zip", {
            "manifest.json": json.dumps({"Guid": "11111111-2222-3333-4444-555555555555", "Name": "A"}),
            f"{ARCHIVE}.patch_0": "p",
        })
        mod_id = self.lib.import_archive(archive, archive.name)["id"]
        dest = self.lib.mods_dir / mod_id
        real_replace = os.replace

        def locked(src, dst):
            if Path(src) == dest:
                raise PermissionError("in use")
            return real_replace(src, dst)

        with mock.patch("hd2mm.core.os.replace", side_effect=locked):
            with self.assertRaises(ModError) as ctx:
                self.lib.import_archive(archive, archive.name)
        self.assertIn("다른 프로그램에서 열려", str(ctx.exception))
        self.assertTrue((dest / f"{ARCHIVE}.patch_0").exists())

    def test_locked_leftover_temp_does_not_block_deploy(self):
        self.import_patch()
        leftover = self.game / "data" / "ffffffffffffffff.patch_7.hd2mm-tmp"
        leftover.write_bytes(b"old temp")
        real_unlink = Path.unlink

        def unlink(path, missing_ok=False):
            if path.name.endswith(".hd2mm-tmp") and path.exists():
                raise PermissionError("in use")
            return real_unlink(path, missing_ok=missing_ok)

        with mock.patch.object(Path, "unlink", autospec=True, side_effect=unlink):
            self.lib.deploy(self.game)
            self.lib.purge(self.game)
        self.assertEqual(self.game_files(), [leftover.name])

    def test_reads_old_single_record_file(self):
        self.import_patch()
        self.lib.deploy(self.game)
        record = self.lib._load_record(self.game)
        self.lib.record_path.write_text(json.dumps(record), encoding="utf-8")  # 예전 형식
        self.assertEqual(self.lib.status(self.game, self.lib.snapshot())["state"], "ok")
        self.assertEqual(self.lib.purge(self.game)["removed"], 3)
        self.assertEqual(self.game_files(), [])


if __name__ == "__main__":
    unittest.main()

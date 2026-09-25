"""화면에 보이는 문구의 한국어·영어 사전.

언어 설정은 "auto"(Windows 표시 언어가 한국어면 한국어, 아니면 영어), "ko", "en" 중 하나다.
화면(웹) 쪽 문구는 hd2mm/web/i18n.js 에 따로 있고, tests/test_i18n.py 가 두 언어의 키와
{자리}가 맞는지 검사한다.
"""
from __future__ import annotations

import locale
import sys

LANGUAGES = ("ko", "en")
SETTINGS = ("auto", "ko", "en")
_current = "ko"


def system_language() -> str:
    """Windows 표시 언어가 한국어면 "ko", 아니면 "en"."""
    if sys.platform == "win32":
        import ctypes

        try:
            langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return "ko" if (langid & 0x3FF) == 0x12 else "en"  # 0x12 = LANG_KOREAN
        except (AttributeError, OSError):
            pass
    name = (locale.getlocale()[0] or "").lower()
    return "ko" if name.startswith(("ko", "korean")) else "en"


def resolve(setting: str | None) -> str:
    return setting if setting in LANGUAGES else system_language()


def set_language(lang: str) -> None:
    global _current
    _current = lang if lang in LANGUAGES else "ko"


def current() -> str:
    return _current


def t(key: str, **params) -> str:
    text = MESSAGES[_current].get(key) or MESSAGES["ko"][key]
    return text.format(**params) if params else text


MESSAGES: dict[str, dict[str, str]] = {
    "ko": {
        # 모드 해석
        "option.default": "옵션 {n}",
        "suboption.default": "선택 {n}",
        "err.manifest_invalid": "manifest.json 형식이 올바르지 않아요.",
        "err.manifest_invalid_detail": "manifest.json 형식이 올바르지 않아요: {detail}",
        # 가져오기
        "err.zip_broken": "압축 파일이 손상되었거나 올바른 zip 파일이 아니에요.",
        "err.need_7zip": "{ext} 파일을 풀려면 7-Zip이 필요해요. 7-Zip을 설치하거나 zip 파일로 받아 주세요.",
        "err.extract_failed": "압축을 풀지 못했어요.{detail}",
        "err.extract_error": "압축을 푸는 중 오류가 났어요: {detail}",
        "err.archive_types": ".zip, .7z, .rar 압축 파일만 추가할 수 있어요.",
        "err.no_patch_files": "이 압축 파일에서 Helldivers 2 모드 파일(.patch_0 등)을 찾지 못했어요.",
        "err.mod_folder_locked": "기존 모드 파일을 바꾸지 못했어요. 이 모드 폴더의 파일이 다른 프로그램에서 열려 있으면 닫고 다시 시도해 주세요. ({detail})",
        "err.store_failed": "모드를 보관함에 저장하지 못했어요: {detail}",
        "err.mod_not_found": "해당 모드를 찾을 수 없어요. 새로고침해 주세요.",
        "err.order_changed": "모드 목록이 바뀌었어요. 새로고침 후 다시 시도해 주세요.",
        # 적용 / 제거
        "backup.file_name": "백업 안내.txt",
        "backup.text": "모드 매니저가 적용하기 전에 게임 data 폴더에 있던 모드 파일을 옮겨 둔 곳입니다.\n"
                       "원래 위치: {path}\n다시 쓰려면 이 파일들을 원래 위치로 복사하세요.\n",
        "err.backup_failed": "기존 모드 파일을 백업 폴더로 옮기지 못했어요: {detail}",
        "err.remove_previous_failed": "이전에 설치한 파일을 지우지 못했어요. 게임이 완전히 꺼졌는지 확인한 뒤 다시 시도해 주세요.",
        "err.no_write_permission": "게임 폴더에 파일을 쓸 권한이 없어요. 게임을 끄고, 그래도 안 되면 관리자 권한으로 실행해 보세요.",
        "err.copy_failed": "파일을 복사하는 중 오류가 났어요: {detail}",
        "err.remove_some_failed": "일부 파일을 지우지 못했어요. 게임이 완전히 꺼졌는지 확인한 뒤 다시 시도해 주세요.",
        # 모드 점검 안내
        "issue.no_files": "지금 고른 옵션으로는 설치할 파일이 없어요. 옵션을 확인해 주세요.",
        "issue.at_least": " ({revision} 이상)",
        "issue.get_from": " 받는 곳: {url}",
        "issue.optional_requirement": "‘{name}’{need}는 일부 기능에만 필요해요{purpose}. 그 기능을 쓰지 않으면 없어도 돼요.{where}",
        "issue.requirement_missing": "‘{name}’{need} 모드가 필요해요. 따로 받아서 목록에 추가해 주세요.{where}",
        "issue.requirement_disabled": "필요한 모드 ‘{name}’가 꺼져 있어요. 켜 주세요.",
        "issue.requirement_outdated": "‘{name}’를 {revision} 이상으로 업데이트해야 해요.",
        "issue.loader_last": "공유 로더는 목록 맨 아래에 있어야 다른 모드를 제대로 불러와요.",
        "issue.duplicate": "같은 모드가 두 개 켜져 있어요. 하나만 켜 두세요.",
        "issue.older_game": "게임 버전 {mod} 기준으로 만든 모드예요 (현재 게임 {game}). "
                            "대부분 그대로 작동하지만, 문제가 생기면 새 버전이 있는지 확인해 보세요.",
        "issue.newer_game": "더 새로운 게임 버전 {mod}용 모드예요 (현재 게임 {game}). 게임을 업데이트해 주세요.",
        # 게임 폴더
        "game.not_set": "게임 폴더가 아직 설정되지 않았어요.",
        "game.missing": "설정된 게임 폴더가 존재하지 않아요.",
        "game.not_hd2": "Helldivers 2 폴더가 아닌 것 같아요 (data 폴더가 없어요).",
        # 서버
        "err.request_too_large": "요청이 너무 커요.",
        "err.bad_request": "잘못된 요청이에요.",
        "err.unknown": "알 수 없는 오류가 났어요. 로그 파일을 확인해 주세요.",
        "err.updating": "새 버전으로 업데이트하는 중이에요. 잠시만 기다려 주세요.",
        "err.shutting_down": "프로그램이 종료 중이에요. 다시 실행해 주세요.",
        "err.needs_confirm": "확인이 필요해요.",
        "err.game_running": "게임이 실행 중이에요. 게임을 완전히 끈 뒤 다시 시도해 주세요.",
        "err.no_file_name": "파일 이름이 없어요.",
        "err.upload_incomplete": "파일을 끝까지 받지 못했어요. 다시 시도해 주세요.",
        "err.set_game_folder": "{problem} 설정에서 게임 폴더를 지정해 주세요.",
        "err.settings_save_failed": "설정을 저장하지 못했어요: {detail}",
        "err.dialog_open": "폴더 선택 창이 이미 열려 있어요.",
        "dialog.pick_game_folder": "Helldivers 2 설치 폴더 선택",
        "err.folder_missing": "열 폴더가 없어요.",
        # 앱 업데이트
        "err.already_updating": "이미 업데이트하는 중이에요.",
        "err.busy_try_later": "다른 작업이 진행 중이에요. 끝난 뒤 다시 시도해 주세요.",
        "err.already_latest": "이미 최신 버전이에요.",
        "err.update_cancelled": "창을 닫아서 업데이트를 취소했어요.",
        "err.update_check_failed": "새 버전을 확인하지 못했어요. 인터넷 연결을 확인해 주세요.",
        "err.update_info_invalid": "새 버전 정보를 읽지 못했어요.",
        "update.only_exe": "exe로 실행할 때만 자동 업데이트할 수 있어요.",
        "update.no_asset": "이 릴리즈에는 자동 업데이트용 파일 정보가 없어요.",
        "err.update_no_write": "이 폴더에는 새 버전을 저장할 수 없어요. 릴리즈 페이지에서 직접 받아 주세요.",
        "err.update_download_failed": "새 버전을 내려받지 못했어요. 인터넷 연결을 확인해 주세요.",
        "err.update_bad_file": "내려받은 파일이 올바르지 않아요(검사값 불일치). 잠시 후 다시 시도해 주세요.",
        # 시작
        "startup.check_failed": "실행 중인 모드 매니저를 확인하지 못했어요.\n\n{detail}",
        "startup.not_responding": "실행 중인 모드 매니저가 응답하지 않아요. 잠시 후 다시 실행해 주세요.",
        "startup.legacy_running": "이전 버전(HD2ModManager)이 실행 중이라 설정을 옮기지 못했어요.\n이전 버전 창을 닫고 다시 실행해 주세요.",
        "startup.data_dir_failed": "모드 보관 폴더를 만들 수 없어요:\n{path}\n\n{detail}",
        "startup.failed": "모드 매니저를 시작하지 못했어요.\n\n{detail}",
        "startup.no_port": "사용할 수 있는 포트가 없어요.",
    },
    "en": {
        "option.default": "Option {n}",
        "suboption.default": "Choice {n}",
        "err.manifest_invalid": "manifest.json is not valid.",
        "err.manifest_invalid_detail": "manifest.json is not valid: {detail}",
        "err.zip_broken": "The archive is damaged or is not a valid zip file.",
        "err.need_7zip": "7-Zip is needed to extract {ext} files. Install 7-Zip or download the mod as a .zip.",
        "err.extract_failed": "Could not extract the archive.{detail}",
        "err.extract_error": "An error occurred while extracting: {detail}",
        "err.archive_types": "Only .zip, .7z and .rar archives can be added.",
        "err.no_patch_files": "No Helldivers 2 mod files (.patch_0 etc.) were found in this archive.",
        "err.mod_folder_locked": "Could not replace the existing mod files. If a file in this mod's folder is open in "
                                 "another program, close it and try again. ({detail})",
        "err.store_failed": "Could not save the mod to the library: {detail}",
        "err.mod_not_found": "That mod could not be found. Please refresh.",
        "err.order_changed": "The mod list has changed. Please refresh and try again.",
        "backup.file_name": "About this backup.txt",
        "backup.text": "The mod manager moved these mod files here from the game's data folder before applying.\n"
                       "Original location: {path}\nTo use them again, copy these files back to that location.\n",
        "err.backup_failed": "Could not move the existing mod files to the backup folder: {detail}",
        "err.remove_previous_failed": "Could not remove the previously installed files. Make sure the game is fully closed and try again.",
        "err.no_write_permission": "No permission to write to the game folder. Close the game, and if it still fails, "
                                   "try running Modocracy as administrator.",
        "err.copy_failed": "An error occurred while copying files: {detail}",
        "err.remove_some_failed": "Some files could not be removed. Make sure the game is fully closed and try again.",
        "issue.no_files": "The selected options don't include any files to install. Please check the options.",
        "issue.at_least": " ({revision} or later)",
        "issue.get_from": " Get it from: {url}",
        "issue.optional_requirement": "‘{name}’{need} is only needed for some features{purpose}. "
                                      "You don't need it if you don't use them.{where}",
        "issue.requirement_missing": "This mod requires ‘{name}’{need}. Download it separately and add it to the list.{where}",
        "issue.requirement_disabled": "The required mod ‘{name}’ is turned off. Please turn it on.",
        "issue.requirement_outdated": "‘{name}’ needs to be updated to {revision} or later.",
        "issue.loader_last": "A shared loader must be at the bottom of the list to load the other mods correctly.",
        "issue.duplicate": "The same mod is turned on twice. Keep only one of them on.",
        "issue.older_game": "This mod was made for game version {mod} (your game: {game}). "
                            "It usually still works, but if you run into problems, check for a newer version.",
        "issue.newer_game": "This mod is for a newer game version {mod} (your game: {game}). Please update the game.",
        "game.not_set": "The game folder hasn't been set yet.",
        "game.missing": "The selected game folder doesn't exist.",
        "game.not_hd2": "This doesn't look like a Helldivers 2 folder (there is no data folder).",
        "err.request_too_large": "The request is too large.",
        "err.bad_request": "Invalid request.",
        "err.unknown": "An unknown error occurred. Please check the log file.",
        "err.updating": "Updating to the new version. Please wait a moment.",
        "err.shutting_down": "The app is shutting down. Please start it again.",
        "err.needs_confirm": "Confirmation needed.",
        "err.game_running": "The game is running. Close it completely and try again.",
        "err.no_file_name": "The file has no name.",
        "err.upload_incomplete": "The file wasn't received completely. Please try again.",
        "err.set_game_folder": "{problem} Please set the game folder in Settings.",
        "err.settings_save_failed": "Couldn't save the settings: {detail}",
        "err.dialog_open": "A folder picker is already open.",
        "dialog.pick_game_folder": "Select the Helldivers 2 installation folder",
        "err.folder_missing": "That folder doesn't exist.",
        "err.already_updating": "An update is already in progress.",
        "err.busy_try_later": "Another task is in progress. Try again when it finishes.",
        "err.already_latest": "You already have the latest version.",
        "err.update_cancelled": "The update was cancelled because the window was closed.",
        "err.update_check_failed": "Couldn't check for a new version. Please check your internet connection.",
        "err.update_info_invalid": "Couldn't read the new version information.",
        "update.only_exe": "Automatic updates only work when running Modocracy.exe.",
        "update.no_asset": "This release has no file information for automatic updates.",
        "err.update_no_write": "The new version can't be saved in this folder. Please download it from the releases page.",
        "err.update_download_failed": "Couldn't download the new version. Please check your internet connection.",
        "err.update_bad_file": "The downloaded file is invalid (checksum mismatch). Please try again later.",
        "startup.check_failed": "Couldn't check whether Modocracy is already running.\n\n{detail}",
        "startup.not_responding": "The running Modocracy isn't responding. Please try again in a moment.",
        "startup.legacy_running": "Your settings couldn't be moved because the previous version (HD2ModManager) is running.\n"
                                  "Close its window and start Modocracy again.",
        "startup.data_dir_failed": "Couldn't create the mod library folder:\n{path}\n\n{detail}",
        "startup.failed": "Modocracy couldn't start.\n\n{detail}",
        "startup.no_port": "No free network port is available.",
    },
}

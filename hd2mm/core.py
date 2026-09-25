"""모드 라이브러리 관리와 게임 폴더 적용(설치) 로직.

게임은 data 폴더의 `<아카이브해시>.patch_<번호>` 파일을 번호 순서대로 읽고, 번호가 클수록
나중에 적용된다(겹치는 부분을 덮어씀). 여러 모드가 같은 아카이브를 고치면 번호가 겹치므로
적용할 때 모드 목록 순서(위 → 아래)대로 0, 1, 2… 번호를 새로 매긴다. 즉 아래 모드가 이긴다.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .gameinfo import CREATE_NO_WINDOW, find_7zip
from .i18n import t

PATCH_RE = re.compile(r"^([0-9a-f]{16})\.patch_(\d+)(\.gpu_resources|\.stream)?$", re.IGNORECASE)
COMPANION_SUFFIXES = (".gpu_resources", ".stream")
SETTINGS_FILE = "settings.json"
ARCHIVE_EXTS = (".zip", ".7z", ".rar")
JUNK_NAMES = {"__macosx", ".ds_store", "thumbs.db", "desktop.ini"}
GUID_RE = re.compile(r"^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$", re.IGNORECASE)
MAX_README_BYTES = 200_000
MOD_ID_RE = re.compile(r"^[0-9a-f-]{8,64}$")
SIGNATURE_VERSION = 2  # 적용 기록의 지문 형식 (1 = v1.0.0의 절대 경로 방식)


class ModError(Exception):
    """사용자에게 그대로 보여줄 수 있는 메시지를 가진 오류."""


class NeedsConfirm(Exception):
    """매니저가 설치하지 않은 패치 파일이 게임 폴더에 있어 사용자 확인이 필요함."""

    def __init__(self, unmanaged: list[dict]):
        super().__init__("unmanaged")
        self.unmanaged = unmanaged


# ---------------------------------------------------------------- 패치 파일

@dataclass
class PatchSet:
    """패치 파일 한 세트: 본 파일 + (있다면) .gpu_resources, .stream."""

    archive: str
    index: int
    main: Path
    companions: dict[str, Path] = field(default_factory=dict)

    def sources(self) -> list[tuple[str, Path | None]]:
        """(접미사, 원본 경로) 목록. 원본이 None이면 빈 파일을 만든다(게임은 세 파일을 모두 기대함)."""
        return [("", self.main)] + [(s, self.companions.get(s)) for s in COMPANION_SUFFIXES]


def scan_patch_sets(directory: Path, recursive: bool = False) -> list[PatchSet]:
    if not directory.is_dir():
        return []
    groups: dict[tuple[Path, str, int], dict[str, Path]] = {}
    entries = directory.rglob("*") if recursive else directory.iterdir()
    for entry in entries:
        match = PATCH_RE.match(entry.name)
        if not match or not entry.is_file():
            continue
        key = (entry.parent, match.group(1).lower(), int(match.group(2)))
        groups.setdefault(key, {})[(match.group(3) or "").lower()] = entry
    sets = [
        PatchSet(archive, index, files[""], {k: v for k, v in files.items() if k})
        for (_, archive, index), files in groups.items()
        if "" in files
    ]
    sets.sort(key=lambda s: (str(s.main.parent).lower(), s.archive, s.index))
    return sets


def scan_game_patch_names(data_dir: Path) -> list[str]:
    try:
        return sorted(e.name for e in data_dir.iterdir() if PATCH_RE.match(e.name) and e.is_file())
    except OSError:
        return []


# ---------------------------------------------------------------- 파일 도우미

def read_text(path: Path, limit: int | None = None) -> str:
    """텍스트 파일을 읽는다. limit이 있으면 앞부분 limit 바이트만 실제로 읽는다."""
    if limit:
        with open(path, "rb") as fh:
            data = fh.read(limit + 1)
        truncated = len(data) > limit
        data = data[:limit]
    else:
        data, truncated = path.read_bytes(), False
    return _decode(data, truncated)


def _decode(data: bytes, truncated: bool) -> str:
    """UTF-8로 읽되, 깨지는 곳이 대부분이면 한국어 윈도우 인코딩(cp949) 파일로 본다.

    UTF-8 파일에 이상한 바이트가 몇 개 섞인 정도면 그 자리만 �로 두고 나머지는 그대로 보여 준다.
    """
    text = data.decode("utf-8-sig", errors="replace")
    if truncated:
        text = text.rstrip("�")  # 잘린 끝에 걸친 글자
    broken = text.count("�")
    if not broken:
        return text
    readable = sum(1 for ch in text if ord(ch) > 127 and ch != "�")
    if readable < broken * 4:
        for cut in (0, 1) if truncated else (0,):
            try:
                return data[: len(data) - cut].decode("cp949")
            except UnicodeDecodeError:
                continue
    return text


def read_json(path: Path):
    text = read_text(path)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 모드 제작자가 흔히 남기는 주석과 끝 쉼표를 걷어내고 한 번 더 시도
        cleaned = re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)
        cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)
        return json.loads(cleaned)


def write_json(path: Path, data) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def safe_join(root: Path, rel) -> Path | None:
    """root 안쪽 경로만 허용한다 (../ 로 밖을 가리키면 None)."""
    rel = str(rel or "").replace("\\", "/").strip().strip("/")
    root_resolved = root.resolve()
    target = root_resolved if rel in ("", ".") else (root_resolved / rel).resolve()
    if target != root_resolved and root_resolved not in target.parents:
        return None
    return target


def _find_child(root: Path, name: str) -> Path | None:
    try:
        for entry in root.iterdir():
            if entry.name.lower() == name.lower() and entry.is_file():
                return entry
    except OSError:
        pass
    return None


def _get(data, key: str, default=None):
    """manifest 키를 대소문자 구분 없이 읽는다."""
    if not isinstance(data, dict):
        return default
    for k, v in data.items():
        if isinstance(k, str) and k.lower() == key.lower():
            return v
    return default


def _str_list(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value if isinstance(v, (str, int, float))]
    return []


def clean_guid(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().strip("{}").lower()
    return str(uuid.UUID(value)) if GUID_RE.match(value) else None


def version_key(text) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", str(text or "")))


# ---------------------------------------------------------------- 모드 해석

@dataclass
class ModOption:
    name: str
    description: str = ""
    image: str | None = None
    include: list[str] = field(default_factory=list)
    subs: list["ModOption"] = field(default_factory=list)


@dataclass
class ModInfo:
    root: Path
    guid: str | None
    name: str
    description: str = ""
    icon: str | None = None
    kind: str = "none"          # manifest 종류: 'v1' | 'legacy' | 'none'
    mode: str = "fixed"         # 'fixed'(선택 없음) | 'multi'(옵션 켜기/끄기) | 'single'(하나 고르기)
    base: list[str] = field(default_factory=list)   # 항상 적용되는 폴더
    options: list[ModOption] = field(default_factory=list)
    readme_file: str | None = None  # README 파일 이름 (본문은 필요할 때 read_readme로 읽는다)
    extra: dict | None = None   # "<이름>-manifest.json" 확장 정보(버전·필요 모드)

    def all_dirs(self) -> list[str]:
        dirs = list(self.base)
        for opt in self.options:
            dirs += opt.include
            for sub in opt.subs:
                dirs += sub.include
        return dirs


def _existing_file(root: Path, rel) -> str | None:
    if not isinstance(rel, str) or not rel.strip():
        return None
    target = safe_join(root, rel)
    if target is None or not target.is_file():
        return None
    return target.relative_to(root.resolve()).as_posix()


def _parse_option(root: Path, raw: dict) -> ModOption:
    # 이름이 없으면 빈 칸으로 두고, 화면에 보낼 때 그 언어로 "옵션 1" 같은 이름을 붙인다
    opt = ModOption(
        name=str(_get(raw, "Name") or "").strip(),
        description=str(_get(raw, "Description") or "").strip(),
        image=_existing_file(root, _get(raw, "Image")),
        include=_str_list(_get(raw, "Include")),
    )
    subs = _get(raw, "SubOptions")
    if isinstance(subs, list):
        opt.subs = [_parse_option(root, s) for s in subs if isinstance(s, dict)]
    return opt


def _find_readme(root: Path) -> str | None:
    try:
        files = sorted(
            (e for e in root.iterdir() if e.is_file() and e.suffix.lower() in (".txt", ".md")),
            key=lambda e: (0 if "readme" in e.name.lower() else 1, e.name.lower()),
        )
    except OSError:
        return None
    for entry in files:
        if "readme" in entry.name.lower() or "read_me" in entry.name.lower() or "설명" in entry.name:
            if not _is_blank_file(entry):
                return entry.name
    return None


def _is_blank_file(path: Path) -> bool:
    """비어 있거나 공백뿐인 파일인지. 큰 파일은 내용이 있다고 보고 읽지 않는다."""
    try:
        size = path.stat().st_size
        return size == 0 or (size < 4096 and not read_text(path).strip())
    except OSError:
        return True


def read_readme(info: ModInfo) -> str | None:
    if not info.readme_file:
        return None
    try:
        return read_text(info.root / info.readme_file, MAX_README_BYTES).strip() or None
    except OSError:
        return None


def _read_extra_manifest(root: Path) -> dict | None:
    """일부 모드가 함께 넣는 "<이름>-manifest.json" (게임 버전, 필요한 모드 정보)."""
    try:
        files = sorted(e for e in root.iterdir() if e.is_file() and e.name.lower().endswith("-manifest.json"))
    except OSError:
        return None
    for entry in files:
        try:
            data = read_json(entry)
        except (ValueError, OSError):
            continue
        if not isinstance(data, dict) or not isinstance(data.get("name"), str):
            continue
        requires = []
        for req in data.get("requires") or []:
            if isinstance(req, dict) and isinstance(req.get("name"), str):
                required_for = str(req.get("required_for") or "").strip()
                requires.append({
                    "name": req["name"],
                    "revision": str(req.get("revision") or ""),
                    "guid": clean_guid(req.get("guid")),
                    # required_for가 있으면 모드 전체가 아니라 그 기능에만 필요한 것 (예: 단축키 바꾸기)
                    "requiredFor": required_for,
                    "optional": bool(req.get("optional")) or bool(required_for),
                    "repository": str(req.get("repository") or "").strip(),
                })
        provides = data.get("provides")
        return {
            "name": data["name"],
            "version": str(data.get("display_version") or data.get("revision") or ""),
            "revision": str(data.get("revision") or ""),
            "exeVersion": str(data.get("exe_version") or ""),
            "requires": requires,
            "provides": sorted(provides) if isinstance(provides, dict) else [],
        }
    return None


def parse_mod(root: Path, fallback_name: str | None = None) -> ModInfo:
    manifest_path = _find_child(root, "manifest.json")
    info = ModInfo(root=root, guid=None, name=fallback_name or root.name)
    info.readme_file = _find_readme(root)
    info.extra = _read_extra_manifest(root)
    if manifest_path:
        try:
            data = read_json(manifest_path)
        except (ValueError, OSError) as exc:
            raise ModError(t("err.manifest_invalid_detail", detail=exc)) from None
        if not isinstance(data, dict):
            raise ModError(t("err.manifest_invalid"))
        info.guid = clean_guid(_get(data, "Guid"))
        info.name = str(_get(data, "Name") or "").strip() or info.name
        info.description = str(_get(data, "Description") or "").strip()
        info.icon = _existing_file(root, _get(data, "IconPath"))
        raw = _get(data, "Options")
        raw = raw if isinstance(raw, list) else []
        if raw and all(isinstance(o, str) for o in raw):
            # 옛 형식: 폴더 이름 목록 중 하나를 고른다
            info.kind, info.mode = "legacy", "single"
            info.options = [ModOption(name=o, include=[o]) for o in raw]
        elif any(isinstance(o, dict) for o in raw):
            info.kind, info.mode = "v1", "multi"
            info.options = [_parse_option(root, o) for o in raw if isinstance(o, dict)]
        else:
            info.kind = "v1" if _get(data, "Version") else "legacy"
    if len(info.options) == 1 and not info.options[0].subs:
        # 옵션이 하나뿐이면 고를 것이 없으니 항상 적용
        info.base, info.options, info.mode = info.options[0].include, [], "fixed"
    if not info.options and not info.base:
        _auto_layout(info)
    if info.icon is None:
        info.icon = next((o.image for o in info.options if o.image), None) or _guess_image(root)
    return info


def _is_shared_loader(info: ModInfo) -> bool:
    return "shared_loader_api" in (info.extra or {}).get("provides", [])


def _auto_layout(info: ModInfo) -> None:
    """manifest가 없을 때: 패치 파일이 있는 폴더를 찾아 구성한다."""
    root = info.root
    if scan_patch_sets(root):
        info.base, info.mode = ["."], "fixed"
        return
    parents = sorted({s.main.parent for s in scan_patch_sets(root, recursive=True)}, key=lambda p: str(p).lower())
    rels = [p.relative_to(root).as_posix() for p in parents]
    if len(rels) == 1:
        info.base, info.mode = rels, "fixed"
    elif rels:
        info.mode = "single"
        info.options = [ModOption(name=r, include=[r]) for r in rels]


def _guess_image(root: Path) -> str | None:
    try:
        for entry in sorted(root.iterdir()):
            if entry.is_file() and entry.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                return entry.name
    except OSError:
        pass
    return None


def normalize_state(info: ModInfo, state: dict | None) -> dict:
    state = state if isinstance(state, dict) else {}
    n = len(info.options)
    enabled = state.get("enabledOptions") if isinstance(state.get("enabledOptions"), list) else []
    subs = state.get("selectedSubs") if isinstance(state.get("selectedSubs"), list) else []
    result = {
        "enabledOptions": [bool(enabled[i]) if i < len(enabled) else True for i in range(n)],
        "selectedSubs": [],
        "choice": 0,
    }
    if info.mode == "multi" and n == 1:
        result["enabledOptions"] = [True]
    for i, opt in enumerate(info.options):
        value = subs[i] if i < len(subs) and isinstance(subs[i], int) else 0
        result["selectedSubs"].append(value if 0 <= value < len(opt.subs) else 0)
    choice = state.get("choice")
    if isinstance(choice, int) and 0 <= choice < n:
        result["choice"] = choice
    return result


def selected_dirs(info: ModInfo, state: dict) -> list[str]:
    dirs = list(info.base)
    if info.mode == "multi":
        for i, opt in enumerate(info.options):
            if not state["enabledOptions"][i]:
                continue
            dirs += opt.include
            if opt.subs:
                dirs += opt.subs[state["selectedSubs"][i]].include
    elif info.mode == "single" and info.options:
        dirs += info.options[state["choice"]].include
    return dirs


def _patch_sets_for(root: Path, dirs: list[str]) -> list[PatchSet]:
    seen: set[Path] = set()
    result = []
    for rel in dirs:
        directory = safe_join(root, rel)
        if directory is None:
            continue
        for ps in scan_patch_sets(directory):
            if ps.main not in seen:
                seen.add(ps.main)
                result.append(ps)
    return result


def resolve_patch_sets(info: ModInfo, state: dict) -> list[PatchSet]:
    return _patch_sets_for(info.root, selected_dirs(info, state))


# ---------------------------------------------------------------- 압축 풀기

def extract_archive(archive: Path, dest: Path, ext: str) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if ext == ".zip":
        try:
            zf = zipfile.ZipFile(archive)
        except zipfile.BadZipFile:
            raise ModError(t("err.zip_broken")) from None
        with zf:
            for member in zf.infolist():
                name = member.filename.replace("\\", "/")
                parts = [p for p in name.split("/") if p not in ("", ".")]
                if not parts or ".." in parts or any(":" in p for p in parts):
                    continue  # 폴더 밖으로 나가는 위험한 경로는 건너뜀
                target = dest.joinpath(*parts)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out, 1024 * 1024)
        return
    seven_zip = find_7zip()
    if not seven_zip:
        raise ModError(t("err.need_7zip", ext=ext))
    result = subprocess.run(
        [seven_zip, "x", "-y", "-bso0", "-bsp0", f"-o{dest}", str(archive)],
        capture_output=True, text=True, errors="ignore", creationflags=CREATE_NO_WINDOW,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise ModError(t("err.extract_failed", detail=f" ({detail[-1]})" if detail else ""))


def find_mod_root(staging: Path) -> Path:
    """압축 안에 폴더가 한 겹 더 감싸져 있으면 안으로 들어간다."""
    root = staging
    for _ in range(6):
        if _find_child(root, "manifest.json") or scan_patch_sets(root):
            return root
        dirs = [e for e in root.iterdir() if e.is_dir() and e.name.lower() not in JUNK_NAMES]
        if len(dirs) != 1:
            return root
        root = dirs[0]
    return root


# ---------------------------------------------------------------- 라이브러리

@dataclass
class ModSnapshot:
    entry: dict
    info: ModInfo | None
    error: str | None
    state: dict
    sets: list[PatchSet]

    @property
    def id(self) -> str:
        return self.entry["id"]

    @property
    def enabled(self) -> bool:
        return bool(self.entry.get("enabled")) and self.info is not None


@dataclass
class PlanItem:
    mod_id: str
    mod_name: str
    patch: PatchSet
    target: str  # 예: 9ba626afa44a3aa3.patch_1
    root: Path   # 모드 폴더 (서명에는 이 폴더 기준 상대 경로를 쓴다)


def build_plan(snapshot: list[ModSnapshot]) -> list[PlanItem]:
    counters: dict[str, int] = {}
    plan = []
    for snap in snapshot:
        if not snap.enabled:
            continue
        root = snap.info.root.resolve()
        for ps in snap.sets:
            number = counters.get(ps.archive, 0)
            counters[ps.archive] = number + 1
            plan.append(PlanItem(snap.id, snap.info.name, ps, f"{ps.archive}.patch_{number}", root))
    return plan


def _signature(plan: list[PlanItem], describe) -> str:
    digest = hashlib.sha256()
    for item in plan:
        for suffix, src in item.patch.sources():
            try:
                stat = src.stat() if src else None
            except OSError:
                stat = None
            size, mtime = (stat.st_size, stat.st_mtime_ns) if stat else (0, 0)
            digest.update(f"{item.target}{suffix}|{describe(item, src)}|{size}|{mtime}\n".encode("utf-8"))
    return digest.hexdigest()


def _relative_source(item: PlanItem, src: Path | None) -> str:
    try:
        rel = src.relative_to(item.root).as_posix() if src else ""
    except ValueError:
        rel = src.name
    return f"{item.mod_id}/{rel}"


def plan_signature(plan: list[PlanItem]) -> str:
    """적용 내용의 지문. 보관 폴더를 옮겨도 바뀌지 않도록 모드 ID와 상대 경로만 쓴다."""
    return _signature(plan, _relative_source)


def legacy_plan_signature(plan: list[PlanItem]) -> str:
    """v1.0.0의 지문(절대 경로 사용). 그 버전으로 적용한 기록을 알아보는 데만 쓴다."""
    return _signature(plan, lambda item, src: str(src))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mtime_ns(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def _tree_stamp(root: Path) -> tuple:
    """모드 폴더가 바뀌었는지 가려내는 값.

    하위 폴더까지 모든 폴더의 수정 시각(안에 파일·폴더가 생기거나 없어지면 바뀜)과
    최상위 .json 파일(manifest, "<이름>-manifest.json")의 수정 시각을 모은다.
    """
    stamp = [("", mtime_ns(root))]
    folders = [(str(root), "")]
    while folders:
        folder, rel = folders.pop()
        try:
            with os.scandir(folder) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError:
            continue
        for entry in entries:
            try:
                # 목록을 읽을 때 함께 받은 정보를 쓰므로 폴더마다 따로 조회하지 않는다 (Windows)
                if entry.is_dir(follow_symlinks=False):
                    sub = f"{rel}/{entry.name}"
                    stamp.append((sub, entry.stat(follow_symlinks=False).st_mtime_ns))
                    folders.append((entry.path, sub))
                elif not rel and entry.name.lower().endswith(".json"):
                    stamp.append((entry.name, entry.stat(follow_symlinks=False).st_mtime_ns))
            except OSError:
                continue
    return tuple(stamp)


def _record_key(game_path) -> str:
    """같은 폴더면 표기(대소문자·구분자)가 달라도 같은 값."""
    return os.path.normcase(os.path.abspath(str(game_path)))


class Library:
    """모드 보관함(압축을 푼 모드들)과 설정, 게임에 적용한 기록을 관리한다."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.mods_dir = data_dir / "mods"
        self.backups_dir = data_dir / "backups"
        self.tmp_dir = data_dir / "tmp"
        self.settings_path = data_dir / SETTINGS_FILE
        self.record_path = data_dir / "deployed.json"
        for directory in (self.mods_dir, self.backups_dir, self.tmp_dir):
            directory.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        self.tmp_dir.mkdir(exist_ok=True)
        self.settings = self._load_settings()
        self._info_cache: dict[str, tuple[tuple, ModInfo]] = {}

    # ---- 설정

    def _load_settings(self) -> dict:
        settings = {"version": 1, "gamePath": None, "mods": []}
        if self.settings_path.exists():
            try:
                loaded = read_json(self.settings_path)
                if isinstance(loaded, dict):
                    settings.update(loaded)
            except (ValueError, OSError):
                broken = self.settings_path.with_name(f"settings.broken-{datetime.now():%Y%m%d-%H%M%S}.json")
                shutil.copyfile(self.settings_path, broken)
        mods = [
            m for m in settings.get("mods") or []
            if isinstance(m, dict) and isinstance(m.get("id"), str) and MOD_ID_RE.match(m["id"])
        ]
        settings["mods"] = [m for m in mods if (self.mods_dir / m["id"]).is_dir()]
        return settings

    def save(self) -> None:
        write_json(self.settings_path, self.settings)

    @property
    def game_path(self) -> str | None:
        return self.settings.get("gamePath")

    def update_settings(self, changes: dict) -> None:
        """설정 값을 바꾸고 저장한다. 저장에 실패하면 바꾸기 전으로 되돌린다 (화면과 파일이 어긋나지 않게)."""
        before = dict(self.settings)
        self.settings.update(changes)
        try:
            self.save()
        except OSError:
            self.settings.clear()
            self.settings.update(before)
            raise

    def set_game_path(self, path: str | None) -> None:
        self.update_settings({"gamePath": path})

    def _entry(self, mod_id: str) -> dict:
        for entry in self.settings["mods"]:
            if entry["id"] == mod_id:
                return entry
        raise ModError(t("err.mod_not_found"))

    def mod_dir(self, mod_id: str) -> Path:
        return self.mods_dir / self._entry(mod_id)["id"]

    # ---- 모드 정보

    def info(self, entry: dict) -> ModInfo:
        """모드 정보를 읽는다. 모드 폴더 구조와 설정 파일이 그대로면 전에 읽은 결과를 다시 쓴다."""
        root = self.mods_dir / entry["id"]
        stamp = (_tree_stamp(root), entry.get("fallbackName"))
        cached = self._info_cache.get(entry["id"])
        if cached and cached[0] == stamp:
            return cached[1]
        info = parse_mod(root, entry.get("fallbackName"))
        self._info_cache[entry["id"]] = (stamp, info)
        return info

    def readme(self, mod_id: str) -> str | None:
        return read_readme(self.info(self._entry(mod_id)))

    def snapshot(self) -> list[ModSnapshot]:
        result = []
        for entry in self.settings["mods"]:
            try:
                info = self.info(entry)
                state = normalize_state(info, entry.get("state"))
                result.append(ModSnapshot(entry, info, None, state, resolve_patch_sets(info, state)))
            except (ModError, OSError) as exc:
                result.append(ModSnapshot(entry, None, str(exc), {}, []))
        return result

    # ---- 추가 / 삭제 / 순서 / 옵션

    def import_archive(self, archive: Path, original_name: str) -> dict:
        ext = Path(original_name).suffix.lower()
        if ext not in ARCHIVE_EXTS:
            raise ModError(t("err.archive_types"))
        fallback_name = Path(original_name).stem
        staging = self.tmp_dir / f"import-{uuid.uuid4().hex}"
        try:
            try:
                extract_archive(archive, staging, ext)
            except OSError as exc:
                raise ModError(t("err.extract_error", detail=exc)) from None
            root = find_mod_root(staging)
            info = parse_mod(root, fallback_name)
            if not _patch_sets_for(root, info.all_dirs()):
                raise ModError(t("err.no_patch_files"))
            mod_id = info.guid or uuid.uuid4().hex
            existing = next((m for m in self.settings["mods"] if clean_guid(m["id"]) == clean_guid(mod_id)), None)
            if existing:
                mod_id = existing["id"]
            dest = self.mods_dir / mod_id
            previous_name = None
            if existing:
                try:
                    previous_name = self.info(existing).name
                except (ModError, OSError):
                    pass
            old = None
            if dest.exists():
                old = self.tmp_dir / f"old-{uuid.uuid4().hex}"
                try:
                    os.replace(dest, old)
                except OSError as exc:
                    raise ModError(t("err.mod_folder_locked", detail=exc)) from None
            self._info_cache.pop(mod_id, None)
            try:
                shutil.move(str(root), str(dest))
            except OSError as exc:
                if old is not None:
                    shutil.rmtree(dest, ignore_errors=True)
                    os.replace(old, dest)
                raise ModError(t("err.store_failed", detail=exc)) from None
            if old is not None:
                shutil.rmtree(old, ignore_errors=True)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

        now = datetime.now().isoformat(timespec="seconds")
        if existing:
            # 같은 모드(같은 GUID)의 새 버전: 순서와 켜짐 상태는 유지
            existing.update({"sourceName": original_name, "fallbackName": fallback_name, "updatedAt": now})
            new_info = self.info(existing)
            if len(new_info.options) != len((existing.get("state") or {}).get("enabledOptions") or []):
                existing["state"] = None
        else:
            self.settings["mods"].insert(self._new_mod_position(info), {
                "id": mod_id, "enabled": True, "state": None,
                "sourceName": original_name, "fallbackName": fallback_name, "addedAt": now,
            })
        self.save()
        return {"id": mod_id, "name": info.name, "updated": existing is not None, "previousName": previous_name}

    def _new_mod_position(self, info: ModInfo) -> int:
        """새 모드는 맨 아래에 넣되, 맨 아래가 공유 로더면 그 바로 위에 넣는다 (로더는 마지막이어야 함)."""
        mods = self.settings["mods"]
        if not mods or _is_shared_loader(info):
            return len(mods)
        last = mods[-1]
        try:
            if _is_shared_loader(self.info(last)):
                return len(mods) - 1
        except (ModError, OSError):
            pass
        return len(mods)

    def remove(self, mod_id: str) -> None:
        entry = self._entry(mod_id)
        self.settings["mods"].remove(entry)
        self.save()
        self._info_cache.pop(entry["id"], None)
        shutil.rmtree(self.mods_dir / entry["id"], ignore_errors=True)

    def reorder(self, ids: list[str]) -> None:
        current = {m["id"]: m for m in self.settings["mods"]}
        if sorted(ids) != sorted(current):
            raise ModError(t("err.order_changed"))
        self.settings["mods"] = [current[i] for i in ids]
        self.save()

    def update(self, mod_id: str, changes: dict) -> None:
        entry = self._entry(mod_id)
        if "enabled" in changes:
            entry["enabled"] = bool(changes["enabled"])
        state_keys = {"enabledOptions", "selectedSubs", "choice"}
        if state_keys & set(changes):
            info = self.info(entry)
            state = normalize_state(info, entry.get("state"))
            for key in state_keys & set(changes):
                state[key] = changes[key]
            entry["state"] = normalize_state(info, state)
        self.save()

    # ---- 게임 폴더 상태

    def load_records(self) -> dict[str, dict]:
        """게임 폴더별 적용 기록. 폴더를 바꿔도 이전 폴더에 설치한 파일을 놓치지 않도록 따로 보관한다."""
        if not self.record_path.exists():
            return {}
        try:
            data = read_json(self.record_path)
        except (ValueError, OSError):
            return {}
        if not isinstance(data, dict):
            return {}
        if isinstance(data.get("records"), dict):
            return {k: v for k, v in data["records"].items() if isinstance(v, dict) and v.get("gamePath")}
        if data.get("gamePath"):  # 예전 형식: 기록이 하나뿐
            return {_record_key(data["gamePath"]): data}
        return {}

    def _load_record(self, game_path: Path) -> dict | None:
        return self.load_records().get(_record_key(game_path))

    def _write_record(self, game_path: Path, record: dict) -> None:
        records = self.load_records()
        records[_record_key(game_path)] = record
        # 설치한 파일이 하나도 없는 기록(모두 제거한 폴더, 잘못 입력했던 경로 등)은 남기지 않는다
        records = {key: value for key, value in records.items() if value.get("files")}
        write_json(self.record_path, {"version": 2, "records": records})

    def _save_record(self, game_path: Path, files: list[dict], signature: str | None, mods: list[dict]) -> None:
        self._write_record(game_path, {
            "gamePath": str(game_path),
            "deployedAt": datetime.now().isoformat(timespec="seconds"),
            "signature": signature,
            "sigVersion": SIGNATURE_VERSION,
            "files": files,
            "mods": mods,
        })

    def other_deployments(self, game_path: Path | None, records: dict | None = None) -> list[dict]:
        """지금 설정된 곳이 아닌 게임 폴더에 이 매니저가 설치해 두고 아직 남아 있는 파일 수."""
        current = _record_key(game_path) if game_path else None
        result = []
        for key, record in (self.load_records() if records is None else records).items():
            if key == current:
                continue
            data_dir = Path(record["gamePath"]) / "data"
            left = [
                f for f in record.get("files") or []
                if isinstance(f, dict) and "name" in f and self._matches_record(data_dir / f["name"], f)
            ]
            if left:
                result.append({"gamePath": record["gamePath"], "files": len(left)})
        return result

    def _signature_matches(self, game_path: Path, record: dict, plan: list[PlanItem]) -> bool:
        saved = record.get("signature")
        current = plan_signature(plan)
        if saved == current:
            return True
        # 지문 형식 표시가 없는 기록은 v1.0.0이 남긴 것: 예전 방식으로 한 번 비교해 보고 같으면 새 형식으로 바꿔 둔다
        if saved and "sigVersion" not in record and saved == legacy_plan_signature(plan):
            self._write_record(game_path, {**record, "signature": current, "sigVersion": SIGNATURE_VERSION})
            return True
        return False

    def status(self, game_path: Path, snapshot: list[ModSnapshot], records: dict | None = None) -> dict:
        data_dir = game_path / "data"
        plan = build_plan(snapshot)
        records = self.load_records() if records is None else records
        record = records.get(_record_key(game_path)) or {}
        recorded = {f["name"].lower(): f for f in record.get("files") or [] if isinstance(f, dict) and "name" in f}
        present = scan_game_patch_names(data_dir)
        managed = {name for name, info in recorded.items() if self._matches_record(data_dir / info["name"], info)}
        unmanaged = [n for n in present if n.lower() not in managed]
        missing = [info["name"] for name, info in recorded.items() if name not in managed]
        if recorded:
            if missing:
                state = "broken"
            elif not self._signature_matches(game_path, record, plan):
                state = "dirty"
            else:
                state = "ok"
        else:
            state = "pending" if plan else "empty"
        return {
            "state": state,
            "deployedAt": record.get("deployedAt") if recorded else None,
            "deployedFiles": len(recorded),
            "deployedMods": len(record.get("mods") or []) if recorded else 0,
            "planFiles": len(plan) * 3,
            "planTargets": {f"{i.mod_id}|{i.patch.main}": i.target for i in plan},
            "missing": missing,
            "unmanaged": unmanaged,
        }

    def describe_unmanaged(self, data_dir: Path, names: list[str], snapshot: list[ModSnapshot]) -> list[dict]:
        """모르는 패치 파일을 묶어서 보여 주고, 보관함의 모드와 같은 파일이면 알려 준다."""
        library: dict[int, list[tuple[Path, str]]] = {}
        for snap in snapshot:
            if not snap.info:
                continue
            for ps in _patch_sets_for(snap.info.root, snap.info.all_dirs()):
                try:
                    library.setdefault(ps.main.stat().st_size, []).append((ps.main, snap.info.name))
                except OSError:
                    continue
        digests: dict[Path, str] = {}

        def digest_of(path: Path) -> str:
            if path not in digests:
                digests[path] = _sha256(path)
            return digests[path]

        groups: dict[str, dict] = {}
        for name in names:
            match = PATCH_RE.match(name)
            base = name[: len(name) - len(match.group(3) or "")] if match else name
            group = groups.setdefault(base.lower(), {"name": base, "files": [], "size": 0, "match": None})
            group["files"].append(name)
            if match and not match.group(3):
                path = data_dir / name
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                group["size"] = size
                candidates = library.get(size, [])
                if candidates:
                    digest = digest_of(path)
                    group["match"] = next((mod for p, mod in candidates if digest_of(p) == digest), None)
        return sorted(groups.values(), key=lambda g: g["name"].lower())

    # ---- 적용 / 제거

    def _backup(self, data_dir: Path, names: list[str]) -> Path:
        dest = self.backups_dir / datetime.now().strftime("%Y%m%d-%H%M%S")
        suffix = 1
        while dest.exists():
            suffix += 1
            dest = self.backups_dir / f"{datetime.now():%Y%m%d-%H%M%S}-{suffix}"
        dest.mkdir(parents=True)
        for name in names:
            shutil.move(str(data_dir / name), str(dest / name))
        (dest / t("backup.file_name")).write_text(t("backup.text", path=data_dir), encoding="utf-8")
        return dest

    @staticmethod
    def _matches_record(path: Path, info: dict) -> bool:
        try:
            stat = path.stat()
            return stat.st_size == info.get("size") and ("mtime" not in info or stat.st_mtime_ns == info["mtime"])
        except OSError:
            return False

    def _prepare(self, game_path: Path, snapshot: list[ModSnapshot], unmanaged_mode: str):
        data_dir = game_path / "data"
        for temp in data_dir.glob("*.hd2mm-tmp"):
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass  # 지난번에 남은 임시 파일 정리는 할 수 있을 때만 한다 (게임은 이 이름을 읽지 않음)
        record = self._load_record(game_path) or {}
        recorded = {f["name"].lower(): f for f in record.get("files") or [] if isinstance(f, dict) and "name" in f}
        recorded = {name: info for name, info in recorded.items() if self._matches_record(data_dir / info["name"], info)}
        present = scan_game_patch_names(data_dir)
        unmanaged = [n for n in present if n.lower() not in recorded]
        if unmanaged and unmanaged_mode == "ask":
            raise NeedsConfirm(self.describe_unmanaged(data_dir, unmanaged, snapshot))
        backup = None
        if unmanaged and unmanaged_mode == "move":
            try:
                backup = self._backup(data_dir, unmanaged)
            except OSError as exc:
                raise ModError(t("err.backup_failed", detail=exc)) from None
        return data_dir, recorded, present, backup

    def _remove_recorded(self, data_dir: Path, recorded: dict, present: list[str]) -> list[dict]:
        """이전에 설치한 파일을 지우고, 지우지 못한 파일 목록을 돌려준다."""
        leftovers = []
        for name in present:
            info = recorded.get(name.lower())
            if not info:
                continue
            try:
                (data_dir / name).unlink()
            except FileNotFoundError:
                pass
            except OSError:
                leftovers.append(info)
        return leftovers

    def deploy(self, game_path: Path, unmanaged_mode: str = "ask") -> dict:
        snapshot = self.snapshot()
        plan = build_plan(snapshot)
        data_dir, recorded, present, backup = self._prepare(game_path, snapshot, unmanaged_mode)
        leftovers = self._remove_recorded(data_dir, recorded, present)
        if leftovers:
            self._save_record(game_path, leftovers, None, [])
            raise ModError(t("err.remove_previous_failed"))
        written: dict[str, dict] = {}
        mods: dict[str, dict] = {}
        complete = False
        try:
            for item in plan:
                for suffix, src in item.patch.sources():
                    dst = data_dir / (item.target + suffix)
                    temp = dst.with_name(dst.name + ".hd2mm-tmp")
                    try:
                        if src is not None:
                            shutil.copyfile(src, temp)
                        else:
                            temp.write_bytes(b"")
                        os.replace(temp, dst)
                    finally:
                        temp.unlink(missing_ok=True)
                    stat = dst.stat()
                    written[dst.name.lower()] = {"name": dst.name, "size": stat.st_size, "mtime": stat.st_mtime_ns}
                mods.setdefault(item.mod_id, {"id": item.mod_id, "name": item.mod_name, "targets": []})
                mods[item.mod_id]["targets"].append(item.target)
            complete = True
        except PermissionError:
            raise ModError(t("err.no_write_permission")) from None
        except OSError as exc:
            raise ModError(t("err.copy_failed", detail=exc)) from None
        finally:
            signature = plan_signature(plan) if complete else None
            self._save_record(game_path, list(written.values()), signature, list(mods.values()))
        return {
            "modCount": len(mods),
            "fileCount": len(written),
            "backup": str(backup) if backup else None,
        }

    def purge(self, game_path: Path, unmanaged_mode: str = "ask") -> dict:
        snapshot = self.snapshot()
        data_dir, recorded, present, backup = self._prepare(game_path, snapshot, unmanaged_mode)
        removed = sum(1 for n in present if n.lower() in recorded)
        leftovers = self._remove_recorded(data_dir, recorded, present)
        self._save_record(game_path, leftovers, None, [])
        if leftovers:
            raise ModError(t("err.remove_some_failed"))
        return {"removed": removed - len(leftovers), "backup": str(backup) if backup else None}


# ---------------------------------------------------------------- 점검

def _feature_turned_off(snap: ModSnapshot, required_for: str) -> bool:
    """required_for에 적힌 기능이 이 모드의 옵션 이름이고, 그 옵션이 꺼져 있으면 True."""
    info, text = snap.info, required_for.lower()
    if info.mode != "multi":
        return False
    for i, opt in enumerate(info.options):
        if len(opt.name) >= 4 and opt.name.lower() in text:
            return not snap.state["enabledOptions"][i]
    return False


def analyze(snapshot: list[ModSnapshot], game_version: str | None) -> dict[str, list[dict]]:
    """모드별 주의 사항: 필요한 모드 누락, 로더 위치, 게임 버전 차이, 중복."""
    issues: dict[str, list[dict]] = {s.id: [] for s in snapshot}
    enabled = [s for s in snapshot if s.enabled]
    by_name: dict[str, list[ModSnapshot]] = {}
    by_guid: dict[str, list[ModSnapshot]] = {}
    for snap in snapshot:
        if snap.info and snap.info.extra:
            by_name.setdefault(snap.info.extra["name"].lower(), []).append(snap)
        if snap.info and clean_guid(snap.id):
            by_guid.setdefault(clean_guid(snap.id), []).append(snap)
    name_count: dict[str, int] = {}
    for snap in enabled:
        key = (snap.info.extra or {}).get("name", snap.info.name).lower()
        name_count[key] = name_count.get(key, 0) + 1

    for snap in snapshot:
        if not snap.info:
            continue
        add = issues[snap.id].append
        extra = snap.info.extra or {}
        if snap.enabled and not snap.sets:
            add({"level": "warn", "text": t("issue.no_files")})
        if snap.enabled:
            for req in extra.get("requires", []):
                if req.get("requiredFor") and _feature_turned_off(snap, req["requiredFor"]):
                    continue  # 그 기능(옵션)을 꺼 두었으면 필요 없음
                found = {p.id: p for p in by_name.get(req["name"].lower(), []) + by_guid.get(req.get("guid") or "", [])}
                providers = list(found.values())
                active = [p for p in providers if p.enabled]
                revisions = [version_key(p.info.extra["revision"]) for p in active if (p.info.extra or {}).get("revision")]
                need = t("issue.at_least", revision=req["revision"]) if req["revision"] else ""
                where = t("issue.get_from", url=req["repository"]) if req.get("repository") else ""
                if req.get("optional"):
                    # 일부 기능에만 필요한 모드: 없어도 나머지는 작동하므로 안내만 한다
                    purpose = f" ({req['requiredFor']})" if req.get("requiredFor") else ""
                    if not active:
                        add({"level": "info", "text": t("issue.optional_requirement", name=req["name"], need=need,
                                                        purpose=purpose, where=where)})
                    continue
                if not providers:
                    add({"level": "error", "text": t("issue.requirement_missing", name=req["name"], need=need, where=where)})
                elif not active:
                    add({"level": "error", "text": t("issue.requirement_disabled", name=req["name"])})
                elif req["revision"] and revisions and all(r < version_key(req["revision"]) for r in revisions):
                    add({"level": "warn", "text": t("issue.requirement_outdated", name=req["name"], revision=req["revision"])})
            if _is_shared_loader(snap.info):
                mine = {ps.archive for ps in snap.sets}
                position = next(i for i, s in enumerate(enabled) if s is snap)
                if any(mine & {ps.archive for ps in later.sets} for later in enabled[position + 1:]):
                    add({
                        "level": "warn", "fix": "bottom",
                        "text": t("issue.loader_last"),
                    })
            key = extra.get("name", snap.info.name).lower()
            if name_count.get(key, 0) > 1:
                add({"level": "warn", "text": t("issue.duplicate")})
        mod_version = extra.get("exeVersion")
        if game_version and mod_version and version_key(mod_version) != version_key(game_version):
            if version_key(mod_version) < version_key(game_version):
                text = t("issue.older_game", mod=mod_version, game=game_version)
            else:
                text = t("issue.newer_game", mod=mod_version, game=game_version)
            add({"level": "info", "text": text})
    return issues

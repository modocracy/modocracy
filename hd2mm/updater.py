"""Modocracy 자체 업데이트: GitHub 최신 릴리즈를 확인하고, 새 exe를 받아 교체한 뒤 다시 켠다.

실행 중인 exe는 코드 일부를 자기 파일에서 그때그때 읽기 때문에, 켜진 채로 파일을 바꾸면 위험하다.
그래서 새 파일을 옆에 받아 두고, 이 프로그램이 완전히 끝난 뒤 작은 PowerShell 작업이 파일을
바꾸고 새 버전을 켜게 한다. 바꾸다 실패하면 원래 파일로 되돌린다.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import APP_NAME, __version__
from .core import ModError, version_key
from .gameinfo import CREATE_NO_WINDOW

REPO = "JJ-dot-eng/modocracy"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
ASSET_NAME = f"{APP_NAME}.exe"
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


@dataclass
class Release:
    version: str
    url: str                # 릴리즈 페이지
    notes: str
    asset_url: str | None   # 우리 저장소의 릴리즈 파일 주소일 때만
    size: int
    sha256: str | None      # GitHub가 알려 주는 파일 지문


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{APP_NAME}/{__version__}",
    })


def fetch_latest(timeout: float = 8) -> Release:
    try:
        with urllib.request.urlopen(_request(LATEST_API), timeout=timeout) as res:
            data = json.loads(res.read().decode("utf-8"))
    except (OSError, ValueError):
        raise ModError("새 버전을 확인하지 못했어요. 인터넷 연결을 확인해 주세요.") from None
    if not isinstance(data, dict):
        raise ModError("새 버전 정보를 읽지 못했어요.")
    asset = next((a for a in data.get("assets") or [] if isinstance(a, dict) and a.get("name") == ASSET_NAME), {})
    url = str(asset.get("browser_download_url") or "")
    digest = str(asset.get("digest") or "").lower()
    return Release(
        version=str(data.get("tag_name") or "").strip().lstrip("vV"),
        url=str(data.get("html_url") or RELEASES_PAGE),
        notes=str(data.get("body") or "")[:4000],
        asset_url=url if url.startswith(DOWNLOAD_PREFIX) else None,
        size=int(asset.get("size") or 0),
        sha256=digest[len("sha256:"):].lower() if digest.startswith("sha256:") else None,
    )


def is_newer(version: str, current: str = __version__) -> bool:
    return bool(version) and version_key(version) > version_key(current)


def current_exe() -> Path | None:
    """바꿔 끼울 실행 파일. 소스(python)로 실행 중이면 None."""
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        return Path(sys.executable).resolve()
    return None


def install_problem(release: Release) -> str | None:
    """자동 업데이트를 할 수 없는 이유. 할 수 있으면 None."""
    if current_exe() is None:
        return "exe로 실행할 때만 자동 업데이트할 수 있어요."
    if not release.asset_url or not release.sha256:
        return "이 릴리즈에는 자동 업데이트용 파일 정보가 없어요."
    return None


def download(release: Release, exe: Path, timeout: float = 60) -> Path:
    """새 exe를 현재 exe 옆에 받고 지문을 검사한다."""
    target = exe.with_name(exe.name + ".download")
    digest = hashlib.sha256()
    total = 0
    try:
        with urllib.request.urlopen(_request(release.asset_url), timeout=timeout) as res, open(target, "wb") as out:
            while chunk := res.read(1024 * 1024):
                out.write(chunk)
                digest.update(chunk)
                total += len(chunk)
    except PermissionError:
        target.unlink(missing_ok=True)
        raise ModError("이 폴더에는 새 버전을 저장할 수 없어요. 릴리즈 페이지에서 직접 받아 주세요.") from None
    except OSError:
        target.unlink(missing_ok=True)
        raise ModError("새 버전을 내려받지 못했어요. 인터넷 연결을 확인해 주세요.") from None
    with open(target, "rb") as fh:
        is_exe = fh.read(2) == b"MZ"
    if not is_exe or (release.size and total != release.size) or digest.hexdigest() != release.sha256:
        target.unlink(missing_ok=True)
        raise ModError("내려받은 파일이 올바르지 않아요(검사값 불일치). 잠시 후 다시 시도해 주세요.")
    return target


# 이 프로그램이 끝난 뒤 실행되는 교체 작업. {이름} 자리는 build_swap_script가 채운다.
SWAP_SCRIPT = """
$ErrorActionPreference = 'Stop'
$exe = '{exe}'; $new = '{new}'; $old = '{old}'; $failed = '{failed}'
$arguments = '{arguments}'
function Start-App {{ if ($arguments) {{ Start-Process -FilePath $exe -ArgumentList $arguments -PassThru }} else {{ Start-Process -FilePath $exe -PassThru }} }}

# 1) 이 프로그램이 완전히 끝날 때까지 기다린다. 끝나지 않으면 아무 파일도 건드리지 않는다.
$deadline = (Get-Date).AddSeconds({wait_seconds})
while (Get-Process -Id {pid} -ErrorAction SilentlyContinue) {{
  if ((Get-Date) -gt $deadline) {{ exit 1 }}
  Start-Sleep -Milliseconds 300
}}

# 2) exe 바꾸기. 실패하면 되돌리고 다시 시도하며, exe가 없는 상태에서는 백업을 절대 지우지 않는다.
$swapped = $false
for ($i = 0; $i -lt {retries} -and -not $swapped; $i++) {{
  try {{
    if (-not (Test-Path -LiteralPath $exe) -and (Test-Path -LiteralPath $old)) {{
      Move-Item -LiteralPath $old -Destination $exe -Force
    }}
    if (Test-Path -LiteralPath $old) {{ Remove-Item -LiteralPath $old -Force }}
    Move-Item -LiteralPath $exe -Destination $old -Force
    try {{ Move-Item -LiteralPath $new -Destination $exe -Force; $swapped = $true }}
    catch {{ Move-Item -LiteralPath $old -Destination $exe -Force; throw }}
  }} catch {{ Start-Sleep -Milliseconds 200 }}
}}
if (-not $swapped) {{
  try {{ if (-not (Test-Path -LiteralPath $exe)) {{ Move-Item -LiteralPath $old -Destination $exe -Force }} }} catch {{ }}
  try {{ Start-App | Out-Null }} catch {{ }}
  exit 2
}}

# 3) 새 버전을 켜고, 화면까지 제대로 뜨는지 본다 (새 버전은 화면이 뜨면 .old.exe를 지운다).
#    그 전에 꺼져 버리면 옛 버전으로 되돌려 다시 켠다.
$proc = Start-App
$deadline = (Get-Date).AddSeconds({verify_seconds})
while ((Get-Date) -lt $deadline) {{
  Start-Sleep -Seconds 1
  if (-not (Test-Path -LiteralPath $old)) {{ exit 0 }}
  if ($proc.HasExited) {{
    try {{
      Move-Item -LiteralPath $exe -Destination $failed -Force
      Move-Item -LiteralPath $old -Destination $exe -Force
      Remove-Item -LiteralPath $failed -Force -ErrorAction SilentlyContinue
      Start-App | Out-Null
    }} catch {{ }}
    exit 3
  }}
}}
"""

# 다시 켤 때 그대로 넘길 실행 옵션 (app.py가 채운다: --data-dir, --browser)
RESTART_ARGS: list[str] = []


def _ps_quote(text: str) -> str:
    return str(text).replace("'", "''")


def build_swap_script(exe: Path, new_file: Path, pid: int, wait_seconds: int = 3600,
                      verify_seconds: int = 30, arguments: list[str] | None = None, retries: int = 100) -> str:
    # 경로에는 큰따옴표가 들어갈 수 없으므로 빈칸이 있는 인수는 큰따옴표로 감싸면 된다
    joined = " ".join(f'"{a}"' if (" " in a or not a) else a for a in (arguments or []))
    return SWAP_SCRIPT.format(
        exe=_ps_quote(exe), new=_ps_quote(new_file), old=_ps_quote(exe.with_name(exe.stem + ".old.exe")),
        failed=_ps_quote(exe.with_name(exe.stem + ".failed.exe")), arguments=_ps_quote(joined),
        pid=int(pid), wait_seconds=int(wait_seconds), verify_seconds=int(verify_seconds), retries=int(retries),
    )


def powershell_command(script: str) -> list[str]:
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-EncodedCommand", encoded]


def schedule_swap(exe: Path, new_file: Path) -> None:
    """이 프로그램이 끝나면 exe를 새 파일로 바꾸고 다시 켜는 PowerShell 작업을 띄운다."""
    command = powershell_command(build_swap_script(exe, new_file, os.getpid(), arguments=RESTART_ARGS))
    flags = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    env = clean_environment()
    try:
        subprocess.Popen(command, creationflags=flags | CREATE_BREAKAWAY_FROM_JOB, close_fds=True, env=env)
    except OSError:
        subprocess.Popen(command, creationflags=flags, close_fds=True, env=env)


def clean_environment() -> dict[str, str]:
    """새로 켜는 exe가 이 프로그램의 임시 폴더를 물려받지 않도록 PyInstaller 표시를 지운 환경.

    그대로 넘기면 새 exe가 '이미 풀어 둔 프로그램의 자식'으로 착각해 옛 버전의 임시 폴더를 쓰고,
    옛 버전은 그 폴더를 지우지 못해 경고 창을 띄운다.
    """
    own_temp = os.path.normcase(getattr(sys, "_MEIPASS", "") or "")
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("_PYI_", "_MEIPASS"))}
    if own_temp and env.get("PATH"):
        env["PATH"] = os.pathsep.join(
            part for part in env["PATH"].split(os.pathsep) if not os.path.normcase(part).startswith(own_temp)
        )
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def cleanup_leftovers() -> None:
    """지난 업데이트가 남긴 파일(옛 exe, 받다 만 파일)을 지운다.

    새 버전의 화면이 제대로 뜬 뒤에 불러야 한다: 교체 작업은 .old.exe가 지워진 것을 보고
    새 버전이 정상으로 켜졌다고 판단한다 (그 전에 꺼지면 옛 버전으로 되돌린다).
    """
    exe = current_exe()
    if exe is None:
        return
    for leftover in (exe.with_name(exe.stem + ".old.exe"), exe.with_name(exe.name + ".download")):
        try:
            leftover.unlink(missing_ok=True)
        except OSError:
            pass

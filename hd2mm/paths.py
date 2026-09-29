"""실행 파일과 함께 두는 파일의 위치."""
from __future__ import annotations

import sys
from pathlib import Path


def log_path() -> Path:
    """exe 옆의 log.txt. 소스 실행은 프로젝트 루트에 저장한다."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "log.txt"
    return Path(__file__).resolve().parent.parent / "log.txt"

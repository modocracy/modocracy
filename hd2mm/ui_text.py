"""Qt 화면과 개발용 웹 화면이 함께 쓰는 문구 사전."""
import json
from pathlib import Path

from . import i18n

CATALOG = json.loads(Path(__file__).with_name("ui_text.json").read_text(encoding="utf-8"))


def tr(key: str, **params) -> str:
    return CATALOG[i18n.current()][key].format(**params)

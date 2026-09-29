"""Qt 작업 스레드에서 호출하는 백엔드. 웹 화면과 동일한 잠금·검증을 사용한다."""
import logging
from pathlib import Path

from .core import ModError
from .i18n import t
from .server import LOCK_FREE_POSTS, AppServer, build_state, dispatch

log = logging.getLogger(__name__)


class Backend:
    def __init__(self, server: AppServer):
        self.server = server

    def state(self):
        with self.server.lock:
            return build_state(self.server.library)

    def command(self, path: str, body: dict | None = None):
        server = self.server
        if not server.begin_operation():
            raise ModError(t("err.updating" if server.updating else "err.shutting_down"))
        try:
            log.info("작업 시작: %s", path)
            if path in LOCK_FREE_POSTS:
                result = dispatch(server, path, body or {})
            else:
                with server.lock:
                    result = dispatch(server, path, body or {})
            if result is None:
                raise ModError(t("err.bad_request"))
            log.info("작업 완료: %s", path)
            return result
        finally:
            server.end_operation()

    def import_file(self, path: Path):
        if not self.server.begin_operation():
            raise ModError(t("err.shutting_down"))
        try:
            with self.server.lock:
                result = self.server.library.import_archive(path, path.name)
            log.info("모드 추가: %s -> %s", path.name, result)
            return result
        finally:
            self.server.end_operation()

    def readme(self, mod_id: str):
        with self.server.lock:
            return self.server.library.readme(mod_id) or ""

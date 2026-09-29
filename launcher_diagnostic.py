"""분석판 진입점. 파일 이름을 바꿔도 로그 기록과 분석판 업데이트를 유지한다."""
import sys

from hd2mm.app import main

if __name__ == "__main__":
    sys.exit(main(diagnostic=True))

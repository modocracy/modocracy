# 저장소 이전에 따른 구버전 업데이트 점검

2026-09-29에 로컬 `v1.3.3` 태그의 `hd2mm/updater.py`를 `git show`로 읽고, 그 코드의 `fetch_latest()`를 실제 GitHub 응답으로 호출했다. 실행 파일 다운로드·설치는 하지 않았다. `install_problem()`은 소스 실행이라는 이유로 먼저 중단되지 않도록 `current_exe()`의 반환값만 exe 경로로 대체해 확인했다.

## 관찰 결과

| 항목 | 실제 값 |
| --- | --- |
| 구버전 API | `https://api.github.com/repos/JJ-dot-eng/modocracy/releases/latest` |
| 리디렉션 후 API | `https://api.github.com/repositories/1386861789/releases/latest` |
| 당시 최신 릴리즈 | `1.3.3` |
| 구버전 허용 접두사 | `https://github.com/JJ-dot-eng/modocracy/releases/download/` |
| 실제 다운로드 주소 | `https://github.com/modocracy/modocracy/releases/download/v1.3.3/Modocracy.exe` |
| `fetch_latest().asset_url` | `None` |
| 파일 크기 | `17519622` bytes |
| GitHub SHA-256 | `3103be14f6c2bc05fdfcd20a2b6513a5b0aa7f88f2c40aaec2b630ea645904a2` |
| `install_problem()` 한국어 | `이 릴리즈에는 자동 업데이트용 파일 정보가 없어요.` |
| `install_problem()` 영어 | `This release has no file information for automatic updates.` |

즉 파일과 SHA-256 정보가 실제로 있지만 구버전의 문자열 접두사 검사 때문에 자동 설치가 거부된다. 점검 시 최신 버전이 여전히 1.3.3이므로, 1.3.3을 실행 중인 사용자에게 새 버전 배너가 당장 뜨지는 않는다. 2.0.0 공개 후에는 이 문제가 업데이트 동작에 영향을 준다.

v1.3.3의 `web/app.js`는 `canInstall=false`이면 [업데이트]를 [받으러 가기]로 바꾸고, 이유를 버튼의 `title` 툴팁으로 넣는다. [변경 내용]과 [받으러 가기]는 모두 릴리즈 페이지를 연다. 릴리즈 본문을 앱 화면 안에 표시하는 구조는 아니다.

## 기존 사용자 안내 제안

- 다음 릴리즈 노트 맨 위에서 위 오류 문구를 그대로 인용하고, 수동 교체 3단계를 안내한다. 구버전의 두 버튼이 도달하는 페이지라 가장 직접적인 대응이다. 한·영 안내를 `docs/releases/v2.0.0.md`에 작성했다.
- 이미 공개된 1.3.3 릴리즈 본문과 저장소 README에도 같은 안내 링크를 붙이면 다음 릴리즈 전에 방문하는 사용자에게 전달할 수 있다. 기존 릴리즈 수정은 아직 수행하지 않았다.
- 구버전 exe의 툴팁이나 버튼 문구를 릴리즈 본문만 바꿔 원격으로 수정할 수는 없다. 구버전이 표시하는 기존 문구와 안내 페이지를 연결하는 방식이 현실적이다.
- 옛 저장소 이름으로 새 저장소를 만들어 우회하지 않는 편이 좋다. GitHub는 이전 이름을 다시 사용하면 기존 리디렉션을 없앨 수 있다고 설명한다. [GitHub 저장소 이름 변경 안내](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository)

## 다음 주소 변경에 대비한 검증 설계 제안 — 미구현

신뢰 대상을 owner/repo 문자열 대신 **고정한 GitHub repository ID**로 삼는 방식을 권한다. 현재 실제 리디렉션에서 확인한 ID는 `1386861789`다. 주소가 바뀌어도 같은 저장소 객체인지 검증한 다음 그 저장소의 현재 이름과 릴리즈·asset 메타데이터를 사용한다. 이번 작업에서는 기존 `DOWNLOAD_PREFIX` 검사를 변경하지 않았다.

1. 고정된 `https://api.github.com`과 repository ID에서 저장소 메타데이터를 조회한다. 반환된 `id`가 고정값과 다르면 중단한다. 이 API로 확인한 현재 `full_name`으로 릴리즈 API 주소를 구성한다. API가 제공하는 숫자 ID 경로도 통합 테스트 대상으로 삼는다.
2. 최신 릴리즈의 정확한 asset 이름(`Modocracy.exe` 또는 `Modocracy-diagnostic.exe`)을 선택한다. 해당 릴리즈 응답에서 받은 asset ID에 대한 GitHub API 다운로드 경로를 구성하거나, 검증된 현재 owner/repo와 릴리즈 tag·파일 이름에 정확히 대응하는 `browser_download_url`만 허용한다.
3. 단순 `startswith()` 대신 URL을 분해해 HTTPS, 정확한 호스트, 기본 포트, 사용자 정보 없음, 예상 저장소 경로와 tag·파일 이름을 검사한다. 문자열에 `github.com`이 포함되거나 `*.github.com`이라는 이유만으로 신뢰하지 않는다.
4. API 리디렉션은 GitHub API 호스트 내로, 파일 리디렉션은 GitHub의 릴리즈 다운로드에 필요한 명시적인 HTTPS 호스트 목록으로 제한한다. 예상 밖 호스트·HTTP 강등·과도한 리디렉션은 중단한다. 배포 전 실제 asset 다운로드 체인으로 허용 목록을 확인한다.
5. GitHub 메타데이터의 `sha256:` 뒤 64자리 16진수와 양수 파일 크기가 모두 유효할 때만 다운로드한다. 다운로드 도중 예상 크기를 넘으면 중단하고, 완료 후 SHA-256과 크기가 모두 일치해야 교체한다. 현재의 MZ 확인도 유지한다.
6. 주소 이전, 옛 이름을 다른 저장소가 재사용한 경우, 다른 저장소 ID, 유사 호스트, 다른 asset 이름, 누락/오염된 hash·size, 외부 리디렉션을 회귀 테스트로 고정한다.

저장소 삭제 후 재생성은 ID가 달라지므로 자동으로 신뢰하면 안 된다. 다른 저장소로의 이전까지 자동화하려면 앱에 넣은 공개키로 서명된 이전 정보·업데이트 매니페스트 같은 별도 신뢰 체계가 필요하다. GitHub 응답의 SHA-256은 받은 파일과 메타데이터의 일치 여부를 보장하며, 계정/저장소 권한 탈취에 대한 별도의 서명을 대신하지는 않는다.

참고: [GitHub 저장소 REST API](https://docs.github.com/en/rest/repos/repos), [릴리즈 asset API](https://docs.github.com/en/rest/releases/assets).

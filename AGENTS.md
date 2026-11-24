# 마롱이 저장소에서 일하는 법

마롱이는 동희님이 친구들을 위해 만든 AI 친구예요. 카카오톡 봇(`marong/`, `run.py`), 디스코드 DM·채널 봇(`run_discord.py`, `marong/discord_*.py`), 웹·디스코드 음성 통화(`tools/vertex_live/`, `tools/discord_voice/`), 안드로이드 앱(`apps/android/`)이 한 저장소에 있어요. 처음이면 [README.md](README.md)와 [docs/10-wbs/README.md](docs/10-wbs/README.md)부터 읽어요.

## 누가 무엇을 하나

2026-11-17 동희님 결정이에요(원문과 자리는 [docs/10-wbs/README.md](docs/10-wbs/README.md#결정)).

| 일 | 하는 쪽 |
| --- | --- |
| 설계: CORTHEX 01 도메인 ~ 09 목업(`docs/01-domain/`~`docs/08-screens/`, `api/`, `design/`, 마이그레이션 초안), 10 작업 목록(`docs/10-wbs/`), 12 시험 계획(TC) | Claude |
| 구현: 11 개발(제품 코드·시험 코드), 빌드·APK 서명, 서버 반영, 12 시험 실행 | GPT(Codex) |
| 체크포인트 통과, 구현 PR 합치기, 실제 폰 확인 | 동희님(현경님 폰은 동희님이 부탁) |

- Claude는 이 저장소에서 제품 코드와 구현 PR을 만들지 않고 서버에 반영하지 않아요. 동희님이 따로 시키면 그 말이 이겨요.
- GPT는 설계 문서를 새로 쓰지 않아요. 문서와 코드가 다르면 아래 '계약과 다를 때'를 따라요.
- 2026-11-21 16:43 KST 동희님(프로젝트 채팅): "니가 머지를 처 하라고 시발", "앞으로도 니가 머지해". Claude가 쓴 설계 PR은 검사가 통과하면 Claude가 합쳐요. 구현 PR은 따로 말씀이 없어 지금처럼 동희님이 합쳐요.

## 서명과 브라우저 일

2026-11-17 17:00 KST 동희님(프로젝트 채팅, D65): "서명 어쩌고도 자기가 알아서 하라고 해줘. 브라우저 필요하면 aside cli한테 시키던가 하라고 하고".

- APK 빌드·서명·릴리스 올리기는 GPT가 끝까지 알아서 해요. 서명 키는 동희님 노트북에만 있으니 노트북에서 빌드·서명하고, 동희님께 단계를 넘기거나 되묻지 않아요. 키 파일과 비밀번호는 Git·PR·로그·메시지에 넣지 않고 다른 기기로 옮기지 않아요.
- 앱 릴리스도 같아요. 게시 전에 `marong/changelog/app-<버전 이름>.json`을 쓰고, 게시 뒤 버전 기록(`history.json`)의 버전 이름·코드·게시 시각과 맞춰 봐요.
- 브라우저가 필요한 일(서비스 가입, 키 발급, 콘솔·스토어·로그인 앱 설정, 웹 화면 확인)은 Aside CLI에 `aside exec "<할 일>"`로 통째로 맡겨요. Aside는 화면을 하나씩 따라 하게 할 도구가 아니라 맡기면 스스로 끝까지 해요. 동희님께 클릭 단계를 넘기지 않아요.
- 돈이 드는 일(유료 가입, 충전, 도메인 구매)은 인계 절이 허락한 한도 안에서만 해요. 받은 키는 Aside Vault나 서버 비공개 설정에 두고 값을 출력하지 않아요. Aside가 막히면(CAPTCHA, 본인 확인) 무엇이 왜 막혔는지만 PR 설명에 적고 다른 일을 이어 가요.

## 구현을 시작할 때(GPT)

1. [docs/10-wbs/README.md](docs/10-wbs/README.md)의 작업 패키지(work package) 표에서 '시작 가능'인 패키지를 고르고, 그 패키지 WBS 파일 맨 위의 `## GPT 인계` 절을 끝까지 읽어요. 인계 절이 없거나 '시작 가능'이 아니면 시작하지 않아요.
2. 인계 절의 '시작 브랜치·커밋'에서 새 브랜치 `codex/<패키지 이름>`을 만들어요. `main`이나 `claude/` 브랜치에 직접 올리지 않아요.
3. 인계 절의 '읽을 것'만 ID로 찾아 읽어요(`git grep -n "SPEC-284"` 처럼). 문서 전체를 다시 요약하지 않아요.
4. TASK 순서대로 구현하고, TASK마다 그 행의 '끝 조건' 시험을 돌려 통과시켜요.
5. PR은 초안으로 열고 제목이나 설명에 TASK·SPEC ID를 적어요. 설명에는 돌린 시험 명령과 결과, 돌리지 못한 것을 나눠 적어요. `@codex review`는 달지 않아요(아래 'PR 리뷰').
6. WBS 파일의 `## 11단계 진행` 표에 TASK마다 상태·커밋·확인한 것을 적어요.

## PR 리뷰

2026-11-22 23시대 KST 동희님 결정(오랑이 항목 8, "그렇게 바꾸기"): Codex 리뷰 한도를 구현에 아끼려고 리뷰 순서를 바꿔요.

1. PR마다 리뷰는 Claude가 해요. Claude Code `/code-review`를 돌리고, 인증·권한·비밀값·외부 입력·결제가 걸린 변경이면 `/security-review`도 돌려요. 발견한 것과 처리 결과(고침, 또는 고치지 않음과 이유)를 PR 댓글로 남겨요.
2. Codex 리뷰는 병합 직전에 한 번만 받아요. 합치는 쪽이 PR에 `@codex review` 댓글을 달아요. 한도에 걸려 리뷰가 실패하면 기다리지 않고 Claude 리뷰 결과로 판단하고, 실패했다는 사실을 PR에 적어요.
3. GPT(Codex)는 PR을 열 때 Codex 리뷰를 부르지 않아요. Claude 리뷰 댓글이 오면 고치거나 이유를 답하고 보고해요.
4. Codex 자동 리뷰(chatgpt-codex-connector)는 2026-11-23 00시대 KST에 껐어요. 그 전에 붙은 자동 리뷰는 그대로 두고, 그 내용도 처리해요.
5. Codex 멘션(@ 다음에 codex)은 2번의 리뷰 요청 댓글에만 써요. PR 제목·설명·커밋 메시지·다른 댓글에 쓰면 connector가 작업 요청으로 읽고 'create an environment' 답을 달아요. 설명할 때는 멘션 없이 'Codex 리뷰'라고 써요.

## 계약과 다를 때

- 명세(SPEC)·API 계약(`api/*.openapi.yaml`)·표(마이그레이션 SQL)·화면 정의(SCR)가 구현할 기준이에요. 코드를 계약에 맞춰요.
- 오타, 빠진 필드 이름처럼 동작이 안 바뀌는 차이는 고치고 PR 설명의 '계약 손봄' 줄에 적어요.
- 동작·응답·표 모양이 바뀌어야 하면 그 TASK를 멈추고 PR 설명 맨 위 '설계 질문'에 무엇이 왜 안 되는지 적어요. 다른 TASK는 이어가도 돼요.
- 정의에 문구가 비어 있으면(예: 오류 때 짧은 말) 지어 넣지 말고 '설계 질문'에 남겨요.

## 시험

Python 3.12, 진짜 Postgres는 `pgserver`로 띄워요(카카오·디스코드·모델은 가짜).

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv -r requirements.txt -r requirements-discord.txt pgserver
.venv/bin/python tests/test_proactive.py   # 윈도는 .venv/Scripts/python
```

- 시험 파일 목록과 하는 일은 [README.md의 '시험(노트북)'](README.md)에 있어요. 바꾼 곳과 닿는 시험은 모두 돌려요.
- 통화 서버: `tools/vertex_live/test_*.py`, `tools/vertex_live/test_*.cjs`(Node).
- 앱: `apps/android/`에서 `npm ci && npm test`, 안드로이드는 Java 21과 Gradle(`./gradlew testDebugUnitTest lintDebug`). 폴더 경로에 한글이 있으면 Gradle이 막혀서 영문 경로 사본에서 빌드해요. 서명 키와 `google-services.json`은 Git에 없고 동희님 노트북에만 있어요([apps/android/README.md](apps/android/README.md)).
- 진짜 모델·진짜 결제 API를 부르는 시험은 인계 절이 허락할 때만 돌려요.
- 노트북에서 `python run.py`·`run_discord.py`를 봇 모드로 켜지 않아요. 서버 봇과 같은 토큰이라 서로 끊어 내요.

## 서버 반영(인계 절에 반영이 들어 있을 때만)

- 서버는 ssh 별칭 `ko-family` 하나예요. 반영 전 지금 서버 파일의 해시를 `main`과 비교해요. 서버가 `main`과 꼭 같지는 않아요.
- 순서: DB·파일 백업 → 마이그레이션 → 파일 → 대화·통화가 없을 때만 재시작 → 로그 5분 오류 확인. 되돌리기 스크립트를 서버 `~/marong-deploy/<날짜>-<이름>/`에 먼저 두고 경로를 PR에 적어요. 예: PR #27 브랜치의 `deploy/release-20261117-topics.py`.
- 업데이트 내역: 친구나 관리자가 알아챌 수 있는 변화를 반영하면, 반영 전에 그 PR에 `marong/changelog/<반영 폴더 이름>.json`을 더해요(형식은 [SPEC-500](docs/04-functional-spec/admin-changelog.md#2-기능-표)). 반영 때 그 파일만 서버 `/opt/marong-app/marong/changelog/`에 복사하고 되돌리기 스크립트가 그 파일을 지우게 해요. 반영 뒤 파일의 반영일(한국 시각)이 재시작 시각과 같은지 보고 PR에 적어요. 보이는 변화가 없는 반영(로그·시험·문서만)은 PR에 '업데이트 내역 없음'이라고 적어요.
- 새 기능은 끄고 켜는 설정(drop-in의 `Environment=`)으로 넣어요. 같은 변수가 `/etc/marong-discord/config`에 있으면 그쪽이 이겨요.
- 서버 시계는 UTC예요. 친구에게 보이는 시각과 하루 경계는 한국 시각으로 계산해요.
- 디스코드 봇은 `/opt/marong-discord`에서 돌지만 `WorkingDirectory`는 `/opt/marong`(옛 카톡 사본)이에요. 봇 Python으로 import를 확인할 땐 현재 폴더를 `/opt/marong-discord`로 해요.
- `/opt/marong/prompt.md`는 동희님이 직접 고친 버전이 있어요. 덮어쓰지 말고 저장소 버전·서버 버전·바꿀 버전을 3-way로 합쳐요.
- 데이터·백업 지우기는 동희님이 스레드에 직접 쓴 말이 있을 때만 해요.

## 비밀값과 개인 대화

- 키·토큰·`.env`·`/etc/marong-discord/config` 값을 Git·PR·로그·메시지에 넣지 않아요. 값을 화면에 출력하지도 않아요(`설정됨`만 확인).
- 친구 대화 원문, 이름과 묶인 기억, 사진을 시험 데이터·PR·로그에 넣지 않아요. 시험은 지어낸 대화로 해요. 로그에는 개수·결과 이름만 남겨요.
- 커밋·PR에 AI 모델 이름을 넣지 않아요.

## 하지 않는 것

- `main`에 직접 올리기, PR 합치기(동희님이 해요).
- 시험을 끄거나 건너뛰어 통과시키기.
- 인계 절에 없는 기능 더하기, 다른 패키지의 파일 고치기(겹치는 파일은 [docs/10-wbs/README.md](docs/10-wbs/README.md#겹치는-파일)를 봐요).

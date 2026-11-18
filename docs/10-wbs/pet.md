# 반려동물 서비스 작업 목록(10단계 WBS, CTX-022~025)

2026-11-17 17시대 KST 작성(Claude, corthex 0.12.1). 입력: 기능 명세 [pet.md](../04-functional-spec/pet.md)의 SPEC-310\~369와 AI-30\~36, 요구사항 [02-prd/pet.md](../02-prd/pet.md)의 REQ-330\~429, 사용자 흐름 FL-150\~168([03-user-flow](../03-user-flow/)), 표 [05-erd/pet.md](../05-erd/pet.md)와 [`marong/pet/schema.sql`](../../marong/pet/schema.sql)(TBL-140\~163, D72로 얼림), API 계약 [`api/pet.openapi.yaml`](../../api/pet.openapi.yaml) 0.1.0(API-150\~210, D72로 얼림), 화면 정의 [08-screens/pet.md](../08-screens/pet.md)(SCR-140\~162)와 목업 방향 A([design/pet-candidates.md](../../design/pet-candidates.md)), 시험 계획 [12-qa/pet.md](../12-qa/pet.md)(TC-380\~429).

## GPT 인계

- 목표: 회원이 자기 반려동물 사진 1\~3장을 올리면 마롱이 그림체의 캐릭터로 만들어 주고, 회원은 그 아이와 글과 통화로 이야기하고, 아이 시점 그림일기를 받고, 옷과 일기장을 꾸며요. 살아 있는 아이와 무지개다리를 건넌 아이(추억 모드)를 같은 무게로 다루는 공개 유료 서비스예요. 근거: 동희님 2026-11-17 사업화 연구 요청(프로젝트 파일 `marong-pet-biz-research-20261117/report.md`), D70(14:03 KST 결정 카드 Q1 '둘 다 같은 무게'), D63 ⑮\~⑰(15:15 KST: 같은 저장소의 엔진을 쓰고 공개 서비스는 새 DB·회원 로그인으로 따로, 특징표와 미리 보기 1장 무료, 가족 공유·선물·굿즈·장례 제휴·미니룸은 1차 범위 밖), D72(16:33 KST '추천대로 모두 정하기': 화면 방향 A, 02 질문 A\~D, 아래 탭 셋, 표와 API 얼리기). 원문 자리는 [README 결정](README.md#결정)과 [도메인 문서](../01-domain/pet.md).
- 시작 조건: **시작 가능**(2026-11-17 17:27 KST, D67). (1) 01~04 단계와 이 10 작업 목록, 12 시험 계획은 동희님 '모두 승인'(D66·D67)으로 체크포인트를 통과했어요. 05 표와 06 API는 D72로 얼렸어요. (2) 08 화면 정의도 통과했고 09 토큰도 얼렸어요(103개 그대로, 방향 A, D67). 화면 작업 TASK-370\~376은 캔버스에 그리지 않은 상태도 08 화면 정의와 와이어프레임대로 만들어요. (3) 다른 패키지 코드에 기대는 네 작업은 그 코드가 `main`에 합쳐진 뒤예요: TASK-352(위기 판정, 성향 TASK-221), TASK-353(친구 기억, 성향 3단계 TASK-230\~243), TASK-356(선톡 게이트, 성향 2단계 TASK-244\~252), TASK-357(일기 줄, 일기 TASK-140\~144). 그 전에는 그 작업만 멈추고 다른 작업은 이어 가요. (4) 서버 반영 TASK-377은 아래 '동희님 준비물'과, 공개 주소를 열어도 된다는 동희님 말(스레드나 PR에 직접 쓴 말) 뒤예요.
- 시작: `main` 머리에서 PR 여섯 개로 나눠요. 앞 PR이 합쳐진 뒤 다음을 시작하되, ③과 ④는 ②가 합쳐진 뒤 같이 해도 돼요(라우트 등록 파일만 늦게 합치는 쪽이 맞춰요). ① `codex/pet-core`(TASK-330\~338, 바탕·로그인·가입·한도) ② `codex/pet-create`(TASK-339\~349, 캐릭터 만들기와 결제) ③ `codex/pet-talk`(TASK-350\~364, 대화·선톡·일기·통화·추억 모드) ④ `codex/pet-decor`(TASK-365\~369, 꾸미기·충전·구독) ⑤ `codex/pet-web`(TASK-370\~376, 화면) ⑥ `codex/pet-release`(TASK-377\~378, 반영과 첫 주).
- 읽을 것: 명세 1절(공통 규칙), 그 PR의 SPEC 행, 3절(3.2 만들기 상태, 3.7 시작 값, 3.8 청약철회, 3.9 아이 지시문, 3.10 오류 코드와 글, 3.11 바깥 서비스는 모든 PR), 4절 경우의 종류, 5절의 그 AI 항목, 7절. 표는 `marong/pet/schema.sql`과 05 문서. 계약은 `api/pet.openapi.yaml`의 그 PR API ID와 `components`. 화면은 08 화면 정의 1절과 그 SCR 절, 와이어프레임 [`wireframes-pet.html`](../08-screens/wireframes-pet.html), [design/README.md](../../design/README.md) 1\~4·8절, 캔버스 [마롱이 화면 설계](https://claude.ai/artifact/CC154gunovJS3tqa8XkpZ9)의 '반려동물' 줄 A 대지(`C022-*`, 비공개라 동희님이 공유해 줘야 열려요. 못 열면 화면 정의와 design/README.md만으로 만들어요). 시험은 12 시험 계획 TC-380\~429. 이 밖의 문서는 ID로 가리킬 때만 읽어요.
- 이미 된 것: 코드는 없어요. `marong/pet/schema.sql`은 표 모양이 D72로 얼려진 첫 마이그레이션이에요(어느 DB에도 넣지 않았어요). 계약은 0.1.0(D72로 얼림)이에요. 화면은 회색 와이어프레임(상태 220개)과 네 화면의 A·B 목업뿐이에요.
- 순서: TASK 번호 순서예요. 같은 PR 안에서 `Depends on`이 끝난 작업은 같이 해도 돼요.
- 시험 환경: Python 3.12와 `pgserver`(AGENTS.md '시험'), 새 DB `marong_pet`를 시험마다 빈 DB에서 만들어요. aiohttp 시험 클라이언트로 API를 불러요. 가짜: 카카오·구글 OIDC(시험용 키로 서명한 id_token을 주는 가짜 발급자), 결제 대행과 본인확인 기관(`marong/pet/pg_fake.py`, 계약 전에는 개발도 이것으로), 모델 AI-30\~36(정해 둔 JSON·그림, 지연·오류·거절을 고름), 웹 푸시 서비스(받은 요청을 모으고 404·410을 고름), 통화 서버 내부 API(시험이 직접 부름). 얼굴 찾기는 진짜 YuNet 모델 파일을 써요(바깥 API 없음). 화면은 Playwright(Chromium, 360·430px)와 브라우저 에이전트(TC-426). 진짜 모델은 TASK-330(개발용 테스트 키, 합 3달러 이하)과 레드팀 TC-427(PR마다 1만 원 안)에서만 불러요. 1만 원 상한은 D63 ⑧의 성향 규칙을 이 패키지에도 쓰는 설계 기본값이고, 넘을 것 같으면 돌리기 전에 PR 설명의 '설계 질문'으로 여쭤요. 진짜 결제·본인인증 API는 부르지 않아요(계약 뒤 따로 인계).
- 반영: TASK-377에서만 해요. 지금 서버 기계(`ko-family`)에 새 시스템 사용자와 서비스 `marong-pet`(`run_pet.py`), 같은 Postgres의 새 DB `marong_pet`과 그 DB에만 권한이 있는 새 역할, 공개 서비스용 통화 서버 하나(지금 통화 서버 코드를 설정만 달리 띄움, 서비스 `marong-pet-call`), Cloudflare Tunnel의 새 공개 호스트(Access 없음). 켜고 끄기: `PET_SIGNUP=invite`, 결제 꺼짐(`payments_enabled=false`), `PET_MONTHLY_BUDGET_KRW`(동희님 값, 없으면 시작 거절). 지금 마롱이 서비스(`marong-discord`, 통화 서버, 카카오 봇)와 DB `marong`은 고치지도 다시 시작하지도 않아요. 되돌리기: 서버 `~/marong-deploy/<날짜>-pet/rollback.sh`(새 서비스 둘을 멈추고 끄고 터널 호스트를 끔). 새 DB와 그 데이터는 되돌릴 때 지우지 않아요.
- 하면 안 되는 것: 지금 마롱이 DB·표·프로세스 고치기(REQ-418, 같이 쓰는 엔진은 (회원, 아이) 키를 받게 감싸기만). 사진 원본·EXIF를 디스크에 쓰기(임시 파일 포함, 명세 3.3). 사람 얼굴을 가리기 전 사진을 바깥으로 보내기. 생년월일·이름·전화번호·이메일 저장하기. 로그에 사진·글·이름·아이 이름·`sub` 남기기(SPEC-366). 단가표나 허용 목록에 없는 모델 쓰기(SPEC-367). 결제 켜기(`payments on`, 동희님만)와 진짜 결제. 가격 바꾸기(3.7은 [추측] 값이고 가격 인터뷰 뒤 설계 스레드가 고침). 확률형 아이템, 할인·상점 권유 문구를 아이 말에 넣기(3.9). 토큰에 없는 색·크기, 새 글꼴·CDN을 밖에서 불러오기(design/README.md 3절). Cloudflare Access 설정 바꾸기. 친구 대화 원문·실제 반려동물 사진을 시험 데이터로 쓰기(지어낸 대본과 합성 그림, 공개 데이터셋만). `/opt/marong/prompt.md` 덮어쓰기.
- 겹치는 파일: `marong/agent.py`의 지시문 조립, `marong/graphs/memory.py`·`marong/friend_memory.py`(성향 3단계), `marong/graphs/proactive.py`(성향 2단계), `marong/diary.py`(일기 패키지)는 그 패키지가 먼저 만들고, 이 패키지는 (회원, 아이) 키로 부르는 감싸기만 `marong/pet/` 안에 둬요. 원래 파일을 고쳐야 하면 그 패키지 PR이 합쳐진 뒤 작게 고치고 PR 설명에 적어요. `tools/vertex_live/server.py`·`live_session.py`는 일기·통화 비용 패키지(TASK-156\~159, 300\~301)가 먼저 고쳐요. 이 패키지는 설정으로 켜는 공개 서비스 분기(토큰 확인·분 쓰기·고정 안내)만 더해요. `design/base.tokens.json`과 `docs/07-sitemap/sitemap.yaml`은 고치지 않아요(설계 스레드가 씀).
- 사람 확인: 첫 주 초대 회원(TASK-378, TC-429): 닮음 시험 10\~20마리의 '내 아이 같다' 점수, 가격 인터뷰, 아이폰·안드로이드 웹 푸시와 사진 고르기. 초대할 사람과 인터뷰는 동희님이 해요. 법 원문 확인(명세 7.1)은 동희님이 전문가와.
- 끝 조건: 그 PR의 TASK 끝 조건 시험이 모두 통과하고 그때까지의 반려동물 시험 전체가 통과해요. API를 건드린 작업은 그 operation이 계약에 적은 응답마다 시험이 통과해야 끝이에요. 회원 격리(TC-383)와 로그(TC-385)는 PR마다 다시 돌려요. 반영 뒤 TC-428.
- 설계 질문: PR 설명 맨 위 '설계 질문'에 적으면 설계 스레드('마롱 설계를 NEXUS 기준으로 잇기', 마롱이 설계 담당)가 답해요. 오류 메시지·안내 문구가 정의에 없으면 지어 넣지 말고 여기에 남겨요.

```bash
.venv/bin/python tests/test_pet_core.py      # 표·시작 검사·오류 모양·격리·출처·로그·원가·로그인·가입·동의·지우기·푸시·한도: TC-380~393
.venv/bin/python tests/test_pet_create.py    # 사진·얼굴·특징표·미리 보기·결제·본인인증·운영 명령·후보·시트·이름: TC-394~405
.venv/bin/python tests/test_pet_talk.py      # 대화·위기·기억·신고·합성·선톡·일기·다시 그리기·공유·통화·추억 모드·작별·보관·내보내기: TC-406~420
.venv/bin/python tests/test_pet_decor.py     # 보관함·상점·아이템 올리기·입히기·반응 선톡·충전·구독·청약철회: TC-421~425
.venv/bin/python tests/test_pet_ai.py        # AI 답 범위와 코드 검사(가짜 모델), 레드팀은 --real: TC-427
npx playwright test tests/pet_web/           # 화면 상태 SCR-140~162: TC-426
```

시험 파일 이름은 제안이에요. 더 맞는 자리가 있으면 바꾸고 PR 설명과 시험 계획의 'Runs as' 칸에 적어요.

### 동희님 준비물

명세 7.1이에요. 개발과 시험은 가짜로 하고, 아래는 TASK-377 반영 전에 있어야 해요. 브라우저로 하는 계정 일은 GPT가 Aside CLI에 맡겨 동희님 계정으로 해요(D65, [AGENTS.md](../../AGENTS.md#서명과-브라우저-일)). 동희님이 정하거나 돈·계약이 드는 것만 동희님 몫이에요.

| 준비물 | 하는 쪽 | 쓰는 곳 |
| --- | --- | --- |
| 공개 도메인 이름(새로 살지, 가진 도메인의 하위 주소를 쓸지) | 동희님이 정함 | TASK-377 |
| Cloudflare Tunnel의 새 공개 호스트 | GPT(서버 명령, 필요하면 Aside) | TASK-377 |
| 카카오·구글 로그인 앱 등록(리디렉션 주소는 `https://<공개 도메인>/api/auth/{provider}/callback`) | GPT(Aside) | TASK-334 실제 확인, TASK-377 |
| OpenAI 공개 서비스 전용 프로젝트·키·월 한도, VAPID 키 | GPT(Aside, VAPID는 서버에서 만듦). 키 값은 서버 비공개 설정에만, Git·로그·메시지에는 넣지 않음 | TASK-377 |
| Anthropic 키를 지금 키와 같이 쓸지, 통화 엔진 키 | 동희님이 정함(정하지 않으면 지금 키를 같이 씀) | TASK-377 |
| `PET_MONTHLY_BUDGET_KRW` 값 | 동희님이 정함 | TASK-377 |
| 결제 대행과 본인확인 기관 계약(사업자 등록·통신판매업 신고 뒤) | 동희님 | 결제 켜기 전. 그 전에는 결제 꺼진 채로 초대 회원과 무료 만들기권(SPEC-361)으로 운영 |
| 법 원문 확인: AI 기본법 시행령의 표시 방식, 전자상거래법 디지털 콘텐츠 청약철회와 정기결제, 개인정보 처리방침·국외 이전 동의 글 | 동희님(전문가와) | `PET_SIGNUP=open`과 결제 켜기 전 |

## 작업

- 담당: 모두 GPT예요. 첫 주 확인(TASK-378)은 동희님과 같이 해요.
- 크기: 사람이 하는 일 기준의 대략값(일)이에요.
- 새 파일 이름(`marong/pet/app.py`, `marong/pet/jobs.py` …)은 제안이에요. 더 맞는 자리가 있으면 바꾸고 PR 설명에 적어요.
- 이 패키지 TASK 범위의 마지막 번호(379)는 비워 둬요.

### ① 바탕·로그인·가입·한도(`codex/pet-core`)

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-330 | 구현 전 실계정 확인(개발용 테스트 키): Anthropic 비전 구조화 출력(처리한 사진 3장, AI-30 스키마)의 칸과 걸린 시간, OpenAI 그림 편집이 투명 배경 1024×1024와 참고 그림 두 장을 받는지·사용량 칸·거절 모양, `claude-haiku-5-5`로 AI-32 답 첫 글자까지 걸린 시간, YuNet 모델의 라이선스와 패키지 크기, OpenAI 그림 엔드포인트의 보관 기간(명세 3.11 [확인 필요]) | SPEC-317, SPEC-318, SPEC-320, SPEC-327, SPEC-367 | 실제 API, 개발 컴퓨터 | 없음 | GPT | 0.5 | 결과(칸 이름, 시간, 오류 모양, 라이선스)를 이 파일 '11단계 진행'에 적고, 명세와 다르면 '설계 질문'. 실제 비용 합 3달러 이하 |
| TASK-331 | 바탕: 새 DB에 `schema.sql` 적용(두 번 돌려도 같음), 역할 권한, 설정 읽기(3.7, `PET_*`)와 단가표 `marong/pet/prices.json`, 허용 목록 밖 모델·단가표 없음·예산 없음이면 시작 거절(종료 코드 2), 작업 큐(TBL-160: 잡기·다시·마감), `run_pet.py`(aiohttp)와 `GET /healthz` | SPEC-367, SPEC-368 | `run_pet.py`(새), `marong/pet/`(새), `requirements-pet.txt`(새), TBL-140\~163, API-210 | 없음 | GPT | 1.5 | TC-380·381 통과 |
| TASK-332 | 공통 규칙: Problem Details 오류(`code`·`traceId`, 3.10 글), `no-store`, 로그인 확인(401), 회원 격리(남의 것 404) 도우미, 쓰기 요청 `Origin` 확인(403 `cross_site`), `pet` 로거(회원 번호 해시 앞 8자), 그림 주소 API-206에도 `no-store` | SPEC-364, SPEC-365, SPEC-366 | `marong/pet/http.py`, `marong/pet/log.py`, API-206, TBL-144 | TASK-331 | GPT | 1 | TC-382·383·384·385 통과(지금 있는 API로. 격리·로그 시험은 뒤 PR마다 다시) |
| TASK-333 | 원가 기록과 월 예산: 모델 부를 때마다 원가 줄(TBL-158), 이번 달 합 80% 운영 알림 한 번, 100% `budget_paused`(새 그림·통화 시작 막기, 결제한 만들기는 계속), 다음 달 1일 00:00 KST 풀림. 걸린 시간 `pet_timing`과 `pet_admin.py timing --days 7` | SPEC-363, SPEC-369 | `marong/pet/cost.py`, `tools/pet_admin.py`(새), TBL-158, TBL-163 | TASK-331 | GPT | 1 | TC-386·387 통과 |
| TASK-334 | 로그인: 카카오·구글 OIDC(`openid`만), PKCE·`state`·`nonce` 10분 쿠키, id_token 서명·`iss`·`aud`·`nonce`·`exp` 확인, (공급자, `sub`)로 찾기, 가입 대기 세션 30분, 세션 쿠키 `pet_session`(30일, 쓸 때 늘림, 처음부터 90일까지, DB에는 SHA-256만), 로그아웃 | SPEC-310 | API-150, API-151, API-152, `marong/pet/auth.py`, TBL-140, TBL-141 | TASK-332 | GPT | 1.5 | TC-388 통과 |
| TASK-335 | 가입과 동의: 만 19세(한국 시각 오늘 기준) 확인, 필수 동의 셋, 생년월일은 저장하지 않고 `adult_self_declared_at`만, 동의 줄 쌓기, 초대 코드(`PET_SIGNUP=invite`), 무료 기본 아이템 넣기, `GET /api/me`, 동의 보기·바꾸기(국외 이전만, 끄면 모델 부르는 일을 409 `consent_required`) | SPEC-311, SPEC-312, SPEC-346 | API-153, API-154, API-156, API-157, TBL-140, TBL-142, TBL-143, TBL-152 | TASK-334 | GPT | 1.5 | TC-389·390 통과 |
| TASK-336 | 계정 지우기: `confirm` 확인, 세션 끊기, 구독 해지 요청, `deleting`, 지우기 작업(24시간 안, 1시간마다 다시), 주문은 회원 없이 5년 | SPEC-314 | API-155, `marong/pet/delete.py`, TBL-140\~162 | TASK-335 | GPT | 1 | TC-391 통과 |
| TASK-337 | 웹 푸시: VAPID, 구독 넣기·지우기, 보내기(잠금 화면은 '<아이 이름>(AI)'과 원문 없는 한 줄), 404·410이면 구독 지움, 추억 모드·보관된 아이로는 보내지 않음 | SPEC-337 | API-159, API-160, `marong/pet/push.py`, TBL-161 | TASK-335 | GPT | 1 | TC-392 통과 |
| TASK-338 | 하루 한도: 무료 100·구독 200 단위, 한국 시각 04:00 경계, 한 트랜잭션에서 남은 단위 확인 뒤 잡기(TBL-157), 확정·돌려주기, 다 씀 409 `quota_exhausted`, `GET /api/me/quota`(남은 비율만, 단위·원가 없음) | SPEC-353, SPEC-354 | API-197, `marong/pet/quota.py`, TBL-155, TBL-156, TBL-157 | TASK-335 | GPT | 1 | TC-393 통과 |

### ② 캐릭터 만들기와 결제(`codex/pet-create`)

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-339 | 사진 받기와 사람 얼굴 가리기: multipart 1\~3장, 형식·8MB·4096px, 메모리에서만 EXIF 방향 적용 뒤 메타데이터 없는 PNG, YuNet 신뢰도 0.6, 상자 사방 20% 넓혀 #9E9E9E, 모델 없으면 503, 아이와 진행 중 만들기 상한, 만들기 줄 `photos` | SPEC-316, SPEC-317 | API-162, `marong/pet/photos.py`, TBL-144, TBL-145 | TASK-338 | GPT | 1.5 | TC-394·395 통과 |
| TASK-340 | 특징표: 작업 큐가 AI-30을 부르고 서버 확인(3.4 목록 값), `rejected`·`failed_traits`, 고치기와 확정(몸 템플릿 3.5) | SPEC-318, SPEC-319, AI-30 | API-165, API-166, `marong/pet/traits.py`, TBL-145 | TASK-339, TASK-330 | GPT | 1.5 | TC-396 통과 |
| TASK-341 | 만들기 상태 보기와 목록, 30일 만료(사진·그림 지움) | SPEC-326 | API-163, API-164, TBL-145 | TASK-340 | GPT | 0.5 | TC-397 통과 |
| TASK-342 | 그림 모델 감싸기(AI-31, 주 모델과 예비 모델, 투명 배경 확인)와 미리 보기 1장: 하루 3장(성공만 셈), 예산 멈춤, 실패하면 `traits_confirmed`로 | SPEC-320, AI-31 | API-167, `marong/pet/images.py`, TBL-144, TBL-145, TBL-158 | TASK-341, TASK-333 | GPT | 1.5 | TC-398 통과 |
| TASK-343 | 결제 어댑터와 주문: 결제 대행 인터페이스와 가짜(`pg_fake.py`), 주문 만들기(멱등 키, 결제 꺼짐 409 `payments_off`, 첫 결제 전 409 `identity_required`), 결제 확인과 웹훅(서명 확인, 먼저 온 쪽만), 지급 한 번, 주문 목록 | SPEC-355, SPEC-356, SPEC-357 | API-198, API-199, API-200, API-202, `marong/pet/billing.py`, `marong/pet/pg_fake.py`, TBL-153, TBL-163 | TASK-338 | GPT | 2 | TC-399 통과 |
| TASK-344 | 본인인증: 기관 결과 다시 받기, 만 19세, `identity_verified_at`과 CI 솔트 해시만, 미성년이면 `minor_locked`와 7일 뒤 지움 | SPEC-313 | API-158, TBL-140 | TASK-343, TASK-336 | GPT | 0.75 | TC-400 통과 |
| TASK-345 | 운영 명령: `payments on·off`(사업자 정보는 DB 설정, Git에 없음), `ticket grant`, `invite create --uses N` | SPEC-361, SPEC-362, SPEC-368 | `tools/pet_admin.py`, TBL-140, TBL-143, TBL-163 | TASK-343 | GPT | 0.75 | TC-401 통과 |
| TASK-346 | 캐릭터 만들기 결제 시작: 주문(`character_creation`) 또는 무료 만들기권, `paid` | SPEC-321 | API-168, TBL-145, TBL-153 | TASK-342, TASK-345 | GPT | 0.75 | TC-402 통과 |
| TASK-347 | 그림 후보 4장과 맞춤 검사(IoU 0.75), 다시 만들기 2번, 후보 0장이면 자동 전액 취소(`failed_candidates`) | SPEC-322, SPEC-323, SPEC-360 | API-169, `marong/pet/creation.py`, TBL-144, TBL-145, TBL-153 | TASK-346 | GPT | 1.5 | TC-403 통과 |
| TASK-348 | 정면 그림 고르기와 표정 6장(IoU 0.85, 머리 중심), 캐릭터 시트 `sheet_ready`·`sheet_needs_operator`, 완성 웹 푸시 | SPEC-324 | API-170, TBL-144, TBL-145 | TASK-347, TASK-337 | GPT | 1.5 | TC-404 통과 |
| TASK-349 | 이름과 아이 소개, 첫 인사, 아이 생김(`done`), 아이 목록·보기·고치기, 아이 5마리 상한 | SPEC-325 | API-171, API-172, API-173, API-174, TBL-145, TBL-146, TBL-147 | TASK-348 | GPT | 1 | TC-405 통과 |

### ③ 대화·선톡·일기·통화·추억 모드(`codex/pet-talk`)

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-350 | 아이 대화 답(AI-32): 메시지 저장(`clientId`), 첫 메시지부터 8초 모아 합치기, 쓰는 중 새 메시지면 버리고 다시, 지시문 3.9, 보내기 전 코드 검사(`guard_words.txt`), 실패 `reply_failed`, 보관 409, 메시지 목록과 SSE, AI 표시 | SPEC-327, SPEC-331, AI-32 | API-176, API-177, API-178, `marong/pet/chat.py`, `marong/pet/guard_words.txt`, TBL-147, TBL-158 | TASK-349 | GPT | 2.5 | TC-406 통과, TC-427의 AI-32 줄이 가짜 모델로 통과 |
| TASK-351 | 메시지 수, 100번째 휴식 권유, 301번째부터 잠듦(409 `asleep`, 04:00에 깸) | SPEC-328 | TBL-156 | TASK-350 | GPT | 0.5 | TC-407 통과 |
| TASK-352 | 위기 안내: 성향의 위기 판정과 109 한 번을 회원 메시지에, `system` 메시지로 따로 | SPEC-330 | `marong/pet/chat.py` | TASK-350, 성향 TASK-221 | GPT | 0.5 | TC-408 통과 |
| TASK-353 | 기억: 성향의 기억 정리를 (회원, 아이) 키로, 근거가 회원 메시지인 항목만 남김 | SPEC-329 | `marong/pet/memory.py`, TBL-149 | TASK-350, 성향 TASK-230\~243 | GPT | 1 | TC-409 통과 |
| TASK-354 | 신고: 6종 이유, 같은 대상 하나, 하루 20건, 매일 09:00 KST 처리하지 않은 수 운영 알림, `pet_admin.py report list·show·resolve` | SPEC-315 | API-161, TBL-159 | TASK-350 | GPT | 0.75 | TC-410 통과 |
| TASK-355 | 합성 그림: 1536×1024, 배경 → 표정 → 몸 → 목 → 머리 순서, 배경 `stage`와 태그, 배경 세트 12장 자리 | SPEC-334 | `marong/pet/compose.py`, `design/pet/`(그림 파일 자리), TBL-144, TBL-151 | TASK-349 | GPT | 1 | TC-411 통과 |
| TASK-356 | 살아 있는 아이의 선톡과 그림 화두(AI-36): 성향의 선톡 게이트를 (회원, 아이) 키로, 회원 단위 하루 3번(기억형 1번), 조용 시간 22\~08시, 추억 모드·보관 아이는 후보 없음, 웹 푸시 | SPEC-332, AI-36 | `marong/pet/proactive.py`, TBL-162, TBL-147 | TASK-353, TASK-355, TASK-337, 성향 TASK-244\~252 | GPT | 1.5 | TC-412 통과 |
| TASK-357 | 아이 시점 그림일기(AI-33): 일기 줄 시각(04:10 만들기, 30분·2시간 다시, 22:00 마감)을 (회원, 아이)마다, 하루 모음(글 대화와 통화 자막), 40자 미만 건너뜀, 합성 지정 저장, 살아 있는 아이만 08:30 뒤 웹 푸시, 일기 목록과 한 장 | SPEC-335, AI-33 | API-186, API-187, `marong/pet/diary.py`, TBL-150 | TASK-355, TASK-337, 일기 TASK-140\~144 | GPT | 2 | TC-413 통과 |
| TASK-358 | 새 그림으로 다시 그리기: 일기마다 2번, 한도 40 단위, 예산 멈춤, 그리는 중 409 `busy` | SPEC-336 | API-188, TBL-150, TBL-157 | TASK-357, TASK-342 | GPT | 0.75 | TC-414 통과 |
| TASK-359 | 그림일기 카드 공유 PNG(워터마크와 메타데이터, 명세 SPEC-342와 같은 표시) | SPEC-343 | API-190, `marong/pet/watermark.py` | TASK-357 | GPT | 0.75 | TC-415 통과 |
| TASK-360 | 통화: 시작 API(30 단위 잡기, 일회용 토큰 60초, 회원마다 하나), 공개 서비스용 통화 서버 분기(내부 API로 토큰 한 번 확인과 AI-35 지시문, 고정 안내 녹음, 종마다 목소리, 1분마다 30 단위, `exhausted`면 인사 지시와 30초 뒤 끊기, 끝 보고와 자막 `kind: call`) | SPEC-344, SPEC-345, AI-35 | API-193, API-207, API-208, API-209, `marong/pet/calls.py`, `tools/vertex_live/`(설정으로 켜는 분기), TBL-148, TBL-147 | TASK-350, TASK-338 | GPT | 2.5 | TC-416 통과 |
| TASK-361 | 추억 모드: 회원만 켬, 켜면 선톡·상점·충전 권유 꺼짐, 7일 안 되돌리기, 화면과 말(3.9 추억 모드 절, 한도 다 씀 글) | SPEC-338, SPEC-339 | API-179, TBL-146 | TASK-356, TASK-357 | GPT | 1 | TC-417 통과 |
| TASK-362 | 작별 의식(아이마다 한 번): 마지막 편지(AI-34)와 작별 그림, 실패 503 `farewell_failed` | SPEC-340, AI-34 | API-180, TBL-146, TBL-150 | TASK-361, TASK-342 | GPT | 1 | TC-418 통과 |
| TASK-363 | 보관·꺼내기·아이 지우기 | SPEC-341 | API-175, API-181, API-182, TBL-146 | TASK-361 | GPT | 0.75 | TC-419 통과 |
| TASK-364 | 기록 내보내기: zip(`pictures/`, `diary.html`, `chat.txt`, `README.txt`), 모든 PNG 워터마크와 메타데이터, 아이마다 하루 1번, 받기 24시간, 완료 웹 푸시 | SPEC-342 | API-183, API-184, API-185, `marong/pet/export.py`, `marong/pet/watermark.py` | TASK-359, TASK-363 | GPT | 1.5 | TC-420 통과 |

### ④ 꾸미기·충전·구독(`codex/pet-decor`)

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-365 | 보관함·상점 목록·레이어 그림·미리 입혀 보기(합성만, 저장 안 함), 추억 모드면 상점 없음 | SPEC-346, SPEC-347, SPEC-348 | API-194, API-195, API-196, TBL-151, TBL-152 | TASK-355 | GPT | 1 | TC-421 통과 |
| TASK-366 | 아이템 올리기 도구: `item add <폴더>`(라이선스 대장 `design/pet/licenses.csv`, 템플릿 5종 레이어 1024×1024 PNG·알파·자리 상자 밖 2% 이하, 테마 1080×1920, 글꼴 woff2), `item end`, `item list` | SPEC-352 | `tools/pet_admin.py`, `design/pet/licenses.csv`(새), TBL-151 | TASK-365 | GPT | 1 | TC-422 통과 |
| TASK-367 | 입히기·벗기기(자리마다 하나), 일기장 테마와 글꼴, 스티커 10개 | SPEC-349, SPEC-350, SPEC-351 | API-189, API-191, API-192, TBL-154, TBL-150 | TASK-365, TASK-357 | GPT | 1 | TC-423 통과 |
| TASK-368 | 아이템 반응 선톡: (아이, 아이템)마다 한 번, 무료 기본 아이템 없음, 살아 있는 아이만, 배경은 아이템 태그로 | SPEC-333 | `marong/pet/proactive.py`, TBL-162 | TASK-367, TASK-356 | GPT | 0.75 | TC-424 통과 |
| TASK-369 | 충전권(하루 3장, 사면 바로 채움), 구독(빌링 키, 갱신, 해지, 가격 바뀜 동의), 청약철회(3.8 표)와 환불 | SPEC-358, SPEC-359, SPEC-360 | API-201, API-203, API-204, API-205, TBL-153, TBL-155 | TASK-343, TASK-367 | GPT | 2 | TC-425 통과 |

### ⑤ 화면(`codex/pet-web`)

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-370 | PWA 껍데기: manifest, 서비스 워커(웹 푸시 받기, 화면 파일만 캐시), 아래 탭 셋(홈·상점·내 정보, 살아 있는 아이가 없으면 상점 숨김), AI 표시, 오류 메시지 3.10, 홈 SCR-140과 가입 SCR-141 | SPEC-310, SPEC-311, SPEC-331, SPEC-337, SCR-140, SCR-141 | `marong/pet/static/`(새) | TASK-338 | GPT | 2 | TC-426의 SCR-140·141 줄 통과 |
| TASK-371 | 만들기 화면: 사진 고르기(긴 변 1600px로 다시 그림, HEIC), 특징표, 미리 보기와 결제(본인인증 창과 결제 창 돌아오기), 후보 고르기, 이름 짓기 | SPEC-316\~326, SCR-142\~146 | `marong/pet/static/` | TASK-370, TASK-349 | GPT | 2.5 | TC-426의 SCR-142\~146 줄 통과 |
| TASK-372 | 아이 화면(대화, SSE, 잠듦·예산 멈춤·보관 띠), 한도 다 씀과 충전 칸, 신고 칸 | SPEC-327\~331, SPEC-353, SPEC-354, SPEC-358, SPEC-315, SCR-147, SCR-155, SCR-156 | `marong/pet/static/` | TASK-370, TASK-354, TASK-369 | GPT | 2 | TC-426의 SCR-147·155·156 줄 통과 |
| TASK-373 | 통화 화면(마이크 권한, 고정 안내 표시, 남은 분, 끝 이유) | SPEC-344, SPEC-345, SCR-148 | `marong/pet/static/` | TASK-372, TASK-360 | GPT | 1.5 | TC-426의 SCR-148 줄 통과 |
| TASK-374 | 일기장, 일기 한 장(테마·글꼴·스티커·공유), 새 그림으로 다시 그리기 칸 | SPEC-335, SPEC-336, SPEC-343, SPEC-350, SPEC-351, SCR-149, SCR-150, SCR-151 | `marong/pet/static/` | TASK-372, TASK-367 | GPT | 2 | TC-426의 SCR-149\~151 줄 통과 |
| TASK-375 | 옷 입히기, 상점, 아이템 보기(미리 입혀 보기, 철회할 수 없는 경우를 결제 전에 보임) | SPEC-347\~349, SPEC-360, SCR-152, SCR-157, SCR-158 | `marong/pet/static/` | TASK-372, TASK-369 | GPT | 1.5 | TC-426의 SCR-152·157·158 줄 통과 |
| TASK-376 | 아이 설정(추억 모드·보관·지우기·내보내기), 작별 의식, 내 정보(동의·계정 지우기), 한도와 구독, 주문 내역(철회), 결제 확인 | SPEC-312, SPEC-314, SPEC-338\~342, SPEC-359, SPEC-360, SCR-153, SCR-154, SCR-159\~162 | `marong/pet/static/` | TASK-372, TASK-364 | GPT | 2 | TC-426의 SCR-153·154·159\~162 줄 통과 |

### ⑥ 반영과 첫 주(`codex/pet-release`)

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-377 | 서버 반영: 새 DB·역할, 새 시스템 사용자와 서비스 `marong-pet`·`marong-pet-call`, 터널 공개 호스트, 비공개 설정(키·VAPID·예산), `PET_SIGNUP=invite`, 결제 꺼짐, 로그 5분 확인, 되돌리기 스크립트. 지금 마롱이 서비스는 그대로 | SPEC-368, 명세 7.1 | 서버, `deploy/`(반영 스크립트) | TASK-330\~376, 동희님 준비물과 공개 허락 | GPT | 1 | TC-428 통과, 되돌리기 경로를 PR에 적음 |
| TASK-378 | 첫 주 초대 회원: 초대 코드와 무료 만들기권, 닮음 시험 10\~20마리, 가격 인터뷰, 걸린 시간 P95와 무료 회원 하루 원가, 아이폰·안드로이드 기기 확인 | SPEC-363, SPEC-369, 명세 7.2·7.3, REQ-423\~427 | 운영, 폰 | TASK-377 | GPT(동희님이 초대·인터뷰·폰 확인) | 1주 관찰 | TC-429 결과 기록, 다르면 버그로 기록하고 맞춤 검사 값·가격은 '설계 질문'으로 |

## 확인

- 명세의 행(SPEC-310\~369, 모두 active)마다 작업이 있어요: 310 → 334·370, 311 → 335·370, 312 → 335·376, 313 → 344, 314 → 336·376, 315 → 354·372, 316·317 → 339·371, 318·319 → 340·371, 320 → 342·371, 321 → 346·371, 322·323 → 347·371, 324 → 348·371, 325 → 349·371, 326 → 341·371, 327 → 350·372, 328 → 351·372, 329 → 353·372, 330 → 352·372, 331 → 350·370·372, 332 → 356, 333 → 368, 334 → 355, 335 → 357·374, 336 → 358·374, 337 → 337·370, 338·339 → 361·376, 340 → 362·376, 341 → 363·376, 342 → 364·376, 343 → 359·374, 344·345 → 360·373, 346 → 335·365, 347·348 → 365·375, 349 → 367·375, 350·351 → 367·374, 352 → 366, 353·354 → 338·372, 355·356·357 → 343, 358 → 369·372, 359 → 369·376, 360 → 347·369·375·376, 361·362 → 345, 363 → 333, 364·365·366 → 332, 367 → 331, 368 → 331·345·377, 369 → 333.
- 계약의 operation 61개(API-150\~210)마다 작업이 있어요: 150\~152 → 334, 153·154·156·157 → 335, 155 → 336, 158 → 344, 159·160 → 337, 161 → 354, 162 → 339, 163·164 → 341, 165·166 → 340, 167 → 342, 168 → 346, 169 → 347, 170 → 348, 171\~174 → 349, 175·181·182 → 363, 176\~178 → 350, 179 → 361, 180 → 362, 183\~185 → 364, 186·187 → 357, 188 → 358, 189·191·192 → 367, 190 → 359, 193·207\~209 → 360, 194\~196 → 365, 197 → 338, 198\~200·202 → 343, 201·203\~205 → 369, 206 → 332, 210 → 331. API를 만지는 작업은 그 operation이 계약에 적은 응답마다 시험이 통과해야 끝이에요.
- 화면 SCR-140\~162(23개)마다 작업이 있어요(TASK-370\~376).
- 표 TBL-140\~163(24개)은 TASK-331이 모두 만들고, 각 작업의 Touches에 쓰는 표를 적었어요.
- 의존에 고리가 없어요. 이 패키지 안의 작업은 번호가 더 작은 작업에만 기대고, 다른 패키지에 기대는 넷(TASK-352·353·356·357)은 그 패키지 TASK를 적었어요.

## 11단계 진행

GPT가 TASK마다 상태·커밋·확인한 것을 적어요(AGENTS.md '구현을 시작할 때' 6).

| TASK | 상태 | 커밋 | 확인한 것 |
| --- | --- | --- | --- |
| TASK-330 | 실계정 확인 대기 | | 공개 서비스 전용 시험 자격과 프로젝트 확인이 남음. |
| TASK-331 | 시험 통과 | `a02dc49` | 격리 PostgreSQL에서 스키마 두 번·24개 표의 권한·서로 다른 DB 접근 확인. 시작 거절, 정상 /healthz, 작업 임대·재시도·마감 확인(TC-380·381). |
| TASK-332 | 구현·격리 시험 | 4578a0b | TC-382~385 현재 API |
| TASK-333 | 구현·격리 시험 | 4578a0b | TC-386·387 가짜 원가와 걸린 시간 |
| TASK-334 | 구현·격리 시험 | 4578a0b | TC-388 두 가짜 발급자, 실제 등록 대기 |
| TASK-335 | 구현·격리 시험 | 7eaed4f | TC-389, TC-390 동의와 가짜 호출 문 |
| TASK-336 | 구현·격리 시험 | c707a3b | TC-391 파일·세션·회원 제거, 가짜 빌링 키 지우기, 주문 보존과 실패 재시도 |
| TASK-337 | 구현·격리 시험 | c707a3b | TC-392 가짜 푸시, 실제 VAPID와 브라우저 대기 |
| TASK-338 | 구현·격리 시험 | c707a3b | TC-393 동시 한도, 초기화, 구독 시작·끝, 잡기 돌려주기 |
| TASK-339\~378 | 앞 PR 병합 대기 | | TASK-339부터 코어 PR 병합 뒤 착수 |
| TASK-370 | 구현·일부 화면 시험 | 68ce4b5 | 360·430px Chromium과 Aside 320·390·1440px. 홈·가입, 동의 표시·입력, 정적 셸. |
| TASK-371 | 무료 경로 화면 시험 | 68ce4b5 | 합성 사진→특징표→미리 보기→무료 주문→후보→이름. 유료와 본인확인 반환 시험 대기. |
| TASK-372·374·376 | 일부 화면 | 68ce4b5 | 첫 대화와 일기·동의 표시. 전체 상태와 실제 호출 검증 대기. |
| TASK-374 | 일기 꾸미기 화면 시험 | 94384ac | Chromium 360px에서 보관함 테마 미리 보기, 사용 전 안내, 취소, 스티커 추가·위치 조절, 저장 후 재진입을 확인. 실제 일기 생성·다시 그리기와 기기 확인은 대기. |
| TASK-372 | 충전 안내 화면 시험 | b20f3d0 | SCR-155. Chromium에서 한도 줄로 열기, 첫 다시 그리기 한도에만 자동 열림, 추억 모드 제외, 결제 꺼짐. API 계약에서 주지 않는 남은 충전 장 수는 설계 질문. |
| TASK-374 | 일기 합성·날짜 이동 | b20f3d0·5c4b117 | SCR-150. 저장된 배경·표정·착용과 같은 배치 좌표, 날짜 이동, 건너뛴 날 제외. 격리 AioHTTP에서 WebP 12개와 좌표 파일을 확인. |
| TASK-373 | 통화 UI·격리 브라우저 검증 | b8ad667 | Chromium 390px에서 마이크 거절 후 재시도, PCM 재생·입력, 한도 종료, 마이크 해제, 대화 복귀. 실제 음성 공급자와 폰 시험 대기. |
| TASK-375 | 옷 입히기·상점·아이템 화면과 가짜 API 시험 | dbd492c·f0ce416 | Chromium 360·430px에서 착용 전 철회 안내, 취소, 입힘과 벗김, 잘못된 자리 복구, 추억 모드, 판매 목록과 미리 보기 실패, 결제 꺼짐과 같은 주문 키 재시도를 확인. Aside 360·430px에서 가로 넘침 없음, 상점 카드와 철회 안내·취소 확인. AioHTTP에서 페이지와 게시 썸네일을 확인. 실제 결제·본인확인 창은 공급자 확정 뒤. |
| TASK-376 | 주문·결제 반환 화면 시험 | 6592f58 | SCR-161·162 목록·철회 결과와 결제 확인·이미 확인·취소. 결제 대행 창 및 실제 청약철회 API 대기. |
| TASK-376 | SCR-160 합성 API 화면 시험 | f3a8e87 | Chromium 360px에서 한도·결제 꺼짐, 가격 동의, 해지 확인과 남은 기간을 검증. 결제 등록 창은 대행사 결정 뒤. |
| TASK-376 | 추억 모드와 내보내기 화면 시험 | 22c3a63 | SCR-153·154 가짜 API. 이름 확인, 모드 전환, 작별 편지와 내보내기 폴링. 실제 API는 TASK-361~364 뒤. |

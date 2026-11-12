# 마롱이 얼굴 그림

통화 홈과 통화 중 화면에 보이는 마롱이 얼굴 그림이에요(TERM-018). 동희님이 2026-11-12 14:21(한국 시각)에 올린 표정 그림 19장(1024×1024 투명 PNG)과 그 그림을 만든 지시문에서 왔어요. 언제 어떤 얼굴을 쓰는지의 원본은 [기능 명세 3.5 '얼굴 규칙'](../../docs/04-functional-spec/spec.md)(SPEC-029, SPEC-030)이고, 이 문서는 그림 번호·파일·만드는 법만 적어요.

## 위치

| 무엇 | 위치 | Git |
| --- | --- | --- |
| 화면용 512px WebP 17장(합계 975,936바이트, 약 953KB) | [`marong/call/static/face/v1/`](../../marong/call/static/face/v1/) | 넣음 |
| 1024 PNG 원본 19장 | 동희님이 올린 `marongi-expressions.zip`(5.8MB, 프로젝트 파일) | 넣지 않음 |
| 그림을 만든 지시문 | 동희님이 올린 `marongi-imagegen-prompts.txt`(프로젝트 파일) | 넣지 않음 |

어디에 둘지는 동희님이 2026-11-12 14:48(한국 시각) 결정 카드에서 '화면용 그림만 넣기'를 골라 정했어요(Notion '결정할 것' D14). 원본이 필요하면 프로젝트 파일의 zip에서 꺼내요.

통화 서버는 `/static/face/v1/`을 `Cache-Control: public, max-age=31536000, immutable`로 내줘요. 그림을 바꾸면 폴더를 `v2`로 바꿔요. 서비스 워커는 그림을 캐시하지 않아요(SPEC-027, SPEC-029).

## 그림 번호와 쓰임

| 번호 | 원본 파일 | 화면용 파일 | 쓰임 |
| --- | --- | --- | --- |
| 01 | `marongi-01-neutral.png` | `01-neutral.webp` | 기본 얼굴. 입 닫음과 눈 뜸 칸도 이 그림 |
| 02 | `marongi-02-big-laugh.png` | `02-big-laugh.webp` | 느낌 `laugh` |
| 03 | `marongi-03-listening.png` | `03-listening.webp` | 현경님이 말하는 중 |
| 04 | `marongi-04-thinking.png` | `04-thinking.webp` | 현경님 말이 끝나고 마롱이 소리가 아직일 때 |
| 05 | `marongi-05-excited.png` | `05-excited.webp` | 느낌 `excited` |
| 06 | `marongi-06-sad.png` | `06-sad.webp` | 느낌 `sad`, 예산·오류 상태 |
| 07 | `marongi-07-crying.png` | `07-crying.webp` | 느낌 `crying`(장난스럽게 엉엉 우는 말에만) |
| 08 | `marongi-08-surprised.png` | `08-surprised.webp` | 느낌 `surprised` |
| 09 | `marongi-09-pouting.png` | `09-pouting.webp` | 느낌 `pouting` |
| 10 | `marongi-10-shy.png` | `10-shy.webp` | 느낌 `shy` |
| 11 | `marongi-11-drowsy.png` | `11-drowsy.webp` | 쉬기 시작 3초, 깨우는 중 |
| 12 | `marongi-12-asleep.png` | `12-asleep.webp` | 쉬는 중(4초에 한 번 숨쉬기) |
| 13 | `marongi-13-concerned.png` | `13-concerned.webp` | 느낌 `concerned`, 다시 잇는 중·권한·마이크 거절 |
| 14 | `marongi-14-mouth-closed.png` | 없음 | 01과 같은 파일이라 01을 써요 |
| 15 | `marongi-15-mouth-slightly-open.png` | `15-mouth-slightly-open.webp` | 입 조금(마롱이 소리 RMS 0.08~0.20) |
| 16 | `marongi-16-mouth-wide-open.png` | `16-mouth-wide-open.webp` | 입 크게(RMS 0.20 이상) |
| 17 | `marongi-17-eyes-open.png` | 없음 | 01과 같은 파일이라 01을 써요 |
| 18 | `marongi-18-eyes-half-closed.png` | `18-eyes-half-closed.webp` | 깜빡임 반쯤 감음(0.06초) |
| 19 | `marongi-19-eyes-closed.png` | `19-eyes-closed.webp` | 깜빡임 감음(0.09초) |

문턱값(RMS)은 처음 값이고 12단계 실기기 시험에서 맞춰요.

## 그림이 맞춰진 방식

올린 파일을 읽어서 잰 값이에요(2026-11-12).

- 19장 모두 1024×1024 RGBA이고 네 귀퉁이가 투명해요.
- 몸 상자는 모든 그림에서 x 205~819, y 239~785로 같아요. 그래서 칸을 바꿔 끼워도 몸이 흔들리지 않아요.
- 14번과 17번은 01번과 바이트까지 같아요.
- 15·16번은 01번에서 입 부분(x 462~551, y 459~544)만, 18·19번은 눈 부분(x 413~600, y 430~472)만 달라요. 그래서 입·눈 칸은 기본 얼굴(01)에만 맞아요. 감정 얼굴(02~13)에는 입 칸이 없어서, 마롱이가 말하는 동안 감정 얼굴은 소리 크기만큼 위로 0~4px 튀기만 해요.

## 화면용 그림 만들기

- 원본을 RGBA로 열어 Lanczos로 512×512로 줄이고, 무손실 WebP(`lossless=True, quality=100, method=6`)로 저장해요. 알파는 그대로예요.
- 파일 이름은 원본 이름에서 `marongi-`를 빼고 확장자를 `.webp`로 바꿔요. 14·17번은 만들지 않아요.
- 화면은 248px(통화 중), 200px(홈), 152px(끝난 화면)로 그려요(토큰 `size.face-*`). 기기 화소 비율이 3인 화면에서 248px 상자는 744화소라서 512px 그림을 키워 그려요. 흐려 보이는지 실기기에서 보고, 흐리면 더 큰 판으로 다시 만들어요(파일이 커져요, 기능 명세 7절 11번).

## 새 얼굴을 더할 때

- 01번을 편집 기준으로 같은 1024 캔버스와 같은 몸 상자를 지켜요. 원본 지시문의 공통 부분을 그대로 써요.
- 감정 얼굴에도 입을 움직이고 싶으면 그 감정마다 입 그림 두 장(조금·크게)을 더 만들어야 해요.
- 그림을 더하거나 바꾸면 `v2` 폴더로 옮기고 기능 명세 3.5의 표를 같은 변경에서 고쳐요.

## 확인하지 못한 것

- 갤럭시 Chrome에서 원격 WebRTC 소리를 `AnalyserNode`로 잴 수 있는지(못 재면 자막 조각으로 입을 움직여요).
- 248px에서의 선명함과 LTE에서 17장을 미리 받는 시간.

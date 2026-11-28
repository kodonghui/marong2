# FL-189 0원 상점에서 아이템 받기

Serves: REQ-525, REQ-526, REQ-527, REQ-530, REQ-532, REQ-534, REQ-691
Screens: SCR-181, SCR-182, SCR-183
Context: CTX-030

```mermaid
flowchart TD
  A(["내 마롱이·<br/>일기장의<br/>'상점'"])
  B["상점<br/>SCR-181<br/>값은 모두 0원<br/>REQ-525"]
  C["아이템 보기<br/>SCR-182"]
  D{"착용<br/>아이템인가?"}
  E["지금 쓰는<br/>마롱이나<br/>아이가<br/>입은 모습<br/>REQ-534·691"]
  F["일기장<br/>미리 보기"]
  G{"이미<br/>받았나?"}
  H(["보관함에<br/>있음<br/>'입히기'·<br/>'쓰기'"])
  I["결제 없이<br/>보관함에<br/>넣음<br/>REQ-526"]
  J(["보관함<br/>SCR-183<br/>바로 입히기·<br/>쓰기"])
  K(["관리자가<br/>내린<br/>아이템"])
  A e1@--> B
  B e2@--> C
  C e3@--> D
  D e4@-->|"예"| E
  D e5@-->|"아니오<br/>일기장<br/>아이템"| F
  E e6@--> G
  F e7@--> G
  G e8@-->|"예"| H
  G e9@-->|"아니오<br/>받기 누름"| I
  I e10@--> J
  K e11@-->|"상점에서만<br/>사라짐<br/>REQ-530"| B
  %% legend: below
  classDef term fill:#e7f5ff,stroke:#1c7ed6,color:#212529
  classDef proc fill:#f8f9fa,stroke:#495057,color:#212529
  classDef decide fill:#f3f0ff,stroke:#7048e8,color:#212529
  classDef key stroke:#e03131,stroke-width:4px
  classDef pass stroke:#868e96,stroke-width:1.5px
  class A,H,J,K term
  class B,C,E,F,I proc
  class D,G decide
  class D,E key
  class e1,e2,e3,e4,e5,e6,e7,e8,e9,e10,e11 pass
```

| Shape | Means |
| --- | --- |
| Rectangle | 화면이나 친구가 하는 한 단계 |
| Diamond | 분기. 나가는 선마다 이름이 있어요 |
| Stadium | 흐름이 시작하거나 끝나는 곳 |
| K에서 오는 선 | 다른 흐름(FL-192)에서 오는 일 |
| 빨간 굵은 테 | 기능 변경 1이 바꾸는 곳: 착용 아이템이면 기본 마롱이도 미리 봐요 |

- 상점 화면에는 값이 보여요(지금은 모두 '0원'). 결제 화면이나 충전권 안내는 없어요(REQ-527, D103).
- 뽑기 같은 확률형 상품은 없어요(REQ-531).
- 받은 아이템은 그 친구의 모든 캐릭터가 같이 써요.
- 기능 변경 1(2026-11-28, D192. 체크포인트 통과 D193): 갈림과 미리 보기 칸을 기본 마롱이까지 넓혔어요. 바뀌기 전 글은 [02 기능 변경 목록 1](../02-prd/pet-app.md#기본-마롱이-입히기-기능-변경-목록-1)의 1-7에 있어요. `MARONG_DEFAULT_WEAR=0`이면 기본 마롱이는 지금처럼 썸네일만 봐요.
- 그림 손봄(2026-11-28, 뜻은 그대로): 칸 글을 줄이고 칸 종류와 줄바꿈을 그림 문법에 맞췄어요(main에서 diagram-check 22건 → 0건). 줄이기 전 글: 시작 '내 마롱이 (SCR-165)나 일기장 (SCR-113)의 '상점'', 상점 '모자·옷·목도리·일기장 배경·속지·글꼴·스티커, 값은 모두 0원', 이미 받음의 끝 ''보관함에 있어요'와 '입히기'·'쓰기' 버튼', 받기의 끝 '보관함 (SCR-183)으로, 바로 입히기·쓰기'.

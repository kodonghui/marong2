# FL-215 업데이트 내역 보기

Serves: REQ-620, REQ-621, REQ-622
Screens: SCR-220
Context: CTX-026(관리자 화면 TERM-176, 읽기만)
상태: proposed(2026-11-24 KST, Claude, 체크포인트 전). 관리 페이지 기능 변경 '업데이트 내역'([도메인](../01-domain/admin-changelog.md), D170·D171).

```mermaid
flowchart TD
  A(["관리 페이지<br/>어느 화면이든<br/>탭 줄"])
  B["업데이트 내역<br/>탭 누름<br/>SCR-220"]
  C["API-300 읽기<br/>REQ-620"]
  D{"읽기<br/>됐나?"}
  D1(["오류 한 줄과<br/>다시 해 볼게요"])
  E{"반영 단위가<br/>있나?"}
  E1(["아직 적은<br/>업데이트<br/>내역이 없어요"])
  F["반영 단위마다<br/>그룹 새것부터<br/>반영일·이름<br/>근거"]
  G["항목마다<br/>구분·영역·항목<br/>변경 전·변경 후<br/>REQ-621"]
  H{"영역을<br/>골랐나?"}
  H1(["모든 영역<br/>그대로 읽기"])
  I["그 영역 항목만<br/>REQ-622"]
  J{"남은<br/>항목이 있나?"}
  J1(["이 영역의<br/>내역이 없어요"])
  K(["근거 PR 링크<br/>새 창으로 엶"])
  A e1@--> B
  B e2@--> C
  C e3@--> D
  D e4@-->|"아니오"| D1
  D e5@-->|"예"| E
  E e6@-->|"없음"| E1
  E e7@-->|"있음"| F
  F e8@--> G
  G e9@--> H
  H e10@-->|"전체"| H1
  H e11@-->|"영역 하나"| I
  I e12@--> J
  J e13@-->|"없음"| J1
  J e14@-->|"있음"| K
  H1 e15@--> K
  %% legend: below
  classDef term fill:#e7f5ff,stroke:#1c7ed6,color:#212529
  classDef proc fill:#f8f9fa,stroke:#495057,color:#212529
  classDef decide fill:#f3f0ff,stroke:#7048e8,color:#212529
  classDef key stroke:#e03131,stroke-width:4px
  classDef pass stroke:#868e96,stroke-width:1.5px
  class A,D1,E1,H1,J1,K term
  class B,C,F,G,I proc
  class D,E,H,J decide
  class G key
  class e1,e2,e3,e4,e5,e6,e7,e8,e9,e10,e11,e12,e13,e14,e15 pass
```

| Shape | Means |
| --- | --- |
| Rectangle | 화면이 하는 한 단계 |
| Diamond | 분기. 나가는 선마다 이름이 있어요 |
| Stadium | 흐름이 시작하거나 끝나는 곳 |
| 빨간 굵은 테 | 이 흐름의 핵심 단계: 항목마다 변경 전과 변경 후를 나눠 읽기 |

관리자가 보는 곳은 반영 단위 그룹 아래의 항목 줄이고, 항목마다 변경 전과 변경 후를 나란히 읽는다는 것을 보세요. 영역 고르기는 같은 응답을 화면에서 거르는 것이라 서버를 다시 부르지 않아요.

- 화면은 API-300 하나만 불러요. 쓰기 단추는 없어요(내역은 반영 절차가 저장소에서 써요, FL-216).
- 반영일이 '기록 없음'인 지난 단위는 단위 이름 앞 날짜의 자리에 놓여요(명세 SPEC-501).
- 근거 링크는 공개 저장소의 PR 주소예요(`https://github.com/kodonghui/marong2/pull/<번호>`). 커밋 근거는 커밋 주소예요. 새 창으로 열고 관리 페이지는 그대로예요.
- 읽지 못한 내역 파일이 있으면(형식이 틀림) 맨 위에 그 개수만 회색 글로 보이고 나머지는 그대로 그려요(SCR-220#skipped).

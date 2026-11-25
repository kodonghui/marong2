# FL-223 글 알림을 눌러 해당 방 열기

03단계 초안 · CTX-001·026 · [02 고정 요구사항](../02-prd/iphone-home-webapp-notifications-version-candidate.md)

연결 요구사항 REQ-651, REQ-652, REQ-653, REQ-657, REQ-658, REQ-659, REQ-664.

글 알림을 눌러도 계정, 방, 메시지의 접근을 확인해야 대화를 열 수 있습니다. 오프라인에서는 서버가 확인할 때까지 내용을 표시하지 않습니다.

```mermaid
flowchart TB
  %% legend: below
  subgraph Lane1["① 알림을 연 사용자의 진입"]
    A(["새<br/>답변·선톡·일정<br/>알림 탭<br/>REQ-651 REQ-652<br/>REQ-653 REQ-658"])
    B{"서버에 연결할<br/>수 있나요?<br/>REQ-664"}
    C(["연결 필요 ·<br/>대상 미확인<br/>REQ-664"])
    D{"로그인이<br/>유효한가요?<br/>REQ-657"}
    E["기존 로그인<br/>열기<br/>REQ-657<br/>SCR-164"]
    F{"로그인을<br/>마쳤나요?<br/>REQ-657 REQ-659"}
    G(["인증 없이<br/>종료<br/>REQ-657 REQ-659"])
  end
  subgraph Lane2["② 서버 대상 확인"]
    H{"현재 계정의<br/>대상이<br/>유효한가요?<br/>REQ-658 REQ-659<br/>REQ-664"}
    I["해당 방의 글<br/>대화 열기<br/>REQ-658<br/>SCR-107"]
    J(["현재 계정의<br/>대화 표시<br/>REQ-658<br/>SCR-107"])
    K(["대상 접근<br/>거절<br/>REQ-659"])
  end
  A e1@--> B
  B e2@-->|아니요| C
  B e3@-->|예| D
  D e4@-->|예| H
  D e5@-->|아니요| E
  E e6@--> F
  F e7@-->|완료| H
  F e8@-->|취소 또는 실패| G
  H e9@-->|연결 끊김| C
  H e10@-->|다른 계정 또는 대상 무효| K
  H e11@-->|계정과 방·메시지 확인| I
  I e12@--> J
  classDef term fill:#e7f5ff,stroke:#1c7ed6,color:#212529
  classDef proc fill:#f8f9fa,stroke:#495057,color:#212529
  classDef decide fill:#f3f0ff,stroke:#7048e8,color:#212529
  classDef pass stroke:#868e96,stroke-width:1.5px
  class A,C,G,J,K term
  class E,I proc
  class B,D,F,H decide
  class e1,e2,e3,e4,e5,e6,e7,e8,e9,e10,e11,e12 pass
```

| 기호 | 의미 |
| --- | --- |
| 둥근 상자 | 시작 또는 종료 상태 |
| 사각형 | 사용자 동작 또는 시스템 처리 |
| 마름모 | 관찰 결과나 사용자 선택 |
| 실선 화살표 | 다음 단계 또는 종료 상태 |

## 기존 흐름과의 차이

[FL-176](FL-176-web-inbox.md)은 사용자가 웹을 직접 열면 안 읽은 글을 보여 줍니다. 이 흐름은 보낸 알림에서 같은 기존 방으로 들어오는 경로를 추가합니다. 로그인 만료는 [FL-171](FL-171-add-device.md), Android 알림 누르기는 기존 [SPEC-122·146](../app-chat.md)을 사용합니다.

## 확인 조건

알림에 들어 있는 정보만으로 대화 내용은 공개되지 않습니다. 다른 계정으로 로그인하거나 대상이 없어진 경우에는 방이나 메시지 내용을 노출하지 않습니다. 연결 뒤 다시 열면 로그인·대상 확인을 새로 합니다. 방 안에서 대상 글을 어디에 표시할지는 03의 이동 의미를 유지하며 08에서 정합니다.

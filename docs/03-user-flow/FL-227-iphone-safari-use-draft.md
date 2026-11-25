# FL-227 일반 Safari에서 기존 웹 기능 사용

03단계 초안 · CTX-001·002·026 · [02 고정 요구사항](../02-prd/iphone-home-webapp-notifications-version-candidate.md)

연결 요구사항 REQ-640, REQ-669.

일반 Safari에서는 기존 가입·글 대화·통화로 바로 들어갈 수 있습니다. 웹앱 설치와 알림 허용은 알림을 원할 때 선택합니다.

```mermaid
flowchart TB
  %% legend: below
  subgraph Lane1["① 일반 Safari 이용"]
    A(["일반<br/>Safari에서<br/>마롱이 열기<br/>REQ-669"])
    B{"무엇을 하려<br/>하나요?<br/>REQ-640 REQ-669"}
  end
  subgraph Lane2["② 기존 사용자 경로"]
    C(["기존 가입<br/>또는 로그인<br/>REQ-669<br/>SCR-163<br/>SCR-164"])
    D(["기존 글 대화<br/>사용<br/>REQ-669<br/>SCR-107"])
    E(["기존 통화<br/>걸기 또는<br/>받기<br/>REQ-669<br/>SCR-001<br/>SCR-002"])
    F(["FL-220 설치<br/>안내 보기<br/>REQ-640"])
  end
  A e1@--> B
  B e2@-->|가입·재로그인| C
  B e3@-->|글 쓰기·조회| D
  B e4@-->|통화| E
  B e5@-->|웹 알림 안내| F
  classDef term fill:#e7f5ff,stroke:#1c7ed6,color:#212529
  classDef decide fill:#f3f0ff,stroke:#7048e8,color:#212529
  classDef pass stroke:#868e96,stroke-width:1.5px
  class A,C,D,E,F term
  class B decide
  class e1,e2,e3,e4,e5 pass
```

| 기호 | 의미 |
| --- | --- |
| 둥근 상자 | 시작 또는 종료 상태 |
| 마름모 | 관찰 결과나 사용자 선택 |
| 실선 화살표 | 다음 단계 또는 종료 상태 |

## 기존 흐름과의 차이

[FL-169](FL-169-invite-join.md)·[FL-171](FL-171-add-device.md)의 인증, [FL-176](FL-176-web-inbox.md)의 기존 방 조회, [FL-002](FL-002-call.md)의 전화 걸기를 회귀 확인합니다. 기존 웹을 직접 열었을 때 유효한 약속 전화 받기 버튼도 확인합니다. [기존 FL-111](../app-ring.md#3-사용자-흐름-03)

## 확인 조건

계정 인증·기존 마이크 권한·유효 시간은 기존 흐름을 따릅니다. 일반 탭에서 로그인·기기 코드·글 전송과 조회·통화 걸기·직접 받기가 가능한지 검증합니다. 아이폰 경로에서 잠금과 망 전환이 생긴 뒤에는 FL-226을 별도로 확인합니다.

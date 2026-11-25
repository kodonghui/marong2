# FL-226 잠금이나 앱 전환 뒤 통화로 돌아가기

03단계 초안 · CTX-002 · [02 고정 요구사항](../02-prd/iphone-home-webapp-notifications-version-candidate.md)

연결 요구사항 REQ-672, REQ-673.

현재 연결이 살아 있으면 이어서 쓰고, 재연결 가능한 같은 클라이언트의 단절은 같은 통화로 복구합니다. 종료된 통화는 다시 걸기로 이어집니다.

```mermaid
flowchart TB
  %% legend: below
  subgraph Lane1["① 사용자 복귀"]
    A(["잠금 해제<br/>또는 앱 복귀<br/>REQ-672 REQ-673"])
    B{"기존 통화<br/>연결 상태는?<br/>REQ-672 REQ-673"}
  end
  subgraph Lane2["② 기존 통화 판정"]
    C(["기존 통화<br/>계속 사용<br/>REQ-672<br/>SCR-002"])
    D["같은 통화로<br/>재연결 요청<br/>REQ-672"]
    E{"재연결<br/>결과는?<br/>REQ-672 REQ-673"}
    F(["같은 통화에서<br/>대화 재개<br/>REQ-672<br/>SCR-002"])
    G(["연결 확인 뒤<br/>다시 시도<br/>REQ-672"])
    H(["기존 다른<br/>기기 통화<br/>안내<br/>REQ-672"])
    I["기존 다시<br/>걸기 안내<br/>REQ-673"]
    J(["FL-002에서<br/>다시 걸기<br/>REQ-673<br/>SCR-001"])
    K{"다시 걸기를<br/>선택했나요?<br/>REQ-673"}
    L(["통화 없이<br/>종료<br/>REQ-673"])
  end
  A e1@--> B
  B e2@-->|아직 연결됨| C
  B e3@-->|살아 있는 같은 클라이언트| D
  B e4@-->|페이지 또는 통화 종료| I
  B e5@-->|연결 확인 불가| G
  D e6@--> E
  E e7@-->|같은 통화 복구| F
  E e8@-->|망 단절로 확인 불가| G
  E e9@-->|실제 다른 기기 통화 중| H
  E e10@-->|재연결 조건 상실| I
  B e11@-->|실제 다른 기기 통화 중| H
  I e12@--> K
  K e13@-->|예| J
  K e14@-->|아니요| L
  classDef term fill:#e7f5ff,stroke:#1c7ed6,color:#212529
  classDef proc fill:#f8f9fa,stroke:#495057,color:#212529
  classDef decide fill:#f3f0ff,stroke:#7048e8,color:#212529
  classDef pass stroke:#868e96,stroke-width:1.5px
  class A,C,F,G,H,J,L term
  class D,I proc
  class B,E,K decide
  class e1,e2,e3,e4,e5,e6,e7,e8,e9,e10,e11,e12,e13,e14 pass
```

| 기호 | 의미 |
| --- | --- |
| 둥근 상자 | 시작 또는 종료 상태 |
| 사각형 | 사용자 동작 또는 시스템 처리 |
| 마름모 | 관찰 결과나 사용자 선택 |
| 실선 화살표 | 다음 단계 또는 종료 상태 |

## 기존 흐름과의 차이

[FL-004](FL-004-reconnect.md)와 [SPEC-386](../04-functional-spec/unified.md#39-목소리와-동시-통화spec-385-spec-386)의 같은 클라이언트 재연결을 적용합니다. [BUG-114·TC-643](../12-qa/BUG-114-web-call-reconnect.md)의 알려진 회귀 검증을 일반 Safari와 홈 화면 웹앱에서 각각 확인합니다.

## 확인 조건

잠금·앱 전환·망 전환은 각각 시험합니다. 같은 클라이언트임을 확인할 수 있는 경우의 통화 ID와 양방향 오디오 성공을 기록합니다. 운영체제가 페이지를 닫거나 서버가 통화를 종료한 경우와 다른 기기가 실제 통화 중인 경우를 나눕니다. 이 흐름은 잠금 중 오디오 지속을 약속하지 않습니다.

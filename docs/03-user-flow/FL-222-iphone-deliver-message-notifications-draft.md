# FL-222 새 답변·선톡·일정 알림 받기

03단계 초안 · CTX-001·026 · [02 고정 요구사항](../02-prd/iphone-home-webapp-notifications-version-candidate.md)

연결 요구사항 REQ-645, REQ-647, REQ-648, REQ-649, REQ-651, REQ-652, REQ-653, REQ-655, REQ-656, REQ-658, REQ-666, REQ-667, REQ-670, REQ-675.

방 기록은 발생한 이벤트당 한 번입니다. 읽고 있다고 확인된 바로 그 설치의 새 답변만 생략하며 다른 기기의 자격과 기록은 별도로 처리합니다.

```mermaid
flowchart TB
  %% legend: below
  subgraph Lane1["① 기존 글 대화 이벤트"]
    A(["방에 알릴<br/>일이 발생<br/>REQ-651 REQ-652<br/>REQ-653"])
    B["기존 결과를<br/>방에 한 번<br/>기록<br/>REQ-655"]
    C{"조회할 방<br/>기록이<br/>있나요?<br/>REQ-651 REQ-652<br/>REQ-653 REQ-655"}
    D(["해당 글의<br/>전송 종료<br/>REQ-655"])
  end
  subgraph Lane2["② 전달 대상과 내용"]
    V["웹과 Android<br/>대상 각각<br/>판단<br/>REQ-645 REQ-670"]
    E{"이 설치는<br/>받을 수<br/>있나요?<br/>REQ-645 REQ-647<br/>REQ-648 REQ-649"}
    F{"이 설치에서<br/>해당 새<br/>답변을 보고<br/>있나요?<br/>REQ-651 REQ-675"}
    G(["이 설치의<br/>전송 생략<br/>REQ-645 REQ-675"])
    H["원문 없는<br/>알림 만들기<br/>REQ-666"]
    I["웹 알림 전송<br/>REQ-651 REQ-652<br/>REQ-653"]
    J(["FL-228의<br/>Android 자격<br/>REQ-670"])
    K["민감값 없이<br/>전송 결과<br/>기록<br/>REQ-667"]
  end
  subgraph Lane3["③ 홈 화면 웹앱 표시"]
    L{"알림을 어떻게<br/>처리하나요?<br/>REQ-649 REQ-656"}
    M["첫 도착만<br/>표시<br/>REQ-656 REQ-666"]
    N(["FL-223에서 열<br/>수 있음<br/>REQ-658"])
    O(["방에 남은<br/>기록으로 확인<br/>REQ-655 REQ-656"])
    P(["FL-221에서<br/>구독 판정<br/>REQ-649 REQ-667"])
  end
  A e1@--> B
  B e2@--> C
  C e3@-->|없음| D
  E e4@-->|자격 없음| G
  E e5@-->|자격 있음| F
  F e6@-->|해당 답변 열람 확인| G
  F e7@-->|답변 확인 없음 또는 다른 유형| H
  H e8@--> I
  I e9@--> K
  K e10@--> L
  L e11@-->|기기에서 첫 도착| M
  L e12@-->|중복·일시 오류 또는 수신 미확인| O
  L e13@-->|영구 무효 또는 만료| P
  M e14@--> N
  C e15@-->|있음| V
  V e16@-->|웹 설치별| E
  V e17@-->|Android 기기별| J
  classDef term fill:#e7f5ff,stroke:#1c7ed6,color:#212529
  classDef proc fill:#f8f9fa,stroke:#495057,color:#212529
  classDef decide fill:#f3f0ff,stroke:#7048e8,color:#212529
  classDef pass stroke:#868e96,stroke-width:1.5px
  class A,D,G,J,N,O,P term
  class B,V,H,I,K,M proc
  class C,E,F,L decide
  class e1,e2,e3,e4,e5,e6,e7,e8,e9,e10,e11,e12,e13,e14,e15,e16,e17 pass
```

| 기호 | 의미 |
| --- | --- |
| 둥근 상자 | 시작 또는 종료 상태 |
| 사각형 | 사용자 동작 또는 시스템 처리 |
| 마름모 | 관찰 결과나 사용자 선택 |
| 실선 화살표 | 다음 단계 또는 종료 상태 |

## 기존 흐름과의 차이

[FL-176](FL-176-web-inbox.md)과 [SPEC-383](../04-functional-spec/unified.md#38-디스코드-없는-보내기-경로spec-383)의 방 기록 경로를 사용합니다. REQ-462 범위 안에서 새 답변·선톡·일정의 웹 알림을 추가합니다. [SPEC-119·120](../app-chat.md)의 Android 글 알림도 기존 자격을 적용합니다.

## 확인 조건

발생 이벤트와 방 기록을 새 스케줄러에서 다시 만들 필요가 없습니다. 유효한 동일 계정·로그인·허용 확인은 설치별로 적용합니다. 푸시 요청 결과와 기기 표시 여부는 따로 검증합니다. 알림 전송에 실패해도 기존 방 기록을 조회할 수 있습니다. 기본 미리보기에는 대화 원문이나 일정 제목이 없습니다. 전송 결과 기록에는 대화 원문·개인 식별값·구독 원본이 없습니다.

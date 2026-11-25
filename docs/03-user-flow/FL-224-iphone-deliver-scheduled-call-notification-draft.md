# FL-224 유효한 약속 전화 알림 받기

03단계 초안 · CTX-020·002·026 · [02 고정 요구사항](../02-prd/iphone-home-webapp-notifications-version-candidate.md)

연결 요구사항 REQ-645, REQ-648, REQ-649, REQ-654, REQ-656, REQ-660, REQ-665, REQ-666, REQ-667, REQ-670.

기존 약속 전화 한 건에 대해 웹앱의 전송 자격과 기한을 확인합니다. 알림이 도착해도 통화 수락은 시작되지 않습니다.

```mermaid
flowchart TB
  %% legend: below
  subgraph Lane1["① 기존 일정 처리"]
    A(["기존 전화<br/>약속 시각<br/>도래<br/>REQ-654"])
    B{"받을 수 있는<br/>전화가<br/>생겼나요?<br/>REQ-654 REQ-665"}
    C(["새 웹 전화<br/>알림 없음<br/>REQ-654 REQ-665"])
    D(["FL-228로<br/>Android 처리<br/>REQ-670"])
  end
  subgraph Lane2["② 웹앱의 전송 자격"]
    P["웹과 Android<br/>대상 각각<br/>판단<br/>REQ-645 REQ-670"]
    E{"계정과 설치가<br/>받을 수<br/>있나요?<br/>REQ-645 REQ-648"}
    F{"전송 시점까지<br/>유효한가요?<br/>REQ-665"}
    G["일정 제목과<br/>할 말 제외<br/>REQ-666"]
    H["기기별 웹<br/>알림 전송<br/>REQ-654"]
    I["민감값 없이<br/>전송 결과<br/>기록<br/>REQ-667"]
  end
  subgraph Lane3["③ 도착 결과"]
    J{"알림의<br/>도착·전송<br/>결과는?<br/>REQ-649 REQ-656"}
    K["첫 도착만<br/>표시<br/>REQ-656"]
    L(["탭할 때<br/>FL-225로 이동<br/>REQ-660"])
    M(["새 표시 없이<br/>종료<br/>REQ-656"])
    N(["FL-221에서<br/>구독 판정<br/>REQ-649 REQ-667"])
  end
  A e1@--> B
  B e2@-->|통화 중·대기 중 또는 전화 불가| C
  E e3@-->|자격 없음| C
  E e4@-->|자격 있음| F
  F e5@-->|만료| C
  F e6@-->|유효| G
  G e7@--> H
  H e8@--> I
  I e9@--> J
  J e10@-->|기기에서 첫 도착| K
  J e11@-->|중복·일시 오류 또는 수신 미확인| M
  J e12@-->|영구 무효 또는 만료| N
  K e13@--> L
  B e14@-->|응답 가능| P
  P e15@-->|웹 설치별| E
  P e16@-->|Android 기기별| D
  classDef term fill:#e7f5ff,stroke:#1c7ed6,color:#212529
  classDef proc fill:#f8f9fa,stroke:#495057,color:#212529
  classDef decide fill:#f3f0ff,stroke:#7048e8,color:#212529
  classDef pass stroke:#868e96,stroke-width:1.5px
  class A,C,D,L,M,N term
  class P,G,H,I,K proc
  class B,E,F,J decide
  class e1,e2,e3,e4,e5,e6,e7,e8,e9,e10,e11,e12,e13,e14,e15,e16 pass
```

| 기호 | 의미 |
| --- | --- |
| 둥근 상자 | 시작 또는 종료 상태 |
| 사각형 | 사용자 동작 또는 시스템 처리 |
| 마름모 | 관찰 결과나 사용자 선택 |
| 실선 화살표 | 다음 단계 또는 종료 상태 |

## 기존 흐름과의 차이

[기존 약속 전화 FL-110·111](../app-ring.md#3-사용자-흐름-03)과 [FL-176](FL-176-web-inbox.md)의 유효한 벨을 재사용합니다. 알림을 받을 수 있는 홈 화면 웹앱으로만 웹 전송을 추가합니다. 선 전화 [FL-142](FL-142-hello-call.md)는 기존 정책 범위입니다.

## 확인 조건

웹 전송 전에 이미 만료됐으면 새 전화 알림은 0건입니다. 공급자에게 건넨 뒤 늦게 도착한 알림은 [FL-225](FL-225-iphone-answer-call-notification-draft.md)에서 현재 상태를 다시 봅니다. 벨의 응답 기한 숫자와 같은 전화의 전송별 정책은 기술 계약으로 남깁니다.

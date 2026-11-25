# FL-221 웹 알림 구독 확인·변경·해제

03단계 초안 · CTX-026 · [02 고정 요구사항](../02-prd/iphone-home-webapp-notifications-version-candidate.md)

연결 요구사항 REQ-642, REQ-644, REQ-646, REQ-647, REQ-648, REQ-649, REQ-650, REQ-667, REQ-668.

사용자가 구독을 관리할 때는 현재 계정과 설치를 확인합니다. 철회, 로그인 종료, 영구 무효는 해당 구독만 새 전송에서 제외합니다.

```mermaid
flowchart TB
  %% legend: below
  subgraph Lane1["① 상태 변경의 시작"]
    A(["구독 상태<br/>확인 또는<br/>변경<br/>REQ-642"])
    B{"무엇이<br/>발생했나요?<br/>REQ-642 REQ-646<br/>REQ-647 REQ-648<br/>REQ-649"}
    C{"계정과 설치<br/>권한이<br/>유효한가요?<br/>REQ-668"}
    D(["접근 거절<br/>REQ-668"])
  end
  subgraph Lane2["② 사용자가 관리"]
    E["이 설치의<br/>상태 표시<br/>REQ-642"]
    F{"어떤 작업을<br/>선택하나요?<br/>REQ-642 REQ-647<br/>REQ-650"}
    G["이 설치의<br/>수신 해제<br/>REQ-647"]
    H["알림 다시<br/>켜기 선택<br/>REQ-650"]
    I(["FL-220에서<br/>다시 등록<br/>REQ-644 REQ-650"])
    J(["상태 확인<br/>완료<br/>REQ-642"])
  end
  subgraph Lane3["③ 시스템 상태 반영"]
    M{"구독 갱신에<br/>성공했나요?<br/>REQ-646"}
    N["이전 구독을<br/>새 구독으로<br/>대체<br/>REQ-646"]
    O(["갱신 상태<br/>안내<br/>REQ-642 REQ-646"])
    P["해당<br/>로그인으로 새<br/>전송 차단<br/>REQ-648"]
    Q["해당 구독만<br/>전송에서 제외<br/>REQ-647 REQ-649"]
    R(["다른 설치의<br/>수신 유지<br/>REQ-647 REQ-648<br/>REQ-649"])
    S(["일시 오류로<br/>기록<br/>REQ-649 REQ-667"])
    T{"동일 설치<br/>권한이<br/>있나요?<br/>REQ-646 REQ-668"}
    U["대상 구독의<br/>무효화<br/>REQ-649"]
  end
  A e1@--> B
  B e2@-->|설정을 엶| C
  B e3@-->|구독 정보 변경| T
  B e4@-->|OS 철회 확인| Q
  B e5@-->|로그아웃 또는 로그인 종료| P
  B e6@-->|만료 또는 영구 무효 확인| U
  B e7@-->|일시 오류| S
  C e8@-->|예| E
  C e9@-->|아니요| D
  E e10@--> F
  F e11@-->|조회만| J
  F e12@-->|수신 해제| G
  F e13@-->|다시 켜기| H
  G e14@--> Q
  H e15@--> I
  T e16@-->|예| M
  M e17@-->|예| N
  M e18@-->|아니요| O
  N e19@--> O
  P e20@--> R
  Q e21@--> R
  U e22@--> R
  T e23@-->|아니요| D
  classDef term fill:#e7f5ff,stroke:#1c7ed6,color:#212529
  classDef proc fill:#f8f9fa,stroke:#495057,color:#212529
  classDef decide fill:#f3f0ff,stroke:#7048e8,color:#212529
  classDef pass stroke:#868e96,stroke-width:1.5px
  class A,D,I,J,O,R,S term
  class E,G,H,N,P,Q,U proc
  class B,C,F,M,T decide
  class e1,e2,e3,e4,e5,e6,e7,e8,e9,e10,e11,e12,e13,e14,e15,e16,e17,e18,e19,e20,e21,e22,e23 pass
```

| 기호 | 의미 |
| --- | --- |
| 둥근 상자 | 시작 또는 종료 상태 |
| 사각형 | 사용자 동작 또는 시스템 처리 |
| 마름모 | 관찰 결과나 사용자 선택 |
| 실선 화살표 | 다음 단계 또는 종료 상태 |

## 기존 흐름과의 차이

[FL-171](FL-171-add-device.md)의 로그인 경로와 [SPEC-371·374](../04-functional-spec/unified.md)의 계정 확인을 사용합니다. Android 기기 보고·FCM 등록 해제와 별개로 웹 구독의 상태를 다룹니다. [Android 상태 보고 FL-194](FL-194-app-update-report.md) · [FCM 등록 해제 요구사항](../02-prd/fcm-unregistered.md)

## 확인 조건

설정에서 해제를 마쳤거나 웹이 OS 권한 철회를 확인한 뒤에는 해당 웹앱의 새 전송을 막습니다. 이미 공급자에게 전달된 알림을 회수하는 동작은 전제하지 않습니다. 알림을 다시 누르면 [글 FL-223](FL-223-iphone-open-message-notification-draft.md) 또는 [전화 FL-225](FL-225-iphone-answer-call-notification-draft.md)에서 로그인·계정을 검증합니다. 영구 무효와 일시 오류의 판정, 갱신 실패 뒤 기존 구독의 유효성 판단은 계약 단계로 넘깁니다.

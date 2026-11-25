# FL-220 아이폰 홈 화면에 추가하고 알림 허용

03단계 초안 · CTX-026 · [02 고정 요구사항](../02-prd/iphone-home-webapp-notifications-version-candidate.md)

연결 요구사항 REQ-640, REQ-641, REQ-642, REQ-643, REQ-644, REQ-650, REQ-668, REQ-669, REQ-671, REQ-674.

일반 Safari에서는 설치를 안내합니다. 지원되는 홈 화면 웹앱에서 로그인한 사용자가 알림을 선택할 때만 권한 요청으로 이어집니다.

```mermaid
flowchart TB
  %% legend: below
  subgraph Lane1["① 설치와 실행"]
    A(["웹 알림을<br/>쓰려 함<br/>REQ-640"])
    B{"어디에서<br/>열었나요?<br/>REQ-640 REQ-671"}
    C["홈 화면 추가<br/>안내<br/>REQ-640"]
    D{"홈 화면에<br/>추가하나요?<br/>REQ-640 REQ-669"}
    E["홈 화면<br/>아이콘 열기<br/>REQ-671"]
    F(["일반 Safari<br/>계속 이용<br/>REQ-669 REQ-674"])
  end
  subgraph Lane2["② 지원과 로그인"]
    G["알림 설정<br/>상태 확인<br/>REQ-642"]
    H{"사용 가능<br/>상태는?<br/>REQ-642 REQ-674"}
    I["알림 없이<br/>이용 안내<br/>REQ-674"]
    J(["연결 필요<br/>상태<br/>REQ-642"])
    K{"로그인이<br/>유효한가요?<br/>REQ-644 REQ-668"}
    L["기존<br/>로그인으로<br/>이동<br/>REQ-644 REQ-668<br/>SCR-164"]
    M{"로그인을<br/>마쳤나요?<br/>REQ-644 REQ-668"}
    N(["알림 설정<br/>종료<br/>REQ-642"])
  end
  subgraph Lane3["③ 권한과 활성화"]
    O{"권한과 구독<br/>상태는?<br/>REQ-642 REQ-643<br/>REQ-644"}
    P["OS 설정에서<br/>변경 안내<br/>REQ-643"]
    Q{"알림 켜기를<br/>선택했나요?<br/>REQ-641 REQ-650"}
    R{"OS 권한이<br/>필요한가요?<br/>REQ-641"}
    S["시스템 권한<br/>요청<br/>REQ-641"]
    T{"알림을<br/>허용했나요?<br/>REQ-641 REQ-643"}
    U["계정과 설치의<br/>구독 등록<br/>REQ-644 REQ-650<br/>REQ-668"]
    V{"구독 등록에<br/>성공했나요?<br/>REQ-642 REQ-644"}
    W(["알림 수신<br/>가능<br/>REQ-642 REQ-644<br/>REQ-650"])
    X(["등록 미완료<br/>안내<br/>REQ-642"])
  end
  A e1@--> B
  B e2@-->|일반 Safari| C
  B e3@-->|홈 화면 웹앱| E
  C e4@--> D
  D e5@-->|예| E
  D e6@-->|아니요| F
  E e7@--> G
  G e8@--> H
  H e9@-->|미지원| I
  H e10@-->|오프라인| J
  H e11@-->|지원| K
  I e12@--> F
  K e13@-->|예| O
  K e14@-->|아니요| L
  L e15@--> M
  M e16@-->|완료| O
  M e17@-->|취소 또는 실패| N
  O e18@-->|거부| P
  O e19@-->|허용과 등록 완료| W
  O e20@-->|허용 전 또는 등록 필요| Q
  P e21@--> N
  Q e22@-->|예| R
  Q e23@-->|아니요| N
  R e24@-->|아직 응답 없음| S
  R e25@-->|이미 허용| U
  S e26@--> T
  T e27@-->|허용| U
  T e28@-->|거부| P
  T e29@-->|응답 없이 닫음| N
  U e30@--> V
  V e31@-->|예| W
  V e32@-->|아니요| X
  classDef term fill:#e7f5ff,stroke:#1c7ed6,color:#212529
  classDef proc fill:#f8f9fa,stroke:#495057,color:#212529
  classDef decide fill:#f3f0ff,stroke:#7048e8,color:#212529
  classDef pass stroke:#868e96,stroke-width:1.5px
  class A,F,J,N,W,X term
  class C,E,G,I,L,P,S,U proc
  class B,D,H,K,M,O,Q,R,T,V decide
  class e1,e2,e3,e4,e5,e6,e7,e8,e9,e10,e11,e12,e13,e14,e15,e16,e17,e18,e19,e20,e21,e22,e23,e24,e25,e26,e27,e28,e29,e30,e31,e32 pass
```

| 기호 | 의미 |
| --- | --- |
| 둥근 상자 | 시작 또는 종료 상태 |
| 사각형 | 사용자 동작 또는 시스템 처리 |
| 마름모 | 관찰 결과나 사용자 선택 |
| 실선 화살표 | 다음 단계 또는 종료 상태 |

## 기존 흐름과의 차이

[FL-169](FL-169-invite-join.md)·[FL-171](FL-171-add-device.md)의 가입·로그인을 사용합니다. [SPEC-396](../04-functional-spec/unified.md)의 manifest와 기존 홈 화면 아이콘 진입을 이어 가며 권한 허용 흐름을 추가합니다. 기존에 추가한 아이콘과 새 아이콘, 설치 전후 로그인 상태는 실기기에서 각각 확인합니다.

## 확인 조건

권한 허용과 서버 구독 등록 성공은 다른 상태입니다. 이미 거부한 사용자는 OS 설정에서 권한을 바꿀 수 있고, 기존 웹 이용은 [FL-227](FL-227-iphone-safari-use-draft.md)로 이어집니다. 미지원 여부를 결정할 최소 iOS 버전과 감지 방법은 04·06에서 정합니다.

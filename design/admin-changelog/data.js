// 목업 자료(API-300 모양). 맨 위 '(예시)' 단위와 long 상태는 지어낸 줄이고, 나머지는 docs/10-wbs/admin-changelog-backfill.md의 실제 지난 내역 줄이에요.
window.MOCK_CHANGES = {
 "normal": {
  "units": [
   {
    "id": "20261127-changes",
    "kind": "server",
    "title": "업데이트 내역 화면(예시)",
    "deployedOn": "2026-11-27",
    "sortOn": "2026-11-27",
    "app": null,
    "backfilled": false,
    "evidence": [
     {
      "label": "PR #130",
      "url": "https://github.com/kodonghui/marong2/pull/130"
     }
    ],
    "items": [
     {
      "type": "added",
      "area": "admin",
      "title": "업데이트 내역 탭(예시)",
      "before": "없음",
      "after": "관리 페이지 끝에 업데이트 내역 탭이 생겨 바뀐 것을 변경 전·후로 봐요",
      "evidence": [
       {
        "label": "PR #130",
        "url": "https://github.com/kodonghui/marong2/pull/130"
       }
      ]
     },
     {
      "type": "fixed",
      "area": "web",
      "title": "예시 줄",
      "before": "지어낸 예시 글이에요. 실제 반영이 아니에요",
      "after": "화면 모양을 보려고 넣은 줄이에요",
      "evidence": [
       {
        "label": "PR #130",
        "url": "https://github.com/kodonghui/marong2/pull/130"
       }
      ]
     }
    ]
   },
   {
    "id": "20261124-bug-124",
    "kind": "server",
    "title": "관리 아이템 화면 열기",
    "deployedOn": "2026-11-24",
    "sortOn": "2026-11-24",
    "app": null,
    "backfilled": true,
    "evidence": [
     {
      "label": "PR #125",
      "url": "https://github.com/kodonghui/marong2/pull/125"
     },
     {
      "label": "PR #126",
      "url": "https://github.com/kodonghui/marong2/pull/126"
     }
    ],
    "items": [
     {
      "type": "fixed",
      "area": "admin",
      "title": "아이템 탭",
      "before": "관리 페이지의 아이템 탭을 누르면 404였어요",
      "after": "아이템 탭이 열려요",
      "evidence": [
       {
        "label": "PR #125",
        "url": "https://github.com/kodonghui/marong2/pull/125"
       },
       {
        "label": "PR #126",
        "url": "https://github.com/kodonghui/marong2/pull/126"
       }
      ]
     }
    ]
   },
   {
    "id": "20261124-bug123",
    "kind": "server",
    "title": "글 대화 빈 스크롤 고침",
    "deployedOn": "2026-11-24",
    "sortOn": "2026-11-24",
    "app": null,
    "backfilled": true,
    "evidence": [
     {
      "label": "PR #123",
      "url": "https://github.com/kodonghui/marong2/pull/123"
     },
     {
      "label": "PR #124",
      "url": "https://github.com/kodonghui/marong2/pull/124"
     }
    ],
    "items": [
     {
      "type": "fixed",
      "area": "web",
      "title": "대답 중 빈 스크롤",
      "before": "대답하는 동안 글 대화 아래에 빈 스크롤이 생겼어요",
      "after": "빈 스크롤 없이 대답이 이어져요",
      "evidence": [
       {
        "label": "PR #123",
        "url": "https://github.com/kodonghui/marong2/pull/123"
       },
       {
        "label": "PR #124",
        "url": "https://github.com/kodonghui/marong2/pull/124"
       }
      ]
     }
    ]
   },
   {
    "id": "20261124-bug118-122",
    "kind": "server",
    "title": "통화 기록 고침",
    "deployedOn": "2026-11-24",
    "sortOn": "2026-11-24",
    "app": null,
    "backfilled": true,
    "evidence": [
     {
      "label": "PR #119",
      "url": "https://github.com/kodonghui/marong2/pull/119"
     },
     {
      "label": "PR #122",
      "url": "https://github.com/kodonghui/marong2/pull/122"
     }
    ],
    "items": [
     {
      "type": "fixed",
      "area": "call",
      "title": "다시 이은 통화의 시작 시각",
      "before": "통화를 다시 이으면 시작 시각이 바뀌었어요",
      "after": "다시 이어도 처음 시작 시각(한국 시각)을 지켜요",
      "evidence": [
       {
        "label": "PR #119",
        "url": "https://github.com/kodonghui/marong2/pull/119"
       },
       {
        "label": "PR #122",
        "url": "https://github.com/kodonghui/marong2/pull/122"
       }
      ]
     },
     {
      "type": "fixed",
      "area": "call",
      "title": "통화 인사 자막",
      "before": "앱의 인사 지시가 자막 기록에 남았어요",
      "after": "인사 지시는 한 번만 보내고 자막에 남기지 않아요",
      "evidence": [
       {
        "label": "PR #119",
        "url": "https://github.com/kodonghui/marong2/pull/119"
       },
       {
        "label": "PR #122",
        "url": "https://github.com/kodonghui/marong2/pull/122"
       }
      ]
     },
     {
      "type": "improved",
      "area": "call",
      "title": "짧은 통화의 기억",
      "before": "기록 없음",
      "after": "친구 말이 20자보다 짧은 통화는 기억 카드를 만들지 않아요",
      "evidence": [
       {
        "label": "PR #119",
        "url": "https://github.com/kodonghui/marong2/pull/119"
       },
       {
        "label": "PR #122",
        "url": "https://github.com/kodonghui/marong2/pull/122"
       }
      ]
     }
    ]
   },
   {
    "id": "20261124-admin",
    "kind": "server",
    "title": "관리 페이지 다시 만들기",
    "deployedOn": "2026-11-24",
    "sortOn": "2026-11-24",
    "app": null,
    "backfilled": true,
    "evidence": [
     {
      "label": "PR #116",
      "url": "https://github.com/kodonghui/marong2/pull/116"
     },
     {
      "label": "PR #117",
      "url": "https://github.com/kodonghui/marong2/pull/117"
     },
     {
      "label": "PR #121",
      "url": "https://github.com/kodonghui/marong2/pull/121"
     }
    ],
    "items": [
     {
      "type": "improved",
      "area": "admin",
      "title": "관리 페이지 화면 나누기",
      "before": "관리자 화면 하나에 초대 링크·회원·비용이 함께 있었어요",
      "after": "개요·회원·초대 링크·앱 버전·비용·아이템 여섯 탭으로 나눠 봐요",
      "evidence": [
       {
        "label": "PR #116",
        "url": "https://github.com/kodonghui/marong2/pull/116"
       },
       {
        "label": "PR #117",
        "url": "https://github.com/kodonghui/marong2/pull/117"
       },
       {
        "label": "PR #121",
        "url": "https://github.com/kodonghui/marong2/pull/121"
       }
      ]
     },
     {
      "type": "added",
      "area": "admin",
      "title": "개요의 손볼 일",
      "before": "없음",
      "after": "개요 맨 위에 손볼 일(예산 80%, 뒤처진 폰, 곧 끝나는 링크)이 보여요",
      "evidence": [
       {
        "label": "PR #116",
        "url": "https://github.com/kodonghui/marong2/pull/116"
       }
      ]
     },
     {
      "type": "added",
      "area": "admin",
      "title": "초대 링크 거두기",
      "before": "없음",
      "after": "열린 초대 링크를 거둬요",
      "evidence": [
       {
        "label": "PR #117",
        "url": "https://github.com/kodonghui/marong2/pull/117"
       }
      ]
     }
    ]
   },
   {
    "id": "20261124-bug114",
    "kind": "server",
    "title": "웹 통화 다시 잇기",
    "deployedOn": "2026-11-24",
    "sortOn": "2026-11-24",
    "app": null,
    "backfilled": true,
    "evidence": [
     {
      "label": "PR #115",
      "url": "https://github.com/kodonghui/marong2/pull/115"
     },
     {
      "label": "PR #118",
      "url": "https://github.com/kodonghui/marong2/pull/118"
     }
    ],
    "items": [
     {
      "type": "fixed",
      "area": "call",
      "title": "같은 웹에서 다시 잇기",
      "before": "같은 웹 화면에서 통화가 끊긴 뒤 다시 이어지지 않았어요",
      "after": "같은 웹 화면에서 다시 이어져요",
      "evidence": [
       {
        "label": "PR #115",
        "url": "https://github.com/kodonghui/marong2/pull/115"
       },
       {
        "label": "PR #118",
        "url": "https://github.com/kodonghui/marong2/pull/118"
       }
      ]
     }
    ]
   },
   {
    "id": "20261123-bug113",
    "kind": "server",
    "title": "늦게 뜬 화면의 업데이트 배너",
    "deployedOn": "2026-11-23",
    "sortOn": "2026-11-23",
    "app": null,
    "backfilled": true,
    "evidence": [
     {
      "label": "PR #111",
      "url": "https://github.com/kodonghui/marong2/pull/111"
     }
    ],
    "items": [
     {
      "type": "fixed",
      "area": "web",
      "title": "늦게 뜬 화면의 배너",
      "before": "늦게 로드된 화면에는 업데이트 배너가 보이지 않았어요",
      "after": "늦게 로드된 화면에도 배너가 보여요",
      "evidence": [
       {
        "label": "PR #111",
        "url": "https://github.com/kodonghui/marong2/pull/111"
       }
      ]
     }
    ]
   },
   {
    "id": "app-0.3.4",
    "kind": "app",
    "title": "새 버전 바로 받기와 지금 설치",
    "deployedOn": "2026-11-23",
    "sortOn": "2026-11-23",
    "app": {
     "versionName": "0.3.4",
     "versionCode": 12
    },
    "backfilled": true,
    "evidence": [
     {
      "label": "PR #107",
      "url": "https://github.com/kodonghui/marong2/pull/107"
     },
     {
      "label": "PR #110",
      "url": "https://github.com/kodonghui/marong2/pull/110"
     }
    ],
    "items": [
     {
      "type": "improved",
      "area": "app",
      "title": "새 버전 받기",
      "before": "기록 없음",
      "after": "새 버전이 나오면 몇 분 안에 받아 두고, 홈과 글 대화에서 '지금 설치'로 깔아요",
      "evidence": [
       {
        "label": "PR #107",
        "url": "https://github.com/kodonghui/marong2/pull/107"
       },
       {
        "label": "PR #110",
        "url": "https://github.com/kodonghui/marong2/pull/110"
       }
      ]
     }
    ]
   },
   {
    "id": "20261119-unified-cutover",
    "kind": "server",
    "title": "통합 앱으로 전환",
    "deployedOn": "2026-11-19",
    "sortOn": "2026-11-19",
    "app": null,
    "backfilled": true,
    "evidence": [
     {
      "label": "PR #54",
      "url": "https://github.com/kodonghui/marong2/pull/54"
     },
     {
      "label": "PR #64",
      "url": "https://github.com/kodonghui/marong2/pull/64"
     }
    ],
    "items": [
     {
      "type": "added",
      "area": "web",
      "title": "초대 링크 가입과 내 마롱이",
      "before": "없음",
      "after": "초대 링크로 가입하고, 사람마다 자기 마롱이(이름·목소리)를 가져요. 전에는 모두 같은 마롱이였어요",
      "evidence": [
       {
        "label": "PR #54",
        "url": "https://github.com/kodonghui/marong2/pull/54"
       },
       {
        "label": "PR #64",
        "url": "https://github.com/kodonghui/marong2/pull/64"
       }
      ]
     },
     {
      "type": "added",
      "area": "call",
      "title": "목소리 고르기와 동시 통화",
      "before": "없음",
      "after": "통화 목소리를 고르고, 세 사람까지 동시에 통화해요",
      "evidence": [
       {
        "label": "PR #54",
        "url": "https://github.com/kodonghui/marong2/pull/54"
       },
       {
        "label": "PR #64",
        "url": "https://github.com/kodonghui/marong2/pull/64"
       }
      ]
     },
     {
      "type": "removed",
      "area": "legacy",
      "title": "디스코드 봇",
      "before": "디스코드 DM·서버 채널·음성 방에서 마롱이와 대화하고 통화했어요",
      "after": "없음",
      "evidence": [
       {
        "label": "PR #54",
        "url": "https://github.com/kodonghui/marong2/pull/54"
       },
       {
        "label": "PR #64",
        "url": "https://github.com/kodonghui/marong2/pull/64"
       }
      ]
     },
     {
      "type": "improved",
      "area": "admin",
      "title": "관리자 화면 잠금",
      "before": "기록 없음",
      "after": "Cloudflare Access 로그인은 관리자 화면(/chat/admin)에만 걸려요",
      "evidence": [
       {
        "label": "PR #54",
        "url": "https://github.com/kodonghui/marong2/pull/54"
       },
       {
        "label": "PR #64",
        "url": "https://github.com/kodonghui/marong2/pull/64"
       }
      ]
     }
    ]
   },
   {
    "id": "20261115-pr15",
    "kind": "server",
    "title": "통화: 끊어 달라면 인사하고 끊기",
    "deployedOn": "2026-11-15",
    "sortOn": "2026-11-15",
    "app": null,
    "backfilled": true,
    "evidence": [
     {
      "label": "PR #15",
      "url": "https://github.com/kodonghui/marong2/pull/15"
     }
    ],
    "items": [
     {
      "type": "improved",
      "area": "call",
      "title": "통화 끊기",
      "before": "친구가 꺼 달라고 해도 마롱이는 대답만 하고 끊지 못했어요",
      "after": "끊어 달라고 하면 인사하고 끊고, 스스로 먼저 끊지는 않아요",
      "evidence": [
       {
        "label": "PR #15",
        "url": "https://github.com/kodonghui/marong2/pull/15"
       }
      ]
     }
    ]
   },
   {
    "id": "20261026-pr1",
    "kind": "server",
    "title": "카톡: 1:1 얘기 나누기와 연달아 온 말",
    "deployedOn": null,
    "sortOn": "2026-10-26",
    "app": null,
    "backfilled": true,
    "evidence": [
     {
      "label": "PR #1",
      "url": "https://github.com/kodonghui/marong2/pull/1"
     },
     {
      "label": "PR #2",
      "url": "https://github.com/kodonghui/marong2/pull/2"
     }
    ],
    "items": [
     {
      "type": "improved",
      "area": "legacy",
      "title": "1:1에서 한 얘기 나누기",
      "before": "한 친구가 1:1에서 한 얘기를 다른 친구의 1:1에서 마롱이가 몰랐어요(요약이 쌓일 때만 메모를 만듦)",
      "after": "1:1에서 한 얘기를 바로 공유해서 다른 친구와의 대화에서도 알아요",
      "evidence": [
       {
        "label": "PR #1",
        "url": "https://github.com/kodonghui/marong2/pull/1"
       }
      ]
     },
     {
      "type": "improved",
      "area": "legacy",
      "title": "연달아 온 말에 한 번에 답하기",
      "before": "기록 없음",
      "after": "연달아 온 말을 묶어 한 번에 답하고, 단체방에서는 친구마다 따로 묶어요",
      "evidence": [
       {
        "label": "PR #1",
        "url": "https://github.com/kodonghui/marong2/pull/1"
       },
       {
        "label": "PR #2",
        "url": "https://github.com/kodonghui/marong2/pull/2"
       }
      ]
     }
    ]
   }
  ],
  "skipped": 0
 },
 "skipped": {
  "units": [
   {
    "id": "20261127-changes",
    "kind": "server",
    "title": "업데이트 내역 화면(예시)",
    "deployedOn": "2026-11-27",
    "sortOn": "2026-11-27",
    "app": null,
    "backfilled": false,
    "evidence": [
     {
      "label": "PR #130",
      "url": "https://github.com/kodonghui/marong2/pull/130"
     }
    ],
    "items": [
     {
      "type": "added",
      "area": "admin",
      "title": "업데이트 내역 탭(예시)",
      "before": "없음",
      "after": "관리 페이지 끝에 업데이트 내역 탭이 생겨 바뀐 것을 변경 전·후로 봐요",
      "evidence": [
       {
        "label": "PR #130",
        "url": "https://github.com/kodonghui/marong2/pull/130"
       }
      ]
     },
     {
      "type": "fixed",
      "area": "web",
      "title": "예시 줄",
      "before": "지어낸 예시 글이에요. 실제 반영이 아니에요",
      "after": "화면 모양을 보려고 넣은 줄이에요",
      "evidence": [
       {
        "label": "PR #130",
        "url": "https://github.com/kodonghui/marong2/pull/130"
       }
      ]
     }
    ]
   },
   {
    "id": "20261124-bug-124",
    "kind": "server",
    "title": "관리 아이템 화면 열기",
    "deployedOn": "2026-11-24",
    "sortOn": "2026-11-24",
    "app": null,
    "backfilled": true,
    "evidence": [
     {
      "label": "PR #125",
      "url": "https://github.com/kodonghui/marong2/pull/125"
     },
     {
      "label": "PR #126",
      "url": "https://github.com/kodonghui/marong2/pull/126"
     }
    ],
    "items": [
     {
      "type": "fixed",
      "area": "admin",
      "title": "아이템 탭",
      "before": "관리 페이지의 아이템 탭을 누르면 404였어요",
      "after": "아이템 탭이 열려요",
      "evidence": [
       {
        "label": "PR #125",
        "url": "https://github.com/kodonghui/marong2/pull/125"
       },
       {
        "label": "PR #126",
        "url": "https://github.com/kodonghui/marong2/pull/126"
       }
      ]
     }
    ]
   },
   {
    "id": "20261124-bug123",
    "kind": "server",
    "title": "글 대화 빈 스크롤 고침",
    "deployedOn": "2026-11-24",
    "sortOn": "2026-11-24",
    "app": null,
    "backfilled": true,
    "evidence": [
     {
      "label": "PR #123",
      "url": "https://github.com/kodonghui/marong2/pull/123"
     },
     {
      "label": "PR #124",
      "url": "https://github.com/kodonghui/marong2/pull/124"
     }
    ],
    "items": [
     {
      "type": "fixed",
      "area": "web",
      "title": "대답 중 빈 스크롤",
      "before": "대답하는 동안 글 대화 아래에 빈 스크롤이 생겼어요",
      "after": "빈 스크롤 없이 대답이 이어져요",
      "evidence": [
       {
        "label": "PR #123",
        "url": "https://github.com/kodonghui/marong2/pull/123"
       },
       {
        "label": "PR #124",
        "url": "https://github.com/kodonghui/marong2/pull/124"
       }
      ]
     }
    ]
   },
   {
    "id": "20261124-bug118-122",
    "kind": "server",
    "title": "통화 기록 고침",
    "deployedOn": "2026-11-24",
    "sortOn": "2026-11-24",
    "app": null,
    "backfilled": true,
    "evidence": [
     {
      "label": "PR #119",
      "url": "https://github.com/kodonghui/marong2/pull/119"
     },
     {
      "label": "PR #122",
      "url": "https://github.com/kodonghui/marong2/pull/122"
     }
    ],
    "items": [
     {
      "type": "fixed",
      "area": "call",
      "title": "다시 이은 통화의 시작 시각",
      "before": "통화를 다시 이으면 시작 시각이 바뀌었어요",
      "after": "다시 이어도 처음 시작 시각(한국 시각)을 지켜요",
      "evidence": [
       {
        "label": "PR #119",
        "url": "https://github.com/kodonghui/marong2/pull/119"
       },
       {
        "label": "PR #122",
        "url": "https://github.com/kodonghui/marong2/pull/122"
       }
      ]
     },
     {
      "type": "fixed",
      "area": "call",
      "title": "통화 인사 자막",
      "before": "앱의 인사 지시가 자막 기록에 남았어요",
      "after": "인사 지시는 한 번만 보내고 자막에 남기지 않아요",
      "evidence": [
       {
        "label": "PR #119",
        "url": "https://github.com/kodonghui/marong2/pull/119"
       },
       {
        "label": "PR #122",
        "url": "https://github.com/kodonghui/marong2/pull/122"
       }
      ]
     },
     {
      "type": "improved",
      "area": "call",
      "title": "짧은 통화의 기억",
      "before": "기록 없음",
      "after": "친구 말이 20자보다 짧은 통화는 기억 카드를 만들지 않아요",
      "evidence": [
       {
        "label": "PR #119",
        "url": "https://github.com/kodonghui/marong2/pull/119"
       },
       {
        "label": "PR #122",
        "url": "https://github.com/kodonghui/marong2/pull/122"
       }
      ]
     }
    ]
   },
   {
    "id": "20261124-admin",
    "kind": "server",
    "title": "관리 페이지 다시 만들기",
    "deployedOn": "2026-11-24",
    "sortOn": "2026-11-24",
    "app": null,
    "backfilled": true,
    "evidence": [
     {
      "label": "PR #116",
      "url": "https://github.com/kodonghui/marong2/pull/116"
     },
     {
      "label": "PR #117",
      "url": "https://github.com/kodonghui/marong2/pull/117"
     },
     {
      "label": "PR #121",
      "url": "https://github.com/kodonghui/marong2/pull/121"
     }
    ],
    "items": [
     {
      "type": "improved",
      "area": "admin",
      "title": "관리 페이지 화면 나누기",
      "before": "관리자 화면 하나에 초대 링크·회원·비용이 함께 있었어요",
      "after": "개요·회원·초대 링크·앱 버전·비용·아이템 여섯 탭으로 나눠 봐요",
      "evidence": [
       {
        "label": "PR #116",
        "url": "https://github.com/kodonghui/marong2/pull/116"
       },
       {
        "label": "PR #117",
        "url": "https://github.com/kodonghui/marong2/pull/117"
       },
       {
        "label": "PR #121",
        "url": "https://github.com/kodonghui/marong2/pull/121"
       }
      ]
     },
     {
      "type": "added",
      "area": "admin",
      "title": "개요의 손볼 일",
      "before": "없음",
      "after": "개요 맨 위에 손볼 일(예산 80%, 뒤처진 폰, 곧 끝나는 링크)이 보여요",
      "evidence": [
       {
        "label": "PR #116",
        "url": "https://github.com/kodonghui/marong2/pull/116"
       }
      ]
     },
     {
      "type": "added",
      "area": "admin",
      "title": "초대 링크 거두기",
      "before": "없음",
      "after": "열린 초대 링크를 거둬요",
      "evidence": [
       {
        "label": "PR #117",
        "url": "https://github.com/kodonghui/marong2/pull/117"
       }
      ]
     }
    ]
   },
   {
    "id": "20261124-bug114",
    "kind": "server",
    "title": "웹 통화 다시 잇기",
    "deployedOn": "2026-11-24",
    "sortOn": "2026-11-24",
    "app": null,
    "backfilled": true,
    "evidence": [
     {
      "label": "PR #115",
      "url": "https://github.com/kodonghui/marong2/pull/115"
     },
     {
      "label": "PR #118",
      "url": "https://github.com/kodonghui/marong2/pull/118"
     }
    ],
    "items": [
     {
      "type": "fixed",
      "area": "call",
      "title": "같은 웹에서 다시 잇기",
      "before": "같은 웹 화면에서 통화가 끊긴 뒤 다시 이어지지 않았어요",
      "after": "같은 웹 화면에서 다시 이어져요",
      "evidence": [
       {
        "label": "PR #115",
        "url": "https://github.com/kodonghui/marong2/pull/115"
       },
       {
        "label": "PR #118",
        "url": "https://github.com/kodonghui/marong2/pull/118"
       }
      ]
     }
    ]
   },
   {
    "id": "20261123-bug113",
    "kind": "server",
    "title": "늦게 뜬 화면의 업데이트 배너",
    "deployedOn": "2026-11-23",
    "sortOn": "2026-11-23",
    "app": null,
    "backfilled": true,
    "evidence": [
     {
      "label": "PR #111",
      "url": "https://github.com/kodonghui/marong2/pull/111"
     }
    ],
    "items": [
     {
      "type": "fixed",
      "area": "web",
      "title": "늦게 뜬 화면의 배너",
      "before": "늦게 로드된 화면에는 업데이트 배너가 보이지 않았어요",
      "after": "늦게 로드된 화면에도 배너가 보여요",
      "evidence": [
       {
        "label": "PR #111",
        "url": "https://github.com/kodonghui/marong2/pull/111"
       }
      ]
     }
    ]
   },
   {
    "id": "app-0.3.4",
    "kind": "app",
    "title": "새 버전 바로 받기와 지금 설치",
    "deployedOn": "2026-11-23",
    "sortOn": "2026-11-23",
    "app": {
     "versionName": "0.3.4",
     "versionCode": 12
    },
    "backfilled": true,
    "evidence": [
     {
      "label": "PR #107",
      "url": "https://github.com/kodonghui/marong2/pull/107"
     },
     {
      "label": "PR #110",
      "url": "https://github.com/kodonghui/marong2/pull/110"
     }
    ],
    "items": [
     {
      "type": "improved",
      "area": "app",
      "title": "새 버전 받기",
      "before": "기록 없음",
      "after": "새 버전이 나오면 몇 분 안에 받아 두고, 홈과 글 대화에서 '지금 설치'로 깔아요",
      "evidence": [
       {
        "label": "PR #107",
        "url": "https://github.com/kodonghui/marong2/pull/107"
       },
       {
        "label": "PR #110",
        "url": "https://github.com/kodonghui/marong2/pull/110"
       }
      ]
     }
    ]
   },
   {
    "id": "20261119-unified-cutover",
    "kind": "server",
    "title": "통합 앱으로 전환",
    "deployedOn": "2026-11-19",
    "sortOn": "2026-11-19",
    "app": null,
    "backfilled": true,
    "evidence": [
     {
      "label": "PR #54",
      "url": "https://github.com/kodonghui/marong2/pull/54"
     },
     {
      "label": "PR #64",
      "url": "https://github.com/kodonghui/marong2/pull/64"
     }
    ],
    "items": [
     {
      "type": "added",
      "area": "web",
      "title": "초대 링크 가입과 내 마롱이",
      "before": "없음",
      "after": "초대 링크로 가입하고, 사람마다 자기 마롱이(이름·목소리)를 가져요. 전에는 모두 같은 마롱이였어요",
      "evidence": [
       {
        "label": "PR #54",
        "url": "https://github.com/kodonghui/marong2/pull/54"
       },
       {
        "label": "PR #64",
        "url": "https://github.com/kodonghui/marong2/pull/64"
       }
      ]
     },
     {
      "type": "added",
      "area": "call",
      "title": "목소리 고르기와 동시 통화",
      "before": "없음",
      "after": "통화 목소리를 고르고, 세 사람까지 동시에 통화해요",
      "evidence": [
       {
        "label": "PR #54",
        "url": "https://github.com/kodonghui/marong2/pull/54"
       },
       {
        "label": "PR #64",
        "url": "https://github.com/kodonghui/marong2/pull/64"
       }
      ]
     },
     {
      "type": "removed",
      "area": "legacy",
      "title": "디스코드 봇",
      "before": "디스코드 DM·서버 채널·음성 방에서 마롱이와 대화하고 통화했어요",
      "after": "없음",
      "evidence": [
       {
        "label": "PR #54",
        "url": "https://github.com/kodonghui/marong2/pull/54"
       },
       {
        "label": "PR #64",
        "url": "https://github.com/kodonghui/marong2/pull/64"
       }
      ]
     },
     {
      "type": "improved",
      "area": "admin",
      "title": "관리자 화면 잠금",
      "before": "기록 없음",
      "after": "Cloudflare Access 로그인은 관리자 화면(/chat/admin)에만 걸려요",
      "evidence": [
       {
        "label": "PR #54",
        "url": "https://github.com/kodonghui/marong2/pull/54"
       },
       {
        "label": "PR #64",
        "url": "https://github.com/kodonghui/marong2/pull/64"
       }
      ]
     }
    ]
   },
   {
    "id": "20261115-pr15",
    "kind": "server",
    "title": "통화: 끊어 달라면 인사하고 끊기",
    "deployedOn": "2026-11-15",
    "sortOn": "2026-11-15",
    "app": null,
    "backfilled": true,
    "evidence": [
     {
      "label": "PR #15",
      "url": "https://github.com/kodonghui/marong2/pull/15"
     }
    ],
    "items": [
     {
      "type": "improved",
      "area": "call",
      "title": "통화 끊기",
      "before": "친구가 꺼 달라고 해도 마롱이는 대답만 하고 끊지 못했어요",
      "after": "끊어 달라고 하면 인사하고 끊고, 스스로 먼저 끊지는 않아요",
      "evidence": [
       {
        "label": "PR #15",
        "url": "https://github.com/kodonghui/marong2/pull/15"
       }
      ]
     }
    ]
   },
   {
    "id": "20261026-pr1",
    "kind": "server",
    "title": "카톡: 1:1 얘기 나누기와 연달아 온 말",
    "deployedOn": null,
    "sortOn": "2026-10-26",
    "app": null,
    "backfilled": true,
    "evidence": [
     {
      "label": "PR #1",
      "url": "https://github.com/kodonghui/marong2/pull/1"
     },
     {
      "label": "PR #2",
      "url": "https://github.com/kodonghui/marong2/pull/2"
     }
    ],
    "items": [
     {
      "type": "improved",
      "area": "legacy",
      "title": "1:1에서 한 얘기 나누기",
      "before": "한 친구가 1:1에서 한 얘기를 다른 친구의 1:1에서 마롱이가 몰랐어요(요약이 쌓일 때만 메모를 만듦)",
      "after": "1:1에서 한 얘기를 바로 공유해서 다른 친구와의 대화에서도 알아요",
      "evidence": [
       {
        "label": "PR #1",
        "url": "https://github.com/kodonghui/marong2/pull/1"
       }
      ]
     },
     {
      "type": "improved",
      "area": "legacy",
      "title": "연달아 온 말에 한 번에 답하기",
      "before": "기록 없음",
      "after": "연달아 온 말을 묶어 한 번에 답하고, 단체방에서는 친구마다 따로 묶어요",
      "evidence": [
       {
        "label": "PR #1",
        "url": "https://github.com/kodonghui/marong2/pull/1"
       },
       {
        "label": "PR #2",
        "url": "https://github.com/kodonghui/marong2/pull/2"
       }
      ]
     }
    ]
   }
  ],
  "skipped": 2
 },
 "empty": {
  "units": [],
  "skipped": 0
 },
 "unreadable": {
  "units": [],
  "skipped": 3
 },
 "long": {
  "units": [
   {
    "id": "20261128-long",
    "kind": "server",
    "title": "가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가",
    "deployedOn": "2026-11-28",
    "sortOn": "2026-11-28",
    "app": null,
    "backfilled": false,
    "evidence": [
     {
      "label": "PR #131",
      "url": "https://github.com/kodonghui/marong2/pull/131"
     },
     {
      "label": "0123abc",
      "url": "https://github.com/kodonghui/marong2/commit/0123abc"
     }
    ],
    "items": [
     {
      "type": "improved",
      "area": "call",
      "title": "나나나나나나나나나나나나나나나나나나나나나나나나나나나나나나나나나나나나나나나나",
      "before": "변경 전 글이 길면 칸 안에서 줄바꿈해요. 변경 전 글이 길면 칸 안에서 줄바꿈해요. 변경 전 글이 길면 칸 안에서 줄바꿈해요. 변경 전 글이 길면 칸 안에서 줄바꿈해요. 변경 전",
      "after": "변경 후 글도 백 자까지 써요 marong/app_chat_static/unified.css 변경 후 글도 백 자까지 써요 marong/app_chat_static/unified.",
      "evidence": [
       {
        "label": "PR #131",
        "url": "https://github.com/kodonghui/marong2/pull/131"
       },
       {
        "label": "0123abc",
        "url": "https://github.com/kodonghui/marong2/commit/0123abc"
       }
      ]
     },
     {
      "type": "removed",
      "area": "legacy",
      "title": "제거 예시",
      "before": "<img src=x onerror=alert(1)> 글자 그대로 보여요",
      "after": "없음",
      "evidence": [
       {
        "label": "PR #131",
        "url": "https://github.com/kodonghui/marong2/pull/131"
       },
       {
        "label": "0123abc",
        "url": "https://github.com/kodonghui/marong2/commit/0123abc"
       }
      ]
     }
    ]
   }
  ],
  "skipped": 0
 }
};

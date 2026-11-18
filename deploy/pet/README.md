# 반려동물 서비스 배포

TASK-377 · SPEC-368 · TC-428

## 반영 준비

공개 주소, 월 예산, 로그인·그림·통화 공급자 설정, 법적 안내 문서와 공개 허락을 확인한다. 선행 브랜치가 병합된 뒤 승인한 커밋 전체를 사용한다. 기존 마롱이 서비스의 실행 시각과 파일 해시, PostgreSQL 상태를 먼저 기록한다.

1. 서버의 `~/marong-deploy/<날짜>-pet/`에 이 디렉터리의 `rollback.sh`와 공개 호스트만 철회하는 `remove-pet-hostname.sh`를 실행 가능하게 둔다. `bash rollback.sh --dry-run`을 기록한다. Cloudflare Tunnel 설정과 PostgreSQL 인증 설정은 적용 전에 백업한다.
2. 시스템 사용자·그룹 `marong_pet`을 전용으로 준비한다. PostgreSQL 16의 `pg_hba.conf`에서 일반 접속 규칙 앞에 `marong-pet.pg_hba.conf`를 포함한다. `pg_hba_file_rules`의 오류가 없고 전용 역할 규칙이 일반 규칙보다 먼저인지 확인한 뒤 인증 설정을 다시 읽힌다. 인증 설정을 검증한 뒤 DB 관리자로 `psql -X -d postgres -f deploy/pet/provision-db.sql`을 실행한다. 전용 역할이 Unix 소켓으로 전용 DB에 들어가고 기존 DB의 소켓·TCP가 모두 거절되는지 확인한다.
3. 승인한 소스를 `/opt/marong-pet`에 두고 세 요구사항 파일(`requirements.txt`, `requirements-pet.txt`, `tools/vertex_live/requirements.txt`)로 해당 디렉터리의 Python 3.12 가상환경을 만든다. 실행 사용자는 코드에 읽기만 가능하게 하고 미디어는 systemd가 만드는 `/var/lib/marong-pet` 아래에 둔다. 두 유닛은 `/etc/systemd/system/`에 둔다.
4. `/etc/marong-pet/app.env`와 `/etc/marong-pet/call.env`는 서버 안에서만 작성하고 root만 읽게 한다. 아래 항목을 채운 뒤 새 서비스만 실행한다. 두 루프백 건강 확인이 통과한 뒤 공개 경로를 연결한다.
5. `pet-ingress.example.yml`의 예시 호스트를 승인 주소로 바꾼 경로를 기존 터널 설정의 마지막 기본 규칙 앞에 추가한다. 기존 호스트의 첫 일치 규칙과 기본 규칙을 보존한다. `cloudflared tunnel ingress validate`와 `ingress rule`로 새 주소의 웹·통화·내부 경로를 확인한다. 이 공개 호스트에는 Access를 적용하지 않는다.

## 환경 파일

- 웹 `app.env`에는 `PET_ORIGIN`, `PET_DATABASE_URL`, `PET_MONTHLY_BUDGET_KRW`, `PET_SIGNUP=invite`, `PET_PORT=8797`을 둔다. DB는 `user=marong_pet dbname=marong_pet host=/var/run/postgresql`처럼 Unix 소켓을 사용한다.
- 로그인은 `PET_KAKAO_CLIENT_ID`, `PET_KAKAO_CLIENT_SECRET`, `PET_GOOGLE_CLIENT_ID`, `PET_GOOGLE_CLIENT_SECRET`, `PET_AUTH_SECRET`을 설정한다. 콜백은 승인한 공개 주소의 `/api/auth/{provider}/callback`이다. `PET_OPENAI_API_KEY`, `PET_ANTHROPIC_API_KEY`, 유효한 `PET_YUNET_MODEL_PATH`, `PET_LEGAL_DIR`, `PET_VAPID_PRIVATE_KEY`와 `PET_VAPID_SUBJECT`를 확인한다.
- 웹의 `PET_CALL_WS_URL`은 공개 주소의 `wss://…/pet-call`, `PET_CALL_HEALTH_URL`은 `http://127.0.0.1:8798/healthz`다.
- 통화 `call.env`의 `PET_ORIGIN`은 웹의 값과 같고, `PET_CALL_BACKEND=http://127.0.0.1:8797`, `PET_CALL_PORT=8798`을 사용한다. `PET_CALL_VERTEX_PROJECT`, `PET_CALL_VERTEX_REGION`, `PET_CALL_DOG_VOICE`, `PET_CALL_CAT_VOICE`와 해당 실행 사용자가 읽을 수 있는 통화 공급자 인증을 설정한다. `PET_CALL_INTERNAL_SECRET`은 두 환경 파일에서 같은 새 비밀값을 사용한다.

## 얼굴 가리기 모델 준비

[OpenCV Zoo의 고정 커밋](https://github.com/opencv/opencv_zoo/tree/f12e12798e8314f7c074a6656816c048dcc95b7a/models/face_detection_yunet)에서 [YuNet ONNX 원본](https://media.githubusercontent.com/media/opencv/opencv_zoo/f12e12798e8314f7c074a6656816c048dcc95b7a/models/face_detection_yunet/face_detection_yunet_2023mar.onnx)과 [MIT 라이선스](https://raw.githubusercontent.com/opencv/opencv_zoo/f12e12798e8314f7c074a6656816c048dcc95b7a/models/face_detection_yunet/LICENSE)를 받는다. 원본 크기는 232,589바이트이며 SHA-256은 `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`다.

검증한 파일과 라이선스를 `/opt/marong-pet/assets/`에 보관한다. `PET_YUNET_MODEL_PATH`에는 ONNX의 절대 경로를 넣는다. 서비스 사용자가 파일을 읽고 같은 가상환경에서 `marong.pet.photos.load_detector()`로 불러올 수 있는지 확인한 뒤 공개 경로를 연결한다. 웹의 `/healthz` 확인과 별도로 이 검사를 실행한다.

## 반영 확인과 되돌리기

공개 주소에서 건강 확인 200, 초대 없는 가입 403 `invite_required`, 주문 409 `payments_off`를 확인한다. 인증이 필요한 시험은 전용 시험 회원을 사용한다. 새 서비스 로그를 5분 동안 보면서 Traceback과 ERROR가 각각 0건인지, 기존 서비스 실행 시각·파일 해시·기존 DB 상태가 반영 전과 같은지 확인한다.

되돌리기는 반영 폴더의 `rollback.sh`로 실행한다. 두 새 유닛을 중지·비활성화하고 공개 호스트만 거둔다. 반려동물 DB·미디어 보존과 기존 DB 접속 차단을 위해 전용 역할의 PostgreSQL 규칙은 보존한다.

로컬 관리 터널의 `remove-pet-hostname.sh`를 준비할 때 시스템 Python(PyYAML 사용)으로 철회 후보 파일을 만든다. 도메인이 확정되면 `HOST`에 반려동물 공개 호스트를 넣고 `ACTIVE_CONFIG`와 `CANDIDATE`에 각각 현재 설정과 새 파일 경로를 넣는다.

```bash
python3 deploy/pet/prepare-pet-withdrawal.py "$ACTIVE_CONFIG" "$HOST" "$CANDIDATE"
cloudflared tunnel --config "$CANDIDATE" ingress validate
cloudflared tunnel --config "$CANDIDATE" ingress rule "https://${HOST}/pet-call"
```

후보 파일은 두 반려동물 라우트를 전용 404 규칙으로 바꾼다. 규칙을 맨 앞에 두어 와일드카드가 이 호스트를 처리하지 않게 하고, 기존 호스트의 규칙 순서는 보존한다. 후보 파일로 반려동물의 웹·통화가 404에 일치하고 기존 호스트가 원래 서비스에 일치하는 것을 확인한다. Cloudflare의 전환 절차는 연결 중인 WebSocket을 끊을 수 있으므로, 반영할 때 대상 터널과 실행 중인 연결 상태를 확인한 뒤 전용 철회 명령을 확정한다. [Cloudflare 로컬 터널 설정 갱신 안내](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/configuration-file/#update-a-configuration-file)

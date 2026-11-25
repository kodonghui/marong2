-- TASK-560: implements the approved 05 SQL for TBL-183 after migration 023.
-- Adds an empty table. Existing sessions and Android devices are left intact.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL ROLE marong_owner;

-- TBL-183 web_push_subscriptions (CTX-026) ← SPEC-522, SPEC-524~530, SPEC-535 | terms: TERM-174, 웹 푸시 구독
-- 홈 화면 웹앱 설치마다 현재 구독 상태 하나. 계정은 기기 로그인 외래키로 확인한다.
CREATE TABLE IF NOT EXISTS marong.web_push_subscriptions (
  installation_id uuid PRIMARY KEY,
  session_id bigint NOT NULL REFERENCES marong.app_sessions(id) ON DELETE CASCADE,
  revision uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  state text NOT NULL CHECK (state IN ('active', 'revoked', 'expired', 'invalid')),
  endpoint_fingerprint bytea,
  protected_material bytea,
  subscription_expires_at timestamptz,
  CONSTRAINT web_push_subscriptions_state_material_check CHECK (
    CASE WHEN state = 'active' THEN
      endpoint_fingerprint IS NOT NULL AND octet_length(endpoint_fingerprint) = 32
      AND protected_material IS NOT NULL AND octet_length(protected_material) > 0
    ELSE
      endpoint_fingerprint IS NULL AND protected_material IS NULL AND subscription_expires_at IS NULL
    END
  )
);

-- 같은 구독 주소가 활성 설치 두 곳에 동시에 귀속되는 것을 막는다.
CREATE UNIQUE INDEX IF NOT EXISTS web_push_subscriptions_active_endpoint_idx
  ON marong.web_push_subscriptions(endpoint_fingerprint) WHERE state = 'active';
-- 기기 로그인 소유권 조회, 발송 자격 조회, 세션 종료 뒤 상태 전환 및 FK cascade에 사용한다.
CREATE INDEX IF NOT EXISTS web_push_subscriptions_session_idx ON marong.web_push_subscriptions(session_id);
-- 구독 자체의 기한이 있는 활성 행만 정리할 때 사용한다. 발송 직전에는 기한을 별도로 확인한다.
CREATE INDEX IF NOT EXISTS web_push_subscriptions_active_expiry_idx
  ON marong.web_push_subscriptions(subscription_expires_at)
  WHERE state = 'active' AND subscription_expires_at IS NOT NULL;

COMMENT ON TABLE marong.web_push_subscriptions IS
  'TBL-183 (CTX-026) | TERM-174, 웹 푸시 구독 | 홈 화면 웹앱 설치별 현재 구독과 기기 로그인 연결';
COMMENT ON COLUMN marong.web_push_subscriptions.revision IS
  '구독 상태 변경 때 교체하는 UUID. 이전 발송 결과가 새 등록의 상태를 바꾸지 않도록 비교한다.';
COMMENT ON COLUMN marong.web_push_subscriptions.endpoint_fingerprint IS
  '서버 비밀키를 사용한 주소의 HMAC-SHA-256. 원본 주소와 이 값 모두 로그에 남기지 않는다.';
COMMENT ON COLUMN marong.web_push_subscriptions.protected_material IS
  '발송에 필요한 구독 주소와 키 재료의 암호화 봉투. 활성 행에만 둔다.';
COMMENT ON COLUMN marong.web_push_subscriptions.subscription_expires_at IS
  '구독 자체의 기한. NULL은 확인한 기한 정보 없음. 개별 알림과 약속 전화 기한과 별개다.';

REVOKE ALL ON TABLE marong.web_push_subscriptions FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON TABLE marong.web_push_subscriptions TO marong;
COMMIT;

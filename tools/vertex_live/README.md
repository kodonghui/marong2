# 마롱이 Vertex Live

Singapore `ko-family` hosts this standalone web app at
<https://marong.corthex-hq.com/>. It uses the existing Gemini key on the server
only, through **Vertex AI**, with `gemini-3.8-live`. It does not fall back to the
AI Studio or OpenAI billing paths.

The UI follows the user's Claude artifact, candidate A (밤하늘), and reuses
`marong/call/static/face/v1` assets. Mouth animation follows the approved 13-frame,
1.98-second talk sequence, synchronized to actual queued audio playback. It
supports reduced motion, microphone mute, optional text input and captions.

The voice is **Sulafat**, Korean (`ko-KR`), with a natural adult female speaking
instruction. Gacrux was replaced after the user reported an overly deep voice.
Audio input is resampled from the device's native rate to 16 kHz; output is
24 kHz PCM. A 900 ms playout reserve absorbs packet jitter and grows up to 2 s
after an underrun. The learned reserve is reused on the same browser. Numeric playback/connection diagnostics are kept in RAM only;
they contain no audio or conversation text. No client or relay call-duration/count timer ends calls. Provider
GoAway and transport failures reconnect automatically with session resumption
and context compression. Only one concurrent call is allowed. Mobile OS
suspension, loss of connectivity and provider quota/billing errors can still
interrupt audio; this is not a guarantee of uninterrupted background calls.

## Authentication and operations

- The dedicated named Cloudflare Tunnel forwards to `127.0.0.1:8792`.
- Cloudflare Access uses an exact email allowlist and a one-month session.
  Current login is email one-time PIN; Google OAuth is not configured.
- The origin independently verifies Access RS256 signature, issuer, audience,
  expiry and email. Set `CF_ACCESS_TEAM_DOMAIN`, `CF_ACCESS_AUD` and
  `CF_ACCESS_EMAILS` on the server. No private values belong in Git.
- A previous temporary link remains compatible through an HttpOnly, Secure,
  SameSite invite cookie. Its token is generated and retained on the server.
- Credentials stay under the existing server account's `.config/marong-call`.
  Do not transfer credentials between devices. Only source and approved image
  assets are deployed from this repository.
- Runtime: `/home/opc/marong-vertex-test/app`; Python environment:
  `/home/opc/marong-vertex-test/venv`. App user unit:
  `marong-vertex-live.service`. Named tunnel user unit:
  `marong-cloudflare-named-tunnel.service`.
- User-specific Access settings live in the app unit's server-side drop-in.
  The relay binds only to loopback. `/healthz` is a liveness check; `/status` and
  `/live` require authentication. Mutating requests also verify Origin.
- No raw audio or transcripts are written to server storage. Resume handles and
  queues are kept in RAM. New calls clear the page's previous captions.
- Assets are served from `static/face/v1` in a deployment bundle, or from the
  existing repository asset directory in a checkout. Do not commit duplicates.
- Check `/status.active` before a planned restart. Keep a source backup for
  rollback; do not package the state/credential directories.

Credit balance is controlled by the Google billing account, not this app.
The relay does not enforce a financial spending cap. Exhausted or expired
credits on an upgraded paid account can lead to paid usage.

## Relationship to the existing design

This relay is not the full implementation of PR #11. The canonical ERD is
`marong/call/schema.sql`, explained in `docs/05-erd/erd.md`; the functional
contract is `docs/04-functional-spec/spec.md` (especially SPEC-004 and SPEC-024).
The Notion summary is
<https://app.notion.com/p/416bf16cc3ec818d94eeeba9a3524c0a>.

A read-only production inspection on 2026-11-12 found the existing `marong`
schema and the intended person's records, but no `call` or `call_graph` schema
and no `marong_call` DB role. This relay does not connect to PostgreSQL. Existing
Kakao memories are therefore not read into voice conversations, and voice
transcripts/cards/memories are not persisted. No existing data or schema was
changed during the inspection. Connecting this requires implementing the
approved identity mapping, scoped memory retrieval, call persistence and
privacy/deletion rules; it must not map every allowed login to one person's
private memory or simply export the whole database into a prompt.

## Validation

Install `requirements.txt` in an isolated environment, then run:

```sh
python tools/vertex_live/test_relay.py
python tools/vertex_live/test_access.py
node tools/vertex_live/test_capture.cjs
node tools/vertex_live/test_playback.cjs
```

These use fake upstream connections and generated test signing keys, without
real Google calls or credentials. They cover auth/origin rejection, asset MIME
types, 25 turns, provider GoAway/resume, replay acknowledgement, repeated calls,
explicit-stop cleanup, JWT verification and 16/44.1/48 kHz capture.

`probe_live.py` makes one short real Vertex request using the server's existing
credentials. Run it on that server only. It reports voice, audio MIME/rate,
synthetic-response transcript and audio length; it never outputs the key.

Deployment validation on 2026-11-12: real Korean audio with Sulafat and
`audio/pcm;rate=24000`; authenticated fixed-domain UI and `/status` 200;
unauthenticated Access challenge; both intended email addresses saved in the
Cloudflare policy. The second user's mailbox login and physical Safari mic / iOS
background operation were not independently tested.

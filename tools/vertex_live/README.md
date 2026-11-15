# 마롱이 Vertex Live: 통화와 카톡 기억

Singapore `ko-family` serves https://marong.corthex-hq.com/ through the existing named Cloudflare Tunnel. `gemini-3.8-live`, **Sulafat**, and Korean (`ko-KR`) are unchanged. All Google calls use the existing server-side Vertex credentials and billing project. Credentials are never sent to the browser or copied between devices.

The call page uses the Claude mockup's **군밤 크림** theme from 08:00 to just before 20:00 Korea Standard Time (UTC+9), and **밤하늘** for the rest of the day. It changes the theme in place at the boundary and rechecks when the page returns to the foreground. The three frontend files can be updated without restarting the call service.

## Audio path

Input: `capture AudioWorklet -> dedicated network Worker -> Singapore relay -> Vertex Live`.

Output: `Vertex PCM -> 600 ms server playout reserve -> LiveKit/Opus/WebRTC -> native browser audio`. LiveKit 1.13.11 runs on the same Singapore server. Only signaling passes through the existing Cloudflare hostname (`/rtc`); media uses encrypted WebRTC on UDP 7882, with TCP 7881 available. The LiveKit API binds only to loopback 7880. The browser receives a short-lived room-scoped, subscribe-only token; the signing secret remains on the server. The frontend SDK is pinned to 2.24.0 and vendored with its license. A media disconnect reconnects the same logical call.

WebSocket PCM is the fallback for initial failure **and mid-call WebRTC loss**. Disconnection/reconnecting events or a stalled RTP packet counter request PCM over the existing control socket. The server serializes the ACK and pending audio before new PCM. The microphone, Google session and logical call remain intact. Duplicate requests are idempotent; PCM stays selected until the next call, including control-socket reconnects. Both microphone PCM and fallback received PCM cross transferable MessagePorts directly. Caption rendering and main-thread pauses do not carry those audio packets. Input is 16 kHz mono PCM16; output is 24 kHz PCM16, continuously resampled to the actual device rate. Fallback playback waits for **actual queued samples**, with a 900 ms initial reserve that grows to 2 s after starvation and slowly decreases after stable turns. Finished short replies do not wait for the full reserve. Interruptions invalidate the previous audio epoch. Fault detection, unavailable network/audio hardware and buffer refill can still cause a temporary audible gap.

The change to WebRTC followed a measured public-browser failure: the provider delivered a 13.1 s clip in 12.9 s with a 240 ms maximum packet gap, while the public WebSocket playback had roughly 2 s arrival gaps. Dedicated Worker transport alone still produced two underruns. A subsequent two-turn WebRTC browser trial played 28.97 s with zero source underruns; the second 14.86 s turn added no packet concealment or loss. This is a bounded desktop result, not a guarantee for all networks.

New clients supply a `client` UUID to `/live`. Binary frames have a 24-byte big-endian `MRG2` header: magic, epoch, turn, sequence, source sample offset, sample count, then little-endian PCM16. Previously loaded clients without the query keep headerless PCM until refreshed.

`/status.diagnostics` distinguishes received/played samples, queued audio, actual underruns, source starvation, rebuffer waiting, browser arrival gaps, server send waiting, provider interruptions/reconnects, and AudioContext suspension. It contains no conversation text. There is no application duration/count cutoff. Provider GoAway and transport loss resume automatically; explicit user stop ends the logical call.

Marong never ends a call on her own. When the friend asks her to ("끊어 줘", "전화 꺼"), she says a one-sentence goodbye and calls `end_call`. The tool is offered only to clients that can end a call on a `hangup` message: pages that open `/live?hangup=1` and the Discord bot, which sends `X-Marong-Hangup: 1`. Pages loaded earlier get no tool. The server answers `refused` unless the friend's own words in the last 90 seconds of this call ask to end it, or agree to Marong's "끊을까?" (`hangup.py`; it waits up to 2 s for a late input caption). After `ending`, microphone audio no longer reaches Google, and the server sends `hangup` once the goodbye audio has stopped (1.2 s of model silence; a goodbye that only starts after the answer gets 3 s to begin; at most 15 s). The page plays what it has received, then ends the call; if no client stop arrives within 25 s, the server ends the call itself. The segment closes as `close_requested`. The Discord bot plays the goodbye, leaves the voice channel and stays out until the friend leaves and enters again.

## Identity and bidirectional memory

The origin verifies Cloudflare Access signature, issuer, audience, expiry and exact email allowlist. Private access additionally requires an explicitly approved `caller_logins.email_sha256 -> callers.friend_id` mapping. An invite cookie alone cannot read or write personal memory. The two approved aliases map to the existing intended friend; future allowlisted accounts are not mapped automatically.

The schema is `marong/call/schema.sql` plus `marong/call/migrations/002_vertex_memory.sql`. `call_graph` holds LangGraph checkpoints containing IDs/revisions only. The call role reads scoped Kakao data but cannot mutate Kakao raw messages; the Kakao role cannot read voice transcripts.

- Start context: the caller's 1:1 rooms and explicitly linked rooms, bounded notes/summaries/recent messages, existing permitted shared-friend notes, active voice memories, and recent call cards.
- `recall`: escaped ILIKE keyword search within that same scope; no new vector service is required.
- Call content is organized automatically after the call. There are no spoken save/delete commands, memory-management screens or public memory mutation/history APIs. The Live model can only retrieve relevant context and read the clock.
- Server-side maintenance retains caller-scoped deletion/invalidation primitives for test cleanup and data lifecycle enforcement. These invalidate provider resume context, checkpoints and derived Kakao material; they are not exposed as conversation features.
- The independent organizer runs after **explicit** call completion. Gemini 3.8 Flash uses the Vertex `global` endpoint and LOW reasoning. Proposed quotes must occur in actual user text; call cards are extractive, so invented model summaries cannot become facts. The Live model itself receives no thinking configuration.
- The next Kakao **1:1** response gets the person's call context. A persistent room provenance guard prevents new private derivatives from entering linked-group prompts or shared notes. Sharing retains the pre-bridge safe notes; this is intentionally conservative. Revision checks also stop in-flight summaries and late replies from reviving forgotten material.

Transcripts and source quotes expire after 180 days. Cards and verified memories remain until deleted. No raw call audio is persisted. Provider resumption may use its own temporary cache. Test probes generate synthetic audio only in the isolated test workflow.

## Operations

For the verified Google API-key route, key rotation procedure, open ports, mid-call failover results and five-minute session reporting, see [OPERATIONS.md](OPERATIONS.md). Apply `003_transport_reporting.sql` after migration 002 before deploying this version. Non-secret systemd and LiveKit configuration templates are in [deploy/](deploy/).

- App: `/home/opc/marong-vertex-test/app`, user unit `marong-vertex-live.service`.
- Call instruction: `call_instruction.md` (Korean) is the Live `systemInstruction` for web and Discord calls. The service reads it at start, and a missing or empty file stops the start. It reads the file again for each Google connection, so an edited file reaches the next call or reconnection without a restart; a failed read keeps the last good text. Replace it atomically (write a temporary file, then `mv`). Its counseling and crisis rules (`고민 들어 주기`, `위험한 순간`) match the same two sections of the text-chat `prompt.md` (used by the Discord DM bot), and `tests/test_counsel_prompts.py` checks that they agree.
- Pinned Python runtime: `/home/opc/marong-vertex-test/venv-memory2`.
- Discord voice relay: `marong-discord-voice-relay.service` imports its own copies of `server.py`, `live_session.py` and `call_instruction.md` from `/opt/marong-discord-voice-relay/` (checked on the server 2026-11-15), not the app folder. A change to the call code or instruction goes to both folders. From the hang-up change on, `live_session.py` also imports `hangup.py`, so that file goes to both folders too, and the Discord bot's `index.mjs` and `audio.mjs` change with it. Restarting the relay also restarts `marong-discord-voice.service`.
- Organizer: user unit `marong-voice-memory.service`.
- Media: user unit `marong-rtc.service`; server-only `.config/marong-call/livekit.json` and `livekit.yaml` are never included in the repository or copied. `/api/rtc` checks identity, Origin and active-call ownership. `/rtc` remains behind the same authentication boundary. Native WebRTC packet loss/concealment and source-buffer underruns are reported separately.
- Kakao: `/opt/marong`, system unit `marong.service`.
- Database: `MARONG_CALL_DSN=dbname=marong user=marong_call`, exact local peer mapping from `opc`; no password files move.
- Kakao: `MARONG_CALL_MEMORY=1` enables privacy enforcement. `MARONG_CALL_CONTEXT=0` can stop injection **without disabling privacy guards**. Once private derivatives exist, do not roll back to unguarded Kakao code or set `MARONG_CALL_MEMORY=0`.
- Check authenticated `/status.active` before a planned restart. Back up the database and sources on the server. Additive schema remains during application rollback. A database restore must preserve/replay the latest deletion ledger before enabling retrieval; an old dump alone is not a valid privacy-preserving restore.
- `/healthz` is liveness only. `/status`, `/live`, and the remaining `/api/*` endpoints require authentication; mutations verify Origin. Automatic memory access requires a mapped caller and remains caller-scoped.
- Call lifecycle: POST `/api/calls/{uuid}/end` marks explicit user hangup and schedules automatic organization. It verifies both identity and ownership.

Credit balance and expiry remain controlled by Google Billing. This change does not add a paid subscription or move usage to another provider; it also does not impose a spending cap.

## Tests

```sh
python tools/vertex_live/test_access.py
python tools/vertex_live/test_relay.py
python tools/vertex_live/test_instruction.py
python tools/vertex_live/test_hangup.py
python tools/vertex_live/test_transcripts.py
python tools/vertex_live/test_rtc_api.py
node tools/vertex_live/test_capture.cjs
node tools/vertex_live/test_playback.cjs
node tools/vertex_live/test_transport.cjs
node tools/vertex_live/test_fallback.cjs
node tools/vertex_live/test_rtc_watchdog.cjs
node tools/vertex_live/test_hangup_client.cjs
python tools/vertex_live/test_midcall.py
python tools/vertex_live/test_call_report.py  # isolated restored test database only
```

On the server, `test_rtc.py` uses the private SFU with synthetic audio to check actual encrypted media delivery under 400 ms burst jitter. It sends no Kakao messages and does not use private conversation content.

Database integration uses `test_memory_bridge.py` only against a restored `marong_voice_verify_*` database with synthetic identities. It exercises the real Kakao Agent with a fake delivery callback: no Kakao message is sent to another person. `REAL_VERTEX_TEST=1` also checks the actual structured organizer API.

`probe_memory_live.py` runs on the authorized server only: ordinary synthetic Korean preference -> real Vertex ASR -> automatic organizer -> PostgreSQL -> actual Kakao Agent prompt; Kakao seed -> spoken answer. No save/delete phrase is used and delivery is a fake callback. It never prints credentials. Physical iPhone Safari, Bluetooth, phone lock/background and cellular handoff require separate device acceptance; desktop Chrome and simulated transport tests do not establish those results.

The existing broader PR #11 screen/admin/budget design remains reference material. The deployed call page combines the approved voice and memory features with the two scheduled themes.

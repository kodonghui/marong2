"""Local Discord audio ingress. The web listener and its login stay separate."""
from __future__ import annotations

import asyncio
import logging
import os
import pwd
import re
import socket
import struct
import uuid
from pathlib import Path

from aiohttp import web

from call_memory import MemoryStore, Principal
from live_session import LiveSession
from server import LOCATION, MODEL, VOICE, google_headers, setup

SOCKET = Path('/run/marong-discord-voice/live.sock')
log = logging.getLogger('discord_voice_relay')


class DiscordMemoryStore(MemoryStore):
    async def start_call(self, person, client_id, voice, prompt_version):
        async with self.pool.connection() as conn, conn.transaction():
            caller = await conn.execute('SELECT id FROM call.callers WHERE id=%s AND enabled FOR UPDATE', (person.caller_id,))
            if not await caller.fetchone():
                raise PermissionError('caller_disabled')
            cursor = await conn.execute("""SELECT id,entrypoint FROM call.calls
                WHERE caller_id=%s AND status<>'ended' AND deleted_at IS NULL""", (person.caller_id,))
            existing = await cursor.fetchone()
            if existing:
                if existing['entrypoint'] != 'discord':
                    raise PermissionError('caller_busy')
                await conn.execute("""UPDATE call.calls SET status='live',client_id=%s,last_beat_at=now()
                    WHERE id=%s""", (client_id, existing['id']))
                return str(existing['id']), True
            cursor = await conn.execute("""INSERT INTO call.calls(caller_id,client_id,voice,prompt_version,entrypoint)
                VALUES(%s,%s,%s,%s,'discord') RETURNING id""", (person.caller_id, client_id, voice, prompt_version))
            return str((await cursor.fetchone())['id']), False

    async def discord_principal(self, user_id):
        row = await self.one("""SELECT caller_id,friend_id,name,context_revision,room_key,kakao_room_key
            FROM call.discord_voice_bindings WHERE discord_user_id=%s""", (user_id,))
        if row:
            return Principal(row['caller_id'], row['friend_id'], row['name'], row['context_revision'],
                             (row['room_key'], row['kakao_room_key']))

    async def finish_discord_client(self, person, client_id):
        row = await self.one("""SELECT id FROM call.calls WHERE caller_id=%s AND client_id=%s
            AND entrypoint='discord' AND status<>'ended' AND deleted_at IS NULL""", (person.caller_id, client_id))
        if row:
            await self.finish(person, row['id'], explicit=True)


class DiscordRelay:
    def __init__(self, store, uid, user_id, guild_id, channel_id):
        self.store = store
        self.uid = uid
        self.user_id = user_id
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.lease = asyncio.Lock()
        self.resume = {}
        self.session = None

    async def identity(self, request):
        sock = request.transport.get_extra_info('socket') if request.transport else None
        if not sock:
            raise web.HTTPForbidden()
        try:
            _, uid, _ = struct.unpack('3i', sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        except OSError:
            raise web.HTTPForbidden() from None
        if uid != self.uid or any(request.headers.get(name) != value for name, value in (
            ('X-Marong-Discord-User', self.user_id),
            ('X-Marong-Discord-Guild', self.guild_id),
            ('X-Marong-Discord-Channel', self.channel_id),
        )):
            raise web.HTTPForbidden()
        try:
            client_id = str(uuid.UUID(request.headers.get('X-Marong-Client-Id', '')))
        except ValueError:
            raise web.HTTPBadRequest() from None
        person = await self.store.discord_principal(self.user_id)
        if not person:
            raise web.HTTPForbidden()
        return person, client_id

    async def live(self, request):
        person, client_id = await self.identity(request)
        if self.lease.locked():
            raise web.HTTPConflict()
        async with self.lease:
            ws = web.WebSocketResponse(heartbeat=15, max_msg_size=32_000)
            await ws.prepare(request)
            diagnostics = {}
            session = LiveSession(ws, f'discord:{person.caller_id}', self.store, person,
                                  setup, google_headers, self.resume, diagnostics,
                                  LOCATION, MODEL, VOICE, client_id, entry_transport='discord')
            self.session = session
            try:
                await session.run()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                log.warning('session_failed type=%s', type(error).__name__)
            finally:
                self.session = None
                await ws.close()
                log.info('session_closed explicit=%s transcripts_failed=%s upstream_reconnects=%s samples=%s',
                         session.explicit, diagnostics.get('memoryWriteFailures', 0),
                         diagnostics.get('providerReconnects', 0), diagnostics.get('receivedSamples', 0))
            return ws

    async def end(self, request):
        person, client_id = await self.identity(request)
        if self.session and self.session.client_id != client_id:
            return web.Response(status=204)
        if self.session and self.session.client_id == client_id:
            self.session.explicit = True
            await self.session.ws.close()
        async with self.lease:
            await self.store.finish_discord_client(person, client_id)
        return web.Response(status=204)

    async def shutdown(self, _app):
        if self.session:
            await self.session.ws.close(code=1001)


def create_app(store, uid, user_id, guild_id, channel_id):
    relay = DiscordRelay(store, uid, user_id, guild_id, channel_id)
    app = web.Application(client_max_size=1024)
    app.router.add_get('/live', relay.live)
    app.router.add_post('/end', relay.end)
    app.on_shutdown.append(relay.shutdown)
    return app


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    ids = [os.environ[key] for key in ('MARONG_DISCORD_VOICE_USER_ID', 'MARONG_DISCORD_GUILD_ID',
                                      'MARONG_DISCORD_VOICE_CHANNEL_ID')]
    if not all(re.fullmatch(r'[1-9][0-9]{16,19}', value) for value in ids):
        raise SystemExit('invalid Discord voice configuration')
    store = DiscordMemoryStore(os.environ['MARONG_CALL_DSN'])
    app = create_app(store, pwd.getpwnam('marong-discord-voice').pw_uid, *ids)

    async def database(_):
        try:
            await store.open()
            if not await store.discord_principal(ids[0]):
                raise RuntimeError('discord_caller_unavailable')
            yield
        finally:
            await store.close()

    app.cleanup_ctx.append(database)
    SOCKET.unlink(missing_ok=True)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(SOCKET))
    SOCKET.chmod(0o660)
    web.run_app(app, sock=listener, access_log=None, print=None, shutdown_timeout=8)

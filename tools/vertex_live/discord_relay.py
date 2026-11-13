"""Local Discord audio ingress. The web listener and its login stay separate."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import pwd
import re
import socket
import struct
import uuid
from pathlib import Path

from aiohttp import web

from call_memory import CallBusy, MemoryStore, Principal
from live_session import LiveSession
from server import LOCATION, MODEL, VOICE, google_headers, setup

SOCKET = Path('/run/marong-discord-voice/live.sock')
log = logging.getLogger('discord_voice_relay')


class DiscordMemoryStore(MemoryStore):
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
            await self.finish(person, row['id'], explicit=True, entrypoint='discord', client_id=client_id)

    async def discord_busy(self, person, client_id):
        return await self.one("""SELECT 1 FROM call.calls WHERE caller_id=%s AND status='live'
            AND deleted_at IS NULL AND (entrypoint<>'discord' OR client_id<>%s)""",
            (person.caller_id, client_id)) is not None


class RoomCall:
    def __init__(self):
        self.lease = asyncio.Lock()
        self.resume = {}
        self.session = None


class DiscordRelay:
    def __init__(self, store, uid, rooms):
        self.store = store
        self.uid = uid
        self.calls = {room: RoomCall() for room in rooms}

    async def identity(self, request):
        sock = request.transport.get_extra_info('socket') if request.transport else None
        if not sock:
            raise web.HTTPForbidden()
        try:
            _, uid, _ = struct.unpack('3i', sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        except OSError:
            raise web.HTTPForbidden() from None
        user_id, guild_id, channel_id = (request.headers.get('X-Marong-Discord-' + name)
                                         for name in ('User', 'Guild', 'Channel'))
        call = self.calls.get((user_id, guild_id, channel_id))
        if uid != self.uid or call is None:
            raise web.HTTPForbidden()
        try:
            client_id = str(uuid.UUID(request.headers.get('X-Marong-Client-Id', '')))
        except ValueError:
            raise web.HTTPBadRequest() from None
        person = await self.store.discord_principal(user_id)
        if not person:
            raise web.HTTPForbidden()
        return call, person, client_id

    async def available(self, request):
        call, person, client_id = await self.identity(request)
        if call.lease.locked() or await self.store.discord_busy(person, client_id):
            raise web.HTTPConflict()
        return web.Response(status=204)

    async def live(self, request):
        call, person, client_id = await self.identity(request)
        if call.lease.locked():
            raise web.HTTPConflict()
        async with call.lease:
            if await self.store.discord_busy(person, client_id):
                raise web.HTTPConflict()
            ws = web.WebSocketResponse(heartbeat=15, max_msg_size=32_000)
            await ws.prepare(request)
            diagnostics = {}
            session = LiveSession(ws, f'discord:{person.caller_id}', self.store, person,
                                  setup, google_headers, call.resume, diagnostics,
                                  LOCATION, MODEL, VOICE, client_id, entry_transport='discord')
            call.session = session
            try:
                await session.run()
            except CallBusy:
                await ws.send_json({'type': 'call_busy'})
            except asyncio.CancelledError:
                raise
            except Exception as error:
                log.warning('session_failed type=%s', type(error).__name__)
            finally:
                call.session = None
                await ws.close()
                log.info('session_closed explicit=%s transcripts_failed=%s upstream_reconnects=%s samples=%s',
                         session.explicit, diagnostics.get('memoryWriteFailures', 0),
                         diagnostics.get('providerReconnects', 0), diagnostics.get('receivedSamples', 0))
            return ws

    async def end(self, request):
        call, person, client_id = await self.identity(request)
        if call.session and call.session.client_id != client_id:
            return web.Response(status=204)
        if call.session:
            call.session.explicit = True
            await call.session.ws.close()
        async with call.lease:
            await self.store.finish_discord_client(person, client_id)
        return web.Response(status=204)

    async def shutdown(self, _app):
        await asyncio.gather(*(call.session.ws.close(code=1001)
                               for call in self.calls.values() if call.session))


def create_app(store, uid, rooms):
    relay = DiscordRelay(store, uid, rooms)
    app = web.Application(client_max_size=1024)
    app.router.add_get('/available', relay.available)
    app.router.add_get('/live', relay.live)
    app.router.add_post('/end', relay.end)
    app.on_shutdown.append(relay.shutdown)
    return app


def configured_rooms(raw):
    fields = ('user_id', 'guild_id', 'channel_id')
    try:
        items = json.loads(raw)
        if not isinstance(items, list) or not items:
            raise ValueError
        if any(not isinstance(item, dict) or set(item) != set(fields) for item in items):
            raise ValueError
        rooms = [tuple(item[key] for key in fields) for item in items]
        if any(not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{16,19}', value)
               for room in rooms for value in room):
            raise ValueError
        if any(len({room[column] for room in rooms}) != len(rooms) for column in range(len(fields))):
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError('invalid Discord voice configuration') from None
    return rooms


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    rooms = configured_rooms(os.environ['MARONG_DISCORD_VOICE_ROOMS'])
    store = DiscordMemoryStore(os.environ['MARONG_CALL_DSN'])
    app = create_app(store, pwd.getpwnam('marong-discord-voice').pw_uid, rooms)

    async def database(_):
        try:
            await store.open()
            for user_id, _, _ in rooms:
                if not await store.discord_principal(user_id):
                    raise RuntimeError('discord_caller_unavailable')
            await store.recover_entrypoint('discord')
            yield
        finally:
            await store.close()

    app.cleanup_ctx.append(database)
    SOCKET.unlink(missing_ok=True)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(SOCKET))
    SOCKET.chmod(0o660)
    web.run_app(app, sock=listener, access_log=None, print=None, shutdown_timeout=8)

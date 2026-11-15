"""Vertex authentication stays on this server; no browser credentials."""
import asyncio
import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2 import service_account

PROJECT='project-bc2d15a4-11c0-476b-ae8'
LOCATION='us-central1'
MODEL='gemini-3.8-live'
VOICE='Sulafat'
CONFIG=Path.home()/'.config/marong-call'
_credentials=None

async def google_headers():
    global _credentials
    if os.environ.get('VERTEX_AUTH_MODE','api_key')=='api_key':
        return {'x-goog-api-key':(CONFIG/'gemini2.key').read_text().strip()}
    if _credentials is None:
        _credentials=service_account.Credentials.from_service_account_file(
            str(CONFIG/'vertex.json'),scopes=['https://www.googleapis.com/auth/cloud-platform'])
    if not _credentials.valid:await asyncio.to_thread(_credentials.refresh,Request())
    return {'Authorization':'Bearer '+_credentials.token}

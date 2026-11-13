"""Run the private Discord bot using the existing server-side Marong settings."""
import asyncio
from dataclasses import replace
import logging
import os
from pathlib import Path

from marong.config import load_dotenv, load_settings
from marong.discord_dm import DiscordAgent, DiscordDM, DiscordProactive
from marong.discord_store import DiscordStore
from marong.embed import Embeddings
from marong.llm import LLM
from marong.memory import MemoryWorker
from marong.store import Store


async def main():
    load_dotenv()
    settings = replace(load_settings(), proactive=True, timezone="Asia/Seoul")
    if any("BOT_TOKEN" not in item for item in settings.problems()):
        raise SystemExit("Invalid Marong model or database settings")
    token = (Path(os.environ["CREDENTIALS_DIRECTORY"]) / "discord-token").read_text(encoding="ascii").strip()
    store = DiscordStore(settings.database_url, call_bridge=True)
    store.discord_context_enabled = False
    llm = LLM(settings)
    emb = Embeddings(settings.embed_model, settings.embed_cache_dir)
    # During parallel operation the Kakao process already maintains these tables.
    standalone = os.getenv("MARONG_DISCORD_MEMORY_WORKER") == "1"
    worker_store = Store(settings.database_url, call_bridge=True) if standalone else None
    worker = MemoryWorker(settings, worker_store, emb, llm) if worker_store else None
    tasks = []
    try:
        await store.open(wait=True)
        await store.proactive_rooms()  # Fail before login if the private binding schema is unavailable.
        if worker_store:
            await worker_store.open(wait=True)
        emb.start()
        if worker:
            tasks.append(asyncio.create_task(worker.run()))
        agent = DiscordAgent(settings, store, emb, llm, on_saved=worker.kick if worker else None)
        client = DiscordDM(agent, store, int(os.environ["MARONG_DISCORD_APP_ID"]), int(os.environ["MARONG_DISCORD_GUILD_ID"]))
        async with client:
            tasks.append(asyncio.create_task(DiscordProactive(settings, store, agent, client).run()))
            await client.start(token)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if worker_store:
            await worker_store.close()
        await store.close()
        await llm.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    for name in ("httpx", "httpcore", "psycopg.pool", "huggingface_hub"):
        logging.getLogger(name).setLevel(logging.WARNING)
    asyncio.run(main())

"""Organizer checkpoints keep working after PostgreSQL restarts. Isolated database only, no call data.

A PostgreSQL restart ends every client session. Ending this test's own sessions
is the same event for the client: AdminShutdown on the next use, then a closed
connection. Unattended upgrades restarted the server on 2026-11-14 and the
organizer's single checkpoint connection failed every later job.
"""
import asyncio,os,uuid
from typing import TypedDict
import psycopg
from langgraph.graph import StateGraph,START,END
from organizer import AsyncPostgresSaver,checkpoint_pool

DB=os.environ.get('TEST_DATABASE','marong_voice_verify_20261112')
assert DB.startswith('marong_voice_verify_'),'Only the isolated restored database is allowed'
BASE=f'dbname={DB} user=marong_call'
APP='organizer_reconnect_'+uuid.uuid4().hex[:10]
DSN=f'{BASE} application_name={APP}'
CHECKS=0
def ok(value,label):
    global CHECKS
    assert value,label
    CHECKS+=1
    print('PASS',label,flush=True)


class State(TypedDict):
    n:int

async def step(state):return {'n':state['n']+1}

def compiled(saver):
    graph=StateGraph(State);graph.add_node('step',step)
    graph.add_edge(START,'step');graph.add_edge('step',END)
    return graph.compile(checkpointer=saver)

async def run(graph,threads):
    thread='test-reconnect:'+uuid.uuid4().hex;threads.append(thread)
    return (await graph.ainvoke({'n':0},{'configurable':{'thread_id':thread}}))['n']

async def end_sessions():
    """End this test's other sessions and wait until the server has closed them."""
    async with await psycopg.AsyncConnection.connect(BASE,autocommit=True) as c:
        cur=await c.execute('SELECT count(*) FILTER (WHERE pg_terminate_backend(pid)) FROM pg_stat_activity WHERE application_name=%s AND pid<>pg_backend_pid()',(APP,))
        ended=(await cur.fetchone())[0]
        for _ in range(50):
            cur=await c.execute('SELECT count(*) FROM pg_stat_activity WHERE application_name=%s AND pid<>pg_backend_pid()',(APP,))
            if (await cur.fetchone())[0]==0:break
            await asyncio.sleep(0.1)
        return ended

async def failure(graph,threads):
    try:await run(graph,threads)
    except psycopg.OperationalError as error:return type(error).__name__
    return None

async def main():
    threads=[]
    try:
        # Before: one long-lived connection, as the organizer used until 2026-11-15.
        async with AsyncPostgresSaver.from_conn_string(DSN+" options='-c search_path=call_graph,public'") as saver:
            await saver.setup();graph=compiled(saver)
            ok(await run(graph,threads)==1,'single connection: works before the restart')
            ok(await end_sessions()==1,'single connection: server ended the session')
            first,second=await failure(graph,threads),await failure(graph,threads)
            ok(first and second,f'single connection: fails on every later job ({first}, {second})')
        # After: the organizer's pool replaces a connection the server has closed.
        async with checkpoint_pool(DSN) as pool:
            saver=AsyncPostgresSaver(pool);await saver.setup();graph=compiled(saver)
            ok(await run(graph,threads)==1,'pool: works before the restart')
            ok(await end_sessions()>=1,'pool: server ended its sessions')
            ok(await run(graph,threads)==1,'pool: next job works right after the restart')
            ok(await run(graph,threads)==1,'pool: later jobs keep working')
            ok(await end_sessions()>=1 and await run(graph,threads)==1,'pool: recovers from a second restart')
    finally:
        async with await psycopg.AsyncConnection.connect(BASE,autocommit=True) as c:
            for table in ('checkpoint_writes','checkpoint_blobs','checkpoints'):
                await c.execute(f'DELETE FROM call_graph.{table} WHERE thread_id=ANY(%s)',(threads,))
    print(f'{CHECKS} checks passed',flush=True)

asyncio.run(main())

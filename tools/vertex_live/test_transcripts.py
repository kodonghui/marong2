import asyncio
from memory_tools import TranscriptRecorder
async def main():
    saved=[]
    async def save(*a):saved.append(a)
    r=TranscriptRecorder(save,lambda *a:None)
    r.boundary('user')
    r.feed('user','나는 ')
    await asyncio.sleep(.2)
    r.feed('user','차를 좋아해')
    await asyncio.sleep(.4);await r.flush()
    assert saved[-1][1:]==('user','나는 차를 좋아해',True,False)
    r.speech_start();r.feed('user','다음 문장')
    await asyncio.sleep(.4);await r.flush()
    assert saved[-1][3] is False
    r.feed('user',finished=True);await r.flush()
    assert saved[-1][3] is True and saved[-1][0]!=saved[0][0]
    r.feed('assistant','말하는 중');r.feed('assistant',finished=True,interrupted=True);await r.flush()
    assert saved[-1][4] is True
    await r.close()
    print('PASS: absent finished flag, late input deltas, independent user/assistant buffers, new speech boundary, interrupted output')
asyncio.run(main())

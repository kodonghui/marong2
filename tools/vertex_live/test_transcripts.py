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
    # Real Live run of 2026-11-15: after end_call the reply was transcribed as '<no' + ' speech>{pause}'.
    saved.clear();shown=[]
    r=TranscriptRecorder(save,lambda role,text,key:shown.append(text))
    r.feed('assistant','<no');r.feed('assistant',' speech>{pause}');r.feed('assistant',finished=True);await r.flush()
    assert shown==[] and saved==[],(shown,saved)
    r.feed('assistant','응, 알겠어! {pa');r.feed('assistant','use}또 얘기하자.<no speech>',finished=True);await r.flush()
    assert saved[-1][1:4]==('assistant','응, 알겠어! 또 얘기하자.',True) and not any('<' in x[2] or '{' in x[2] for x in saved),saved
    assert shown==['응, 알겠어!','응, 알겠어! 또 얘기하자.'],shown
    count=len(saved);r.feed('user','<noise>');await r.close()
    assert len(saved)==count,saved
    print('PASS: absent finished flag, late input deltas, independent user/assistant buffers, new speech boundary, interrupted output, '
          'non-speech markers neither shown nor saved')
asyncio.run(main())

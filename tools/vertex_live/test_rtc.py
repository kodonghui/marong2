"""Synthetic encrypted WebRTC audio round trip against the local private SFU."""
import asyncio,math,struct,time
from livekit import rtc
from rtc_transport import Bridge
async def main():
    bridge=Bridge('test','rtc-loopback-test');listener=rtc.Room();tasks=[];levels=[]
    async def read(track):
        stream=rtc.AudioStream(track,sample_rate=24000,num_channels=1)
        async for item in stream:
            data=item.frame.data.cast('h') if item.frame.data.format!='h' else item.frame.data
            levels.append(max(abs(x) for x in data))
    @listener.on('track_subscribed')
    def subscribed(track,*_):tasks.append(asyncio.create_task(read(track)))
    try:
        await bridge.open();await listener.connect('ws://127.0.0.1:7880',bridge.token())
        await asyncio.sleep(.5)
        for i in range(30):
            samples=[round(6000*math.sin((i*4800+j)*2*math.pi*440/24000)) for j in range(4800)]
            bridge.feed(struct.pack('<4800h',*samples),1,1)
            if i==29:bridge.finish(1,1)
            await asyncio.sleep(.16+(.4 if i==12 else 0))
        await asyncio.sleep(2)
        nonzero=[i for i,v in enumerate(levels) if v>100]
        assert nonzero,'No received WebRTC audio'
        assert all(v>100 for v in levels[nonzero[0]:nonzero[-1]+1]),'Inserted silent frame'
        assert bridge.stats['rtcSourceUnderruns']==0,bridge.stats
        print({'test':'WebRTC source -> Opus -> native receiver','nonzero_frames':len(nonzero),'source_underruns':0,'injected_jitter_ms':400})
    finally:
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True);await listener.disconnect();await bridge.close()
asyncio.run(main())

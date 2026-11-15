"""One short real response through the exact production Vertex setup."""
import asyncio,base64,json,time
import aiohttp
import server

async def main():
    report={'project':server.PROJECT,'model':server.MODEL,'voice':server.VOICE,'audio_formats':[],'setup':False,'audio_bytes':0,'turn_complete':False,'resumable':False,'transcript':'','usage':[]}
    try:
        headers=await server.google_headers()
        url=f'wss://{server.LOCATION}-aiplatform.googleapis.com/ws/google.cloud.aiplatform.v1beta1.LlmBidiService/BidiGenerateContent'
        async with aiohttp.ClientSession() as http:
            async with http.ws_connect(url,headers=headers,max_msg_size=2_000_000) as ws:
                config=server.setup()
                await ws.send_json(config)
                deadline=time.monotonic()+30
                while time.monotonic()<deadline:
                    msg=await ws.receive(timeout=20)
                    if msg.type not in (aiohttp.WSMsgType.TEXT,aiohttp.WSMsgType.BINARY):
                        report['close']=ws.close_code;report['reason']=str(msg.extra)[:300];break
                    data=json.loads(msg.data)
                    if 'setupComplete' in data:
                        report['setup']=True
                        await ws.send_json({'clientContent':{'turns':[{'role':'user','parts':[{'text':'Please answer in English only: say hello in one short sentence.'}]}],'turnComplete':True}})
                    sc=data.get('serverContent',{})
                    report['transcript']+=sc.get('outputTranscription',{}).get('text','')
                    for part in sc.get('modelTurn',{}).get('parts',[]):
                        inline=part.get('inlineData',{})
                        if inline.get('mimeType','').startswith('audio/pcm') and inline.get('data'):
                            report['audio_bytes']+=len(base64.b64decode(inline['data']))
                            if inline['mimeType'] not in report['audio_formats']:report['audio_formats'].append(inline['mimeType'])
                    if data.get('sessionResumptionUpdate',{}).get('resumable'):report['resumable']=True
                    if data.get('usageMetadata'):report['usage'].append(data['usageMetadata'])
                    if sc.get('turnComplete'):report['turn_complete']=True;break
                    if data.get('error'):report['error']=data['error'];break
    except Exception as e:report['error_type']=type(e).__name__
    report['audio_seconds']=round(report['audio_bytes']/48000,2)
    print(json.dumps(report,ensure_ascii=False))
    return report['setup'] and report['turn_complete'] and report['audio_bytes']>0

if __name__=='__main__':raise SystemExit(0 if asyncio.run(main()) else 1)

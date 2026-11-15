"""Temporarily drop only the SFU's external media output during our test call."""
from pathlib import Path
import hashlib,json,subprocess,sys,time,urllib.request,signal
base=Path('/home/opc/marong-vertex-test');expected=sys.argv[1]
cookie=hashlib.sha256(('browser:'+(base/'join-token').read_text().strip()).encode()).hexdigest()
def status():
    return json.load(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8792/status',headers={'Cookie':'marong_live='+cookie}),timeout=3))
s=status();assert s['active'] and s['diagnostics'].get('callId')==expected,'Test call no longer owns service'
assert s['diagnostics'].get('audioPath')=='webrtc','Need live WebRTC before fault'
rules=[];samples=[];start=time.monotonic()
def interrupted(*_):raise InterruptedError('terminated')
signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
try:
    for command in ('iptables','ip6tables'):
        for protocol,port in [('udp','7882'),('tcp','7881')]:
            rule=['OUTPUT','!','-o','lo','-p',protocol,'--sport',port,'-m','comment','--comment','marong-failover-test','-j','DROP']
            subprocess.run(['sudo','-n',command,'-w','5','-I',*rule],check=True);rules.append((command,rule))
    print('WebRTC UDP/TCP external media blocked for 20 seconds; HTTPS/control and loopback relay remain available',flush=True)
    for _ in range(20):
        time.sleep(1);s=status();d=s['diagnostics']
        samples.append({'seconds':round(time.monotonic()-start,2),'sameCall':d.get('callId')==expected,'active':s['active'],
            'path':d.get('audioPath'),'engine':d.get('engine'),'fallbacks':d.get('transportFallbacks',0),
            'providerReconnects':d.get('providerReconnects',0),'playedMs':d.get('playedMs',0),'reason':d.get('transportFallbackReason')})
finally:
    for command,rule in reversed(rules):subprocess.run(['sudo','-n',command,'-w','5','-D',*rule],check=True)
    print('Temporary packet-drop rules removed',flush=True)
result={'beforeCall':expected,'blockedSeconds':20,'samples':samples}
Path('/home/opc/marong-voice-build/failover-blackhole.json').write_text(json.dumps(result,indent=2))
assert all(x['sameCall'] and x['active'] and x['providerReconnects']==0 for x in samples),samples
converted=next((x for x in samples if x['path']=='pcm'),None)
assert converted and converted['fallbacks']==1,samples
print(json.dumps({'convertedBySeconds':converted['seconds'],'reason':converted['reason'],'sameCall':True,'providerReconnects':0,'fallbacks':1,'final':samples[-1]}))

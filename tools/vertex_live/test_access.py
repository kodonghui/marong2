"""Reject forged/expired/wrong-account Cloudflare identity at the origin."""
import asyncio,json,tempfile,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

async def main():
    with tempfile.TemporaryDirectory() as tmp:
        with patch.object(Path,'home',return_value=Path(tmp)):
            import server
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        public=json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
        public['kid']='test-key'
        server.ACCESS_TEAM='test-team.cloudflareaccess.com'
        server.ACCESS_AUD='test-aud'
        server.ACCESS_EMAILS={'allowed@example.com'}
        server.access_keys.update(keys=[public],expires=time.time()+3600)
        claims={'iss':'https://'+server.ACCESS_TEAM,'aud':['test-aud'],'sub':'user-1',
                'email':'allowed@example.com','iat':int(time.time()),'exp':int(time.time()+60)}
        def request(values,algorithm='RS256',signing_key=key):
            token=jwt.encode(values,signing_key,algorithm=algorithm,headers={'kid':'test-key'})
            return SimpleNamespace(cookies={},headers={'Cf-Access-Jwt-Assertion':token})
        assert await server.identity(request(claims))=='user-1'
        for overrides in [{'aud':['other-app']},{'iss':'https://wrong.cloudflareaccess.com'},{'email':'outsider@example.com'},{'exp':int(time.time()-1)},{'nbf':int(time.time()+90)}]:
            assert await server.identity(request(claims|overrides)) is None
        assert await server.identity(request(claims,'HS256','forged-secret-at-least-32-characters')) is None
        other=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        assert await server.identity(request(claims,signing_key=other)) is None
        assert await server.identity(SimpleNamespace(cookies={},headers={'Cf-Access-Authenticated-User-Email':'allowed@example.com'})) is None
        server.ACCESS_EMAILS=set()
        assert await server.identity(request(claims)) is None
    print('PASS: Access signature, algorithm, issuer, audience, expiry, not-before and exact email allowlist')

asyncio.run(main())

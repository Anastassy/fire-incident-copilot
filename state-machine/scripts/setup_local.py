"""Create independent local credentials; never rotate an existing configuration."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import secrets
import time

ROOT=Path(__file__).resolve().parents[1]

def setup(output, public_url):
    output=Path(output);output.mkdir(parents=True,exist_ok=True);os.chmod(output,0o700)
    server=output/'server.json';client=output/'client.json'
    if server.exists() or client.exists():
        if not server.exists() or not client.exists():raise RuntimeError('Incomplete credentials; recover them before setup')
        print('Existing credentials preserved in '+str(output));return
    reader=secrets.token_urlsafe(32);controller=secrets.token_urlsafe(32);expiry=int(time.time()+30*86400)
    config={'public_url':public_url.rstrip('/'),'ticket_secret':secrets.token_urlsafe(48),'max_runs':16,'max_streams':24,
        'extra_origins':[],'tokens':[{'sha256':hashlib.sha256(value.encode()).hexdigest(),'owner':'local-demo',
            'scopes':scopes,'expires_at':expiry} for value,scopes in [(reader,['state:read']),(controller,['state:read','run:control'])]]}
    for path,value in [(server,config),(client,{'base_url':public_url.rstrip('/'),'read_token':reader,'control_token':controller,'expires_at':expiry})]:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:json.dump(value,f,indent=2);f.write('\n')
    print('Created local credentials in '+str(output)+' (values are not printed)')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=ROOT/'var/private')
    p.add_argument('--public-url',default='http://127.0.0.1:8787/api/v1');a=p.parse_args();setup(a.output,a.public_url)

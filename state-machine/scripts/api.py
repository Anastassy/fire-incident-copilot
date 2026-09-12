"""Local JSON API helper: reads credentials from a private file, not command arguments."""
from pathlib import Path
import argparse
import json
import urllib.request
import urllib.error
import uuid

ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('method',choices=['GET','POST']);p.add_argument('path')
    p.add_argument('json_body',nargs='?');p.add_argument('--config',type=Path,default=ROOT/'var/private/client.json')
    p.add_argument('--idempotency-key');a=p.parse_args()
    config=json.loads(a.config.read_text());body=None if a.json_body is None else json.loads(a.json_body)
    headers={'Authorization':'Bearer '+config['control_token' if a.method=='POST' else 'read_token'],'Content-Type':'application/json'}
    if a.method=='POST' and a.path=='/runs':headers['Idempotency-Key']=a.idempotency_key or str(uuid.uuid4())
    if a.method=='POST' and a.path.endswith('/commands') and body is not None:body.setdefault('command_id',str(uuid.uuid4()))
    req=urllib.request.Request(config['base_url'].rstrip('/')+a.path,method=a.method,headers=headers,
        data=None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(req,timeout=20) as response:print(json.dumps(json.load(response),ensure_ascii=False,indent=2))
    except urllib.error.HTTPError as error:
        print(error.read().decode());raise SystemExit(1)

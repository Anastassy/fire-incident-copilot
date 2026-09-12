"""Explicit pull/publish commands; no model or platform network traffic on import."""
import argparse
import asyncio
import json
import os
from .store import Store
from .platform import connect, Reader, Publisher

async def run(args):
    store=Store(args.db)
    async with connect(args.url,os.environ['FIRE_PLATFORM_API_KEY']) as tools:
        if args.command=='pull':
            # Session must already exist. The operator explicitly supplies scope and epoch.
            result=await Reader(tools,store).pull(session_id=args.session,generation=args.generation,
                device_id=args.device,since=args.since,until=args.until,epoch=args.epoch,
                description_field=args.description_field,media_field=args.media_field)
        else: result={'processed':await Publisher(tools,store).step()}
        print(json.dumps(result,ensure_ascii=False,indent=2))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',default='work/runtime.sqlite3')
    p.add_argument('--url',required=True,help='Full MCP URL, e.g. http://localhost:8000/mcp-server/mcp')
    sub=p.add_subparsers(dest='command',required=True)
    pull=sub.add_parser('pull')
    for name in ['session','device','since','until','epoch']:pull.add_argument('--'+name,required=True)
    pull.add_argument('--generation',type=int,required=True)
    pull.add_argument('--description-field',default='description')
    pull.add_argument('--media-field',default='audio_url')
    sub.add_parser('publish-one',help='Writes one queued observation to the platform')
    asyncio.run(run(p.parse_args()))
if __name__=='__main__':main()

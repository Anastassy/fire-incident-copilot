"""Seed synthetic local UI records. No model or external platform calls."""
import argparse
import os
import httpx

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8010')
    parser.add_argument('action',choices=['assign','complete','reset'])
    args=parser.parse_args()
    cookies={'fire_ui_session':os.environ['FIRE_UI_SESSION_TOKEN']} if os.getenv('FIRE_UI_SESSION_TOKEN') else {}
    with httpx.Client(base_url=args.url,cookies=cookies,timeout=10) as client:
        response=client.post('/sessions/ui-demo');response.raise_for_status();session=response.json()
        if args.action=='reset':
            response=client.post('/sessions/ui-demo/reset');response.raise_for_status();session=response.json()
        else:
            completed=args.action=='complete'
            response=client.post('/events',json={'session_id':'ui-demo','generation':session['generation'],
                'event_id':'demo-completion' if completed else 'demo-assignment','reading_id':43 if completed else 42,
                'time_ms':1000 if completed else 0,'source_id':'00000000-0000-0000-0000-000000000001','kind':'radio',
                'description':'Synthetic: completion of task T1 was reported.' if completed else 'Synthetic: task T1 was assigned to team 2.',
                'payload':{'fixture':{'action':'completed' if completed else 'assigned','task_ref':'T1','team':'2'}}})
            response.raise_for_status()
            response=client.post(f"/sessions/ui-demo/{session['generation']}/clock",json={'time_ms':max(session['time_ms'],1000 if completed else 0)})
            response.raise_for_status()
        print({'demo_context_id':'ui-demo','generation':session['generation'],'subject_id':'all','data':'synthetic fixture'})
if __name__=='__main__':main()

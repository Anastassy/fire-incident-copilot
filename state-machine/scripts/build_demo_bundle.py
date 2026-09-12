"""Build small reproducible inputs without private datasets or downloaded media."""
from pathlib import Path
import argparse
import copy
import hashlib
import json
import math
import shutil
import struct
import subprocess
import sys
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.media_bundle import build_live, checksum, probe

def dump(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n')

def build(output):
    output = Path(output).resolve()
    if output.exists(): raise ValueError('Choose a new output directory; bundles are immutable')
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise RuntimeError('Install FFmpeg/ffprobe to generate synthetic test media')
    spec_path = ROOT/'scenarios/synthetic-demo.json'
    spec = json.loads(spec_path.read_text())
    assets = output/'assets';assets.mkdir(parents=True)
    seconds = spec['media_duration_ms']/1000
    def provenance(device):
        return {'source_id':'synthetic-demo','acquisition_id':'synthetic-demo-v1','origin':'synthetic',
            'source_file':'scenarios/synthetic-demo.json','source_url':None,'source_sha256':checksum(spec_path),
            'source_row':None,'source_channel':device,
            'recorded_time':{'value':None,'unit':'unknown','reference':'Authored simulation clock'},
            'transformation':'Generated synthetic values/patterns/tones; not recorded observations',
            'time_mapping':'sim_ms = authored offset_ms','independence_group':'synthetic-demo-v1',
            'composition_note':spec['description'],'attribution':'Synthetic fixture authored for this project'}
    devices=[]
    for did,kind,metric,unit in [('TMP-SRV','temperature_sensor','temperature','degC'),
        ('SMK-SRV','smoke_sensor','obscuration','%/ft'),('IOT-VOC','multisensor','tvoc','ppb'),
        ('CAM-EXT','camera',None,''),('CAM-SRV','camera',None,''),
        ('RADIO-A','radio_channel',None,''),('RADIO-B','radio_channel',None,''),
        ('BADGE-DOOR','access_reader',None,'')]:
        radio=kind=='radio_channel'
        devices.append({'device_id':did,'name':did+' · synthetic','kind':kind,'building_id':spec['building_id'],
            'room_id':None if radio else 'server','floor_id':None if radio else 'floor-1',
            'position_m':None if radio else [0,0,1],'stale_after_ms':spec['stale_after_ms'],'metric':metric,'unit':unit,
            **({'transcript_delivery':'prerecorded'} if did=='RADIO-A' else {})})
    templates=[];media={};streams={}
    def event(kind,device,end,data):
        return {'kind':kind,'device_id':device,'room_id':None if device.startswith('RADIO') else 'server',
            'observed_sim_time_ms':end,'received_sim_time_ms':end,'provenance':provenance(device),'data':data}
    def register(path,device,kind,start,end,index):
        p=probe(path);track=p['streams'][0];mid=path.stem
        media[mid]={'file':'assets/'+path.name,'kind':kind,'status':'ready',
            'mime_type':'audio/wav' if kind=='audio' else 'video/mp4','codec':track['codec_name'],
            'byte_length':path.stat().st_size,'sha256':checksum(path),'duration_ms':end-start,
            'width':track.get('width'),'height':track.get('height'),
            'sample_rate_hz':int(track['sample_rate']) if 'sample_rate' in track else None,
            'channels':track.get('channels'),'supports_range':True,'failure_code':None,
            'media_id':mid,'device_id':device,'capture_start_sim_time_ms':start,'capture_end_sim_time_ms':end,
            'published_sim_time_ms':end,'chunk_index':index,'provenance':provenance(device)}
        data={'channel_id':device,'media_id':mid,'chunk_index':index,'audio_start_sim_time_ms':start,'audio_end_sim_time_ms':end} if kind=='audio' else {
            'camera_id':device,'media_id':mid,'media_kind':'video','capture_start_sim_time_ms':start,'capture_end_sim_time_ms':end}
        templates.append(event('radio_audio' if kind=='audio' else 'camera',device,end,data))
    for device,frequency in [('RADIO-A',440),('RADIO-B',660)]:
        source=assets/(device.lower()+'-source.wav')
        pcm=b''.join(struct.pack('<h',int(1000*math.sin(2*math.pi*frequency*i/16000))) for i in range(round(seconds*16000)))
        with wave.open(str(source),'wb') as f:
            f.setparams((1,2,16000,0,'NONE','not compressed'));f.writeframes(pcm)
        for i,start in enumerate(range(0,spec['media_duration_ms'],2000)):
            end=min(start+2000,spec['media_duration_ms']);part=assets/(device.lower()+f'-{i:04d}.wav')
            with wave.open(str(part),'wb') as f:
                f.setparams((1,2,16000,0,'NONE','not compressed'));f.writeframes(pcm[start*32:end*32])
            register(part,device,'audio',start,end,i)
        streams[device]=build_live(assets,device,source,'audio',seconds,provenance(device),source_clock=True)
    for device,color in [('CAM-EXT','blue'),('CAM-SRV','orange')]:
        source=assets/(device.lower()+'-source.mp4')
        subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',f'color=c={color}:s=320x180:r=5',
            '-t',str(seconds),'-c:v','libx264','-pix_fmt','yuv420p','-bf','0','-force_key_frames','expr:gte(t,n_forced*2)',str(source)],check=True)
        for i,start in enumerate(range(0,spec['media_duration_ms'],2000)):
            end=min(start+2000,spec['media_duration_ms']);part=assets/(device.lower()+f'-{i:04d}.mp4')
            subprocess.run(['ffmpeg','-v','error','-y','-ss',str(start/1000),'-i',str(source),'-t',str((end-start)/1000),
                '-c','copy','-avoid_negative_ts','make_zero',str(part)],check=True)
            register(part,device,'video',start,end,i)
        streams[device]=build_live(assets,device,source,'video',seconds,provenance(device))
    templates.append(event('radio_transcript','RADIO-A',4000,{
        'channel_id':'RADIO-A','stream_id':'RADIO-A','segment_id':'synthetic-0001','source_segment_id':'1',
        'language':'en','text':spec['synthetic_transcript'],'audio_start_sim_time_ms':2000,'audio_end_sim_time_ms':3500,
        'full_recording_offset_ms':0,'delivery':'prerecorded','machine_generated':False,'human_verified':False,
        'model':None,'audio_source_file':'assets/radio-a-source.wav','audio_source_sha256':checksum(assets/'radio-a-source.wav'),
        'words':[],'timing_notes':['Authored fixture text accompanies a tone, not speech.']}))
    catalog=[]
    for sid in ['normal','escalation','degraded']:
        duration=660000 if sid=='degraded' else 600000
        events=copy.deepcopy(templates)
        for t in spec['measurement_times_ms']:
            for device,metric,unit,value in [('TMP-SRV','temperature','degC',22+t/60000),
                ('SMK-SRV','obscuration','%/ft',1+t/120000),('IOT-VOC','tvoc','ppb',20+t/60000)]:
                events.append(event('measurement',device,t,{'metric':metric,'value':value,'unit':unit,'quality':'valid'}))
        if sid=='degraded':
            events.append(event('transport','IOT-VOC',1500,{'mode':'silent'}))
            events.append(event('connectivity','SMK-SRV',420000,{'connected':False,'reason':'Synthetic connection loss'}))
        events.append(event('access','BADGE-DOOR',5000,{'reader_id':'BADGE-DOOR','door_id':'door-1','action':'badge_presented',
            'direction':'unknown','subject_ref':'synthetic-badge-1','passage_count':None,'from_room_id':None,'to_room_id':None}))
        priorities={'transport':0,'connectivity':1,'measurement':2,'camera':3,'radio_audio':4,'radio_transcript':5,'access':6}
        events.sort(key=lambda e:(e['received_sim_time_ms'],priorities[e['kind']],e['device_id']))
        for i,e in enumerate(events):e['source_event_id']=f'{sid}-{i:06d}'
        public={'scenario_id':sid,'name':sid+' · synthetic demo','description':spec['description'],'duration_ms':duration,
            'building_id':spec['building_id'],'supported_speeds':[1,10,60],
            'modalities':['smoke','temperature','camera','access','radio'],'composition_note':spec['description']}
        scene={'scenario':public,'devices':devices,'rooms':[{'room_id':'server','name':'Synthetic room',
            'building_id':spec['building_id'],'floor_id':'floor-1','device_ids':[d['device_id'] for d in devices if d['room_id']]}],'events':events}
        public['scenario_version']=hashlib.sha256(json.dumps({'scene':scene,'media':media,'streams':streams},sort_keys=True).encode()).hexdigest()
        dump(output/(sid+'.json'),scene);catalog.append(public)
    dump(output/'catalog.json',catalog);dump(output/'media.json',media);dump(output/'live-streams.json',streams)
    dump(output/'selection.json',{'synthetic':True,'recognition':False,'whole_datasets_uploaded':False,
        'scenarios':3,'continuous_http_streams':4,'description':spec['description']})
    return output

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'var/demo-bundle')
    args=parser.parse_args();print(build(args.output))

"""Prepare indexed fMP4 once; serving never launches FFmpeg."""
import copy
import hashlib
import json
import math
import struct
import subprocess

def checksum(path):
    with open(path, 'rb') as f:
        digest = hashlib.sha256()
        for block in iter(lambda: f.read(1024 * 1024), b''): digest.update(block)
    return digest.hexdigest()

def probe(path):
    return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(path)]))

def build_live(assets, device_id, source, kind, seconds, provenance, source_clock=False):
    path=assets/(device_id.lower()+'-live.mp4')
    codec=['-map','0:a:0','-c:a','aac','-b:a','96k'] if kind=='audio' else ['-map','0:v:0','-map','0:a?','-c:v','libx264','-preset','fast','-crf','23','-bf','0','-force_key_frames','expr:gte(t,n_forced*2)','-c:a','aac']
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(source),'-t',str(seconds),*codec,
        '-movflags','empty_moov+default_base_moof+frag_keyframe','-frag_duration','2000000','-f','mp4',str(path)],check=True)
    packets=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_packets','-show_entries','packet=pos,pts_time,duration_time','-of','json',str(path)]))['packets']
    data=path.read_bytes();boxes=[];offset=0
    while offset<len(data):
        size,kind_bytes=struct.unpack('>I4s',data[offset:offset+8])
        if size==1:size=struct.unpack('>Q',data[offset+8:offset+16])[0]
        if size==0:size=len(data)-offset
        if size<8 or offset+size>len(data):raise ValueError('Invalid MP4 box')
        boxes.append((offset,size,kind_bytes));offset+=size
    starts=[pos for pos,_,typ in boxes if typ==b'moof']
    trailer=next((pos for pos,_,typ in boxes if typ==b'mfra'),len(data))
    if not starts:raise RuntimeError('No fragmented media produced')
    fragments=[]
    for i,start in enumerate(starts):
        end=starts[i+1] if i+1<len(starts) else trailer
        times=[float(packet['pts_time'])+float(packet.get('duration_time',0)) for packet in packets if start<=int(packet['pos'])<end]
        if not times:raise RuntimeError('Fragment has no timed packets')
        fragments.append({'offset':start,'length':end-start,'end_ms':math.ceil(max(times)*1000)})
    provenance=copy.deepcopy(provenance)
    provenance['origin']='derived'
    provenance['transformation']=provenance.get('transformation', '') + '; Fragmented MP4 for continuous HTTP delivery; H.264 video/AAC audio; no recognition, no semantic filtering'
    if kind=='audio':
        rate=int(next(s['sample_rate'] for s in probe(path)['streams'] if s['codec_type']=='audio'))
        provenance['time_mapping']+=f'; AAC stream timestamps include {1024/rate:.9f} seconds encoder priming: source offset = max(0, stream_pts - {1024/rate:.9f}); trailing encoder padding may extend duration'
    result={'stream_id':device_id,'device_id':device_id,'kind':kind,
        'mime_type':'audio/mp4' if kind=='audio' else 'video/mp4','codec':'aac' if kind=='audio' else 'h264',
        'file':'assets/'+path.name,'init_length':starts[0],'fragments':fragments,
        'capture_start_sim_time_ms':0,'duration_ms':fragments[-1]['end_ms'],
        'provenance':provenance,'sha256':checksum(str(path))}
    if source_clock:
        # Map encoded timestamps to source time: priming/padding is not new source audio.
        if kind != 'audio': raise ValueError('Source clock mapping currently requires audio')
        offset_ms = 1024 / rate * 1000
        for fragment in fragments:
            fragment['end_ms'] = max(0, min(round(seconds * 1000), math.ceil(fragment['end_ms'] - offset_ms)))
        result['duration_ms'] = round(seconds * 1000)
        result['media_timestamp_offset_ms'] = offset_ms
    return result

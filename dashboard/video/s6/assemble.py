#!/usr/bin/env python3
"""Assemble S6 from immutable slides, measured browser frames and audio stems."""
import argparse, concurrent.futures, json, math, subprocess
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--root', type=Path, required=True, help='External media directory containing slides/, capture/, voice/, production/')
ROOT = parser.parse_args().root.resolve()
WORK = ROOT / 'production' / 'render'
WORK.mkdir(parents=True, exist_ok=True)
FONT = '/System/Library/Fonts/Supplemental/Arial.ttf'
BOLD = '/System/Library/Fonts/Supplemental/Arial Bold.ttf'
FPS = 30

def run(args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL)

def title_filter(text, y, size=42, color='0xf6f3ec', x=84):
    p = WORK / ('text-' + str(len(list(WORK.glob('text-*')))) + '.txt')
    p.write_text(text)
    return f"drawtext=fontfile='{BOLD if size > 30 else FONT}':textfile='{p}':fontsize={size}:fontcolor={color}:x={x}:y={y}"

def cap(id, start, end, source, offset, crop, title, mode='wide', lines=None):
    return dict(id=id,start_s=start,end_s=end,source=source,offset_s=offset,crop=crop,title=title,mode=mode,lines=lines or [])

SHOTS = [
 cap('D01',25,30,'live-conditions',0,[175,42,1180,650],'ONE OPERATOR. MANY SOURCES.'),
 cap('D02',30,33,'live-conditions',5,[925,116,425,565],'SENSORS / CAMERAS / RADIO', 'source'),
 cap('D03',33,38,'live-conditions',32,[175,42,1180,650],'THE INCIDENT CONTINUES TO CHANGE'),
 cap('D04',38,43,'power-loss-briefing',0,[195,350,705,300],'COPILOT / AUTOMATIC ASSESSMENT'),
 cap('D05',43,47,'power-loss-briefing',1,[200,445,690,205],'EVIDENCE AND UNKNOWNS, SIDE BY SIDE'),
 cap('D06a',47,49,'power-evidence',0,[1185,0,305,345],'FOLLOW THE EVIDENCE','drawer',['SOURCE RECORD','Original reading','Device, time and provenance']),
 cap('D06b',49,53,'camera-inspect',0,[926,300,424,165],'CAMERA VIEWS / CHECK SOURCE FRESHNESS'),
 cap('D07',53,59,'source-connectivity',0,[1185,0,305,330],'FRESHNESS IS PART OF THE EVIDENCE','drawer',['CONNECTION LOST','SMK-B2-GRADAS / 03:04','A last reading is not a current reading.']),
 cap('D08a',59,63,'operator-question',0,[190,450,720,148],'ASK INCIDENT COPILOT'),
 cap('D08b',63,64,'occupancy-answer',0,[190,118,715,310],'ASK INCIDENT COPILOT'),
 cap('D09a',64,66,'access-check',0,[1185,0,305,315],'CHECK THE SOURCE / ACCESS','drawer',['PERMISSION IS NOT PRESENCE','Access record / Gradas','A badge event cannot confirm occupancy.']),
 cap('D09b',66,70,'occupancy-answer',1,[190,155,715,255],'COPILOT / GROUNDED ANSWER'),
 cap('D10',70,74,'occupancy-answer',8,[190,165,715,230],'THE ANSWER EXPLAINS ITS LIMITS'),
 cap('D11',74,78,'radio-source',0,[1185,0,305,300],'LISTEN TO THE ORIGINAL RADIO','radio',['PALISADES ARCHIVE','Original transmission','Separate incident / source attached']),
 cap('D12',78,82,'radio-source',4,[1185,0,305,300],'KEEP INCIDENT PROVENANCE VISIBLE','radio',['SOURCE BOUNDARY','Palisades is a separate incident.','It cannot confirm conditions in Base2.']),
 cap('D13',82,90,'occupancy-answer',4,[190,165,715,230],'BRIEF COMMAND WITH EVIDENCE'),
]
for s in json.loads((ROOT/'slides/slides.json').read_text())['slides']:
    SHOTS.append(dict(id=s['id'],start_s=s['start_s'],end_s=s['end_s'],slide=s['png']))
SHOTS.sort(key=lambda s:s['start_s'])
assert SHOTS[0]['start_s']==0 and SHOTS[-1]['end_s']==120
assert all(a['end_s']==b['start_s'] for a,b in zip(SHOTS,SHOTS[1:]))
(ROOT/'production/edit.json').write_text(json.dumps({'duration_s':120,'fps':30,'size':[1920,1080],'capture_note':'Native in-app browser screenshots, about 5 fps. Correct first tile cropped from a duplicated screenshot response. Actual capture timing retained; editorial cuts labeled replay excerpts. No generated UI answers.','shots':SHOTS},indent=2))

def sequence(s):
    src=ROOT/'capture'/s['source']
    meta=json.loads((src/'frames.json').read_text())
    start=s['offset_s']; end=start+s['end_s']-s['start_s']
    rows=meta['rows']; result=['ffconcat version 1.0']
    chosen=[]
    for i,row in enumerate(rows):
        a=row['at']; b=rows[i+1]['at'] if i+1<len(rows) else max(meta['elapsed'],end)
        dur=min(b,end)-max(a,start)
        if dur>0:
            result.extend([f"file '{src/row['file']}'",f'duration {dur:.6f}'])
            chosen.append(row['file'])
    result.append(f"file '{src/chosen[-1]}'")
    p=WORK/(s['id']+'.ffconcat'); p.write_text('\n'.join(result)+'\n');return p

def build(s):
    out=WORK/(s['id']+'.mp4'); length=s['end_s']-s['start_s']
    base=['ffmpeg','-hide_banner','-loglevel','error','-y','-filter_threads','1','-filter_complex_threads','1']
    if 'slide' in s:
        args=base+['-loop','1','-framerate','30','-i',str(ROOT/'slides'/s['slide']),'-vf','setsar=1,format=yuv420p']
    else:
        inp=sequence(s); x,y,w,h=s['crop']; mode=s['mode']
        boxw,boxh=(660,670) if mode in ('drawer','radio') else ((660,690) if mode=='source' else (1750,690))
        left=1150 if mode in ('drawer','radio','source') else 85
        filt=f"[0:v]crop=1496:842:0:0,crop={w}:{h}:{x}:{y},fps=30,scale={boxw}:{boxh}:force_original_aspect_ratio=decrease:flags=lanczos,pad={boxw}:{boxh}:(ow-iw)/2:(oh-ih)/2:color=0x141b1e,setsar=1[p];color=c=0x141b1e:s=1920x1080:r=30:d={length}[bg];[bg][p]overlay={left}:165:shortest=1,"
        fs=[title_filter('FIREWATCH',38,25,'0xed995c'),title_filter(s['title'],91,41),title_filter('TRAINING DEMO  /  REPLAY EXCERPT',45,22,'0xb5bdbe',1390), 'drawbox=x=84:y=148:w=1752:h=2:color=0xed995c:t=fill']
        if mode=='source':
            for i,txt in enumerate(['A SHARED INCIDENT PICTURE','Temperature and smoke','Two camera views','Radio with source transcripts']):
                fs.append(title_filter(txt,275+i*93,36 if i==0 else 31,'0xf6f3ec' if i==0 else '0xb5bdbe'))
        for i,txt in enumerate(s['lines']):
            fs.append(title_filter(txt,285+i*106,38 if i==0 else 30,'0xed995c' if i==0 else '0xf6f3ec'))
        if mode=='radio':
            fs += [title_filter('Audio Provided by Broadcastify / CC-BY-3.0-US',785,22,'0xb5bdbe')]
        fs += [title_filter('Actual interface capture / Base2 simulation + independently sourced radio',1026,20,'0x8e9b9e')]
        filt+=','.join(fs)+',format=yuv420p[v]'
        args=base+['-f','concat','-safe','0','-i',str(inp),'-filter_complex',filt,'-map','[v]']
    run(args+['-an','-frames:v',str(round(length*30)),'-r','30','-c:v','libx264','-threads','2','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-video_track_timescale','15360',str(out)])
    print('Encoded',s['id'],flush=True);return out

def main():
    # Construct filter text files sequentially: filenames are allocated in build().
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        paths=list(pool.map(build,SHOTS))
    concat=WORK/'all.ffconcat';concat.write_text('ffconcat version 1.0\n'+'\n'.join(f"file '{p}'" for p in paths)+'\n')
    video=WORK/'picture.mp4'
    run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(concat),'-c','copy',str(video)])
    # Narration is entirely silent during D11. Preserve archival radio duration and pitch.
    mix="[1:a]loudnorm=I=-16:TP=-1.5:LRA=7,aresample=48000[a];[2:a]loudnorm=I=-16:TP=-1.5:LRA=7,aresample=48000,adelay=74500|74500,apad=whole_dur=120[b];[a][b]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.89:level=false,atrim=duration=120[aout]"
    out=ROOT/'firewatch-120s-clean.mp4'
    run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(video),'-i',str(ROOT/'voice/narration-120s.wav'),'-i',str(ROOT/'production/radio-original-3s.wav'),'-filter_complex',mix,'-map','0:v','-map','[aout]','-c:v','copy','-c:a','aac','-b:a','192k','-ar','48000','-ac','2','-t','120','-movflags','+faststart',str(out)])
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(out)]))
    (ROOT/'production/clean-master-probe.json').write_text(json.dumps(probe,indent=2))
    vs=next(s for s in probe['streams'] if s['codec_type']=='video')
    assert int(vs['nb_frames'])==3600 and abs(float(probe['format']['duration'])-120)<0.05
    (ROOT/'production/clean-master.ready').write_text(str(out)+'\n')
    print(out,flush=True)

if __name__=='__main__': main()

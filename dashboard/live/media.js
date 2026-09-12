/** Source-timed fragmented MP4. Gaps are preserved; only received buffers are played. */
export class LiveMedia {
 constructor(element,item,run,onStatus=()=>{}){this.el=element;this.item=item;this.run=run;this.onStatus=onStatus;this.controller=new AbortController();this.queue=[];this.history=[];this.subscribers=new Set();this.eof=false;this.failed=false;this.received=0;this.lastStatus='';}
 status(value){if(this.lastStatus!==value){this.lastStatus=value;this.onStatus(value);}}
 async start(sourcePlayer){
  if(!window.MediaSource){this.status('This browser does not support MediaSource');return;}
  const mime=this.item.kind==='audio'?'audio/mp4; codecs="mp4a.40.2"':'video/mp4; codecs="avc1.64001e"';
  if(!MediaSource.isTypeSupported(mime)){this.status('Codec unavailable in this browser');return;}
  this.ms=new MediaSource();this.objectUrl=URL.createObjectURL(this.ms);this.el.src=this.objectUrl;
  await new Promise(resolve=>this.ms.addEventListener('sourceopen',resolve,{once:true}));if(this.controller.signal.aborted)return;
  try{this.sb=this.ms.addSourceBuffer(mime);this.sb.mode='segments';this.sb.addEventListener('updateend',()=>this.pump());this.sb.addEventListener('error',()=>this.status('Decoding error'));this.ms.duration=this.run.duration_ms/1000+.1;
   // Review reuses received audio bytes. It must not open a sixth persistent HTTP/1 stream
   // and starve the browser's control/API connection pool.
   if(sourcePlayer){this.sourcePlayer=sourcePlayer;this.queue=[...sourcePlayer.history];this.eof=sourcePlayer.eof;sourcePlayer.subscribers.add(this);this.pump();return;}
   const url=new URL(this.item.content_url,location.href);const marker='/api/v1';
   if(!url.pathname.startsWith(marker+'/runs/'))throw new Error('Unexpected media route');
   const response=await fetch('/api/state'+url.pathname.slice(marker.length)+url.search,{signal:this.controller.signal});
   if(!response.ok)throw new Error(`HTTP ${response.status}`);
   const reader=response.body.getReader();this.status('Waiting for frames');
   while(true){const {value,done}=await reader.read();if(done){this.eof=true;this.pump();for(const p of this.subscribers){p.eof=true;p.pump();}break;}this.received+=value.length;if(this.item.kind==='audio')this.history.push(value);this.queue.push(value);this.pump();for(const p of this.subscribers){p.queue.push(value);p.pump();}}
  }catch(error){if(error.name!=='AbortError'){this.failed=true;this.status(error.message);}}
 }
 pump(){if(!this.sb||this.sb.updating||this.ms.readyState!=='open')return;
  if(this.queue.length){try{this.sb.appendBuffer(this.queue.shift());}catch(error){this.failed=true;this.status('Buffer error: '+error.name);}return;}
  if(this.eof){try{this.ms.endOfStream();}catch{}}
 }
 buffered(time){for(let i=0;i<this.el.buffered.length;i++)if(time>=this.el.buffered.start(i)-.02&&time<this.el.buffered.end(i)-.03)return true;return false;}
 sync(simMs,playing,speed=1){
  if(this.review)return this.syncReview();
  if(!this.sb||this.failed)return;
  const offset=(this.item.media_timestamp_offset_ms||0)/1000;
  // Two-second delivery latency is applied to all tracks, independently of replay speed.
  const target=Math.max(0,simMs/1000-2.15)+offset;
  if(this.item.kind==='audio'&&playing&&speed!==1){this.el.pause();this.status('Select 1× to listen');return;}
  if(!playing){this.el.pause();let last=null;for(let i=0;i<this.el.buffered.length;i++){if(this.el.buffered.start(i)<=target)last=Math.min(target,this.el.buffered.end(i)-.06);}if(last!=null&&Math.abs(this.el.currentTime-last)>.3)this.el.currentTime=Math.max(0,last);this.status(this.el.buffered.length?'Paused':'Waiting for Play');return;}
  if(this.buffered(target)){
   if(Math.abs(this.el.currentTime-target)>.5)this.el.currentTime=target;
   this.el.playbackRate=Math.min(16,speed);this.el.play().catch(()=>{if(!this.el.muted)this.status('Click Sound to listen');});
   this.status('Streaming');
  }else{this.el.pause();this.status(this.eof&&simMs>=this.item.duration_ms?'Recording ended':'No new frames');}
 }
 reviewInterval(startMs,endMs){this.review={start:startMs/1000+(this.item.media_timestamp_offset_ms||0)/1000,end:endMs/1000+(this.item.media_timestamp_offset_ms||0)/1000,started:false};this.el.muted=false;this.el.playbackRate=1;}
 syncReview(){const r=this.review;if(!r.started&&this.buffered(r.start)){this.el.currentTime=r.start;r.started=true;this.el.play().catch(()=>this.status('Press Play in the player'));}if(r.started&&this.el.currentTime>=r.end)this.el.pause();}
 destroy(){this.controller.abort();this.sourcePlayer?.subscribers.delete(this);for(const p of this.subscribers)p.destroy();this.subscribers.clear();this.el.pause();this.queue=[];this.history=[];try{this.el.removeAttribute('src');this.el.load();}catch{}if(this.objectUrl)URL.revokeObjectURL(this.objectUrl);}
}

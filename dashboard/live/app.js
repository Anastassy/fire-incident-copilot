import {esc, timecode, statusLabel, kindLabel, applyEvent, addObservation, contextEqual, api, sse} from './state.js';
import {LiveMedia} from './media.js';
import {scenarioName, deviceName} from './labels.js';

const $ = id => document.getElementById(id);
const icon = name => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
let config, scenarios = [], snapshot, observations = [], streams = [], players = [], reviewPlayer;
let epoch = 0, stateAbort, stateConnected = false, clockAnchor = {time:0, wall:0}, renderTimer;
let filter = 'all', displayLimit = 100, historyLoading = false, sound = false, selectedCamera = 'both';
let radioSelection;
let agentContext, agentSnapshot, agentAbort, agentEpoch = 0, agentTab = 'assistant', agentRefreshPending = false;
let drawerEpoch = 0, commandPending = false, lastAgentError = '', pendingQuestion, uncertainQuestion;
const runPath = () => `/api/state/runs/${encodeURIComponent(snapshot.run.run_id)}`;
const contextQuery = context => new URLSearchParams(context).toString();
const toast = message => { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(()=>$('toast').hidden=true, 6000); };
const connection = (id, ok, label) => { $(id).classList.toggle('online',ok); $(id).innerHTML = `<i></i>${esc(label)}`; };
const timeOf = o => o.observed_sim_time_ms ?? o.received_sim_time_ms ?? 0;
const byTime = (a,b) => timeOf(a)-timeOf(b) || a.evidence_id.localeCompare(b.evidence_id);
const valueText = (value, unit='') => value == null ? '—' : `${typeof value==='number'?Number(value.toFixed(2)):value}${unit?' '+unit:''}`;
function observe(item) { if(item.run_id===snapshot?.run.run_id && item.generation===snapshot?.run.generation) addObservation(observations,item); }
function setClock(time) { clockAnchor = {time,wall:performance.now()}; }
function simTime() { return snapshot ? Math.min(snapshot.run.duration_ms,clockAnchor.time+(snapshot.run.status==='playing'&&stateConnected?(performance.now()-clockAnchor.wall)*snapshot.run.speed:0)) : 0; }
function scheduleRender() { if(!renderTimer)renderTimer=setTimeout(()=>{renderTimer=null;renderState();},180); }

async function connectState(runId, scenarioId) {
  const ticket=++epoch; stateAbort?.abort(); stopMedia(); closeEvidence(); stateConnected=false;
  snapshot=null; observations=[]; renderState(); connection('state-connection',false,'Connecting…');
  try {
    if(!runId){ const run=await api('/api/state/runs',{scenario_id:scenarioId,speed:1},{headers:{'Idempotency-Key':crypto.randomUUID()}});runId=run.run_id; }
    const next=await api(`/api/state/runs/${encodeURIComponent(runId)}/snapshot`);
    if(ticket!==epoch)return; snapshot=next; setClock(next.run.sim_time_ms);
    const url=new URL(location.href);url.searchParams.set('run',runId);history.replaceState(null,'',url);
    $('run-id-input').value=runId; $('scenario-select').value=next.run.scenario_id;
    await startMedia(ticket); if(ticket!==epoch)return;
    loadHistory(ticket); consumeState(ticket); renderState();
  }catch(error){if(ticket===epoch){connection('state-connection',false,'Disconnected');toast('State API: '+error.message);renderState();}}
}
async function resync(ticket) {
  const next=await api(runPath()+'/snapshot');if(ticket!==epoch)return;
  const changed=next.run.generation!==snapshot.run.generation;
  snapshot=next;setClock(next.run.sim_time_ms);
  if(changed){observations=[];displayLimit=100;stopMedia();closeEvidence();await startMedia(ticket);}
  await loadHistory(ticket);scheduleRender();
}
async function consumeState(ticket) {
  stateAbort=new AbortController(); const signal=stateAbort.signal;
  while(ticket===epoch&&!signal.aborted){
    try { await sse(runPath()+'/stream',{signal,lastEventId:snapshot.as_of.cursor,
      onOpen:()=>{stateConnected=true;connection('state-connection',true,'Sources · SSE');},
      onMessage:message=>{
        if(ticket!==epoch)return;
        const item=message.data;
        if(message.type==='stream_error')throw new Error(item.error?.message||'Resynchronization required');
        if(message.type==='snapshot'){
          if(item.run.generation!==snapshot.run.generation)throw new Error('GENERATION_CHANGED');
          if(item.as_of.sequence>=snapshot.as_of.sequence){snapshot=item;setClock(item.run.sim_time_ms);}
        }else if(message.type==='event'){
          if(item.generation!==snapshot.run.generation||item.kind==='stream.reset')throw new Error('GENERATION_CHANGED');
          if(applyEvent(snapshot,item)){
            if(item.kind==='observation.created')observe(item.data);
            if(item.kind==='run.updated')setClock(item.data.sim_time_ms);
          }
        }else if(message.type==='heartbeat'){
          if(item.generation!==snapshot.run.generation)throw new Error('GENERATION_CHANGED');
          setClock(item.sim_time_ms);
        }
        scheduleRender();
      }});
    }catch(error){
      if(signal.aborted||ticket!==epoch)return;
      stateConnected=false;connection('state-connection',false,'Reconnecting');
      try{await resync(ticket);}catch{await sleep(1800);}
      await sleep(500);
    }
  }
}
async function loadHistory(ticket=epoch) {
  if(!snapshot)return;
  const generation=snapshot.run.generation,path=runPath();historyLoading=true;scheduleRender();
  try {let cursor;
    do{const page=await api(path+`/observations?generation=${generation}&limit=500`+(cursor?'&cursor='+encodeURIComponent(cursor):''));
      if(ticket!==epoch||snapshot.run.generation!==generation)return;
      page.items.forEach(observe);cursor=page.next_cursor;scheduleRender();
    }while(cursor);
  }catch(error){if(ticket===epoch)toast('History: '+error.message);}
  finally{if(ticket===epoch){historyLoading=false;scheduleRender();}}
}
function stopMedia(){players.forEach(p=>p.destroy());players=[];streams=[];document.querySelectorAll('.camera-tile').forEach(el=>el.classList.remove('has-frame'));}
async function startMedia(ticket) {
  const generation=snapshot.run.generation;
  const result=await api(runPath()+`/media-streams?generation=${generation}`);
  if(ticket!==epoch||snapshot.run.generation!==generation)return;
  streams=result.items;let videoIndex=0;
  const radioStreams=streams.filter(x=>x.kind==='audio');
  if(!radioStreams.some(x=>x.stream_id===radioSelection))radioSelection=radioStreams[0]?.stream_id;
  $('radio-select').innerHTML=radioStreams.map(x=>`<option value="${esc(x.stream_id)}">${esc(x.device_id)}</option>`).join('');
  $('radio-select').value=radioSelection||'';$('radio-select').hidden=radioStreams.length<2;
  for(const item of streams){
    const index=item.kind==='video'?videoIndex++:null;
    if(index>1||item.kind==='audio'&&item.stream_id!==radioSelection)continue;
    const el=item.kind==='audio'?$('radio-audio'):$('camera-'+index);
    el.muted=item.kind==='audio'?!sound:true;
    const player=new LiveMedia(el,item,snapshot.run,status=>{
      if(ticket!==epoch)return;
      if(index==null)$('audio-status').textContent=status;
      else{$('camera-status-'+index).textContent=status;el.closest('.camera-tile').classList.toggle('has-frame',el.readyState>=2);}
    });players.push(player);player.start();
    if(index!=null){$('camera-name-'+index).textContent=item.device_id.includes('GRADAS')?'Sala de Gradas':item.device_id.includes('GALLERY')?'Door gallery':item.device_id;}
  }
  $('camera-count').textContent=String(videoIndex).padStart(2,'0');
  $('coverage-track').parentElement.hidden=snapshot.run.scenario_id!=='base2-palisades-v1';
  document.querySelector('.floor-panel').hidden=snapshot.run.scenario_id!=='base2-palisades-v1';
  applyCameraLayout();
}
async function command(action,extra={}){
  if(!snapshot||commandPending)return;commandPending=true;renderControls();
  const ticket=epoch;
  try {const result=await api(runPath()+'/commands',{command_id:crypto.randomUUID(),expected_generation:snapshot.run.generation,action,...extra});
    if(ticket!==epoch)return;
    if(result.run.generation!==snapshot.run.generation){stateAbort?.abort();await resync(ticket);consumeState(ticket);}
    else{snapshot.run=result.run;setClock(result.run.sim_time_ms);}
    scheduleRender();
  }catch(error){toast('Command: '+error.message);if(error.status===409)await resync(ticket);}
  finally{commandPending=false;renderControls();}
}
function renderControls(){
  const run=snapshot?.run,playing=run?.status==='playing';
  $('play').disabled=!run||commandPending;$('reset').disabled=!run||commandPending;$('speed').disabled=!run||commandPending;
  $('play').innerHTML=icon(playing?'pause':'play')+`<span>${playing?'Pause':run?.status==='completed'?'Replay':'Play'}</span>`;
  $('run-status').textContent=run?statusLabel(run.status):'WAITING FOR CONNECTION';
  if(run){$('speed').value=run.speed;$('run-duration').textContent=' / '+timecode(run.duration_ms);}
}
function sparkline(deviceId){
  const samples=observations.filter(o=>o.device_id===deviceId&&o.kind==='measurement'&&typeof o.data.value==='number').sort(byTime).slice(-36).map(o=>o.data.value);
  if(samples.length<2)return '';
  const min=Math.min(...samples),range=Math.max(...samples)-min||1;
  return `<svg class="sparkline" viewBox="0 0 94 30" aria-label="Latest published measurements"><path d="${samples.map((v,i)=>`${i?'L':'M'}${i*94/(samples.length-1)},${27-(v-min)*24/range}`).join(' ')}" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>`;
}
function metric(title,value,unit,meta,ico,deviceId){return `<button class="metric metric-click" ${deviceId?`data-device="${esc(deviceId)}"`:'data-system="true"'}><div class="metric-label">${icon(ico)}${esc(title)}</div><div class="metric-value">${esc(value)} <small>${esc(unit)}</small></div><div class="metric-meta">${esc(meta)}</div>${deviceId?sparkline(deviceId):''}</button>`;}
function renderState(){
  renderControls();const devices=snapshot?.devices||[];
  const temp=devices.find(d=>d.device_id==='TMP-B2-GRADAS')||devices.find(d=>d.kind==='temperature_sensor');
  const smoke=devices.find(d=>d.device_id==='SMK-B2-GRADAS')||devices.find(d=>d.kind==='smoke_sensor');
  const gallery=devices.find(d=>d.device_id==='TMP-B2-GALLERY')||devices.filter(d=>d.kind==='temperature_sensor')[1];
  const base2=!snapshot||snapshot.run.scenario_id==='base2-palisades-v1';
  const metricDevice=(d,title,ico)=>{const r=d?.readings?.[0];return metric(title,valueText(r?.value),r?.unit,statusLabel(r?.availability||'missing'),ico,d?.device_id);};
  const transcripts=observations.filter(o=>o.kind==='radio_transcript');
  $('metrics').innerHTML=metricDevice(temp,base2?'Temperature · Gradas':deviceName(temp),'temp')+metricDevice(smoke,base2?'Smoke · Gradas':deviceName(smoke),'smoke')+metricDevice(gallery,base2?'Temperature · gallery':deviceName(gallery),'temp')+
    metric('People in building',valueText(snapshot?.occupancy?.[0]?.count),'',snapshot?.occupancy?.[0]?.count==null?'No occupancy source':statusLabel(snapshot.occupancy[0].availability),'people')+
    metric('Fresh sources',devices.filter(d=>d.availability==='fresh').length,`/ ${devices.length}`,'Reported source availability','link')+
    metric('Radio traffic',transcripts.length,'messages','Published in this run','radio');
  if(snapshot){
    const scenario=scenarios.find(s=>s.scenario_id===snapshot.run.scenario_id);
    $('scenario-subtitle').textContent=scenarioName(scenario)||snapshot.run.scenario_id;
    $('building-label').textContent=base2?'BASE2 · VALENCIA':scenario?.building_id||snapshot.run.scenario_id;
    document.querySelectorAll('.camera-technical').forEach(el=>el.textContent=base2?'SYNTHETIC CCTV':'RECORDED CCTV');
    const gaps=devices.filter(d=>d.availability==='stale'||d.availability==='disconnected');
    const banner=$('alert-banner');banner.hidden=!gaps.length;
    banner.textContent=gaps.length?`${gaps.length} ${gaps.length===1?'source needs':'sources need'} attention · ${gaps.map(deviceName).join(' · ')}. Last readings retained; no new data.`:'';
    $('session-footer').textContent=`RUN ${snapshot.run.run_id.slice(0,8)} · G${snapshot.run.generation} · ${snapshot.system?.events?.dropped??'—'} dropped · ${stateConnected?'stream connected':'stream disconnected'}`;
  }
  renderMap(devices);renderEvents();renderRadio(transcripts);
}
function renderMap(devices){
  const positions={'TMP-B2-GRADAS':[293,44],'SMK-B2-GRADAS':[353,44],'PWR-B2-GRADAS':[422,116],'CAM-B2-GRADAS':[239,114],'ACCESS-B2-GRADAS':[260,144],'TMP-B2-GALLERY':[287,177],'SMK-B2-GALLERY':[350,177],'CAM-B2-GALLERY':[418,177],'TMP-B2-COWORK':[71,45],'SMK-B2-COWORK':[151,45]};
  $('floor-sensors').innerHTML=devices.filter(d=>positions[d.device_id]).map(d=>{const [x,y]=positions[d.device_id],color=d.availability==='fresh'?'#6fc9b5':d.availability==='stale'||d.availability==='disconnected'?'#e5a566':'#7a8287';return `<g class="sensor-dot" data-device="${esc(d.device_id)}" tabindex="0" role="button" aria-label="${esc(deviceName(d))}"><title>${esc(deviceName(d)+' · '+statusLabel(d.availability))}</title><circle cx="${x}" cy="${y}" r="10" fill="${color}" opacity=".12"/><circle cx="${x}" cy="${y}" r="4" fill="${color}"/></g>`;}).join('');
}
function description(o){const d=o.data; if(o.kind==='measurement')return `${d.metric} · ${valueText(d.value,d.unit)}`;if(o.kind==='radio_transcript')return d.text||d.transcript||'Text unavailable';if(o.kind==='camera')return 'Video segment published';if(o.kind==='radio_audio')return 'Radio segment published';if(o.kind==='access')return d.description||d.event_type||d.action||'Badge reader event';if(o.kind==='connectivity')return d.connected?'Connection restored':'Connection lost';return JSON.stringify(d);}
function renderEvents(){
  const search=$('event-search').value.trim().toLowerCase();
  const matching=observations.filter(o=>(filter==='all'||o.kind===filter||(filter==='radio_transcript'&&o.kind==='radio_audio'))&&(!search||[o.device_id,o.room_id,description(o),o.evidence_id].join(' ').toLowerCase().includes(search))).sort(byTime).reverse();
  const list=$('event-list'),scroll=list.scrollTop;
  list.innerHTML=matching.slice(0,displayLimit).map(o=>`<button class="event-row ${esc(o.kind)}" data-observation="${esc(o.evidence_id)}"><span class="event-time">${timecode(timeOf(o))}</span><span class="event-source">${icon(o.kind==='measurement'?'temp':o.kind.startsWith('radio')?'radio':o.kind==='camera'?'camera':'link')}<span>${esc(o.device_id)}</span></span><span class="event-description">${esc(description(o))}</span><span class="event-detail">${esc(kindLabel(o.kind))} ${icon('arrow')}</span></button>`).join('')||'<div class="empty-inline">No published events match these filters.</div>';
  list.scrollTop=$('follow-events').checked?0:scroll;
  $('event-count').textContent=observations.length;
  $('event-footer').textContent=`${historyLoading?'Loading history… · ':''}${Math.min(displayLimit,matching.length)} of ${matching.length} · source time`;
  $('load-history').textContent=matching.length>displayLimit?'Show 100 more':'Refresh history';
}
function renderRadio(items){
  const list=$('transcripts'),wasBottom=list.scrollHeight-list.scrollTop-list.clientHeight<40,scroll=list.scrollTop;
  const selected=streams.find(x=>x.stream_id===radioSelection);
  list.innerHTML=items.filter(o=>!selected||o.device_id===selected.device_id).sort(byTime).map(o=>`<button class="transcript" data-observation="${esc(o.evidence_id)}"><span class="transcript-time">${timecode(o.data.audio_start_sim_time_ms??timeOf(o))} ${icon('play')}</span><p>${esc(description(o))}</p></button>`).join('')||'<div class="empty-inline">Messages will appear as audio arrives.<br><span>Archived recording · prerecorded machine transcript</span></div>';
  list.scrollTop=wasBottom||$('follow-events').checked?list.scrollHeight:scroll;
}
function applyCameraLayout(){
  $('camera-grid').classList.toggle('single',selectedCamera!=='both');
  document.querySelectorAll('[data-camera]').forEach(el=>el.hidden=selectedCamera!=='both'&&el.dataset.camera!==selectedCamera);
  document.querySelectorAll('[data-layout]').forEach(el=>el.classList.toggle('selected',el.dataset.layout===selectedCamera));
}

// The agent owns the projections; SSE messages only invalidate this local view.
async function refreshAgent(){
  if(!agentContext)return;
  const ticket=agentEpoch,context={...agentContext};
  try{const next=await api('/api/agent/agent/v1/state?'+contextQuery(context));
    if(ticket!==agentEpoch||!contextEqual(next.context,agentContext))return;
    if(!agentSnapshot||next.snapshot_revision>=agentSnapshot.snapshot_revision){agentSnapshot=next;lastAgentError='';connection('agent-connection',true,'Agent · API');renderAgent();}
  }catch(error){if(ticket===agentEpoch){lastAgentError=error.message;connection('agent-connection',false,'Agent unavailable');renderAgent();}}
}
async function connectAgent(context){
  agentAbort?.abort();agentContext={...context};agentSnapshot=null;pendingQuestion=null;uncertainQuestion=null;closeEvidence();
  const ticket=++agentEpoch;agentAbort=new AbortController();const signal=agentAbort.signal;
  $('agent-context-input').value=context.demo_context_id;$('agent-generation-input').value=context.generation;$('agent-subject-input').value=context.subject_id;
  renderAgent();await refreshAgent();
  while(ticket===agentEpoch&&!signal.aborted){
    try{await sse('/api/agent/agent/v1/events?'+contextQuery(context),{signal,onOpen:refreshAgent,onMessage:m=>{
      if(ticket!==agentEpoch)return;
      if(m.data.context&&!contextEqual(m.data.context,agentContext))return;
      if(m.data.type==='context.invalidated'){lastAgentError='The server reset this context. Enter the new generation in connection settings.';agentSnapshot=null;renderAgent();return;}
      refreshAgent();
    }});}catch{if(signal.aborted||ticket!==agentEpoch)return;await refreshAgent();await sleep(2000);}
  }
}
function claimMarkup(claim){const kinds={source_report:'Source report',measurement:'Measurement',inference:'Agent inference',absence_in_checked_data:'Not found in checked data'};return `<div class="claim"><span class="claim-kind">${esc(kinds[claim.kind]||claim.kind)}</span><p>${esc(claim.text)}</p><div>${(claim.evidence_ids||[]).map((id,i)=>`<button class="evidence-link" data-evidence="${esc(id)}">${icon('link')} Source ${i+1}</button>`).join('')}</div></div>`;}
function traceMarkup(entity){const c=entity.coverage;return `<div class="unknowns">${(entity.unknowns||[]).length?'<strong>Still unknown</strong>':''}${(entity.unknowns||[]).map(x=>`<p>${esc(x)}</p>`).join('')}</div><details class="trace"><summary>Coverage and queries ${icon('arrow')}</summary>${c?`<p>${timecode(c.checked_from_ms)}–${timecode(c.checked_until_ms)} · ${esc({complete:'Complete',partial:'Partial',unknown:'Completeness unknown'}[c.completeness])}</p>${c.limitations.map(x=>`<p>${esc(x)}</p>`).join('')}`:''}<pre>${esc(JSON.stringify(entity.queries||[],null,2))}</pre></details>`;}
function renderAgent(){
  const answers=agentSnapshot?.answers||[],cards=agentSnapshot?.cards||[];
  $('check-count').textContent=cards.length;
  document.querySelectorAll('[data-agent-tab]').forEach(el=>el.classList.toggle('selected',el.dataset.agentTab===agentTab));
  const welcome='<div class="copilot-welcome"><span class="eyebrow">EVIDENCE BEFORE CONCLUSIONS</span><h3>What we know.<br>What we do not.</h3><p>Ask a question to check the sources in the agent context. Trace each claim back to the original message.</p></div>';
  let content='';
  if(agentTab==='checks')content=cards.map(c=>`<article class="check-card"><div class="card-status-line"><span class="status-tag">${esc(statusLabel(c.assessment))}</span><span>v${c.revision}</span></div><h3>${esc(c.statement)}</h3>${c.claims.map(claimMarkup).join('')}${traceMarkup(c)}<details class="trace"><summary>Check status</summary><p>Lifecycle: ${esc(statusLabel(c.lifecycle))}</p><p>Publication: ${esc(c.publication_status)}. Pending can also mean publication is not in use.</p><p>Platform status: ${esc(c.platform_status||'not assigned')}</p>${c.closure_reason?`<p>${esc(c.closure_reason)}</p>`:''}<button class="evidence-link" data-card="${esc(c.hypothesis_id)}">Full API card</button></details></article>`).join('')||'<div class="empty-inline">No checks in this context yet.</div>';
  else content=[...answers].sort((a,b)=>b.created_at.localeCompare(a.created_at)).map(a=>`<article class="answer-card"><div class="answer-question">${esc(a.question)}</div><div class="answer-status ${esc(a.status)}">${icon(a.status==='ready'?'check':'spark')}${esc(statusLabel(a.status))}${['queued','running'].includes(a.status)?`<button class="evidence-link" data-cancel="${esc(a.request_id)}">Cancel</button>`:''}</div>${a.claims.map(claimMarkup).join('')}${a.error?`<p class="unknowns">${esc(a.error.message)}</p>`:''}${traceMarkup(a)}${a.status==='error'?`<button class="evidence-link" data-retry="${esc(a.request_id)}">Retry question</button>`:''}</article>`).join('')||welcome;
  if(pendingQuestion)content=`<div class="loading-text">${esc(pendingQuestion.question)} · sending…</div>`+content;
  if(uncertainQuestion)content='<div class="empty-inline">Submission response not received. <button class="evidence-link" data-resend="true">Retry with the same ID</button></div>'+content;
  if(lastAgentError)content=`<div class="empty-inline">${esc(lastAgentError)}</div>`+content;
  // Preserve expanded evidence/trace sections through recovery refreshes.
  const target=$('agent-content'),oldHTML=target.dataset.rendered;
  if(oldHTML!==content){const top=target.scrollTop;target.innerHTML=content;target.dataset.rendered=content;target.scrollTop=top;}
}
async function askQuestion(text,reuseBody){
  if(!text.trim()||!agentContext||pendingQuestion)return;
  const context={...agentContext},ticket=agentEpoch;
  const body=reuseBody||{context,client_request_id:crypto.randomUUID(),question:text.trim(),language:'en'};
  pendingQuestion=body;agentTab='assistant';renderAgent();
  try{const answer=await api('/api/agent/agent/v1/questions',body);
    if(ticket!==agentEpoch)return;
    uncertainQuestion=null;$('question').value='';agentSnapshot||={context,snapshot_revision:0,answers:[],cards:[]};
    if(!agentSnapshot.answers.some(x=>x.request_id===answer.request_id))agentSnapshot.answers.push(answer);
    await refreshAgent();
  }catch(error){if(ticket===agentEpoch){if(!error.status||error.status>=500)uncertainQuestion=body;toast('Question: '+error.message);}}
  finally{if(ticket===agentEpoch){pendingQuestion=null;renderAgent();}}
}
async function seedAgent(action){try{const context=await api('/api/agent-demo',{action});if(!contextEqual(agentContext,context))connectAgent(context);else await refreshAgent();}catch(error){toast('Agent demo: '+error.message);}}

function closeEvidence(){drawerEpoch++;reviewPlayer?.destroy();reviewPlayer=null;$('radio-audio').muted=!sound;$('review-audio').pause();$('review-audio').onloadedmetadata=null;$('review-audio').ontimeupdate=null;$('review-audio').removeAttribute('src');$('review-audio').hidden=true;document.querySelectorAll('.evidence-video').forEach(v=>{v.pause();v.removeAttribute('src');v.load();v.remove();});$('evidence-drawer').hidden=true;$('drawer-backdrop').hidden=true;}
function openDrawer(title,body,raw){closeEvidence();$('evidence-drawer').hidden=false;$('drawer-backdrop').hidden=false;$('evidence-body').innerHTML=`<h2>${esc(title)}</h2>${body}`;$('evidence-raw').innerHTML=raw?`<details><summary>Original source JSON</summary><pre>${esc(JSON.stringify(raw,null,2))}</pre></details>`:'';}
function openObservation(id){
  const o=observations.find(x=>x.evidence_id===id);if(!o)return;
  openDrawer(kindLabel(o.kind),`<div class="evidence-meta">${esc(o.device_id)} · ${timecode(timeOf(o))}</div><p>${esc(description(o))}</p><div class="evidence-meta">${esc(o.provenance?.origin||'unknown')} · ${esc(o.provenance?.source_id||'')}<br>${esc(o.provenance?.composition_note||'')}</div>`,o);
  if(o.kind==='radio_transcript'){
    const source=streams.find(s=>s.kind==='audio'&&s.device_id===o.device_id);
    const start=o.data.audio_start_sim_time_ms,end=o.data.audio_end_sim_time_ms;
    if(source&&Number.isFinite(start)&&Number.isFinite(end)){
      $('evidence-body').insertAdjacentHTML('beforeend',`<button class="primary-button" id="review-fragment">${icon('play')} Listen ${timecode(start)}–${timecode(end)}</button><p class="evidence-meta">Machine transcript from the source package. Audio Provided by Broadcastify · CC-BY-3.0-US.</p>`);
      $('review-fragment').onclick=()=>{const ticket=drawerEpoch;
        const original=players.find(x=>x.item.stream_id===source.stream_id),el=$('review-audio');el.hidden=false;
        if(!original)return toast('Select this radio source, then reopen the message.');
        $('radio-audio').muted=true;
        reviewPlayer?.destroy();reviewPlayer=new LiveMedia(el,source,snapshot.run,status=>{if(ticket===drawerEpoch)$('review-fragment').textContent=status;});reviewPlayer.reviewInterval(start,end);reviewPlayer.start(original);
      };
    }
  }
  if(o.kind==='camera'&&o.data.media_id){$('evidence-body').insertAdjacentHTML('beforeend','<button class="primary-button" id="review-video">Open this video segment</button>');
    $('review-video').onclick=async()=>{const ticket=drawerEpoch;try{const m=await api(runPath()+`/media/${encodeURIComponent(o.data.media_id)}?generation=${snapshot.run.generation}`);if(ticket!==drawerEpoch)return;const url=new URL(m.content_url,location.href);if(!url.pathname.startsWith('/api/v1/runs/'))throw new Error('Unknown media path');$('evidence-body').insertAdjacentHTML('beforeend',`<video class="evidence-video" controls autoplay muted playsinline src="${esc('/api/state'+url.pathname.slice(7)+url.search)}"></video>`);$('review-video').hidden=true;}catch(error){toast(error.message);}};
  }
}
async function openAgentEvidence(id){
  const context={...agentContext};openDrawer('Agent evidence','<p>Loading source evidence…</p>');const ticket=drawerEpoch;
  try{const e=await api('/api/agent/agent/v1/evidence/'+encodeURIComponent(id)+'?'+contextQuery(context));if(ticket!==drawerEpoch||!contextEqual(context,agentContext))return;
    openDrawer(e.source_label,`<div class="evidence-meta">${timecode(e.event_from_ms)}–${timecode(e.event_until_ms)} · reading ${e.reading_id}</div><p>${esc(e.text)}</p><div class="evidence-meta">${esc(e.origin)} · ${esc(e.text_kind)} · ${esc(e.verification)}</div>`,e.raw_reading);
    const a=e.audio;if(a?.availability==='available'&&a.playback_url){const url=new URL(a.playback_url,location.href);if(!['http:','https:'].includes(url.protocol))throw new Error('Unsupported audio URL');const el=$('review-audio');el.hidden=false;el.src=url.href;el.onloadedmetadata=()=>el.currentTime=a.start_ms/1000;el.ontimeupdate=()=>{if(el.currentTime>=a.end_ms/1000)el.pause();};}
    else $('evidence-body').insertAdjacentHTML('beforeend',`<p class="unknowns">Audio: ${esc(a?.availability||'missing')}. The agent service has not provided a recording for this evidence.</p>`);
  }catch(error){if(ticket===drawerEpoch)$('evidence-body').textContent='Evidence unavailable: '+error.message;}
}
function openDevice(id){const d=snapshot?.devices.find(x=>x.device_id===id);if(!d)return;openDrawer(deviceName(d),`<div class="evidence-meta">${esc(d.device_id)} · ${esc(d.room_id)} · ${esc(statusLabel(d.availability))}</div>${d.readings.map(r=>`<p>${esc(r.metric)}: <strong>${esc(valueText(r.value,r.unit))}</strong><br><span class="evidence-meta">${esc(statusLabel(r.availability))} · last measurement ${r.observed_sim_time_ms==null?'not received':timecode(r.observed_sim_time_ms)}</span></p>`).join('')}${sparkline(id)}`,d);}

document.addEventListener('click',async event=>{
  const target=event.target.closest('button,[data-device]');if(!target)return;
  if(target.dataset.observation)openObservation(target.dataset.observation);
  if(target.dataset.evidence)openAgentEvidence(target.dataset.evidence);
  if(target.dataset.device)openDevice(target.dataset.device);
  if(target.dataset.system)openDrawer('System and sources',`<p>State API diagnostics. Missing data does not indicate normal conditions.</p>`,{system:snapshot?.system,devices:snapshot?.devices,access:snapshot?.access,occupancy:snapshot?.occupancy});
  if(target.dataset.filter){filter=target.dataset.filter;document.querySelectorAll('[data-filter]').forEach(el=>el.classList.toggle('selected',el===target));renderEvents();}
  if(target.dataset.layout){selectedCamera=target.dataset.layout;applyCameraLayout();}
  if(target.dataset.expand!=null) $('camera-'+target.dataset.expand).closest('article').requestFullscreen?.().catch(()=>toast('Fullscreen unavailable'));
  if(target.dataset.agentTab){agentTab=target.dataset.agentTab;renderAgent();}
  if(target.dataset.demo)seedAgent(target.dataset.demo);
  if(target.dataset.cancel){try{await api('/api/agent/agent/v1/questions/'+encodeURIComponent(target.dataset.cancel)+'/cancel?'+contextQuery(agentContext),{});await refreshAgent();}catch(error){toast(error.message);}}
  if(target.dataset.retry){const a=agentSnapshot.answers.find(x=>x.request_id===target.dataset.retry);if(a)askQuestion(a.question);}
  if(target.dataset.resend&&uncertainQuestion)askQuestion(uncertainQuestion.question,uncertainQuestion);
  if(target.dataset.card){try{const c=await api('/api/agent/agent/v1/cards/'+encodeURIComponent(target.dataset.card)+'?'+contextQuery(agentContext));openDrawer(c.statement,`<p>${esc(statusLabel(c.assessment))}</p>${c.claims.map(claimMarkup).join('')}${traceMarkup(c)}`,c);}catch(error){toast(error.message);}}
  if(target.dataset.nav){const name=target.dataset.nav;document.querySelectorAll('[data-nav]').forEach(el=>el.classList.toggle('active',el===target));const panel={camera:'camera-panel',radio_transcript:'radio-panel',events:'event-panel',agent:'copilot-panel'}[name];if(panel)$(panel).scrollIntoView({behavior:'smooth',block:'start'});else window.scrollTo({top:0,behavior:'smooth'});}
});
$('play').onclick=async()=>{if(snapshot?.run.status==='completed'){await command('reset');await command('play');}else command(snapshot?.run.status==='playing'?'pause':'play');};
$('reset').onclick=()=>command('reset');$('speed').onchange=()=>command('set_speed',{speed:Number($('speed').value)});
$('coverage-track').title='Seek the scenario: this changes the run generation';
$('coverage-track').onclick=e=>{const r=e.currentTarget.getBoundingClientRect();if(snapshot)command('seek',{position_ms:Math.round(Math.max(0,Math.min(1,(e.clientX-r.left)/r.width))*snapshot.run.duration_ms)});};
$('sound-toggle').onclick=()=>{sound=!sound;const audio=$('radio-audio');audio.muted=!sound;if(sound)audio.play().catch(()=>{});$('sound-toggle').classList.toggle('enabled',sound);$('sound-toggle').querySelector('span').textContent=sound?'Sound on':'Sound off';};
$('radio-select').onchange=async()=>{radioSelection=$('radio-select').value;closeEvidence();stopMedia();try{await startMedia(epoch);renderState();}catch(error){toast(error.message);}};
$('event-search').oninput=renderEvents;$('load-history').onclick=()=>{displayLimit+=100;loadHistory();renderEvents();};
$('show-radio-log').onclick=()=>{document.querySelector('[data-filter="radio_transcript"]').click();$('event-panel').scrollIntoView({behavior:'smooth'});};
$('export-events').onclick=()=>{const blob=new Blob([JSON.stringify({run:snapshot?.run,observations:[...observations].sort(byTime)},null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`firewatch-${snapshot?.run.run_id||'empty'}-g${snapshot?.run.generation||0}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
$('question-form').onsubmit=e=>{e.preventDefault();askQuestion($('question').value);};
$('suggestions').onclick=e=>{const b=e.target.closest('button');if(b)askQuestion(b.textContent);};
$('close-evidence').onclick=closeEvidence;$('drawer-backdrop').onclick=closeEvidence;
function openSettings(){$('run-id-input').value=snapshot?.run.run_id||'';$('settings-dialog').showModal();}
$('settings-open').onclick=openSettings;$('connect-button').onclick=openSettings;
$('settings-connect').onclick=()=>{const context={demo_context_id:$('agent-context-input').value.trim(),generation:Number($('agent-generation-input').value),subject_id:$('agent-subject-input').value.trim()};if(!context.demo_context_id||!context.subject_id||!Number.isInteger(context.generation)||context.generation<0){toast('Enter the complete agent context');return;}$('settings-dialog').close();connectState($('run-id-input').value.trim(),$('scenario-select').value);connectAgent(context);};
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeEvidence();if(e.code==='Space'&&!['INPUT','TEXTAREA','SELECT','BUTTON'].includes(e.target.tagName)&&!$('settings-dialog').open){e.preventDefault();$('play').click();}if(e.key==='Enter'&&e.target.matches('[data-device]'))openDevice(e.target.dataset.device);});
setInterval(()=>{if(agentContext&&!agentRefreshPending){agentRefreshPending=true;refreshAgent().finally(()=>agentRefreshPending=false);}},5000);
function animate(){const time=simTime();$('run-clock').textContent=timecode(time);$('coverage-cursor').style.left=(snapshot?time/snapshot.run.duration_ms*100:0)+'%';players.forEach(p=>{p.sync(time,snapshot?.run.status==='playing'&&stateConnected,snapshot?.run.speed||1);if(p.item.kind==='video')p.el.closest('article').classList.toggle('has-frame',p.el.readyState>=2);});reviewPlayer?.syncReview();$('wave').classList.toggle('active',snapshot?.run.status==='playing'&&!$('radio-audio').paused);requestAnimationFrame(animate);}
window.addEventListener('beforeunload',()=>{stateAbort?.abort();agentAbort?.abort();stopMedia();reviewPlayer?.destroy();});
async function boot(){
  $('wave').innerHTML=Array.from({length:35},(_,i)=>`<i style="--h:${8+((i*17+11)%29)}px;--d:${(i%7)*-.13}s"></i>`).join('');renderState();animate();
  try{config=await api('/api/config');
    try{scenarios=(await api('/api/state/scenarios')).items;}catch(error){toast('State API catalog: '+error.message);}
    $('scenario-select').innerHTML=scenarios.map(s=>`<option value="${esc(s.scenario_id)}">${esc(scenarioName(s))}</option>`).join('');$('scenario-select').value=config.scenario;
    const fixture=config.agent.engine==='FixtureEngine';
    $('agent-mode').textContent=fixture?'Demo engine · FixtureEngine':config.agent.engine||'Disconnected';
    $('agent-context-note').textContent=fixture?'Separate agent API demo. These answers and checks do not analyze the Base2 stream.':'Answers and checks from the connected agent context. Each claim includes its sources and coverage.';
    $('agent-demo-tools').hidden=!(fixture&&config.demo_agent);
    $('endpoint-info').textContent=`State: ${config.state_url}\nAgent: ${config.agent_url}\nData Platform: ${config.platform_configured?config.platform_url:'not connected yet'}\nAgent import: ${JSON.stringify(config.agent.platform||{})}`;
    if(fixture&&config.demo_agent){api('/api/agent-demo',{action:'request'}).then(connectAgent).catch(error=>{lastAgentError=error.message;connectAgent(config.agent_context);});}else connectAgent(config.agent_context);
    if(config.state_configured)connectState(new URL(location.href).searchParams.get('run'),config.scenario);else toast('Provide State API credentials when starting the gateway.');
  }catch(error){toast('Connection: '+error.message);}
}
boot();

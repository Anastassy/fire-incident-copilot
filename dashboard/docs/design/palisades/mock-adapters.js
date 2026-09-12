/* MOCK IMPLEMENTATIONS ONLY. Replace createPalisadesAdapters at composition boundary.
   UI never consumes the full fixture. IDs here are local mock IDs, not reading_id. */
(function(root){
 const START=130.42,END=142;
 function createPalisadesAdapters(fixtures,options={}){
  const lag=options.lag??650;let time=START,generation=0,playing=false,omitReply=false,disposed=false,fail=false;
  const listeners=new Set(),checks=new Set();let timer=null,checkTimer=null,lastKey='',revision=0;
  let check={status:'checking',stage:'request',evidenceIds:[],generation,asOf:time};
  const rows=()=>fixtures.filter(r=>r.end<=time&&!(omitReply&&r.start>=138.7&&r.end<=140.27));
  const snapshot=()=>({runId:'mock-palisades',generation,time,startTime:START,endTime:END,playing,ended:time>=END,omitReply,mode:'mock',records:rows().map(r=>({...r}))});
  function notify(){if(!disposed)listeners.forEach(f=>f(snapshot()))}
  function notifyCheck(){if(!disposed)checks.forEach(f=>f({...check,evidenceIds:[...check.evidenceIds]}))}
  function investigate(){
   clearTimeout(checkTimer);const g=generation,at=time,records=rows();
   check={...check,status:'checking',generation:g,asOf:at};notifyCheck();
   checkTimer=setTimeout(()=>{if(g!==generation||disposed)return;
    if(fail){check={...check,status:'error',revision:++revision,generation:g,asOf:at};notifyCheck();return}
    // Deliberately deterministic mock classifier; never presented as a model.
    const request=records.find(r=>r.start===128.6),assignment=records.find(r=>r.start===133.26),reply=records.find(r=>r.start===138.7);
    check={status:'ready',stage:reply&&assignment?'acknowledged':assignment?'answered':'request',channel:assignment?'V-Fire 25':null,evidenceIds:[request,assignment,reply].filter(Boolean).map(r=>r.id),exchange:[['request',request],['assignment',assignment],['reply',reply]].filter(([,r])=>r).map(([role,r])=>({role,evidenceId:r.id})),generation:g,asOf:at,revision:++revision,queries:[{tool:'mock:publishedHistory',count:records.length,asOf:at}],origin:'scripted_mock'};notifyCheck();
   },lag)
  }
  function changed(){notify();const key=rows().map(r=>r.id).join('|');if(key!==lastKey){lastKey=key;investigate()}}
  function pause(){playing=false;clearInterval(timer);timer=null;notify()}
  function advance(seconds){time=Math.min(END,time+Math.max(0,seconds));changed();if(time>=END)pause()}
  function play(){if(playing||time>=END||disposed)return;playing=true;let previous=Date.now();timer=setInterval(()=>{const n=Date.now();advance((n-previous)/1000);previous=n},100);notify()}
  function reset(settings={}){pause();generation++;clearTimeout(checkTimer);time=START;omitReply=settings.omitReply??omitReply;fail=false;lastKey='';check={status:'checking',stage:'request',evidenceIds:[],generation,asOf:time,revision:++revision};notifyCheck();changed()}
  const data={snapshot,subscribe(fn){listeners.add(fn);fn(snapshot());return()=>listeners.delete(fn)},getRecord(id){const r=rows().find(x=>x.id===id);if(!r)throw new Error('Record not published in this generation');return {...r}},history(q=''){return rows().filter(r=>r.text.toLowerCase().includes(q.toLowerCase())).map(r=>({...r}))}};
  const replay={play,pause,reset,advance,dispose(){disposed=true;pause();clearTimeout(checkTimer);listeners.clear();checks.clear()}};
  const agent={subscribe(fn){checks.add(fn);fn({...check});return()=>checks.delete(fn)},retry(){fail=false;investigate()},simulateError(){fail=true;investigate()},async ask(question){
   const g=generation,at=time,records=rows();await new Promise(r=>setTimeout(r,lag));if(g!==generation||disposed)throw new Error('CONTEXT_CHANGED');if(fail)throw new Error('SEARCH_FAILED');
   const assignment=records.find(r=>r.start===133.26),reply=records.find(r=>r.start===138.7),all=/everyone|all|все|вся|всех|переш/i.test(question),ack=/acknow|reply|answer|channel|ответ|канал|подтверж/i.test(question);
   let text=all?'Not established. The published excerpt does not verify every team member’s radio state.':!ack?'This mock supports the two example questions. Connect the agent adapter for open-ended questions.':reply&&assignment?'A channel assignment and an acknowledging reply appear in the published transcript. Verify the source audio.':assignment?'An answer assigning V-Fire 25 is present. No acknowledging reply was found in the published transcript.':'No answer to the group’s request was found in the published transcript.';
   return {generation:g,asOf:at,text,evidenceIds:[assignment,reply].filter(Boolean).map(r=>r.id),origin:'scripted_mock'}
  }};
  const media={async resolve(id){const r=data.getRecord(id);return {url:'../../../data/demo/palisades-radio-demo/audio/decision-focus.mp3',start:r.start,end:r.end,record:r,generation}}};
  changed();return {data,replay,agent,media,capabilities:{mode:'mock',replay:true}};
 }
 root.createPalisadesAdapters=createPalisadesAdapters;
})(typeof window!=='undefined'?window:globalThis);

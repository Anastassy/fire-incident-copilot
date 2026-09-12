import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {esc, timecode, statusLabel, contextEqual} from '../state.js';

// Execute the production controllers against a minimal DOM and deferred transport.
// This exercises response ordering without a browser, timers, or upstream services.
const source=fs.readFileSync(new URL('../app.js',import.meta.url),'utf8');
function section(start,end){
  const from=source.indexOf(start),until=source.indexOf(end,from);
  assert.ok(from>=0&&until>from,`Controller section exists: ${start}`);
  return source.slice(from,until);
}
const pipeline=section('function resetPipeline(){','// The agent owns the projections');
const projection=section('function claimMarkup(','async function askQuestion');
const evidence=section('async function openAgentEvidence(','function openDevice(');
const card=section('async function openAgentCard(','function openDevice(');
const refresh=section('async function refreshAgent(){','async function connectAgent(');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const context=(run='current',generation=4)=>({demo_context_id:`state-${run}-g${generation}`,generation:0,subject_id:'all'});
const live=(run='current',generation=4)=>({state:'live',run_id:run,generation,context:context(run,generation)});

function harness(overrides={}){
  const elements=new Map(),connections=[];
  const $=id=>{
    if(!elements.has(id))elements.set(id,{
      textContent:'',innerHTML:'',value:'',dataset:{},scrollTop:0,
      classList:{toggle(){}},setAttribute(){},querySelector:()=>({}),querySelectorAll:()=>[],
      insertAdjacentHTML(_where,html){this.innerHTML+=html;},
    });
    return elements.get(id);
  };
  const scope={$,elements,connections,AbortController,URLSearchParams,URL,
    esc,timecode,statusLabel,contextEqual,icon:()=>'',contextQuery:c=>new URLSearchParams(c).toString(),
    timeOf:o=>o.observed_sim_time_ms??o.received_sim_time_ms??0,
    sleep:()=>new Promise(()=>{}),document:{querySelectorAll:()=>[]},
    config:{pipeline_enabled:true},snapshot:{run:{run_id:'current',generation:4}},
    stateConnected:true,simTime:()=>141300,
    pipelineEpoch:0,pipelineTarget:null,pipelineStatus:null,pipelineAbort:null,epoch:0,
    agentEpoch:0,agentAbort:null,agentContext:null,agentSnapshot:null,agentTab:'briefing',
    pendingQuestion:null,uncertainQuestion:null,lastAgentError:'',drawerEpoch:0,
    observations:[],connection(){},renderAgent(){},
    api:async()=>{throw new Error('Unexpected transport call');},
    ...overrides,
  };
  scope.closeEvidence=()=>{scope.drawerEpoch++;};
  scope.openDrawer=(_title,body)=>{scope.drawerEpoch++;$('evidence-body').innerHTML=body;};
  scope.connectAgent=value=>{scope.agentContext=value;scope.agentSnapshot={};connections.push(value.demo_context_id);};
  vm.createContext(scope);
  return scope;
}

test('late pipeline response cannot reconnect a previous State run',async()=>{
  let resolveOld;
  const oldResponse=new Promise(resolve=>resolveOld=resolve);
  const scope=harness({api:async(path,body)=>{
    if(path.endsWith('/connect'))return body.run_id==='old'?oldResponse:{};
    return live('new',2);
  }});
  vm.runInContext(pipeline,scope);
  scope.snapshot={run:{run_id:'old',generation:1}};scope.followPipeline();
  scope.epoch++;scope.snapshot={run:{run_id:'new',generation:2}};scope.followPipeline();
  await flush();resolveOld({});await flush();
  assert.deepEqual(scope.connections,['state-new-g2']);
});

test('pipeline rejects a mismatched run, generation, or issued agent context',async()=>{
  for(const response of [live('other',4),live('current',3),{...live(),context:context('other',4)}]){
    const scope=harness({api:async path=>path.includes('/status')?response:{}});
    vm.runInContext(pipeline,scope);scope.followPipeline();await flush();
    assert.deepEqual(scope.connections,[]);
    assert.equal(scope.agentContext,null);
  }
});

test('generation invalidation clears pending UI work and fences an old agent refresh',async()=>{
  let resolveSnapshot;
  const scope=harness({agentContext:context(),agentSnapshot:{answers:[{request_id:'old'}]},
    pendingQuestion:{question:'old'},uncertainQuestion:{question:'old'},lastAgentError:'old error',
    api:()=>new Promise(resolve=>resolveSnapshot=resolve)});
  vm.runInContext(pipeline+refresh,scope);
  const oldRefresh=scope.refreshAgent();scope.resetPipeline();
  assert.equal(scope.agentSnapshot,null);assert.equal(scope.agentContext,null);
  assert.equal(scope.pendingQuestion,null);assert.equal(scope.uncertainQuestion,null);
  assert.equal(scope.lastAgentError,'');
  resolveSnapshot({context:context(),snapshot_revision:100,answers:[{request_id:'old'}]});
  await oldRefresh;assert.equal(scope.agentSnapshot,null);
});

function answer(id,status,text,date,automatic=true){return{
  request_id:id,status,question:automatic?'Live assessment: summarize the current incident':'What is confirmed?',
  created_at:date,claims:text?[{kind:'source_report',text,evidence_ids:['source-1']}]:[],
  unknowns:['Speaker identity remains unverified.'],evidence_ids:['source-1'],
  coverage:{checked_from_ms:0,checked_until_ms:139000,completeness:'partial',limitations:['Bounded source sample.']},queries:[],
};}

test('Briefing retains the latest completed automatic assessment ahead of checks while updating',()=>{
  const scope=harness({agentContext:context(),pipelineStatus:{latest_analysis:{status:'running'}},
    agentSnapshot:{answers:[answer('a','ready','Completed automatic assessment.','2026-09-12T10:00:00Z'),
      answer('b','running',null,'2026-09-12T10:00:05Z'),answer('c','ready','Manual answer.','2026-09-12T10:00:06Z',false)],
    cards:[{statement:'Latest channel check.',claims:[],unknowns:[],lifecycle:'active',assessment:'checking',checked_at:'2026-09-12T10:00:00Z',revision:1}]}});
  vm.runInContext(projection,scope);scope.renderAgent();
  let html=scope.$('agent-content').innerHTML;
  assert.ok(html.indexOf('Completed automatic assessment.')<html.indexOf('Latest channel check.'));
  assert.match(html,/Updating…/);assert.match(html,/Speaker identity remains unverified/);
  assert.equal(scope.$('answer-count').textContent,1);
  scope.agentTab='assistant';scope.renderAgent();html=scope.$('agent-content').innerHTML;
  assert.ok(html.indexOf('Manual answer.')<html.indexOf('Automatic assessment history (2)'));
  scope.agentSnapshot=null;scope.pipelineStatus=null;scope.agentTab='briefing';scope.renderAgent();
  assert.doesNotMatch(scope.$('agent-content').innerHTML,/Completed automatic assessment\./);
  const layout=fs.readFileSync(new URL('../index.html',import.meta.url),'utf8');
  assert.ok(layout.indexOf('id="agent-content"')<layout.indexOf('id="question-form"'));
});

test('pipeline reports source delivery and total assessment lag against the current State clock',()=>{
  const scope=harness({pipelineStatus:{...live(),published:12,imported:10,skipped:2,last_sim_time_ms:139000,
    latest_analysis:{status:'running',as_of_sim_time_ms:138000,latency_ms:1200},analysis_lag_ms:1000,
    analysis_error:'<script>untrusted</script>'}});
  vm.runInContext(pipeline,scope);scope.renderPipeline();
  const html=scope.$('pipeline-status').innerHTML;
  assert.match(html,/Processing 1\.2 s/);
  assert.match(html,/Source lag 2\.3 s \(State clock\)/);
  assert.match(html,/Total assessment lag 3\.3 s \(State clock\)/);
  assert.match(html,/12 published · 10 imported · 2 skipped/);
  assert.doesNotMatch(html,/<script>/);assert.match(html,/&lt;script&gt;/);
  scope.simTime=()=>138000;scope.renderPipeline();
  assert.match(scope.$('pipeline-status').innerHTML,/Source lag 0\.0 s/);
  assert.match(scope.$('pipeline-status').innerHTML,/Total assessment lag 1\.0 s/);
});

test('source and total lag remain unavailable without a current matching live clock and source timestamp',()=>{
  for(const overrides of [
    {pipelineStatus:{...live(),state:'connecting',last_sim_time_ms:139000,analysis_lag_ms:1000}},
    {pipelineStatus:{...live(),last_sim_time_ms:null,analysis_lag_ms:1000}},
    {pipelineStatus:{...live('other'),last_sim_time_ms:139000,analysis_lag_ms:1000}},
    {pipelineStatus:{...live(),last_sim_time_ms:139000,analysis_lag_ms:1000},stateConnected:false},
    {pipelineStatus:{...live(),last_sim_time_ms:139000,analysis_lag_ms:1000},snapshot:null},
  ]){
    const scope=harness(overrides);vm.runInContext(pipeline,scope);scope.renderPipeline();
    assert.doesNotMatch(scope.$('pipeline-status').innerHTML,/Source lag|Total assessment lag/);
  }
  const scope=harness({pipelineStatus:{...live(),last_sim_time_ms:139000,analysis_lag_ms:null}});
  vm.runInContext(pipeline,scope);scope.renderPipeline();
  assert.match(scope.$('pipeline-status').innerHTML,/Source lag 2\.3 s/);
  assert.doesNotMatch(scope.$('pipeline-status').innerHTML,/Total assessment lag/);
});

function sourceEvidence(provenance){return{
  source_label:'Radio source',text:'Copy V-Fire 25.',event_from_ms:1000,event_until_ms:2000,reading_id:90210,
  origin:'recorded',text_kind:'machine_transcript',verification:'unverified',audio:{availability:'missing'},
  raw_reading:{provenance:{state_machine:provenance}},
};}

test('agent radio evidence links only the exact original run, generation, and evidence ID',async()=>{
  const origin={run_id:'current',generation:4,evidence_id:'radio-1'};
  for(const provenance of [origin,{...origin,run_id:'other'},{...origin,generation:3},{...origin,evidence_id:'missing'}]){
    const scope=harness({agentContext:context(),api:async()=>sourceEvidence(provenance),
      observations:[{...origin,kind:'radio_transcript',observed_sim_time_ms:1000}]});
    vm.runInContext(evidence,scope);await scope.openAgentEvidence('agent-source-1');
    const html=scope.$('evidence-body').innerHTML;
    if(provenance===origin){assert.match(html,/Open original radio source/);assert.match(html,/data-observation="radio-1"/);}
    else{assert.doesNotMatch(html,/data-observation=/);assert.match(html,/not loaded for this State run and generation/);}
  }
});

test('a source response arriving after agent context changed cannot replace the current evidence drawer',async()=>{
  let resolveEvidence;
  const scope=harness({agentContext:context(),api:()=>new Promise(resolve=>resolveEvidence=resolve)});
  vm.runInContext(evidence,scope);const pending=scope.openAgentEvidence('old-source');
  scope.agentContext=context('new',5);scope.openDrawer('Current evidence','Current source remains visible.');
  resolveEvidence(sourceEvidence({run_id:'current',generation:4,evidence_id:'old-source'}));await pending;
  assert.equal(scope.$('evidence-body').innerHTML,'Current source remains visible.');
});

test('a delayed Full API card cannot reopen a previous run after context reset',async()=>{
  let resolveCard;
  const scope=harness({agentContext:context(),claimMarkup:()=>'',traceMarkup:()=>'',
    api:()=>new Promise(resolve=>resolveCard=resolve)});
  vm.runInContext(card,scope);const pending=scope.openAgentCard('old-check');
  scope.agentEpoch++;scope.agentContext=context('new',5);
  scope.openDrawer('Current evidence','Current source remains visible.');
  resolveCard({context:context(),statement:'Old check',assessment:'supported',claims:[]});await pending;
  assert.equal(scope.$('evidence-body').innerHTML,'Current source remains visible.');
});

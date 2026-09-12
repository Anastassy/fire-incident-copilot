import test from 'node:test';
import assert from 'node:assert/strict';
import {applyEvent,addObservation,contextEqual,acceptRevision,sse} from '../state.js';

const snapshot=()=>({run:{run_id:'r',generation:2},as_of:{sequence:20,cursor:'r:20'},devices:[],cameras:[],access:[],occupancy:[],rooms:[],radio:{channels:[]}});
const event=(overrides={})=>({run_id:'r',generation:2,sequence:21,cursor:'r:21',kind:'device.updated',data:{device_id:'temperature',readings:[{value:null,availability:'missing'}]},...overrides});
test('old generations and other runs cannot change the current picture',()=>{
  const s=snapshot();assert.equal(applyEvent(s,event({generation:1})),false);assert.equal(applyEvent(s,event({run_id:'other'})),false);assert.deepEqual(s,snapshot());
});
test('sequence holes require snapshot recovery; duplicates are harmless',()=>{
  const s=snapshot();assert.throws(()=>applyEvent(s,event({sequence:22})),/SEQUENCE_GAP/);assert.deepEqual(s,snapshot());
  assert.equal(applyEvent(s,event()),true);assert.equal(applyEvent(s,event()),false);assert.equal(s.devices.length,1);
});
test('missing readings remain null; a measured zero remains available as zero',()=>{
  const s=snapshot();applyEvent(s,event());assert.equal(s.devices[0].readings[0].value,null);
  applyEvent(s,event({sequence:22,data:{device_id:'temperature',readings:[{value:0,availability:'fresh'}]}}));assert.equal(s.devices[0].readings[0].value,0);assert.equal(s.devices[0].readings[0].availability,'fresh');
});
test('SSE/history overlap deduplicates evidence without merging generations',()=>{
  const list=[];addObservation(list,{evidence_id:'a',generation:1});addObservation(list,{evidence_id:'a',generation:1});addObservation(list,{evidence_id:'a',generation:2});assert.equal(list.length,2);
});
test('agent responses are scoped to all three context dimensions and revisions',()=>{
  const c={demo_context_id:'demo',generation:2,subject_id:'radio'};
  for(const changed of [{demo_context_id:'other'},{generation:1},{subject_id:'all'}])assert.equal(contextEqual(c,{...c,...changed}),false);
  const old={request_id:'q',context:c,revision:4};assert.equal(acceptRevision(old,{...old,revision:3},c),false);assert.equal(acceptRevision(old,{...old,revision:5},c),true);
});
test('SSE parses UTF-8 and CRLF split at every byte boundary',async()=>{
  const text=': heartbeat\r\n\r\nid: r:21\r\nevent: event\r\ndata: {"text":"Дым",\r\ndata: "value":null}\r\n\r\n';
  const bytes=new TextEncoder().encode(text),original=globalThis.fetch,received=[];
  globalThis.fetch=async()=>new Response(new ReadableStream({start(c){for(const byte of bytes)c.enqueue(new Uint8Array([byte]));c.close();}}));
  try{await assert.rejects(sse('/fake',{onMessage:m=>received.push(m)}),/STREAM_CLOSED/);assert.deepEqual(received,[{type:'event',id:'r:21',data:{text:'Дым',value:null}}]);}finally{globalThis.fetch=original;}
});

const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const context={setTimeout,clearTimeout,setInterval,clearInterval,Date,window:{}};vm.createContext(context);
for(const f of ['fixtures.js','mock-adapters.js'])vm.runInContext(fs.readFileSync(__dirname+'/'+f,'utf8'),context);
const create=()=>context.window.createPalisadesAdapters(context.window.PalisadesFixtures,{lag:5});
const sleep=()=>new Promise(r=>setTimeout(r,12));
(async()=>{
 const p=create();let check;p.agent.subscribe(c=>check=c);await sleep();assert.equal(check.stage,'request');assert(!p.data.snapshot().records.some(r=>r.start>=133.26));
 p.replay.advance(5.35);await sleep();assert.equal(check.stage,'answered');assert(!check.exchange.some(x=>x.role==='reply'));assert(!p.data.snapshot().records.some(r=>r.start===138.7));
 p.replay.advance(5);await sleep();assert.equal(check.stage,'acknowledged');assert.equal(Array.from(check.exchange,x=>x.role).join(','),'request,assignment,reply');check.exchange.forEach(x=>assert(p.data.getRecord(x.evidenceId).end<=check.asOf));
 const future=context.window.PalisadesFixtures.find(r=>r.start>142);assert.throws(()=>p.data.getRecord(future.id));
 p.replay.reset({omitReply:true});p.replay.advance(12);await sleep();assert.equal(check.stage,'answered');assert(!check.exchange.some(x=>x.role==='reply'));assert(!p.data.snapshot().records.some(r=>r.start===138.7));
 const reply=await p.agent.ask('Did everyone switch?');assert.match(reply.text,/Not established/);
 const pending=p.agent.ask('Was it acknowledged?');p.replay.reset();await assert.rejects(pending,/CONTEXT_CHANGED/);
 p.agent.simulateError();await sleep();assert.equal(check.status,'error');assert(p.data.snapshot().records.length>0);
 p.agent.retry();await sleep();assert.equal(check.status,'ready');
 p.replay.play();p.replay.pause();const t=p.data.snapshot().time;await sleep();assert.equal(p.data.snapshot().time,t);
 p.replay.dispose();console.log('PASS: publication boundary, progression, missing reply, future evidence, reset race, error/retry, pause');
})().catch(e=>{console.error(e);process.exitCode=1});

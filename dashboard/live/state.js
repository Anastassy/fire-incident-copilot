export const esc = (value) => String(value ?? '').replace(/[&<>"']/g, x => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
export const timecode = (ms = 0) => `${String(Math.floor(Math.max(0,ms)/60000)).padStart(2,'0')}:${String(Math.floor(Math.max(0,ms)/1000)%60).padStart(2,'0')}`;
export const statusLabel = (s) => ({fresh:'В сети',stale:'Устарело',missing:'Нет данных',disconnected:'Нет связи',invalid:'Ошибка',paused:'Пауза',playing:'Воспроизведение',completed:'Завершён',queued:'В очереди',running:'Проверяет',ready:'Ответ готов',insufficient_data:'Недостаточно данных',error:'Ошибка',cancelled:'Отменён',checking:'Проверяется',supported:'Есть подтверждающий доклад',refuted:'Опровергнуто',pending:'Ожидает публикации',synced:'Опубликовано',uncertain:'Результат публикации неизвестен',active:'Активна',closed:'Закрыта'}[s] || s || 'Неизвестно');
export const kindLabel = (s) => ({measurement:'Датчик',camera:'Камера',radio_audio:'Радио',radio_transcript:'Транскрипция',connectivity:'Связь',access:'СКУД',people_count:'Люди',transport:'Транспорт'}[s] || s);
export function upsert(items, value, key) { const i=items.findIndex(x=>x[key]===value[key]); if(i<0) items.push(value);else items[i]=value; }
export function applyEvent(snapshot,event) {
  if (!snapshot || event.run_id !== snapshot.run.run_id || event.generation !== snapshot.run.generation) return false;
  if(event.sequence <= snapshot.as_of.sequence) return false;
  if(event.sequence !== snapshot.as_of.sequence+1) throw new Error('SEQUENCE_GAP');
  const targets={'device.updated':['devices','device_id'],'camera.updated':['cameras','camera_id'],'room.updated':['rooms','room_id'],'access.updated':['access','scope_id'],'occupancy.updated':['occupancy','scope_id']};
  if(event.kind==='run.updated')snapshot.run=event.data;
  else if(event.kind==='system.updated')snapshot.system=event.data;
  else if(event.kind==='radio.channel.updated')upsert(snapshot.radio.channels,event.data,'channel_id');
  else if(targets[event.kind]) {const [list,key]=targets[event.kind];upsert(snapshot[list],event.data,key);}
  snapshot.as_of={sequence:event.sequence,cursor:event.cursor};return true;
}
export function addObservation(list,item) {if(!list.some(x=>x.evidence_id===item.evidence_id&&x.generation===item.generation))list.push(item);return list;}
export function contextEqual(a,b) {return !!a&&!!b&&a.demo_context_id===b.demo_context_id&&a.generation===b.generation&&a.subject_id===b.subject_id;}
export function acceptRevision(previous,next,context,key='request_id') {return contextEqual(next.context,context)&&(!previous||next[key]!==previous[key]||next.revision>=previous.revision);}
export async function api(path,body,options={}) {
 const response=await fetch(path,{...options,method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json',...(options.headers||{})},body:body===undefined?undefined:JSON.stringify(body)});
 let result;try{result=await response.json();}catch{result={error:`HTTP ${response.status}`};}
 if(!response.ok) {const error=new Error(result.error?.message||result.message||result.error||`HTTP ${response.status}`);error.status=response.status;error.body=result;throw error;}return result;
}
export async function sse(path,{signal,onMessage,onOpen,lastEventId}) {
 const response=await fetch(path,{signal,headers:{Accept:'text/event-stream',...(lastEventId?{'Last-Event-ID':lastEventId}:{})}});
 if(!response.ok) {const error=new Error(`SSE ${response.status}`);error.status=response.status;throw error;}
 onOpen?.();const reader=response.body.getReader(), decoder=new TextDecoder();let buffer='';
 try {while(true){const {value,done}=await reader.read();if(done)throw new Error('STREAM_CLOSED');buffer+=decoder.decode(value,{stream:true});let match;
 while((match=/\r?\n\r?\n/.exec(buffer))){const block=buffer.slice(0,match.index);buffer=buffer.slice(match.index+match[0].length);let type='message',id=null;const data=[];for(const line of block.split(/\r?\n/)){if(line.startsWith('event:'))type=line.slice(6).trim();if(line.startsWith('id:'))id=line.slice(3).trim();if(line.startsWith('data:'))data.push(line.slice(5).trimStart());}if(data.length)onMessage({type,id,data:JSON.parse(data.join('\n'))});}
 }}finally{reader.cancel().catch(()=>{});reader.releaseLock();}
}

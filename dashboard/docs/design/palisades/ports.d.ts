/** UI normalization seam; does not replace project API contracts. */
export interface RadioRecord { id:string; start:number; end:number; text:string; source:string; machineGenerated:boolean; humanVerified:boolean }
export interface Snapshot { runId:string; generation:number; time:number; startTime:number; endTime:number; playing:boolean; ended:boolean; omitReply:boolean; mode:string; records:RadioRecord[] }
export interface Check { status:'checking'|'ready'|'error'; stage?:'request'|'answered'|'acknowledged'; channel?:string|null; evidenceIds:string[]; generation:number; asOf:number; revision?:number; queries?:unknown[]; origin?:string }
export interface Answer { generation:number; asOf:number; text:string; evidenceIds:string[]; origin:string }
type Unsubscribe=()=>void;
export interface PalisadesAdapters {
 data:{snapshot():Snapshot; subscribe(fn:(s:Snapshot)=>void):Unsubscribe; getRecord(id:string):RadioRecord; history(query?:string):RadioRecord[]};
 replay:{play():void; pause():void; reset(options?:{omitReply?:boolean}):void; dispose():void};
 agent:{subscribe(fn:(c:Check)=>void):Unsubscribe; ask(question:string):Promise<Answer>; simulateError():void; retry():void};
 media:{resolve(id:string):Promise<{url:string;start:number;end:number;record:RadioRecord;generation:number}>};
 capabilities:{mode:string;replay:boolean};
}

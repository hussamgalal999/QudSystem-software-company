import{DurableObject}from"cloudflare:workers";
import type{Env}from"./workflow";
type ReserveRequest={key:string;taskId:string;day:string;limit:number};
export class TaskAdmission extends DurableObject<Env>{
 constructor(ctx:DurableObjectState,env:Env){super(ctx,env);this.ctx.storage.sql.exec("CREATE TABLE IF NOT EXISTS daily_usage(day TEXT PRIMARY KEY,count INTEGER NOT NULL)");this.ctx.storage.sql.exec("CREATE TABLE IF NOT EXISTS admitted(key TEXT PRIMARY KEY,task_id TEXT NOT NULL,day TEXT NOT NULL)");}
 async fetch(request:Request):Promise<Response>{
  if(request.method!=="POST")return Response.json({error:"method_not_allowed"},{status:405});
  let input:ReserveRequest;try{input=await request.json()as ReserveRequest;}catch{return Response.json({error:"invalid_json"},{status:400});}
  if(!input.key||!input.taskId||!/^\d{4}-\d{2}-\d{2}$/.test(input.day)||!Number.isInteger(input.limit)||input.limit<1||input.limit>100)return Response.json({error:"invalid_reservation"},{status:400});
  const prior=this.ctx.storage.sql.exec("SELECT task_id FROM admitted WHERE key=?",input.key).toArray()[0]as{task_id:string}|undefined;
  if(prior)return Response.json({allowed:true,existing:true,taskId:prior.task_id});
  const row=this.ctx.storage.sql.exec("SELECT count FROM daily_usage WHERE day=?",input.day).toArray()[0]as{count:number}|undefined;
  const count=Number(row?.count||0);if(count>=input.limit)return Response.json({allowed:false,reason:"daily_task_limit",limit:input.limit,count});
  this.ctx.storage.sql.exec("INSERT INTO daily_usage(day,count) VALUES(?,1) ON CONFLICT(day) DO UPDATE SET count=count+1",input.day);
  this.ctx.storage.sql.exec("INSERT INTO admitted(key,task_id,day) VALUES(?,?,?)",input.key,input.taskId,input.day);
  this.ctx.storage.sql.exec("DELETE FROM admitted WHERE day < date(?, '-7 days')",input.day);
  this.ctx.storage.sql.exec("DELETE FROM daily_usage WHERE day < date(?, '-7 days')",input.day);
  return Response.json({allowed:true,existing:false,taskId:input.taskId,count:count+1,limit:input.limit});
 }
}
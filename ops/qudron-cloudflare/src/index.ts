import type{Env,TaskPayload}from"./workflow";
import{validateIntake,normalizeIdempotencyKey,isAuthorizedTelegramOwner}from"./policy";
export{QudronTaskWorkflow}from"./workflow";
export{TaskAdmission}from"./admission";
const HEADERS={"content-type":"application/json; charset=utf-8","cache-control":"no-store"};
function json(data:unknown,status=200){return new Response(JSON.stringify(data),{status,headers:HEADERS});}
function bearer(request:Request,token:string){
 const h=request.headers.get("authorization")||"",s=h.startsWith("Bearer ")?h.slice(7):"";
 if(!token||s.length!==token.length)return false;let d=0;for(let i=0;i<token.length;i++)d|=token.charCodeAt(i)^s.charCodeAt(i);return d===0;
}
function owners(env:Env){return new Set((env.TELEGRAM_OWNER_CHAT_IDS||"").split(",").map(x=>x.trim()).filter(Boolean));}
async function stableId(prefix:string,key:string){
 const bytes=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(key));
 const hex=Array.from(new Uint8Array(bytes)).map(x=>x.toString(16).padStart(2,"0")).join("");
 return prefix+"-"+hex.slice(0,48);
}
async function createTask(env:Env,kind:"research"|"draft",title:string,prompt:string,id:string,key:string){
 const day=new Date().toISOString().slice(0,10),limit=Math.min(30,Math.max(1,Number(env.QUDRON_MAX_DAILY_TASKS||"5")));
 const gate=env.TASK_ADMISSION.get(env.TASK_ADMISSION.idFromName("global"));
 const reservation=await gate.fetch("https://admission/reserve",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({key,taskId:id,day,limit})});
 const admission=await reservation.json()as{allowed:boolean;existing?:boolean};
 if(!admission.allowed)return{limited:true as const};
 const payload:TaskPayload={taskId:id,kind,title,prompt,createdAt:new Date().toISOString()};
 try{return{instance:await env.QUDRON_WORKFLOW.create({id,params:payload}),created:true,limited:false as const};}
 catch{return{instance:await env.QUDRON_WORKFLOW.get(id),created:false,limited:false as const};}
}
async function handleTelegram(request:Request,env:Env){
 if(!env.TELEGRAM_BOT_TOKEN||!env.TELEGRAM_WEBHOOK_SECRET||request.headers.get("x-telegram-bot-api-secret-token")!==env.TELEGRAM_WEBHOOK_SECRET)return json({error:"unauthorized"},401);
 const update=await request.json()as Record<string,any>,message=update.message,chatId=String(message?.chat?.id??"");
 if(!isAuthorizedTelegramOwner(message,owners(env)))return json({ok:true,ignored:true});
 const text=typeof message?.text==="string"?message.text.trim():"",parts=text.split(/\s+/),command=(parts.shift()||"").split("@")[0].toLowerCase(),argument=parts.join(" ");
 let reply="Unknown command. Send /help.";
 if(command==="/start"||command==="/help")reply="Qudron Cloud pilot\n/status <task-id> — task status\n/task <request> — internal research task\nOnly synthetic/public information is allowed. External publishing and customer messaging are disabled.";
 else if(command==="/task"||command==="/research"||command==="/draft"){
  const kind=command==="/draft"?"draft":"research",title=kind==="draft"?"Telegram owner draft task":"Telegram owner research task";
  const checked=validateIntake({kind,title,prompt:argument});
  if(!checked.ok)reply=checked.error;
  else{const n=Number(update.update_id);if(!Number.isSafeInteger(n)||n<1)reply="Invalid Telegram update ID; task was not submitted.";
   else{const id=await stableId("tg",String(n)),created=await createTask(env,kind,title,checked.task.prompt,id,"telegram:"+n);
    if(created.limited)reply="Daily internal task allowance reached. The limit resets at 00:00 UTC.";
    else reply="Task "+(created.created?"accepted":"already received")+".\nID: "+created.instance.id+"\nYou will receive the reviewed result here when complete.";}}
 }else if(command==="/status"){
  if(!argument||argument.length>100||!/^[A-Za-z0-9._:-]+$/.test(argument))reply="Usage: /status <task-id>";
  else{try{const instance=await env.QUDRON_WORKFLOW.get(argument),s=await instance.status();reply="Task "+argument+"\nStatus: "+s.status+(s.output?"\nResult available in authenticated API.":"");}catch{reply="Task not found.";}}
 }
 await fetch("https://api.telegram.org/bot"+env.TELEGRAM_BOT_TOKEN+"/sendMessage",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({chat_id:chatId,text:reply.slice(0,3900),disable_web_page_preview:true})});
 return json({ok:true});
}
export default{async fetch(request:Request,env:Env):Promise<Response>{
 const url=new URL(request.url);
 if(request.method==="GET"&&url.pathname==="/health")return json({service:"Qudron Cloudflare Control Plane",status:"healthy",timestamp:new Date().toISOString()});
 if(request.method==="POST"&&url.pathname==="/telegram/webhook"){try{return await handleTelegram(request,env);}catch{return json({error:"telegram_handler_failed"},500);}}
 if(!bearer(request,env.QUDRON_API_TOKEN))return json({error:"unauthorized"},401);
 if(request.method==="POST"&&url.pathname==="/api/tasks"){
  let input:unknown;try{input=await request.json();}catch{return json({error:"invalid_json"},400);}
  const checked=validateIntake(input);if(!checked.ok)return json({error:checked.error},400);
  const key=normalizeIdempotencyKey(request.headers.get("idempotency-key"))||crypto.randomUUID(),id=await stableId("api",key);
  const created=await createTask(env,checked.task.kind,checked.task.title,checked.task.prompt,id,"api:"+key);
  if(created.limited)return json({error:"daily_task_limit_reached",reset:"00:00 UTC"},429);
  return json({taskId:created.instance.id,created:created.created,status:(await created.instance.status()).status},created.created?202:200);
 }
 const match=url.pathname.match(/^\/api\/tasks\/([A-Za-z0-9._:-]{1,100})$/);
 if(request.method==="GET"&&match){try{const instance=await env.QUDRON_WORKFLOW.get(match[1]),s=await instance.status();return json({taskId:match[1],...s});}catch{return json({error:"task_not_found"},404);}}
 return json({error:"not_found"},404);
}};

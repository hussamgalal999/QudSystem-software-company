import{WorkflowEntrypoint,type WorkflowEvent,type WorkflowStep}from"cloudflare:workers";
import type{TaskKind}from"./policy";
export type TaskPayload={taskId:string;kind:TaskKind;title:string;prompt:string;createdAt:string};
type ModelResponse={response?:string;[key:string]:unknown};
export class QudronTaskWorkflow extends WorkflowEntrypoint<Env,TaskPayload>{
 async run(event:WorkflowEvent<TaskPayload>,step:WorkflowStep){
  const task=event.payload;
  const generated=await step.do("produce-initial-result",{retries:{limit:2,delay:"5 seconds",backoff:"exponential"},timeout:"2 minutes"},async()=>{
   const system=task.kind==="research"?"You are Qudron Research. Produce a concise, evidence-conscious research brief. Label assumptions and unknowns. Do not invent sources or claim browsing without sources.":"You are Qudron Content Studio. Produce a useful first draft. Do not invent testimonials, metrics, prices or factual claims.";
   const result=await this.env.AI.run(this.env.QUDRON_AI_MODEL||"@cf/meta/llama-3.3-70b-instruct-fp8-fast",{messages:[{role:"system",content:system},{role:"user",content:"Title: "+task.title+"\n\nRequest:\n"+task.prompt}],max_tokens:Number(this.env.QUDRON_MAX_OUTPUT_TOKENS||"1200")})as ModelResponse;
   if(!result||typeof result.response!=="string"||result.response.trim().length<10)throw new Error("Model returned an empty or invalid response.");
   return{text:result.response.slice(0,16000)};
  });
  const reviewed=await step.do("independent-quality-review",{retries:{limit:1,delay:"5 seconds",backoff:"linear"},timeout:"2 minutes"},async()=>{
   const result=await this.env.AI.run(this.env.QUDRON_AI_MODEL||"@cf/meta/llama-3.3-70b-instruct-fp8-fast",{messages:[{role:"system",content:"You are Qudron QA. Review for unsupported claims, missing caveats, relevance, clarity and safety. Return corrected final text. Do not fabricate facts or citations."},{role:"user",content:"Original request:\n"+task.prompt+"\n\nDraft:\n"+generated.text}],max_tokens:Number(this.env.QUDRON_MAX_OUTPUT_TOKENS||"1200")})as ModelResponse;
   if(!result||typeof result.response!=="string"||result.response.trim().length<10)throw new Error("Reviewer returned an empty or invalid response.");
   return{text:result.response.slice(0,16000)};
  });
  const notification=await step.do("notify-owner",async()=>{
   const token=this.env.TELEGRAM_BOT_TOKEN||"",chatIds=(this.env.TELEGRAM_OWNER_CHAT_IDS||"").split(",").map(x=>x.trim()).filter(Boolean);
   if(!token||chatIds.length===0)return{sent:false,reason:"telegram_not_configured"};
   const text="Qudron task completed\\n"+task.title+"\\nID: "+task.taskId+"\\n\\n"+reviewed.text.slice(0,3000);
   const outcomes=[];
   for(const chatId of chatIds){
    try{const response=await fetch("https://api.telegram.org/bot"+token+"/sendMessage",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({chat_id:chatId,text,disable_web_page_preview:true})});const body=await response.json() as {ok?:boolean};outcomes.push({chatId,ok:response.ok&&body.ok===true});}
    catch{outcomes.push({chatId,ok:false});}
   }
   return{sent:outcomes.some(x=>x.ok),outcomes};
  });
  return{taskId:task.taskId,title:task.title,kind:task.kind,status:"completed",createdAt:task.createdAt,completedAt:new Date().toISOString(),result:reviewed.text,notification,review:"A separate QA inference reviewed the first draft. Human approval is still required before external publication or customer delivery.",model:this.env.QUDRON_AI_MODEL||"@cf/meta/llama-3.3-70b-instruct-fp8-fast"};
 }
}
export interface Env{AI:Ai;QUDRON_WORKFLOW:Workflow<TaskPayload>;TASK_ADMISSION:DurableObjectNamespace;QUDRON_API_TOKEN:string;TELEGRAM_BOT_TOKEN?:string;TELEGRAM_WEBHOOK_SECRET?:string;TELEGRAM_OWNER_CHAT_IDS?:string;QUDRON_AI_MODEL?:string;QUDRON_MAX_OUTPUT_TOKENS?:string;QUDRON_MAX_DAILY_TASKS?:string}
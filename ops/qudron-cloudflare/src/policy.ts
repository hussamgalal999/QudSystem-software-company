export type TaskKind="research"|"draft";
export type IntakeResult={ok:true;task:{kind:TaskKind;prompt:string;title:string}}|{ok:false;error:string};
const SENSITIVE_PATTERNS=[/\b\d{14}\b/,/\b(?:\+?20|0)1[0125]\d{8}\b/,/\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/i,/\b(?:password|api[_ -]?key|secret|otp|pin|wallet|bank account)\b/i,/\b(?:passport|national id|credit card|debit card)\b/i];
export function validateIntake(input:unknown):IntakeResult{
 if(!input||typeof input!=="object"||Array.isArray(input))return{ok:false,error:"Expected a JSON object."};
 const v=input as Record<string,unknown>,kind=v.kind,prompt=v.prompt,title=v.title;
 if(kind!=="research"&&kind!=="draft")return{ok:false,error:"Only research and draft tasks are enabled in this pilot."};
 if(typeof prompt!=="string"||prompt.trim().length<8||prompt.length>4000)return{ok:false,error:"Prompt must contain 8–4000 characters."};
 if(typeof title!=="string"||title.trim().length<3||title.length>120)return{ok:false,error:"Title must contain 3–120 characters."};
 if(SENSITIVE_PATTERNS.some(p=>p.test(prompt)))return{ok:false,error:"This pilot rejects likely personal data, credentials and financial secrets. Use synthetic/public information only."};
 return{ok:true,task:{kind,prompt:prompt.trim(),title:title.trim()}};
}
export function normalizeIdempotencyKey(value:string|null):string|null{
 if(!value||value.length>180||!/^[A-Za-z0-9._:-]+$/.test(value))return null;return value;
}
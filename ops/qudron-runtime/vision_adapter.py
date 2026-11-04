"""Allowlisted local-image analysis through an OpenAI-compatible vision endpoint."""
from __future__ import annotations
import base64,json,mimetypes,os,urllib.request,uuid
from pathlib import Path
import qudron_worker as worker
ALLOWED_MIME={"image/jpeg","image/png","image/webp","image/gif"}
MAX_IMAGE_BYTES=max(1024,min(12*1024*1024,int(os.getenv("QUDRON_VISION_MAX_IMAGE_BYTES",str(8*1024*1024)))))
class VisionError(RuntimeError):pass
def _safe_image(path):
 root=Path(os.getenv("QUDRON_IMAGE_ROOT","/app/inbox/images")).resolve()
 candidate=Path(path).resolve()
 try:candidate.relative_to(root)
 except ValueError:raise VisionError("Image path is outside the configured QUDRON_IMAGE_ROOT") from None
 if not candidate.is_file():raise VisionError("Image file does not exist")
 size=candidate.stat().st_size
 if size<=0 or size>MAX_IMAGE_BYTES:raise VisionError("Image size is empty or exceeds QUDRON_VISION_MAX_IMAGE_BYTES")
 mime=mimetypes.guess_type(candidate.name)[0] or ""
 if mime not in ALLOWED_MIME:raise VisionError("Only JPEG, PNG, WebP and GIF images are supported")
 return candidate.read_bytes(),mime
def analyze_image(path,question,job_id=None,profile="balanced"):
 question=str(question).strip()
 if len(question)<3 or len(question)>4000:raise ValueError("Question must contain 3–4000 characters")
 prefix={"fast":"LLM_FAST","balanced":"LLM_BALANCED","reasoning":"LLM_REASONING"}.get(profile)
 if not prefix:raise ValueError("Unknown model profile")
 base=(os.getenv(f"{prefix}_BASE_URL") or worker.LLM_BASE_URL).rstrip("/")
 key=os.getenv(f"{prefix}_API_KEY") or worker.LLM_API_KEY
 model=os.getenv(f"{prefix}_MODEL") or worker.LLM_MODEL
 if not base or not model:raise VisionError("Configured vision-capable OpenAI-compatible model endpoint is required")
 image,mime=_safe_image(path)
 data_url="data:"+mime+";base64,"+base64.b64encode(image).decode("ascii")
 jid=job_id or "image-"+uuid.uuid4().hex
 reservation=None;slot=None
 try:
  reservation=worker.reserve_model_budget(jid,"image_analyst",profile,model,len(image)+len(question.encode()),"image_analysis")
  slot=worker.acquire_model_call_slot(jid,"image_analyst")
  headers={"Content-Type":"application/json"}
  if key:headers["Authorization"]="Bearer "+key
  body={"model":model,"max_tokens":worker.MAX_OUTPUT_TOKENS,"messages":[
   {"role":"system","content":"You are Qudron Vision Analyst. Describe only visible evidence. If the image contains code, extract it faithfully and mark unreadable areas; if it is a UI/design, describe layout, components, typography, colors and implementation clues. Never infer identity or sensitive traits."},
   {"role":"user","content":[{"type":"text","text":question},{"type":"image_url","image_url":{"url":data_url}}]}]}
  req=urllib.request.Request(base+"/chat/completions",data=json.dumps(body).encode(),headers=headers,method="POST")
  with urllib.request.urlopen(req,timeout=worker.LLM_TIMEOUT) as response:result=json.loads(response.read().decode())
  worker.record_model_usage(jid,"image_analyst",profile,model,result,reservation);reservation=None
  choices=result.get("choices") or []
  content=choices[0].get("message",{}).get("content") if choices else None
  if isinstance(content,list):content="\n".join(str(x.get("text","")) for x in content if isinstance(x,dict))
  if not isinstance(content,str) or not content.strip():raise VisionError("Vision model returned no readable text")
  return content.strip()
 finally:
  worker.release_model_call_slot(slot)
  worker.release_model_budget_reservation(reservation)

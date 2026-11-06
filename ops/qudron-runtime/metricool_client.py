"""Official Metricool API adapter. Reads analytics and schedules drafts only by default."""
from __future__ import annotations
import csv, io, json, os, urllib.parse, urllib.error
from urllib.request import Request
from typing import Any
from endpoint_security import is_allowed_credential_endpoint, open_credential_request

BASE="https://app.metricool.com/api"
NETWORKS={"facebook","instagram","linkedin","youtube","tiktok","pinterest","twitter","threads","bluesky"}

class MetricoolError(RuntimeError): pass

class MetricoolClient:
 def __init__(self,token:str|None=None,user_id:str|None=None,blog_id:str|None=None,base_url:str=BASE):
  self.token=(token if token is not None else os.getenv("METRICOOL_API_TOKEN","")).strip()
  self.user_id=str(user_id if user_id is not None else os.getenv("METRICOOL_USER_ID","")).strip()
  self.blog_id=str(blog_id if blog_id is not None else os.getenv("METRICOOL_BLOG_ID","")).strip()
  self.base_url=base_url.rstrip("/")
  if not is_allowed_credential_endpoint(self.base_url):raise MetricoolError("Metricool API endpoint must use HTTPS or exact loopback HTTP")
  if not self.token or not self.user_id or not self.blog_id:
   raise MetricoolError("METRICOOL_API_TOKEN, METRICOOL_USER_ID and METRICOOL_BLOG_ID are required")
 def request(self,method:str,path:str,params:dict[str,Any]|None=None,payload:dict[str,Any]|None=None)->Any:
  query={"userId":self.user_id,"blogId":self.blog_id}
  query.update({k:v for k,v in (params or {}).items() if v is not None})
  url=self.base_url+path+"?"+urllib.parse.urlencode(query,doseq=True)
  body=json.dumps(payload).encode() if payload is not None else None
  headers={"X-Mc-Auth":self.token,"Accept":"application/json"}
  if body is not None:headers["Content-Type"]="application/json"
  req=Request(url,data=body,headers=headers,method=method.upper())
  try:
   with open_credential_request(req,timeout=30,endpoint_validated=True) as response:
    raw=response.read()
    if not raw:return {}
    content_type=response.headers.get("Content-Type","")
    if "json" in content_type.lower():
     return json.loads(raw.decode())
    text=raw.decode("utf-8",errors="replace")
    if "csv" in content_type.lower():
     return list(csv.DictReader(io.StringIO(text)))
    return text
  except urllib.error.HTTPError as exc:
   if exc.code in (401,403):raise MetricoolError("Metricool authentication or plan permission failed") from None
   if exc.code==429:raise MetricoolError("Metricool rate limit reached") from None
   raise MetricoolError(f"Metricool API returned HTTP {exc.code}") from None
  except (urllib.error.URLError,TimeoutError):
   raise MetricoolError("Metricool API request failed") from None
 def list_scheduled_posts(self,start:str,end:str,timezone:str="Africa/Cairo")->Any:
  if not start or not end or start>=end:raise ValueError("A valid start/end date range is required")
  return self.request("GET","/v2/scheduler/posts",{"start":start,"end":end,"timezone":timezone})
 def list_published_posts(self,network:str,start:str,end:str,timezone:str="Africa/Cairo")->Any:
  if network not in {"facebook","instagram","youtube"}:raise ValueError("Published-post analytics supports facebook, instagram and youtube")
  if not start or not end or start>=end:raise ValueError("A valid start/end date range is required")
  return self.request("GET",f"/v2/analytics/posts/{network}",{"from":start,"to":end,"timezone":timezone})
 def create_review_draft(
  self,
  text:str,
  publication_date:str,
  network:str="facebook",
  timezone:str="Africa/Cairo",
  *,
  content_brand:str|None=None,
  destination_id:str|None=None,
 )->Any:
  if network not in NETWORKS:raise ValueError("Unsupported Metricool network")
  if not text.strip():raise ValueError("Post text is required")
  if not publication_date:raise ValueError("Publication date is required")
  validate_brand_destination(
   text=text,
   content_brand=content_brand,
   brand_id=self.blog_id,
   destination_id=destination_id,
   network=network,
   approved_brand_destinations=_load_owner_approved_brand_destinations(),
  )
  payload={"publicationDate":{"dateTime":publication_date,"timezone":timezone},"text":text,"providers":[{"network":network}],"draft":True,"autoPublish":False}
  return self.request("POST","/v2/scheduler/posts",payload=payload)

def summarize_posts(posts:Any)->dict[str,Any]:
 rows=posts.get("data",posts) if isinstance(posts,dict) else posts
 if not isinstance(rows,list):raise MetricoolError("Unexpected Metricool analytics response")
 totals={"posts":len(rows),"reach":0,"impressions":0,"likes":0,"comments":0,"shares":0,"engagement":0}
 normalized=[]
 for item in rows:
  if not isinstance(item,dict):continue
  metrics=item.get("metrics") if isinstance(item.get("metrics"),dict) else item
  normalized_metrics={str(k).lower():v for k,v in metrics.items()}
  row={}
  for key in ("reach","impressions","likes","comments","shares","engagement"):
   value=normalized_metrics.get(key)
   try:value=float(str(value).replace(",","")) if value not in (None,"") else None
   except (TypeError,ValueError):value=None
   row[key]=value
   if value is not None:totals[key]+=value
  normalized.append({"text":str(item.get("text") or item.get("content") or "")[:240],"url":item.get("url") or item.get("link"),"publicationDate":item.get("publicationDate") or item.get("created"),"metrics":row})
 return {"totals":totals,"posts":normalized}


# Brand isolation is deliberately fail-closed. A brand label alone is not proof
# that Metricool's blog and destination IDs belong together.
_VISION_GUARD_MARKERS = (
 "vision guard",
 "your security our priority",
 "أمانك مسؤوليتنا",
 "كاميرات مراقبة",
 "تركيب كاميرات",
 "أنظمة كاميرات",
 "أنظمة المراقبة",
 "camera installation",
 "security camera",
 "cctv",
)

def _load_owner_approved_brand_destinations()->dict[str,dict[str,str]]:
 raw=os.getenv("QUDRON_METRICOOL_APPROVED_BRAND_DESTINATIONS","").strip()
 if not raw:return {}
 try:
  value=json.loads(raw)
 except json.JSONDecodeError as exc:
  raise MetricoolError("Owner Metricool brand/destination mapping is invalid JSON") from exc
 if not isinstance(value,dict):
  raise MetricoolError("Owner Metricool brand/destination mapping must be a JSON object")
 return value

def validate_brand_destination(
 *,
 text:str,
 content_brand:str|None,
 brand_id:str|None,
 destination_id:str|None,
 network:str,
 approved_brand_destinations:dict[str,dict[str,str]]|None,
)->None:
 """Require an explicit brand -> Metricool blog -> destination allowlist.

 Vision Guard signals in copy cannot be overridden by misclassifying that
 content as QudSystem. Unknown or missing mappings block even draft creation.
 """
 label=" ".join(str(content_brand or "").casefold().replace("_"," ").split())
 if not label:
  raise MetricoolError("Content brand is required before creating a Metricool draft")
 normalized_text=" ".join(str(text or "").casefold().split())
 if label not in {"vision guard","vision guard systems"} and any(
  marker in normalized_text for marker in _VISION_GUARD_MARKERS
 ):
  raise MetricoolError("Vision Guard content cannot be classified or routed as another brand")
 bindings=approved_brand_destinations if isinstance(approved_brand_destinations,dict) else {}
 binding=bindings.get(label)
 if not isinstance(binding,dict):
  raise MetricoolError("No owner-approved Metricool brand/destination mapping exists")
 expected_blog=str(binding.get("brand_id") or "").strip()
 expected_destination=str(binding.get("destination_id") or "").strip()
 expected_network=str(binding.get("network") or "").strip().lower()
 if not expected_blog or not expected_destination or not expected_network:
  raise MetricoolError("Approved Metricool mapping must include brand_id, destination_id and network")
 if not str(brand_id or "").strip() or not str(destination_id or "").strip():
  raise MetricoolError("Metricool brand and destination IDs are required")
 if (
  str(brand_id).strip()!=expected_blog
  or str(destination_id).strip()!=expected_destination
  or str(network or "").strip().lower()!=expected_network
 ):
  raise MetricoolError("Metricool brand/destination/network does not match the approved content-brand mapping")

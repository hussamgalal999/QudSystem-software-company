"""Official Metricool API adapter. Reads analytics and schedules drafts only by default."""
from __future__ import annotations
import csv, io, json, os, urllib.parse, urllib.request, urllib.error
from typing import Any

BASE="https://app.metricool.com/api"
NETWORKS={"facebook","instagram","linkedin","youtube","tiktok","pinterest","twitter","threads","bluesky"}

class MetricoolError(RuntimeError): pass

class MetricoolClient:
 def __init__(self,token:str|None=None,user_id:str|None=None,blog_id:str|None=None,base_url:str=BASE):
  self.token=(token if token is not None else os.getenv("METRICOOL_API_TOKEN","")).strip()
  self.user_id=str(user_id if user_id is not None else os.getenv("METRICOOL_USER_ID","")).strip()
  self.blog_id=str(blog_id if blog_id is not None else os.getenv("METRICOOL_BLOG_ID","")).strip()
  self.base_url=base_url.rstrip("/")
  if not self.token or not self.user_id or not self.blog_id:
   raise MetricoolError("METRICOOL_API_TOKEN, METRICOOL_USER_ID and METRICOOL_BLOG_ID are required")
 def request(self,method:str,path:str,params:dict[str,Any]|None=None,payload:dict[str,Any]|None=None)->Any:
  query={"userId":self.user_id,"blogId":self.blog_id}
  query.update({k:v for k,v in (params or {}).items() if v is not None})
  url=self.base_url+path+"?"+urllib.parse.urlencode(query,doseq=True)
  body=json.dumps(payload).encode() if payload is not None else None
  headers={"X-Mc-Auth":self.token,"Accept":"application/json"}
  if body is not None:headers["Content-Type"]="application/json"
  req=urllib.request.Request(url,data=body,headers=headers,method=method.upper())
  try:
   with urllib.request.urlopen(req,timeout=30) as response:
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
 def create_review_draft(self,text:str,publication_date:str,network:str="facebook",timezone:str="Africa/Cairo")->Any:
  if network not in NETWORKS:raise ValueError("Unsupported Metricool network")
  if not text.strip():raise ValueError("Post text is required")
  if not publication_date:raise ValueError("Publication date is required")
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
  row={k:metrics.get(k) for k in ("reach","impressions","likes","comments","shares","engagement")}
  for key,value in row.items():
   if isinstance(value,(int,float)):totals[key]+=value
  normalized.append({"text":str(item.get("text") or item.get("content") or "")[:240],"url":item.get("url") or item.get("link"),"publicationDate":item.get("publicationDate") or item.get("created"),"metrics":row})
 return {"totals":totals,"posts":normalized}

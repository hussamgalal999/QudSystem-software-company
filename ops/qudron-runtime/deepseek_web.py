"""Metered read-only live web search and fetch through DeepSeek's official API."""
from __future__ import annotations
import ipaddress,json,os,sqlite3,urllib.error,urllib.parse,urllib.request
from pathlib import Path
from urllib.parse import urlsplit
BASE="https://api.deepseek.com/v1/tools"
COST_PER_SUCCESS_USD=0.00075
class WebResearchError(RuntimeError):pass

def _db_path():
 return Path(os.getenv("QUDRON_WEB_SEARCH_DB","/app/data/web_search_usage.sqlite3"))
def _reserve_call(kind):
 limit=max(0,int(os.getenv("QUDRON_WEB_SEARCH_MAX_DAILY_CALLS","0")))
 if limit<1:raise WebResearchError("Web search is disabled; configure QUDRON_WEB_SEARCH_MAX_DAILY_CALLS after setting a spend cap")
 path=_db_path();path.parent.mkdir(parents=True,exist_ok=True)
 import datetime
 day=datetime.datetime.now(datetime.timezone.utc).date().isoformat()
 with sqlite3.connect(path) as db:
  db.execute("CREATE TABLE IF NOT EXISTS web_calls(day TEXT NOT NULL,kind TEXT NOT NULL,calls INTEGER NOT NULL,PRIMARY KEY(day,kind))")
  db.execute("BEGIN IMMEDIATE")
  total=db.execute("SELECT COALESCE(SUM(calls),0) FROM web_calls WHERE day=?",(day,)).fetchone()[0]
  if total>=limit:db.rollback();raise WebResearchError("Daily web search/fetch call limit reached")
  db.execute("INSERT INTO web_calls(day,kind,calls) VALUES(?,?,1) ON CONFLICT(day,kind) DO UPDATE SET calls=calls+1",(day,kind))
  db.commit()
 return {"day_utc":day,"daily_calls":int(total)+1,"max_daily_calls":limit,"reserved_cost_usd":COST_PER_SUCCESS_USD}
def _request(path,payload):
 key=os.getenv("DEEPSEEK_API_KEY","").strip()
 if not key:raise WebResearchError("DEEPSEEK_API_KEY is not configured in the host secret manager")
 reservation=_reserve_call(path.rsplit("/",1)[-1])
 req=urllib.request.Request(BASE+path,data=json.dumps(payload).encode(),headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},method="POST")
 try:
  with urllib.request.urlopen(req,timeout=60) as response:data=json.loads(response.read().decode())
 except urllib.error.HTTPError as exc:
  raise WebResearchError(f"DeepSeek web API returned HTTP {exc.code}") from None
 except (urllib.error.URLError,TimeoutError):
  raise WebResearchError("DeepSeek web API request failed") from None
 return data,reservation
def search_web(query:str,count:int=5,need_content:bool=True):
 query=str(query).strip()
 if not 1<=len(query)<=128:raise ValueError("Query must contain 1–128 characters")
 if not 1<=count<=10:raise ValueError("count must be between 1 and 10 for the bounded pilot")
 data,usage=_request("/search",{"query":query,"count":count,"need_content":bool(need_content)})
 results=data.get("results",[])
 return {"query":query,"results":results,"usage":usage,"cost_usd":COST_PER_SUCCESS_USD if results else 0.0}
def _safe_url(value:str)->str:
 parsed=urlsplit(value)
 if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password or len(value)>8192:
  raise ValueError("Only public HTTPS URLs without embedded credentials are allowed")
 host=parsed.hostname.lower().rstrip(".")
 if host=="localhost" or host.endswith(".localhost") or host.endswith(".local"):
  raise ValueError("Local/private hosts are not allowed")
 try:
  address=ipaddress.ip_address(host)
  if not address.is_global:raise ValueError("Private or non-public IP targets are not allowed")
 except ValueError as exc:
  if str(exc).startswith("Private or"):raise
 return value
def fetch_page(url:str):
 target=_safe_url(url)
 data,usage=_request("/fetch",{"url":target})
 return {"url":target,"title":data.get("title",""),"content":data.get("content",""),"usage":usage,"cost_usd":COST_PER_SUCCESS_USD if data.get("content") else 0.0}

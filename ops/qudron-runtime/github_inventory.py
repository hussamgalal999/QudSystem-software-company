"""Read-only GitHub repository inventory and tree synchronizer.

Requires a fine-grained GitHub token with read-only Metadata access to every
repository in scope. It indexes metadata and paths only; it never clones,
executes, or downloads repository contents.
"""
from __future__ import annotations
import json, os, re, tempfile, urllib.error, urllib.parse, urllib.request
from pathlib import Path
from typing import Any

API="https://api.github.com"
OWNER_RE=re.compile(r"^[A-Za-z0-9-]{1,39}$")

class GitHubInventoryError(RuntimeError): pass

def _request_json(url:str, token:str, timeout:int=30)->dict[str,Any]:
    if not token: raise GitHubInventoryError("GITHUB_TOKEN is required")
    req=urllib.request.Request(url,headers={
        "Accept":"application/vnd.github+json",
        "Authorization":"Bearer "+token,
        "X-GitHub-Api-Version":"2022-11-28",
        "User-Agent":"Qudron-ReadOnly-Inventory"
    })
    try:
        with urllib.request.urlopen(req,timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401,403): raise GitHubInventoryError("GitHub authentication or repository permission failed") from None
        if exc.code==429: raise GitHubInventoryError("GitHub rate limit reached; retry after reset") from None
        raise GitHubInventoryError(f"GitHub API returned HTTP {exc.code}") from None
    except (urllib.error.URLError,TimeoutError) as exc:
        raise GitHubInventoryError("GitHub API request failed") from exc

def discover_repositories(owner:str,token:str,per_page:int=100,max_pages:int=100)->list[dict[str,Any]]:
    if not OWNER_RE.fullmatch(owner): raise ValueError("Invalid GitHub owner")
    if not 1<=per_page<=100: raise ValueError("per_page must be between 1 and 100")
    found={}
    for page in range(1,max_pages+1):
        query=urllib.parse.urlencode({"visibility":"all","affiliation":"owner,collaborator,organization_member","per_page":per_page,"page":page,"sort":"updated","direction":"desc"})
        payload=_request_json(f"{API}/user/repos?{query}",token)
        if not isinstance(payload,list): raise GitHubInventoryError("Unexpected GitHub repository-list response")
        for item in payload:
            if not isinstance(item,dict) or not isinstance(item.get("full_name"),str): continue
            if item.get("owner",{}).get("login","").lower()!=owner.lower() and "owner" not in item.get("permissions",{}):
                # Keep collaborator/org repositories only when the caller asked for all affiliations.
                pass
            found[item["full_name"].lower()]={k:item.get(k) for k in ("id","full_name","name","private","visibility","default_branch","archived","updated_at","size","html_url","description")}
        if len(payload)<per_page: break
    else: raise GitHubInventoryError("Repository pagination reached max_pages; inventory may be incomplete")
    return sorted(found.values(),key=lambda x:(x.get("full_name") or "").lower())

def repository_tree(full_name:str,default_branch:str,token:str)->dict[str,Any]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",full_name): raise ValueError("Invalid repository name")
    branch=urllib.parse.quote(default_branch,safe="")
    payload=_request_json(f"{API}/repos/{full_name}/git/trees/{branch}?recursive=1",token)
    entries=[]
    for item in payload.get("tree",[]):
        if item.get("type") in ("blob","tree"):
            entries.append({"path":item.get("path",""),"type":item.get("type"),"size":item.get("size")})
    return {"repository":full_name,"branch":default_branch,"truncated":bool(payload.get("truncated")),"entries":entries}

def build_inventory(owner:str,token:str,include_trees:bool=False,max_tree_entries:int=50000)->dict[str,Any]:
    repos=discover_repositories(owner,token)
    result={"schema_version":1,"owner":owner,"repository_count":len(repos),"complete_metadata_scan":True,"trees_included":include_trees,"repositories":repos}
    if include_trees:
        trees=[]
        for repo in repos:
            if not repo.get("default_branch"): continue
            tree=repository_tree(repo["full_name"],repo["default_branch"],token)
            tree["entry_count"]=len(tree["entries"])
            if len(tree["entries"])>max_tree_entries:
                tree["entries"]=tree["entries"][:max_tree_entries]
                tree["entry_limit_applied"]=True
            trees.append(tree)
        result["trees"]=trees
        result["complete_tree_scan"]=all(not t["truncated"] and not t.get("entry_limit_applied") for t in trees)
    return result

def save_inventory(inventory:dict[str,Any],destination:str|Path)->Path:
    target=Path(destination).resolve()
    target.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=target.name+".",suffix=".tmp",dir=str(target.parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            json.dump(inventory,stream,ensure_ascii=False,indent=2)
            stream.flush();os.fsync(stream.fileno())
        os.replace(tmp,target)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise
    return target

def sync_inventory_from_env(destination:str|Path|None=None,include_trees:bool=False)->dict[str,Any]:
    owner=os.getenv("GITHUB_OWNER","").strip()
    token=os.getenv("GITHUB_TOKEN","").strip()
    if not owner or not token: raise GitHubInventoryError("Set GITHUB_OWNER and GITHUB_TOKEN in the host secret manager")
    inventory=build_inventory(owner,token,include_trees=include_trees)
    target=Path(destination or os.getenv("QUDRON_GITHUB_INVENTORY_PATH","/app/data/github_inventory.json"))
    save_inventory(inventory,target)
    return {"repository_count":inventory["repository_count"],"trees_included":include_trees,"path":str(target)}

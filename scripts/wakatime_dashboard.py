#!/usr/bin/env python3
"""Update light/dark README dashboard using aggregated WakaTime statistics."""
import argparse
import base64
from collections import defaultdict
from html import escape
import json
import os
from pathlib import Path
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

API="https://wakatime.com/api/v1/users/current"
COLOR={"light":("#24292f","#374151","#57606a","#d8dee4","#6e7781"),
       "dark":("#f0f6fc","#e6edf3","#9da7b3","#30363d","#bac2cc")}

def n(v):
    try:return max(float(v or 0),0)
    except (TypeError,ValueError):return 0.0

def compact(v):
    v=int(n(v))
    return f"{v/1e9:.2f}B" if v>=1e9 else f"{v/1e6:.2f}M" if v>=1e6 else (f"{v/1e3:.0f}K" if v>=1e5 else f"{v/1e3:.1f}K") if v>=1000 else str(v)

def hours(sec):
    h,m=divmod(round(n(sec)/60),60)
    return f"{h}h {m}m" if h else f"{m}m"

def label(s,length=21):
    s=str(s or "Unknown").replace("\n"," ").replace("\r"," ")
    return s if len(s)<=length else s[:length-1]+"…"

def fetch(path,token):
    auth=base64.b64encode(token.encode()).decode()
    req=Request(API+path,headers={"Authorization":"Basic "+auth,"Accept":"application/json","User-Agent":"wakatime-profile-svg/1.0"})
    for retry in range(4):
        try:
            with urlopen(req,timeout=30) as resp:
                if resp.status==202 and retry<3:
                    time.sleep(3*(retry+1));continue
                data=json.load(resp)
                if not isinstance(data,dict) or not isinstance(data.get("data"),(dict,list)):
                    raise RuntimeError("Unexpected WakaTime response schema")
                return data["data"]
        except HTTPError as e:
            if e.code in (429,500,502,503,504) and retry<3:
                time.sleep(3*(retry+1));continue
            raise RuntimeError(f"WakaTime HTTP {e.code} ({path.split('?')[0]})") from None
        except URLError:
            if retry<3:
                time.sleep(3*(retry+1));continue
            raise RuntimeError("Unable to connect to WakaTime") from None
    raise RuntimeError("WakaTime response not ready")

def collect(stats,days):
    if stats is None:
        return dict(code="—",average="—",top="—",days="—",langs=[],editors=[],systems=[],tokens=None,models=[],sessions=None,notice="Awaiting initial sync")
    total=n(stats.get("total_seconds_including_other_language",stats.get("total_seconds")))
    langs=sorted((x for x in stats.get("languages",[]) if isinstance(x,dict)),key=lambda x:-n(x.get("total_seconds")))
    def tools(key):
        items=sorted((x for x in stats.get(key,[]) if isinstance(x,dict)),key=lambda x:-n(x.get("total_seconds")))
        summed=sum(n(x.get("total_seconds")) for x in items)
        return [(label(x.get("name"),14),round(n(x.get("total_seconds"))/summed*100)) for x in items[:2]] if summed else []
    top=next((label(x.get("name"),20) for x in langs if str(x.get("name","")).lower()!="other"),label(langs[0].get("name"),20) if langs else "—")
    d=dict(code=hours(total),average=hours(stats.get("daily_average_including_other_language",stats.get("daily_average"))),top=top,days="—",
           langs=[(label(x.get("name")),hours(x.get("total_seconds")),n(x.get("total_seconds"))/total*100 if total else 0) for x in langs[:5]],
           editors=tools("editors"),systems=tools("operating_systems"),tokens=None,models=[],sessions=stats.get("ai_sessions"),notice="AI stats unavailable")
    if days is None:return d
    d["days"]=f"{sum(n((x.get('grand_total') or {}).get('total_seconds'))>0 for x in days if isinstance(x,dict))}/7"
    by_model=defaultdict(lambda:[0,0,0])
    inp=out=0
    for day in days:
        if not isinstance(day,dict):continue
        g=day.get("grand_total") or {}
        inp+=int(n(g.get("ai_input_tokens")));out+=int(n(g.get("ai_output_tokens")))
        for m in g.get("ai_model_breakdown") or []:
            if not isinstance(m,dict) or not m.get("name"):continue
            vals=by_model[str(m["name"])]
            for i,key in enumerate(("input_tokens","output_tokens","cached_input_tokens")):
                vals[i]+=int(n(m.get(key)))
    inp=max(inp,sum(v[0] for v in by_model.values()))
    out=max(out,sum(v[1] for v in by_model.values()))
    cached=sum(v[2] for v in by_model.values())
    total_tokens=inp+out+cached
    rows=sorted(((name,sum(vals)) for name,vals in by_model.items() if sum(vals)>0),key=lambda x:-x[1])
    missing=max(total_tokens-sum(v for _,v in rows),0)
    if missing:rows.append(("Unattributed",missing));rows.sort(key=lambda x:-x[1])
    if len(rows)>4:rows=rows[:3]+[("Other models",sum(v for _,v in rows[3:]))]
    d["tokens"]=(total_tokens,inp,out,cached)
    d["models"]=[(label(name),value,100*value/total_tokens if total_tokens else 0) for name,value in rows]
    d["notice"]="No AI activity recorded" if not total_tokens else ""
    if d["sessions"] is None:
        d["sessions"]=sum(int(n((x.get("grand_total") or {}).get("ai_sessions"))) for x in days if isinstance(x,dict))
    return d

def svg(mode,d,preview=False):
    fg,body,muted,track,fill=COLOR[mode]
    e=['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="716" viewBox="0 0 1200 716" role="img" aria-labelledby="title desc">',
       '<title id="title">Development Activity and Vibe Coding</title>',
       '<desc id="desc">WakaTime coding, language and AI model usage statistics for the last seven days.</desc>',
       '<style>text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,"Noto Sans",sans-serif;font-variant-numeric:tabular-nums}</style>']
    def t(x,y,s,size=15,color=body,weight=400,anchor="start"):
        e.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" fill="{color}">{escape(str(s))}</text>')
    def bar(y,pct,x=230,width=758):
        e.append(f'<rect x="{x}" y="{y}" width="{width}" height="7" rx="3.5" fill="{track}"/>')
        if pct>0:e.append(f'<rect x="{x}" y="{y}" width="{max(1.5,min(100,pct)*width/100):.2f}" height="7" rx="3.5" fill="{fill}"/>')
    e.append(f'<g fill="none" stroke="{fg}" stroke-width="2.6" stroke-linecap="round"><path d="M57 27 L47 36 L57 45"/><path d="M70 27 L80 36 L70 45"/><path d="M65 24 L61 48"/></g>')
    t(96,47,"Development Activity",29,fg,700)
    t(1150,44,"LAST 7 DAYS",13,muted,500,"end")
    for x,name,val in ((50,"Code Time",d["code"]),(342,"Daily Average",d["average"]),(634,"Top Language",d["top"]),(926,"Active Days",d["days"])):
        t(x,87,name,14,muted);t(x,117,val,24,fg,650)
    t(50,157,"Languages",20,fg,650)
    for i,(name,spent,pct) in enumerate(d["langs"][:5]):
        y=188+29*i;t(58,y,name);bar(y-11,pct);t(1150,y,f"{spent}  ·  {pct:.1f}%",14,muted,anchor="end")
    if not d["langs"]:t(58,188,"Awaiting WakaTime activity",15,muted)
    t(50,352,"Tools",20,fg,650)
    def tools(items):return "   ·   ".join(f"{name} {pct}%" for name,pct in items) or "No data"
    t(58,378,"Editors:",14,muted);t(150,378,tools(d["editors"]))
    e.append(f'<line x1="599" x2="599" y1="362" y2="381" stroke="{track}"/>')
    t(626,378,"Operating Systems:",14,muted);t(815,378,tools(d["systems"]))
    e.append(f'<g fill="none" stroke="{fg}" stroke-width="2.3"><rect x="50" y="418" width="28" height="21" rx="5"/><path d="M64 418 v-5"/><circle cx="64" cy="411" r="1.5" fill="{fg}" stroke="none"/><circle cx="59" cy="429" r="1.5" fill="{fg}" stroke="none"/><circle cx="69" cy="429" r="1.5" fill="{fg}" stroke="none"/></g>')
    t(94,441,"Vibe Coding",28,fg,700)
    t(50,467,"SAMPLE DATA — NOT YOUR STATS" if preview else (d["notice"] or "WAKATIME AI CODING · LAST 7 DAYS"),12,muted)
    values=[compact(x) for x in d["tokens"]] if d["tokens"] is not None else ["N/A"]*4
    for x,name,val in zip((50,342,634,926),("Total Tokens","Input","Output","Cached"),values):
        t(x,502,name,14,muted);t(x,530,val,24,fg,650)
    t(50,566,"Model Usage",20,fg,650)
    for i,(name,amount,pct) in enumerate(d["models"][:4]):
        y=598+29*i;t(58,y,name);bar(y-11,pct,251,737);t(1150,y,f"{compact(amount)}  ·  {pct:.1f}%",14,muted,anchor="end")
    if not d["models"]:t(58,598,d["notice"] or "No AI model data",15,muted)
    t(50,705,"AI Sessions",14,muted)
    t(1150,705,d["sessions"] if d["sessions"] is not None else "N/A",22,fg,650,"end")
    e.append("</svg>")
    return "\n".join(e)+"\n"

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output-dir",type=Path,default=Path("assets"))
    p.add_argument("--empty",action="store_true")
    args=p.parse_args()
    if args.empty:d=collect(None,None)
    else:
        token=os.getenv("WAKATIME_API_KEY")
        if not token:raise RuntimeError("Missing WAKATIME_API_KEY OAuth token")
        stats=fetch("/stats/last_7_days",token)
        if not isinstance(stats,dict) or "languages" not in stats:raise RuntimeError("Invalid Stats API response")
        try:
            days=fetch("/summaries?"+urlencode({"range":"Last 7 Days"}),token)
            if not isinstance(days,list):raise RuntimeError("Invalid Summaries API response")
        except RuntimeError as err:
            if "HTTP 401" in str(err) or "HTTP 403" in str(err):
                print("::warning::Missing WakaTime read_summaries OAuth scope",file=sys.stderr)
                days=None
            else:raise
        d=collect(stats,days)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    for mode in COLOR:
        path=args.output_dir/f"wakatime-dashboard-{mode}.svg"
        path.write_text(svg(mode,d),encoding="utf-8")
        print(f"Generated {path}")

if __name__=="__main__":
    try:main()
    except RuntimeError as err:
        print(f"::error::{err}",file=sys.stderr);sys.exit(1)

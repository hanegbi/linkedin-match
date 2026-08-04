"""Render the AI-scored job report as one self-contained HTML file.

Merges ``report_input`` (companies, contacts, jobs, cached scores) with the fresh
``ai_scores`` from the Sonnet subagents into a single ``DATA`` blob, then embeds it
in a static page: a hero stating the titles the candidate is looking for and a
short blurb, followed by their companies — each showing the people they know there
(contacts) and that company's matching jobs with an AI fit score.

Adapted from the warm-intros page, with the warm-intro framing removed: contacts
stay, but no "warm intro" wording, and the page is a neutral "Job fit report".
Pure data-to-HTML — no network, no template engine.
"""

import html
import json
from pathlib import Path


def merge_scores(report_input: dict, ai_scores: dict) -> dict[str, dict]:
    """Resolve a ``{job_id: {score, tag}}`` map for every job shown in the report.

    A job's score comes from the cache (``cached_scores``) if present, else from the
    LLM via its cache key: the subagents score one representative id per key, so a
    job inherits the score of whichever id shares its key. Unresolved jobs are left
    out and render with a neutral badge.
    """
    id_keys = report_input.get("id_keys", {})
    cached = report_input.get("cached_scores", {})
    # cache_key -> {score, tag} from the fresh LLM scores (keyed by representative id).
    by_key: dict[str, dict] = {}
    for rep_id, hit in (ai_scores or {}).items():
        ck = id_keys.get(rep_id)
        if ck and hit is not None:
            by_key[ck] = hit

    out: dict[str, dict] = {}
    for jid, ck in id_keys.items():
        if jid in cached:
            out[jid] = {"score": int(cached[jid]["score"]), "tag": cached[jid].get("reason") or ""}
        elif ck in by_key:
            hit = by_key[ck]
            out[jid] = {"score": int(hit["score"]), "tag": hit.get("tag") or hit.get("reason") or ""}
    return out


def build_data(report_input: dict, ai_scores: dict) -> dict:
    """Build the ``DATA`` object the page's script renders from."""
    scores = merge_scores(report_input, ai_scores)
    companies = []
    for co in report_input.get("companies", []):
        jobs = []
        for job in co.get("jobs", []):
            hit = scores.get(job["id"])
            jobs.append({
                "id": job["id"],
                "title": job["title"],
                "url": job.get("url"),
                "city": job.get("city") or "",
                "remote": bool(job.get("remote")),
                "score": hit["score"] if hit else None,
                "tag": hit["tag"] if hit else "",
            })
        # Best fit first; unscored jobs sink to the bottom.
        jobs.sort(key=lambda j: j["score"] if j["score"] is not None else -1, reverse=True)
        contacts = [
            {"name": c["name"], "role": c.get("role") or "", "url": c.get("url")}
            for c in co.get("contacts", [])
        ]
        companies.append({"company": co["company"], "contacts": contacts, "jobs": jobs})
    # Companies with a stronger best-fit job first.
    companies.sort(
        key=lambda c: max((j["score"] or -1) for j in c["jobs"]) if c["jobs"] else -1,
        reverse=True,
    )
    return {
        "candidate": report_input.get("candidate", ""),
        "titles": report_input.get("titles", []),
        "blurb": report_input.get("blurb", ""),
        "total_intros": report_input.get("total_intros", 0),
        "companies": companies,
    }


def render(report_input: dict, ai_scores: dict) -> str:
    """Return the full self-contained HTML page as a string."""
    data = build_data(report_input, ai_scores)
    name = html.escape(data["candidate"] or "Job fit report")
    blurb = html.escape(data["blurb"])
    # Embedded in a <script type="application/json"> block: escaping "<" to its
    # JSON unicode escape keeps the blob valid JSON while making a scraped title
    # containing "</script>" unable to break out of the element (prevents XSS in
    # the shareable report).
    data_json = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    return _PAGE.replace("{{NAME}}", name) \
        .replace("{{BLURB}}", blurb).replace("{{DATA_JSON}}", data_json)


def write_report(report_input: dict, ai_scores: dict, out_path: Path) -> Path:
    """Render and write the report; return the path written."""
    out_path.write_text(render(report_input, ai_scores), encoding="utf-8")
    return out_path


# The page: inline CSS/JS, one embedded DATA blob. No external requests except the
# web font (cosmetic; the page works without it). Contacts are shown; the score is
# the candidate's AI fit for that job. Like / hide-job / hide-company and the
# location filter persist in localStorage (keyed per candidate).
_PAGE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"/><meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{{NAME}} · Job fit report</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&family=JetBrains+Mono:wght@500;700&display=swap"/>
<style>
:root{--paper:#f6f7fb;--card:#fff;--ink:#1b1c30;--muted:#5c5f78;--faint:#9498b3;--line:#e9eaf3;--line-strong:#d8dae9;
--ember:#7c3aed;--ember-deep:#6d28d9;--cool:#2563eb;--grad:linear-gradient(135deg,#2f6bff 0%,#6d28d9 55%,#9333ea 100%);
--font-sans:"Inter",system-ui,sans-serif;--font-display:"Space Grotesk","Inter",sans-serif;--font-mono:"JetBrains Mono",ui-monospace,monospace;
--shadow:0 1px 2px rgba(24,25,48,.04),0 6px 20px rgba(24,25,48,.06);--shadow-lg:0 20px 48px rgba(38,30,90,.16);}
*{box-sizing:border-box}html,body{margin:0}body{font-family:var(--font-sans);background:var(--paper);color:var(--ink);line-height:1.5}
a{color:inherit;text-decoration:none}
.hero{background:var(--grad);color:#fff;padding:40px 24px 34px}
.hero .wrap{max-width:1080px;margin:0 auto}
.hero h1{font-family:var(--font-display);font-size:30px;margin:0 0 6px;font-weight:700;letter-spacing:-.02em}
.hero .looking{font-size:15px;opacity:.95;margin:0 0 12px}
.hero .looking b{font-weight:600}
.hero .chips{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 14px}
.hero .chip{background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.26);padding:5px 12px;border-radius:999px;font-size:13px;font-weight:600}
.hero .blurb{font-size:15px;max-width:760px;opacity:.96;margin:0}
header.bar{position:sticky;top:0;z-index:5;background:rgba(246,247,251,.92);backdrop-filter:blur(8px);border-bottom:1px solid var(--line);padding:12px 24px}
header.bar .wrap{max-width:1080px;margin:0 auto;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.search{flex:1;min-width:200px}.search input{width:100%;padding:9px 13px;border:1px solid var(--line-strong);border-radius:10px;font-size:14px;font-family:inherit;background:var(--card)}
.slider{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--muted)}
.count{font-size:13px;color:var(--muted);font-variant-numeric:tabular-nums}
main{max-width:1080px;margin:0 auto;padding:22px 24px 60px}
.co{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px 20px;margin:0 0 16px;box-shadow:var(--shadow)}
.co-head{display:flex;gap:20px;flex-wrap:wrap;justify-content:space-between;align-items:flex-start;margin:0 0 12px}
.co-name{font-family:var(--font-display);font-size:19px;margin:0 0 2px;font-weight:600}
.co-stat{font-size:13px;color:var(--muted)}.co-stat b{color:var(--ink)}
.co-people h4{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--faint);margin:0 0 6px;font-weight:600}
.ipills{display:flex;flex-wrap:wrap;gap:6px;max-width:520px}
.ipill{display:inline-flex;align-items:center;gap:7px;background:var(--paper);border:1px solid var(--line);border-radius:999px;padding:3px 10px 3px 4px;font-size:13px}
.iav{width:22px;height:22px;border-radius:50%;display:grid;place-items:center;color:#fff;font-size:10px;font-weight:700;font-family:var(--font-display)}
.iname{font-weight:600}.irole{color:var(--muted);font-size:12px}
.more-intro{list-style:none;background:none;border:1px dashed var(--line-strong);border-radius:999px;padding:4px 10px;font-size:12px;color:var(--muted);cursor:pointer;font-family:inherit}
.more-intro::-webkit-details-marker{display:none}
.more-wrap{position:relative;display:inline-block}
.more-wrap[open] .more-intro{border-color:var(--ember)}
.more-panel{position:absolute;top:calc(100% + 6px);left:0;z-index:20;background:var(--card);border:1px solid var(--line-strong);border-radius:10px;box-shadow:var(--shadow-lg);padding:8px;display:flex;flex-direction:column;gap:4px;min-width:320px;max-width:440px;max-height:280px;overflow:auto}
.more-panel .ipill{width:100%;white-space:normal}
.more-panel .iname,.more-panel .irole{white-space:normal}
.co-jobs{border-top:1px solid var(--line);margin-top:4px}
.job{display:flex;justify-content:space-between;gap:14px;align-items:center;padding:11px 0;border-bottom:1px solid var(--line)}
.job:last-child{border-bottom:none}
.job-title{font-weight:600;font-size:14.5px}.job-title:hover{color:var(--ember-deep)}
.job-meta{font-size:12.5px;color:var(--muted);margin-top:2px}
.badge{font-family:var(--font-mono);font-weight:700;font-size:13px;min-width:38px;text-align:center;padding:4px 8px;border-radius:8px;background:#eef0f7;color:var(--muted)}
.badge.top{background:#e7f7ee;color:#12854a}.badge.high{background:#eaf1ff;color:#2657cc}.badge.na{background:#f0f0f4;color:var(--faint)}
.foot{max-width:1080px;margin:0 auto;padding:0 24px 40px;color:var(--faint);font-size:12.5px}
.empty{text-align:center;color:var(--muted);padding:50px 0}
select{padding:8px 11px;border:1px solid var(--line-strong);border-radius:10px;font-size:13px;font-family:inherit;background:var(--card);color:var(--ink)}
.xwords{width:150px;padding:9px 13px;border:1px solid var(--line-strong);border-radius:10px;font-size:14px;font-family:inherit;background:var(--card)}
.ms{position:relative}
.ms>summary{list-style:none;cursor:pointer;padding:8px 11px;border:1px solid var(--line-strong);border-radius:10px;font-size:13px;background:var(--card);white-space:nowrap}
.ms>summary::-webkit-details-marker{display:none}
.ms[open]>summary{border-color:var(--ember)}
.ms-panel{position:absolute;top:calc(100% + 6px);left:0;z-index:9;background:var(--card);border:1px solid var(--line-strong);border-radius:10px;box-shadow:var(--shadow-lg);padding:8px;min-width:180px;max-height:280px;overflow:auto}
.ms-panel label{display:flex;align-items:center;gap:8px;padding:5px 6px;font-size:13px;border-radius:7px;cursor:pointer}
.ms-panel label:hover{background:var(--paper)}
.toggle{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--muted);cursor:pointer;user-select:none}
.linkbtn{background:none;border:none;color:var(--cool);font-size:13px;cursor:pointer;font-family:inherit;padding:0}
.hnote{color:var(--muted);font-size:13px;display:none;gap:8px;align-items:center;margin-top:8px}
.co{position:relative}
.co-hide{position:absolute;top:12px;right:12px;background:none;border:1px solid var(--line);border-radius:8px;padding:4px 6px;color:var(--faint);cursor:pointer;line-height:0}
.co-hide:hover{color:var(--ink);border-color:var(--line-strong)}
.job-side{display:flex;align-items:center;gap:8px}
.icbtn{background:none;border:none;padding:3px;cursor:pointer;color:var(--faint);line-height:0;border-radius:6px}
.icbtn:hover{color:var(--ink)}
.like.on{color:#e0245e}
</style></head><body>
<div class="hero"><div class="wrap">
  <h1>{{NAME}}</h1>
  <p class="looking"><b>Looking for</b></p>
  <div class="chips" id="chips"></div>
  <p class="blurb">{{BLURB}}</p>
</div></div>
<header class="bar"><div class="wrap">
  <div class="search"><input id="q" type="text" placeholder="Search company, role, contact…"/></div>
  <input id="xwords" class="xwords" type="text" placeholder="Hide titles with…"/>
  <details class="ms" id="locwrap"><summary id="locsum">All locations</summary><div class="ms-panel" id="locpanel"></div></details>
  <label class="slider">Min fit <input id="min" type="range" min="0" max="100" value="0"/> <b id="minval">0</b></label>
  <label class="toggle"><input type="checkbox" id="likedonly"/> Liked only</label>
  <span class="count" id="count"></span>
</div><div class="wrap"><div class="hnote" id="hnote"></div></div></header>
<main id="main"></main>
<div class="foot" id="foot"></div>
<script id="data" type="application/json">{{DATA_JSON}}</script>
<script>
const DATA=JSON.parse(document.getElementById("data").textContent);
const el=(id)=>document.getElementById(id);
const esc=(s)=>(s||"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const KEY=(DATA.candidate||"report").replace(/\\s+/g,"_");
const load=(k)=>{try{return new Set(JSON.parse(localStorage.getItem(KEY+"_"+k)||"[]"))}catch(e){return new Set()}};
const store=(k,s)=>localStorage.setItem(KEY+"_"+k,JSON.stringify([...s]));
let liked=load("liked"),hiddenJobs=load("hidej"),hiddenCos=load("hidec");
function badge(s){if(s==null)return "badge na";return s>=80?"badge top":s>=55?"badge high":"badge";}
function locLabel(j){return j.remote?"Remote":(j.city||"Location N/A");}
function isNA(j){return !j.remote && !j.city;}
function initials(n){return (n||"").split(/\\s+/).map(w=>w[0]).filter(Boolean).slice(0,2).join("").toUpperCase();}
function hue(s){let h=0;for(const c of s)h=(h*31+c.charCodeAt(0))%360;return h;}
function grad(h){const b=218+(h%60);return `linear-gradient(140deg,hsl(${b} 83% 60%),hsl(${b+12} 72% 50%))`;}
function pill(c){const h=hue(c.name);const inner=`<span class="iav" style="background:${grad(h)}">${esc(initials(c.name))}</span><span class="iname">${esc(c.name)}</span>`+(c.role?`<span class="irole">${esc(c.role)}</span>`:"");
  return c.url?`<a class="ipill" href="${esc(c.url)}" target="_blank" rel="noopener">${inner}</a>`:`<span class="ipill">${inner}</span>`;}
const HEART='<svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor"><path d="M12 21s-7-4.35-9.5-8.5C.8 9.6 2 6 5.5 6 7.7 6 9 7.5 12 10c3-2.5 4.3-4 6.5-4C22 6 23.2 9.6 21.5 12.5 19 16.65 12 21 12 21z"/></svg>';
const EYE='<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';
function jobRow(co,j){const t=j.url?`<a class="job-title" href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)} \\u2197</a>`:`<span class="job-title">${esc(j.title)}</span>`;
  const s=j.score==null?"\\u2014":j.score;const on=liked.has(j.id)?" on":"";
  return `<div class="job"><div><div>${t}</div><div class="job-meta">${esc(locLabel(j))}</div></div>
    <div class="job-side"><button class="icbtn like${on}" data-like="${esc(j.id)}" title="Like">${HEART}</button>
    <button class="icbtn" data-hidej="${esc(j.id)}" title="Hide job">${EYE}</button>
    <span class="${badge(j.score)}">${s}</span></div></div>`;}
// Multi-location filter: checkboxes for Remote + each distinct city. Empty set = all.
const cities=[...new Set(DATA.companies.flatMap(c=>c.jobs).filter(j=>j.city).map(j=>j.city))].sort();
const hasRemote=DATA.companies.some(c=>c.jobs.some(j=>j.remote));
const locOpts=(hasRemote?["__remote"]:[]).concat(cities);
const locName=(v)=>v==="__remote"?"Remote":v;
let locSel=load("loc");   // selected locations; empty = show all
el("locpanel").innerHTML=locOpts.map(v=>`<label><input type="checkbox" value="${esc(v)}"${locSel.has(v)?" checked":""}/> ${esc(locName(v))}</label>`).join("")||`<label>No locations</label>`;
function locSummary(){el("locsum").textContent=locSel.size?(locSel.size===1?locName([...locSel][0]):locSel.size+" locations"):"All locations";}
el("chips").innerHTML=DATA.titles.map(t=>`<span class="chip">${esc(t)}</span>`).join("");
function locMatch(j){if(!locSel.size)return true;
  if(isNA(j))return true;             // N/A always shown once any location is picked
  return (j.remote&&locSel.has("__remote"))||(!!j.city&&locSel.has(j.city));}
function render(){
  const q=el("q").value.trim().toLowerCase(),min=+el("min").value,lo=el("likedonly").checked;
  const xs=el("xwords").value.toLowerCase().split(/[\\s,]+/).filter(Boolean);
  el("minval").textContent=min;locSummary();
  let vc=0,vj=0;
  const html=DATA.companies.filter(c=>!hiddenCos.has(c.company)).map(c=>{
    let jobs=c.jobs.filter(j=>!hiddenJobs.has(j.id) && (j.score==null?0:j.score)>=min && locMatch(j) && (!lo||liked.has(j.id)) && !xs.some(w=>j.title.toLowerCase().includes(w)));
    const hay=(c.company+" "+c.contacts.map(i=>i.name+" "+i.role).join(" ")).toLowerCase();
    if(q&&!hay.includes(q))jobs=jobs.filter(j=>j.title.toLowerCase().includes(q));
    if(!jobs.length)return "";
    vc++;vj+=jobs.length;
    const best=Math.max(...jobs.map(j=>j.score==null?0:j.score));
    const head=c.contacts.slice(0,6).map(pill).join("");
    const extra=c.contacts.slice(6);
    const more=extra.length?`<details class="more-wrap"><summary class="more-intro">+${extra.length} more</summary><div class="more-panel">${extra.map(pill).join("")}</div></details>`:"";
    return `<section class="co"><button class="co-hide" data-hidec="${esc(c.company)}" title="Hide company">${EYE}</button>
      <div class="co-head">
      <div><h3 class="co-name">${esc(c.company)}</h3><span class="co-stat">${jobs.length} role${jobs.length===1?"":"s"} \\u00b7 best fit <b>${best}</b></span></div>
      <div class="co-people"><h4>${c.contacts.length} contact${c.contacts.length===1?"":"s"}</h4><div class="ipills">${head}${more}</div></div>
    </div><div class="co-jobs">${jobs.map(j=>jobRow(c.company,j)).join("")}</div></section>`;
  }).join("");
  el("main").innerHTML=html||`<div class="empty">No roles match your filters.</div>`;
  el("count").textContent=`${vj} jobs \\u00b7 ${vc} companies \\u00b7 ${liked.size} liked`;
  const nh=hiddenCos.size+hiddenJobs.size,hn=el("hnote");
  if(nh){hn.style.display="flex";hn.innerHTML=`${hiddenCos.size} compan${hiddenCos.size===1?"y":"ies"} \\u00b7 ${hiddenJobs.size} job${hiddenJobs.size===1?"":"s"} hidden <button class="linkbtn" id="restore">Restore all</button>`;
    el("restore").onclick=()=>{hiddenCos.clear();hiddenJobs.clear();store("hidec",hiddenCos);store("hidej",hiddenJobs);render();};}
  else hn.style.display="none";
  el("foot").textContent=`Jobs at companies where ${DATA.candidate} has a connection \\u00b7 ${DATA.total_intros} contacts \\u00b7 AI fit scored`;
}
el("main").addEventListener("click",e=>{
  const lk=e.target.closest("[data-like]"),hj=e.target.closest("[data-hidej]"),hc=e.target.closest("[data-hidec]");
  if(lk){const id=lk.dataset.like;liked.has(id)?liked.delete(id):liked.add(id);store("liked",liked);render();}
  else if(hj){hiddenJobs.add(hj.dataset.hidej);store("hidej",hiddenJobs);render();}
  else if(hc){hiddenCos.add(hc.dataset.hidec);store("hidec",hiddenCos);render();}
});
el("xwords").value=localStorage.getItem(KEY+"_xwords")||"";
el("xwords").addEventListener("input",()=>localStorage.setItem(KEY+"_xwords",el("xwords").value));
el("locpanel").addEventListener("change",e=>{const cb=e.target.closest('input[type=checkbox]');if(!cb)return;
  cb.checked?locSel.add(cb.value):locSel.delete(cb.value);store("loc",locSel);render();});
["q","min","xwords","likedonly"].forEach(id=>el(id).addEventListener("input",render));
document.addEventListener("click",e=>{
  document.querySelectorAll("details.more-wrap[open]").forEach(d=>{if(!d.contains(e.target))d.removeAttribute("open");});
});
render();
</script>
</body></html>"""

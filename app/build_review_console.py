#!/usr/bin/env python3
"""
Build the Outreach Review Console — a single, self-contained HTML file you open
outside any chat window and click through one prospect at a time.

Reads the live queue (documents/outreach-queue.md) and writes
"Job Attractor Review Console.html" into the repo root. Zero dependencies
(stdlib only). Data is baked into the file at build time, so re-run this
whenever the queue changes (or wire it to a launcher / scheduled task).

Each entry shows the boss, the why/screen, the flags, and the drafted email.
The action buttons (Prep / Mark sent / Drop / Deeper probe / Full dossier) call
sendPrompt() when the file is rendered inside a chat, and otherwise copy the
instruction to the clipboard so you can paste it into your assistant chat.

Run:  python3 app/build_review_console.py [--open]
"""
import json
import os
import re
import sys
import webbrowser

APP_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(APP_DIR)
QUEUE = os.path.join(REPO, "documents", "outreach-queue.md")
OUT = os.path.join(REPO, "Job Attractor Review Console.html")


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def parse_entries(text):
    """Parse the outreach queue markdown into review-console entries.

    Only reviewable entries are included (NEW / READY FOR REVIEW); SENT and DROP
    live in the archive and are skipped."""
    out = []
    for block in re.split(r"(?m)^## ", text)[1:]:
        lines = block.split("\n")
        header = lines[0].strip()
        body = "\n".join(lines[1:])
        if "STATUS: SENT" in header:
            status = "SENT"
        elif "STATUS: DROP" in header:
            status = "DROP"
        elif "STATUS: NEW" in header:
            status = "NEW"
        elif "READY FOR REVIEW" in header:
            status = "READY FOR REVIEW"
        else:
            status = "NEW"
        if status in ("SENT", "DROP"):
            continue
        segs = [s.strip() for s in header.split(" · ")]
        comp = segs[1] if len(segs) > 1 else header
        m = re.search(r"\(([^)]+)\)", comp)
        url = m.group(1).strip() if m else ""
        company = re.sub(r"\s*\(.*$", "", comp).strip()
        boss = segs[2] if len(segs) > 2 else ""
        boss = re.sub(r"\s*\(.*$", "", boss).strip()
        fm = re.search(r"\(flagged:([^)]*)\)", header) or re.search(r"STATUS:\s*[A-Z ]+?\(([^)]*)\)", header)
        flags = fm.group(1).strip() if fm else ""
        wm = re.search(r"\*\*Why this match:\*\*\s*(.+)", body)
        why = re.sub(r"\*\*|`", "", wm.group(1)).strip() if wm else ""
        if len(why) > 280:
            why = why[:280].rsplit(" ", 1)[0] + "…"
        draft = "\n".join(l[2:] if l.startswith("> ") else "" for l in body.split("\n") if l.startswith(">")).strip()
        sm = re.search(r"\*\*Subject:\*\*\s*(.+)", draft)
        subject = sm.group(1).strip() if sm else ""
        tm = re.search(r"\*\*To:\*\*\s*([^\n·]+)", draft)
        to = tm.group(1).strip() if tm else ""
        email = "\n".join(l for l in draft.split("\n") if not l.startswith("**")).strip()
        out.append({
            "company": company, "url": url, "boss": boss[:70], "status": status,
            "flags": flags[:160], "why": why, "subject": subject, "to": to[:90], "email": email,
        })
    return out


HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job Attractor — Outreach Review Console</title>
<style>
body{margin:0;padding:24px;background:#f4f4f6;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
#app{font-family:inherit;color:var(--tp,#1c1c1e);max-width:940px;margin:0 auto;font-size:14px;line-height:1.5}
:root{--tp:#1c1c1e;--ts:#6b6b70;--ln:#e3e3e6;--card:#fbfbfc;--accent:#3a5bd9;--amber:#b26a00;--amberbg:#fdf1dd;--green:#0a7d4d;--greenbg:#e5f4ec;--grey:#8a8a8e;--greybg:#eeeef0}
@media (prefers-color-scheme:dark){body{background:#161618}#app{--tp:#f2f2f5;--ts:#a0a0a6;--ln:#333338;--card:#1e1e22;--accent:#8aa0ff;--amber:#e0a349;--amberbg:#3a2e18;--green:#4cc98a;--greenbg:#123527;--grey:#9a9aa0;--greybg:#2a2a2e}}
.bar{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:12px;flex-wrap:wrap}
.ttl{font-weight:650;font-size:16px}
.counter{color:var(--ts);font-weight:500;font-size:13px;margin-left:6px}
.filters{display:flex;gap:6px}
.pv{background:var(--card);border:1px solid var(--ln);color:var(--tp);padding:6px 12px;border-radius:8px;cursor:pointer;font-size:13px;font-weight:550}
.pv:hover{border-color:var(--accent);color:var(--accent)}
.grid{display:grid;grid-template-columns:212px 1fr;gap:14px;align-items:start}
#list{border:1px solid var(--ln);border-radius:10px;overflow:hidden;max-height:560px;overflow-y:auto;background:var(--card)}
.li{padding:9px 11px;border-bottom:1px solid var(--ln);cursor:pointer;display:flex;align-items:center;gap:8px}
.li:last-child{border-bottom:none}
.li:hover{background:rgba(120,140,255,.08)}
.li.sel{background:rgba(120,140,255,.14)}
.dot{width:8px;height:8px;border-radius:50%;flex:0 0 auto}
.li .nm{font-weight:550;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.li .dec{margin-left:auto;font-size:10px;font-weight:700;letter-spacing:.03em}
main{border:1px solid var(--ln);border-radius:10px;padding:16px 18px;background:var(--card);min-height:400px}
.co{font-size:19px;font-weight:680;margin:0 0 2px}
.co a{color:var(--accent);text-decoration:none;font-size:13px;font-weight:500;margin-left:8px}
.boss{color:var(--ts);margin-bottom:10px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px}
.chip{font-size:11px;font-weight:650;padding:3px 9px;border-radius:20px}
.c-new{background:var(--amberbg);color:var(--amber)}
.c-drop{background:var(--greybg);color:var(--grey)}
.sec{font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--ts);margin:14px 0 5px}
.why{color:var(--tp)}
.flags{color:var(--amber);font-weight:550}
.draft{background:rgba(120,120,130,.06);border:1px solid var(--ln);border-radius:8px;padding:11px 13px;margin-top:4px}
.dl{font-size:12px;color:var(--ts);margin-bottom:3px}
.dl b{color:var(--tp)}
.body{white-space:pre-wrap;font-size:13px;margin-top:8px;line-height:1.55}
.acts{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}
.btn{border:none;border-radius:8px;padding:8px 13px;font-size:13px;font-weight:600;cursor:pointer}
.b-prep{background:var(--accent);color:#fff}
.b-sent{background:var(--greenbg);color:var(--green)}
.b-drop{background:var(--greybg);color:var(--tp)}
.b-probe,.b-full{background:transparent;border:1px solid var(--ln);color:var(--tp)}
.btn:hover{filter:brightness(1.05);opacity:.92}
.hint{color:var(--ts);font-size:12px;margin-top:12px}
.done{outline:2px solid var(--green);outline-offset:1px}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);border:0}
#toast{position:fixed;left:50%;bottom:26px;transform:translateX(-50%) translateY(20px);background:#1c1c1e;color:#fff;padding:10px 16px;border-radius:9px;font-size:13px;opacity:0;transition:.25s;pointer-events:none;z-index:9;max-width:80vw;text-align:center}
#toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
</style>
</head>
<body>
<h2 class="sr-only">Outreach review console: step through each queued job-outreach prospect one at a time, read the dossier and drafted email, and use the buttons to run or copy a Prep, Mark sent, Drop, or Deeper probe instruction.</h2>
<div id="app">
<div class="bar">
  <div class="ttl">Outreach Review Console <span id="counter" class="counter"></span></div>
  <div class="filters">
    <button class="pv" data-nav="prev">‹ Prev</button>
    <button class="pv" data-nav="next">Next ›</button>
  </div>
</div>
<div class="grid">
  <aside id="list"></aside>
  <main id="detail"></main>
</div>
<p class="hint">Buttons run the instruction when this is open in your assistant chat, otherwise they copy it to your clipboard (with a toast) to paste into chat. Prep runs the two-stage boss-praise picks, builds the résumé, and opens the mailto draft. Nothing sends without you. Progress is saved in this browser. Re-run app/build_review_console.py to refresh from the queue.</p>
</div>
<div id="toast"></div>
<script id="data" type="application/json">
"""

TAIL = """
</script>
<script>
(function(){
 var DATA=JSON.parse(document.getElementById('data').textContent);
 var KEY='ube_review_decisions_v1';
 var state=JSON.parse(localStorage.getItem(KEY)||'{}');
 var idx=0;
 var listEl=document.getElementById('list'),detEl=document.getElementById('detail'),cnt=document.getElementById('counter'),toast=document.getElementById('toast');
 function dotColor(d,s){if(d==='sent')return 'var(--green)';if(d==='dropped')return 'var(--grey)';if(d==='prepped')return 'var(--accent)';return s.indexOf('DROP')>=0?'var(--grey)':'var(--amber)';}
 function decLabel(d){return d?({prepped:'PREP',sent:'SENT',dropped:'DROP',reviewed:'SEEN'}[d]||''):'';}
 function esc(t){return (t||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
 function showToast(m){toast.textContent=m;toast.classList.add('show');setTimeout(function(){toast.classList.remove('show');},2600);}
 function act(text,dec){ if(dec){state[DATA[idx].company]=dec;localStorage.setItem(KEY,JSON.stringify(state));}
   var done=false; try{ if(typeof sendPrompt==='function'){sendPrompt(text);done=true;} }catch(e){}
   if(!done){ try{navigator.clipboard.writeText(text);showToast('Copied — paste into your assistant chat');}catch(_){showToast('Copy this: '+text);} }
   renderList(); renderDetail(); }
 function renderList(){
   listEl.innerHTML='';
   DATA.forEach(function(e,i){
     var d=state[e.company];
     var row=document.createElement('div');row.className='li'+(i===idx?' sel':'');
     row.innerHTML='<span class="dot" style="background:'+dotColor(d,e.status)+'"></span><span class="nm">'+esc(e.company)+'</span><span class="dec" style="color:'+dotColor(d,e.status)+'">'+decLabel(d)+'</span>';
     row.onclick=function(){idx=i;renderList();renderDetail();};
     listEl.appendChild(row);
   });
 }
 function renderDetail(){
   if(!DATA.length){detEl.innerHTML='<div class="why">Queue is empty. The pipeline will refill it, then re-run the build script.</div>';cnt.textContent='';return;}
   var e=DATA[idx];var d=state[e.company];
   cnt.textContent='Entry '+(idx+1)+' of '+DATA.length;
   var statusChip=e.status.indexOf('DROP')>=0?'<span class="chip c-drop">DROP recommended</span>':'<span class="chip c-new">Awaiting your call</span>';
   detEl.className=d==='sent'?'done':'';
   detEl.innerHTML=
     '<div class="co">'+esc(e.company)+'<a href="https://'+esc(e.url)+'" target="_blank" rel="noopener">'+esc(e.url)+' ↗</a></div>'+
     '<div class="boss">Boss: '+esc(e.boss)+'</div>'+
     '<div class="chips">'+statusChip+(d?'<span class="chip c-new" style="background:var(--greenbg);color:var(--green)">you: '+decLabel(d)+'</span>':'')+'</div>'+
     '<div class="sec">Why / screen</div><div class="why">'+esc(e.why)+'</div>'+
     (e.flags?'<div class="sec">Flags for your call</div><div class="flags">'+esc(e.flags)+'</div>':'')+
     '<div class="sec">Drafted email</div>'+
     '<div class="draft"><div class="dl"><b>To:</b> '+esc(e.to)+'</div><div class="dl"><b>Subject:</b> '+esc(e.subject)+'</div><div class="body">'+esc(e.email)+'</div></div>'+
     '<div class="acts">'+
       '<button class="btn b-prep">Prep &amp; open draft</button>'+
       '<button class="btn b-sent">Mark sent</button>'+
       '<button class="btn b-drop">Drop</button>'+
       '<button class="btn b-probe">Deeper probe</button>'+
       '<button class="btn b-full">Full dossier</button>'+
     '</div>';
   detEl.querySelector('.b-prep').onclick=function(){act('Prep the '+e.company+' entry: run the two-stage boss-praise selection (3 accomplishments then 3 phrasings), build the tailored résumé, and open the mailto draft.','prepped');};
   detEl.querySelector('.b-sent').onclick=function(){act('Mark '+e.company+' as SENT today, log it to the outreach log and tracker, and archive it.','sent');};
   detEl.querySelector('.b-drop').onclick=function(){act('Drop '+e.company+' with the reason, and move it to the archive.','dropped');};
   detEl.querySelector('.b-probe').onclick=function(){act('Run a deeper probe on '+e.company+' (culture / disqualifying-signal protocol) before I decide.');};
   detEl.querySelector('.b-full').onclick=function(){act('Show me the full dossier for '+e.company+' from the outreach queue.');};
 }
 document.querySelectorAll('[data-nav]').forEach(function(b){b.onclick=function(){if(!DATA.length)return;idx=(idx+(b.dataset.nav==='next'?1:DATA.length-1))%DATA.length;renderList();renderDetail();};});
 document.addEventListener('keydown',function(ev){if(!DATA.length)return;if(ev.key==='ArrowRight'){idx=(idx+1)%DATA.length;renderList();renderDetail();}if(ev.key==='ArrowLeft'){idx=(idx+DATA.length-1)%DATA.length;renderList();renderDetail();}});
 renderList();renderDetail();
})();
</script>
</body>
</html>
"""


def build(queue_path=QUEUE, out_path=OUT):
    entries = parse_entries(_read(queue_path))
    html = HEAD + json.dumps(entries, ensure_ascii=False) + TAIL
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path, len(entries)


def main():
    out, n = build()
    print("Built review console: %s (%d entries)" % (out, n))
    if "--open" in sys.argv:
        try:
            webbrowser.open("file://" + out)
        except Exception:
            pass


if __name__ == "__main__":
    main()

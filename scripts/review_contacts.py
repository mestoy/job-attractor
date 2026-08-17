#!/usr/bin/env python3
"""review_contacts.py — a localhost tool to REVIEW every contact and set closeness by hand.

WHY (Michael 2026-08-15, [[closeness-is-reviewed-not-inferred-from-message-count]]): review EVERY
contact and set closeness yourself — no shortcuts, no --infer. A close tie can have zero messages, so
message count is not a closeness proxy. The batch tick-pickers do not work for him. This is the home
for BOTH the closeness levelling AND the mutual-groups reads, one contact at a time, with full
context and the LinkedIn profile one click away (the export title is frozen at the connect date and
must be verified live before levelling).

⛔ THE NO-INFER RULING IS ENFORCED BY CONSTRUCTION. There is NO write path that is not an explicit
human button press. The tool never calls level_contacts.infer, never guesses a tier, never
default-files an unseen contact. `never-spoke` is a deliberate press, not a default; skipping a
contact leaves it un-levelled and it stays in the queue. It never scrapes LinkedIn — it shows the
mutual-groups tri-state and a clickable profile link, and the human does the auth-walled read.

⚖️ IT ORCHESTRATES, NEVER REIMPLEMENTS. Closeness writes go through level_contacts.record (atomic +
flock-serialized since BUG-221); mutual-groups writes through mutual_groups.record. Context comes
from the existing readers (export_contacts, _inbound_evidence, mutual_groups.groups_for, the contact
registry). Resumable by construction: the store IS the progress — a levelled contact drops out of the
un-levelled queue on the next load, so a restart resumes where you stopped.

🔒 LOCAL AND SINGLE-USER. Binds 127.0.0.1 only, an ephemeral port, no auth, no external exposure.

Usage:
    scripts/review_contacts.py            # start the server, open the browser
    scripts/review_contacts.py --no-open  # start without opening a browser (prints the URL)
    scripts/review_contacts.py --port N   # pin a port (default: an OS-chosen ephemeral one)
"""
import argparse
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
sys.path.insert(0, HERE)

import level_contacts  # noqa: E402  the closeness store + record() (atomic+locked)


def _closeness_mod():
    import closeness
    return closeness


def _profile_map():
    """{normalized name: profile URL} from the durable contact registry, best-effort."""
    out = {}
    try:
        import state
        cl = _closeness_mod()
        for line in open(os.path.join(REPO, "documents", "state", "contact.jsonl"),
                         encoding="utf-8", errors="ignore"):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("kind") != "contact":
                continue
            pay = row.get("payload") or {}
            nm = (pay.get("name") or "").strip()
            if nm:
                # BUG-180: address off the handle via the ONE sanctioned resolver, never build a URL
                # from a possibly-ambiguous value ourselves. address_for raises when no handle is
                # derivable, so an unaddressable row simply gets no profile link (never a wrong one).
                try:
                    import state
                    out[cl.normalize_name(nm)] = state.address_for(row)
                except Exception:
                    pass
    except Exception:
        pass
    return out


def _list_contacts():
    """The full annotated, lightweight list — one row per export contact, un-levelled first.

    NEVER infers: `tier` is whatever is ALREADY on file (stated), or "" when unset. `has_thread` and
    `group_state` are context flags, never a tier.
    """
    cl = _closeness_mod()
    store = cl.load() or {}
    inbound = level_contacts._inbound_evidence()
    profiles = _profile_map()
    rows = []
    for name, company, position, connected in level_contacts.export_contacts():
        crow = cl.tier_for(name, store)
        tier = (crow or {}).get("closeness") or ""
        source = (crow or {}).get("source") or ""
        stated = source == cl.STATED_SOURCE
        try:
            groups = level_contacts._groups_for(name)
        except Exception:
            groups = None
        group_state = ("yes" if groups else "none") if groups is not None else "unchecked"
        rows.append({
            "name": name, "company": company or "", "title": position or "",
            "connected": connected.isoformat() if hasattr(connected, "isoformat") else (connected or ""),
            "tier": tier, "stated": stated,
            "unlevelled": not (tier and stated),
            "has_thread": cl.normalize_name(name) in inbound,
            "group_state": group_state,
            "profile_url": profiles.get(cl.normalize_name(name), ""),
        })
    # un-levelled (no STATED tier) first; within each group, oldest connection first, then name.
    rows.sort(key=lambda r: (not r["unlevelled"], r["connected"] or "9999", r["name"]))
    return rows


def _detail(name):
    """Full per-contact context: the message thread (their words) and the mutual-groups tri-state."""
    cl = _closeness_mod()
    thread = None
    try:
        hit = level_contacts._evidence_for(name, level_contacts._inbound_evidence())
        if hit:
            when, body = (hit if isinstance(hit, (list, tuple)) and len(hit) == 2 else ("", str(hit)))
            thread = {"when": when, "body": body}
    except Exception:
        pass
    try:
        groups = level_contacts._groups_for(name)
    except Exception:
        groups = None
    crow = cl.tier_for(name, cl.load() or {})
    return {
        "name": name,
        "thread": thread,
        "groups": groups,                       # [names] | [] checked-none | None not-checked
        "how_known": (crow or {}).get("how_known") or "",
        "note": (crow or {}).get("note") or "",
    }


def _record_closeness(name, tier, how):
    """Explicit human tier. Goes through the atomic+locked stated-answer writer. Returns (ok, msg)."""
    if tier not in level_contacts.STATED_TIERS:
        return False, f"unknown tier {tier!r}"
    pair = f"{name}={tier}" + (f"::{how}" if how else "")
    try:
        n, errors = level_contacts.record([pair])
    except Exception as exc:
        return False, str(exc)
    if errors:
        return False, "; ".join(errors)
    return n == 1, "recorded" if n == 1 else "not recorded"


def _record_groups(name, groups):
    """Explicit human mutual-groups read. `groups` is a list, or the string 'NONE' (checked, none)."""
    import mutual_groups
    if isinstance(groups, list):
        val = ";".join(g.strip() for g in groups if g.strip()) or "NONE"
    else:
        val = "NONE"
    try:
        mutual_groups.record([f"{name}={val}"])
        return True, "recorded"
    except Exception as exc:
        return False, str(exc)


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Contact review</title>
<style>
 body{font:15px/1.5 -apple-system,system-ui,sans-serif;margin:0;background:#0f1115;color:#e6e6e6}
 header{padding:10px 16px;background:#161923;border-bottom:1px solid #262b38;position:sticky;top:0}
 header input,header select{background:#0f1115;color:#e6e6e6;border:1px solid #2b3242;border-radius:6px;padding:5px 8px;font:inherit}
 .wrap{max-width:820px;margin:18px auto;padding:0 16px}
 .card{background:#161923;border:1px solid #262b38;border-radius:12px;padding:20px}
 .name{font-size:22px;font-weight:600}
 .meta{color:#9aa4b6;margin:2px 0 12px}
 a{color:#7db1ff}
 .ctx{background:#0f1115;border:1px solid #222836;border-radius:8px;padding:10px 12px;margin:10px 0;white-space:pre-wrap}
 .tiers{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}
 .tier{background:#20263a;border:1px solid #2f3852;color:#e6e6e6;border-radius:8px;padding:9px 12px;cursor:pointer;font:inherit}
 .tier:hover{background:#2b3450}
 .tier .k{color:#7db1ff;font-weight:700;margin-right:6px}
 .cur{color:#8fd19e}
 label{color:#9aa4b6;font-size:13px}
 textarea,#groups{width:100%;box-sizing:border-box;background:#0f1115;color:#e6e6e6;border:1px solid #2b3242;border-radius:6px;padding:8px;font:inherit;margin-top:4px}
 .row{display:flex;gap:10px;align-items:center;margin-top:12px}
 button.act{background:#2f6feb;color:#fff;border:0;border-radius:8px;padding:9px 14px;cursor:pointer;font:inherit}
 button.ghost{background:transparent;color:#9aa4b6;border:1px solid #2b3242;border-radius:8px;padding:9px 14px;cursor:pointer;font:inherit}
 .prog{color:#9aa4b6;font-size:13px}
 .flag{display:inline-block;font-size:12px;padding:2px 8px;border-radius:20px;margin-right:6px}
 .f-thread{background:#1d3a2a;color:#8fd19e}.f-group{background:#1d2f3a;color:#7db1ff}.f-un{background:#3a2a1d;color:#e0b080}
</style></head><body>
<header>
 <span class="prog" id="prog">loading…</span>
 &nbsp; filter:
 <select id="filter">
   <option value="unlevelled">un-levelled first</option>
   <option value="all">all (revisit)</option>
   <option value="has_thread">has a message thread</option>
   <option value="in_group">in a shared group</option>
 </select>
 <input id="company" placeholder="by company…" size="14">
</header>
<div class="wrap"><div class="card" id="card">…</div></div>
<script>
let ALL=[], TIERS=[], i=0, cur=null;
async function boot(){
  const r=await fetch('/api/list'); const d=await r.json(); ALL=d.contacts; TIERS=d.tiers; render();
}
function view(){
  let v=ALL.slice(); const f=document.getElementById('filter').value;
  const co=document.getElementById('company').value.trim().toLowerCase();
  if(f==='unlevelled') v=v.filter(c=>c.unlevelled);
  if(f==='has_thread') v=v.filter(c=>c.has_thread);
  if(f==='in_group') v=v.filter(c=>c.group_state==='yes');
  if(co) v=v.filter(c=>(c.company||'').toLowerCase().includes(co));
  return v;
}
async function render(){
  const v=view(); if(i>=v.length)i=Math.max(0,v.length-1);
  const c=v[i]; cur=c;
  document.getElementById('prog').textContent =
    v.length? `${i+1} / ${v.length} shown · ${ALL.filter(x=>x.unlevelled).length} un-levelled of ${ALL.length}` : 'nothing matches this filter';
  const el=document.getElementById('card');
  if(!c){el.innerHTML='<div class=meta>No contacts match. Change the filter.</div>';return;}
  let flags='';
  if(c.unlevelled)flags+='<span class="flag f-un">un-levelled</span>';
  if(c.has_thread)flags+='<span class="flag f-thread">has thread</span>';
  if(c.group_state==='yes')flags+='<span class="flag f-group">shared group</span>';
  el.innerHTML=`<div class=name>${esc(c.name)}</div>
    <div class=meta>${esc(c.title||'?')} @ ${esc(c.company||'?')} · connected ${esc(c.connected||'?')}${c.tier?` · <span class=cur>current: ${esc(c.tier)}${c.stated?'':' (inferred — confirm)'}</span>`:''}</div>
    <div>${flags}</div>
    ${c.profile_url?`<div class=row><a href="${esc(c.profile_url)}" target=_blank rel=noopener>↗ open LinkedIn profile (verify the live title before levelling)</a></div>`:'<div class=meta>no profile URL on file</div>'}
    <div id=ctx class=meta>loading context…</div>
    <div class=tiers id=tiers>${TIERS.map((t,n)=>`<button class=tier data-t="${t}"><span class=k>${n+1}</span>${t}</button>`).join('')}</div>
    <label>how you know them (optional, kept verbatim)</label>
    <textarea id=how rows=2 placeholder="e.g. worked together at… / school friend / met at…"></textarea>
    <div class=row>
      <label>shared LinkedIn groups (semicolon-separated; you read these off the profile):</label>
    </div>
    <div class=row><input id=groups placeholder="Group A; Group B"><button class=ghost onclick=saveGroups()>save groups</button><button class=ghost onclick=saveGroups(true)>none</button></div>
    <div class=row>
      <button class=ghost onclick="go(-1)">‹ prev</button>
      <button class=ghost onclick="go(1)">skip / next ›</button>
      <span class=prog id=msg></span>
    </div>`;
  document.querySelectorAll('.tier').forEach(b=>b.onclick=()=>setTier(b.dataset.t));
  const D=await (await fetch('/api/detail?name='+encodeURIComponent(c.name))).json();
  let ctx='';
  if(D.thread){ctx+=`<div class=ctx><b>thread</b> ${esc(D.thread.when||'')}\\n${esc(D.thread.body||'')}</div>`;}
  else ctx+='<div class=meta>no message thread on file (a close tie can still have none — judge from who they are)</div>';
  if(D.groups===null)ctx+='<div class=meta>mutual groups: NOT CHECKED — open the profile and read the Highlights card</div>';
  else if(D.groups.length===0)ctx+='<div class=meta>mutual groups: checked, none</div>';
  else ctx+=`<div class=ctx><b>shared groups</b>: ${D.groups.map(esc).join('; ')}</div>`;
  if(D.how_known)ctx+=`<div class=meta>recorded how-known: ${esc(D.how_known)}</div>`;
  document.getElementById('ctx').innerHTML=ctx;
  if(D.groups && D.groups.length){document.getElementById('groups').value=D.groups.join('; ');}
}
function esc(s){return (s==null?'':''+s).replace(/[&<>"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));}
async function setTier(t){
  const how=document.getElementById('how').value;
  const r=await fetch('/api/closeness',{method:'POST',headers:{'content-type':'application/json'},
    body:JSON.stringify({name:cur.name,tier:t,how:how})});
  const d=await r.json();
  if(d.ok){ // reflect locally + advance
    const c=ALL.find(x=>x.name===cur.name); if(c){c.tier=t;c.stated=true;c.unlevelled=false;}
    go(1);
  } else {document.getElementById('msg').textContent='⚠ '+(d.msg||'not recorded');}
}
async function saveGroups(none){
  const raw=document.getElementById('groups').value;
  const groups = none? 'NONE' : raw.split(';').map(s=>s.trim()).filter(Boolean);
  const r=await fetch('/api/groups',{method:'POST',headers:{'content-type':'application/json'},
    body:JSON.stringify({name:cur.name,groups:groups})});
  const d=await r.json();
  document.getElementById('msg').textContent = d.ok? '✓ groups saved' : ('⚠ '+(d.msg||'error'));
  const c=ALL.find(x=>x.name===cur.name); if(c)c.group_state = (none||groups.length===0)?'none':'yes';
}
function go(n){const v=view(); i=Math.min(Math.max(0,i+n),Math.max(0,v.length-1)); render();}
document.addEventListener('keydown',e=>{
  if(e.target.tagName==='TEXTAREA'||e.target.tagName==='INPUT')return;
  if(e.key>='1'&&e.key<='8'){const t=TIERS[+e.key-1]; if(t)setTier(t);}
  if(e.key==='n'||e.key==='ArrowRight')go(1);
  if(e.key==='p'||e.key==='ArrowLeft')go(-1);
});
document.getElementById('filter').onchange=()=>{i=0;render();};
document.getElementById('company').oninput=()=>{i=0;render();};
boot();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass  # quiet

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        u = urlparse(self.path)
        if u.path == "/":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if u.path == "/api/list":
            return self._send(200, json.dumps({"contacts": _list_contacts(),
                                               "tiers": list(level_contacts.STATED_TIERS)}))
        if u.path == "/api/detail":
            name = (parse_qs(u.query).get("name") or [""])[0]
            return self._send(200, json.dumps(_detail(name)))
        return self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 1_000_000:            # a review POST is tiny; cap the read so a bogus length can't
                return self._send(413, json.dumps({"ok": False, "msg": "too large"}))
            data = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send(400, json.dumps({"ok": False, "msg": "bad request"}))
        if self.path == "/api/closeness":
            ok, msg = _record_closeness(data.get("name", ""), data.get("tier", ""),
                                        (data.get("how") or "").strip())
            return self._send(200, json.dumps({"ok": ok, "msg": msg}))
        if self.path == "/api/groups":
            ok, msg = _record_groups(data.get("name", ""), data.get("groups"))
            return self._send(200, json.dumps({"ok": ok, "msg": msg}))
        return self._send(404, json.dumps({"ok": False, "msg": "not found"}))


def main():
    ap = argparse.ArgumentParser(description="localhost contact-review tool (closeness + mutual groups)")
    ap.add_argument("--port", type=int, default=0, help="0 = an OS-chosen ephemeral port")
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args()
    srv = HTTPServer(("127.0.0.1", a.port), Handler)   # 127.0.0.1 ONLY — never externally reachable
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"contact review: {url}   (Ctrl-C to stop)")
    if not a.no_open:
        try:
            import webbrowser
            threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()
        except Exception:
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

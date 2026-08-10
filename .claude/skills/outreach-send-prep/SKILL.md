---
name: outreach-send-prep
description: "RETIRED. The send path is scripts/mail-draft.sh, which lints, dedups, logs the send and attaches the resume. This skill's mailto route bypasses all four and is kept only as a documented last resort for an install where mail-draft.sh cannot run. Do not load it to prepare a normal send; run mail-draft.sh."
---

# Skill: Outreach Send-Prep (review package)

> # ⛔ RETIRED, 2026-08-09
> **The send path is `scripts/mail-draft.sh`.** It lints the body with `check_outreach.py`, runs the
> dedup check, requires the rung's evidence, writes `documents/send-log.jsonl`, and attaches the
> résumé. The `mailto:` route in this file does **none** of those, so a message sent that way has
> passed no gate.
>
> ⚖️ Retired at the request of the partner running it, who is on the gated path: *"I would rather not
> have an ungated send route sitting next to the gated one."* Kept on disk, not deleted, for an
> install where `mail-draft.sh` genuinely cannot run (it drives Apple Mail through AppleScript, so a
> client on another platform has no equivalent). If that is you, section 1 lists the checks you must
> run BY HAND to replace what the script does for you.

**When:** an entry in `documents/outreach-queue.md` is finalized (boss verified, copy approved) and you want it ready to send.

**Goal:** produce the two review-ready artifacts you inspect before sending, every time, the same way. You are the human gate: **the pipeline never sends, connects, submits, or auto-opens-and-types. It prepares.**

---

## The method (do exactly this)

### 1. Email draft: `scripts/mail-draft.sh` IS THE PATH

⛔ **`mail-draft.sh` is the only send path that passes the gates.** It lints the body with
`check_outreach.py`, runs the dedup check, requires the rung's evidence, writes the row to
`documents/send-log.jsonl`, and attaches the résumé. It builds a **visible draft and never sends**;
you review and press Send.

```
scripts/mail-draft.sh --to "first@company.com" --subject "..." --body-file draft.txt \
    --rung cold-boss --company "Acme" --boss "Jane Roe" --attach "Resume - Acme.pdf"
```

⚠️ **A message that skips it has passed NO gate**, and the cost is not theoretical: the send log is
the source of truth for your reply rate, your daily 3-3-3 count, the segment hot zone, and the guard
that stops one company being named in two different warm asks. A send missing from that log makes
all four read wrong, silently.

#### The `mailto:` route is RETIRED, and is a documented last resort only

It is kept here for an install where `mail-draft.sh` cannot run at all (it drives Apple Mail through
AppleScript, so a client on another platform has no equivalent). ⛔ **It bypasses the lint, the dedup, the send
log, and the résumé attachment**, so if you have no other option you MUST do by hand what
the script does for you:

1. `python3 scripts/check_outreach.py <body-file>` and fix what it flags, BEFORE sending.
2. `python3 scripts/check_dup.py "<Company>" "<Boss>"` and proceed only on 🟢 NEW.
3. `python3 scripts/log_linkedin_send.py` (or hand-write the row) so the send reaches the log.

Only then fire the prefilled draft:
- Fire a `mailto:` from a **real browser tab** with `location.href`; the OS hands off to your default mail client and opens a **prefilled compose window** (To, Subject, Body).
- Build the URL with `encodeURIComponent` on subject and body so emoji, accents, and line breaks survive.
- To change the copy, **re-fire the mailto** with the new body; discard any stale window.
- **NEVER** use desktop/keyboard control to type or edit inside the compose window. **NEVER** click Send. If the address is a guess, note it; you verify and send.

Reference snippet:
```js
const to='first@company.com', subject='...', body=`Hi, First!\n...`;
location.href = `mailto:${to}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
```
(If the active tab is a browser-internal page, navigate to any real page first, then fire.)

### 2. Tailored résumé — build it and hand it over as a file
- Clone your newest résumé template; tailor the summary and skills to the role's angle. Keep the honesty-vetted experience content.
- Apply **your honesty guardrails** (see `documents/PROFILE.md`): only claims you can defend; no unverifiable figures; consistent employer/product naming; no over-claiming. No em dashes; no spaces around slashes if that's your style rule.
- Compile, verify page count and that a text-extraction shows your email + phone as literal text with no glyph errors, then export to your naming convention: **`<Your Name> - Resume - <Company>.pdf`**.
- **Surface it as a file** for your inspection. Do **not** open apps on your screen for "inspection."
- **Attaching it.** `mail-draft.sh --attach` does this for you and is the reason it is the path. NEVER desktop-control the compose window. If you are on the retired mailto route, a `mailto:` cannot carry a file, so:
  - **(a) A mail connector that supports attachments — preferred when you have one.** If your email provider has an MCP connector that can add a file to a draft, use it: the assistant attaches the tailored PDF to the draft directly, no computer control. **If you use Outlook, this is your path: connect the Outlook / Microsoft 365 connector** and the assistant can build the draft *with the résumé already attached* (you can also keep a standard résumé handy to auto-attach when a tailored one isn't needed). You still review and send yourself — the connector prepares the draft, it never sends.
  - **(b) You self-attach — the universal fallback.** The assistant fires the prefilled `mailto:` draft and hands you the tailored PDF as a file card; you drag it into the compose window and send. Use this when your provider has no connector or its connector can't attach files (e.g. a `mailto:`-only or self-hosted setup).
  - **Which to default to:** if you have an attachment-capable connector (Outlook/M365, etc.), prefer (a). Otherwise default to (b). Either way, the résumé is a real file and **you are the sender.**

### 3. Leave the gate to you
- Keep the queue entry **STATUS: NEW**. You review both artifacts, edit if needed, **attach the résumé, and send yourself.**
- When you confirm it's sent, mark **SENT** with the date and move the entry to the archive (queue hygiene).

### 4. Commit everything to durable storage after EVERY outreach (send AND drop)
Nothing important stays only in the chat. Immediately after each outreach, write to the repo: (1) `outreach_log.md` with your EXACT sent copy + delivery/bounce status (or the DROP reason); (2) a `job_search_tracker.csv` row; (3) move the queue entry to `documents/outreach-queue-archive.md`; (4) any voice edits → `documents/writing-style-guide.md`; (5) any new rule/lesson → your workflow/handoff docs. Then report the new NEW-count.

---

## Do / Don't
**Do:** use `scripts/mail-draft.sh`; build + present the résumé as a file; keep yourself the sender.
**Don't:** reach for the retired `mailto:` route while `mail-draft.sh` works; type into or click inside the compose window with desktop control; auto-send, auto-connect or auto-submit; invent an unverified email without flagging it.

### Email delivery hedge — To + 2 Bcc variants
Maximize deliverability: **To** = the single most-likely address (`firstname@domain`); **Bcc** = at least 2 format variants (`first-initial+lastname@domain`, `firstname.lastname@domain`). The prefilled `mailto:` carries a `bcc=` parameter with both. The recipient never sees Bcc; bounce-backs on the Bcc variants confirm the correct address format. Record the exact To + Bcc used in your outreach log.

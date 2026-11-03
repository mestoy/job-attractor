#!/usr/bin/env python3
"""mac_time_sampler.py — passive, once-a-minute record of which pipeline phase the Mac is in.

WHY. The owner ruled 2026-09-10: "We can't rely on manual logging from me or future users."
Every hour the pipeline measures has to come from what already happens. This script runs
under launchd on the Mac, once a minute, and writes ONE line: timestamp, frontmost app name,
the hostname of the active Safari or Chrome tab, and the phase those map to
(scripts/phase_map.py). It never stores a URL path, a page title, or page text, and it
writes nothing at all when the Mac has been idle for more than IDLE_SECONDS.

WHERE IT WRITES. Outside the repo, so raw samples never enter git or a backup:
    ~/Library/Application Support/jobkit/mac-time-<YYYY-MM-DD>.jsonl
mac_time_rollup.py reads those files and writes one summary line per day into the repo.

PERMISSIONS. macOS asks once for Automation access (System Events, Safari, Google Chrome)
on the first run. No Screen Recording is needed. If a prompt is declined, the sample is
written with the field blank rather than crashing the agent.

Usage (on the Mac):
    python3 scripts/mac_time_sampler.py              # take one sample now
    python3 scripts/mac_time_sampler.py --install    # write the launchd agent and start it
    python3 scripts/mac_time_sampler.py --uninstall  # stop it and remove the agent
    python3 scripts/mac_time_sampler.py --status     # is the agent loaded, where is today's file
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from phase_map import phase_for  # noqa: E402

LABEL = "com.jobkit.mactime"
ROLLUP_LABEL = "com.jobkit.mactime.rollup"
ROLLUP_HOUR, ROLLUP_MINUTE = 23, 55   # one summary line per day, written into the repo
INTERVAL = 60
IDLE_SECONDS = 300
DATA_DIR = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "jobkit")
PLIST = os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents", LABEL + ".plist")
ROLLUP_PLIST = os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents", ROLLUP_LABEL + ".plist")


def _osascript(script, timeout=5):
    try:
        out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def idle_seconds():
    """Seconds since the last keyboard or mouse event, from IOKit; 0 if unreadable."""
    try:
        out = subprocess.run(["ioreg", "-c", "IOHIDSystem"], capture_output=True, text=True, timeout=5).stdout
        for line in out.splitlines():
            if "HIDIdleTime" in line:
                return int(line.split("=")[-1].strip()) / 1_000_000_000
    except Exception:
        pass
    return 0


def frontmost_app():
    return _osascript('tell application "System Events" to get name of first application process whose frontmost is true')


def active_host(app):
    url = ""
    if app == "Safari":
        url = _osascript('tell application "Safari" to get URL of current tab of front window')
    elif app in ("Google Chrome", "Chrome"):
        url = _osascript('tell application "Google Chrome" to get URL of active tab of front window')
    if not url:
        return ""
    try:
        return (urlsplit(url).hostname or "").lower()
    except Exception:
        return ""


def sample(now=None):
    """Return the sample row for this minute, or None if the Mac is idle."""
    if idle_seconds() > IDLE_SECONDS:
        return None
    app = frontmost_app()
    host = active_host(app)
    now = now or datetime.datetime.now().astimezone()
    return {"ts": now.isoformat(timespec="seconds"), "app": app, "host": host, "phase": phase_for(app, host)}


def day_file(now=None, data_dir=DATA_DIR):
    now = now or datetime.datetime.now().astimezone()
    return os.path.join(data_dir, f"mac-time-{now.date().isoformat()}.jsonl")


def write_sample(row, data_dir=DATA_DIR):
    os.makedirs(data_dir, exist_ok=True)
    with open(day_file(data_dir=data_dir), "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def plist_text(python=sys.executable, script=os.path.abspath(__file__)):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{python}</string>
    <string>{script}</string>
  </array>
  <key>StartInterval</key><integer>{INTERVAL}</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>/tmp/jobkit-mactime.out</string>
  <key>StandardErrorPath</key><string>/tmp/jobkit-mactime.err</string>
</dict>
</plist>
"""


def rollup_plist_text(python=sys.executable, repo=None):
    repo = repo or os.path.dirname(HERE)
    script = os.path.join(HERE, "mac_time_rollup.py")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{ROLLUP_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{python}</string>
    <string>{script}</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>CLAUDE_PROJECT_DIR</key><string>{repo}</string></dict>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>{ROLLUP_HOUR}</integer><key>Minute</key><integer>{ROLLUP_MINUTE}</integer></dict>
  <key>StandardOutPath</key><string>/tmp/jobkit-mactime-rollup.out</string>
  <key>StandardErrorPath</key><string>/tmp/jobkit-mactime-rollup.err</string>
</dict>
</plist>
"""


def _bootstrap(label, plist, text):
    with open(plist, "w", encoding="utf-8") as f:
        f.write(text)
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"], capture_output=True)
    r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", plist], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"launchctl bootstrap failed for {label}:", r.stderr.strip() or r.stdout.strip())
        return False
    return True


def install(repo=None):
    """The sampler once a minute, and the rollup once a night into the repo the kit lives in."""
    os.makedirs(os.path.dirname(PLIST), exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    if not _bootstrap(LABEL, PLIST, plist_text()):
        return 1
    print(f"installed {LABEL}: one sample a minute into {DATA_DIR}")
    repo = repo or os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
    if _bootstrap(ROLLUP_LABEL, ROLLUP_PLIST, rollup_plist_text(repo=repo)):
        print(f"installed {ROLLUP_LABEL}: one summary line at {ROLLUP_HOUR:02d}:{ROLLUP_MINUTE:02d} into {repo}/documents/state/mac-time-summary.jsonl")
    print("macOS will ask once for Automation access to System Events, Safari and Google Chrome. Allow all three.")
    return 0


def uninstall():
    uid = os.getuid()
    for label, plist in ((LABEL, PLIST), (ROLLUP_LABEL, ROLLUP_PLIST)):
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"], capture_output=True)
        if os.path.exists(plist):
            os.remove(plist)
    print(f"removed {LABEL}; samples in {DATA_DIR} are kept, delete them yourself if you want them gone")
    return 0


def status():
    uid = os.getuid()
    r = subprocess.run(["launchctl", "print", f"gui/{uid}/{LABEL}"], capture_output=True, text=True)
    loaded = r.returncode == 0
    f = day_file()
    n = sum(1 for _ in open(f, encoding="utf-8")) if os.path.exists(f) else 0
    print(f"agent {'loaded' if loaded else 'not loaded'}; today's file {f} has {n} samples")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--repo", default=None, help="repo the nightly rollup writes into (default: the kit's parent dir or CLAUDE_PROJECT_DIR)")
    a = ap.parse_args(argv)
    if a.install:
        return install(repo=a.repo)
    if a.uninstall:
        return uninstall()
    if a.status:
        return status()
    row = sample()
    if row is not None:
        write_sample(row)
    return 0


if __name__ == "__main__":
    sys.exit(main())

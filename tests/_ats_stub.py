#!/usr/bin/env python3
"""A stand-in for scripts/check_ats.py that never touches the network. It answers by the fake company name, with check_ats.py's own exit codes:
0 a live in-lane role, 1 no live role (radar), 2 no board or an ambiguous one."""
import sys

import os
import time

time.sleep(float(os.environ.get("JA_ATS_DELAY", "0") or 0))
name = " ".join(sys.argv[1:]).upper()
if "LIVE" in name:
    print("  ✅ greenhouse board 'fake' — 9 open roles total")
    print("     ▸ Fake Product Manager | Remote, US")
    print("  VERDICT: \U0001f535 LIVE IN-LANE ROLE(S)")
    sys.exit(0)
if "RADAR" in name:
    print("  (no in-lane role on this board)")
    print("  VERDICT: \U0001f7e1 NO live in-lane role -> RADAR")
    sys.exit(1)
if "SLOW" in name:
    import time
    time.sleep(30)
if "AMBIG" in name:
    print("  \U0001f534 AMBIGUOUS: 2 different ATS boards match this name. NOT verifying.")
    sys.exit(2)
print("  No ATS board found for these tokens (custom/other ATS, or wrong token).")
sys.exit(2)

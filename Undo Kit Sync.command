#!/bin/bash
# ============================================================
#  Undo Kit Sync — double-click to reverse the LAST "Sync Kit".
#  If you have not committed anything since that sync, this
#  returns your clone to the exact state from before (your own
#  commits are all kept). If you HAVE committed since, it leaves
#  your history alone and just restores the files the sync
#  replaced, from the backup. Either way, nothing is destroyed.
# ============================================================
cd "$(dirname "$0")" || {
  echo "Could not find the kit folder."
  read -n1 -s -p "Press any key to close."; echo; exit 1;
}

if ! command -v python3 >/dev/null 2>&1; then
  echo "⚠  python3 was not found, so the kit tools can't run."
  echo "   Install Python 3 (https://www.python.org/downloads/), then try again."
  echo ""; read -n1 -s -p "Press any key to close."; echo; exit 1
fi

echo ""
python3 scripts/kit_vendor_sync.py --repo . --undo
_rc=$?
echo ""
if [ "$_rc" -ne 0 ]; then
  echo "ℹ  Nothing of yours was destroyed. If the undo didn't finish, send the message above"
  echo "   to the kit maintainer."
fi
echo ""
read -n1 -s -p "Press any key to close."
echo
exit "$_rc"

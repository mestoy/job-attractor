#!/bin/bash
# ============================================================
#  Sync Kit — double-click to update the kit's files SAFELY.
#  Use this only if the normal "Update Kit" stopped with a
#  message about your own commits, or your clone's history no
#  longer matches the published kit. It never runs pull / reset
#  / merge, so it can NEVER delete a commit of yours, and it
#  can be undone with "Undo Kit Sync".
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
echo "Sync Kit — updates the kit's files one at a time. It never deletes your work, and"
echo "you can undo it. Use this when the normal \"Update Kit\" stopped over your own commits."
echo ""
python3 scripts/kit_vendor_sync.py --repo .
_rc=$?
echo ""
if [ "$_rc" -eq 2 ]; then
  echo "ℹ  The sync stopped before finishing (see the message above). Nothing of yours was destroyed."
  echo "   Send this to the kit maintainer if it repeats."
elif [ "$_rc" -ne 0 ]; then
  echo "ℹ  Nothing of yours was changed. If this keeps happening, send the message above"
  echo "   to the kit maintainer."
fi
echo ""
read -n1 -s -p "Press any key to close."
echo
exit "$_rc"

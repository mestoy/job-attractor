#!/usr/bin/env bash
# Run the kit's regression suite. Standard library only, no install step, no network.
#   bash tests/run_all.sh
# Exit 0 = green. Run it after editing anything under scripts/, and before trusting a gate again.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
python3 -m unittest discover -s tests -p 'test_*.py' -v

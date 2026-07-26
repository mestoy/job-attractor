#!/bin/bash
# Job Attractor — Review Console launcher (macOS). Double-click to build & open.
# Rebuilds the console from your live queue, then opens it in your browser.
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
python3 "app/build_review_console.py" --open

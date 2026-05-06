#!/bin/bash
# get-sapphire-page.sh — Headless render of a Sapphire web UI page.
#
# Usage: tools/get-sapphire-page.sh <route> [width] [height]
#   route   alias (chat|store|settings|dashboard|mind|prompts|toolsets|
#           spices|schedule|help|apps|plugins) OR raw "#fragment" OR any
#           other view id (gets a leading '#' added).
#   width   viewport width in px  (default 1440)
#   height  viewport height in px (default 900)
#
# Outputs (printed to stdout, in this order):
#   /tmp/sapphire-page-<route>.png   viewport screenshot, post-JS render
#   /tmp/sapphire-page-<route>.html  rendered DOM
#
# Auth: SAPPHIRE_PASSWORD env (defaults to 'changeme'), same flow as
# ask-sapphire.sh — login form CSRF + session cookie, then transplanted
# into a Playwright chromium context.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${SAPPHIRE_PYTHON:-$HOME/miniconda3/envs/sapphire/bin/python}"
if [ ! -x "$PYTHON" ]; then
    PYTHON="$(command -v python)"
fi

exec "$PYTHON" "$SCRIPT_DIR/_get_sapphire_page.py" "$@"

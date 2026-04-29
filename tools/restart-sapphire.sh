#!/bin/bash
# restart-sapphire.sh — Restart Sapphire via systemd (user service)
# Usage: tools/restart-sapphire.sh [--status]
set -euo pipefail

if [ "${1:-}" = "--status" ]; then
    systemctl --user status sapphire 2>&1 | head -20
    exit 0
fi

# Check for running agents before restarting
AGENTS=$(curl -sk -b /tmp/sapphire-claude-cookies.txt "https://localhost:8073/api/agents/status?chat=default" 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    running = [a for a in d.get('agents', []) if a.get('status') == 'running']
    if running:
        print(f'WARNING: {len(running)} agent(s) running: {[a[\"name\"] for a in running]}')
except: pass
" 2>/dev/null)

if [ -n "$AGENTS" ]; then
    echo "$AGENTS"
    if [ "${1:-}" != "--force" ]; then
        echo "Use --force to restart anyway, or wait for agents to finish."
        exit 1
    fi
    echo "Forcing restart..."
fi

echo "Restarting Sapphire..."
systemctl --user restart sapphire
sleep 3
STATUS=$(systemctl --user is-active sapphire 2>&1)
echo "Status: $STATUS"

if [ "$STATUS" = "active" ]; then
    echo "Sapphire is running."
else
    echo "WARNING: Sapphire may not have started. Check logs:"
    echo "  journalctl --user -u sapphire -n 20"
fi

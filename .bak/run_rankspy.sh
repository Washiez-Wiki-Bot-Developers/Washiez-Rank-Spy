#!/bin/bash
cd /root/CascadeProjects/WashiezWikiBotDevelopers/Washiez-Rank-Spy/
source venv/bin/activate
export PYTHONUNBUFFERED=1

trap 'echo "$(date --iso-8601=seconds) SIGTERM/SIGINT received, exiting"; exit' SIGTERM SIGINT

while true; do
    echo "$(date --iso-8601=seconds) Starting app.py"
    python -u app.py
    rc=$?
    echo "$(date --iso-8601=seconds) app.py exited with code $rc"

    if [ "$rc" -ne 0 ]; then
        echo "$(date --iso-8601=seconds) Non‑zero exit ($rc). Stopping loop."
        break
    fi

    echo "$(date --iso-8601=seconds) Clean exit (0). Restarting in 5s..."
    sleep 5
done

echo "$(date --iso-8601=seconds) Supervisor script exiting."

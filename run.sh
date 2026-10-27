#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

PID_FILE="$DIR/.rotator.pid"
LOG_FILE="$DIR/rotator.log"

case "$1" in
    start|--daemon|-d)
        if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
            echo "[WARN] Rotator is already running in background (PID $(cat "$PID_FILE"))."
            exit 0
        fi
        echo "[INFO] Starting Antigravity Rotator in background..."
        if command -v launchctl >/dev/null 2>&1; then
            launchctl setenv CLOUD_CODE_URL "http://127.0.0.1:8888" 2>/dev/null || true
        fi
        nohup python3 rotator.py > /dev/null 2>&1 &
        echo $! > "$PID_FILE"
        sleep 1
        if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
            echo "[OK] Rotator started in background (PID $(cat "$PID_FILE"))."
            echo "     Logs: $LOG_FILE"
            echo "     You can safely close this terminal window now."
        else
            echo "[ERROR] Rotator failed to start. Check $LOG_FILE for details."
            rm -f "$PID_FILE"
            exit 1
        fi
        ;;
    stop)
        if command -v launchctl >/dev/null 2>&1; then
            launchctl unsetenv CLOUD_CODE_URL 2>/dev/null || true
        fi

        if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
            PID="$(cat "$PID_FILE")"
            echo "[INFO] Stopping background Rotator (PID $PID)..."
            kill "$PID" 2>/dev/null || true
            rm -f "$PID_FILE"
            sleep 1
        fi

        if lsof -i :8888 -sTCP:LISTEN 2>/dev/null | grep -q LISTEN; then
            PORT_PID=$(lsof -ti :8888 -sTCP:LISTEN | head -n 1)
            echo "[INFO] Terminating process on port 8888 (PID $PORT_PID)..."
            kill "$PORT_PID" 2>/dev/null || true
            sleep 1
        fi

        python3 account_manager.py unconfigure-ide
        echo "[OK] Rotator stopped and Antigravity unlinked."
        ;;
    restart)
        "$0" stop
        sleep 1
        "$0" start
        ;;
    status)
        echo "================================================================================"
        echo "                           ROTATOR STATUS CHECK                                 "
        echo "================================================================================"
        if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
            echo "[PROCESS] Rotator daemon: RUNNING (PID $(cat "$PID_FILE"))"
        elif lsof -i :8888 -sTCP:LISTEN 2>/dev/null | grep -q LISTEN; then
            ACTIVE_PID=$(lsof -ti :8888 -sTCP:LISTEN | head -n 1)
            echo "[PROCESS] Rotator process: RUNNING on port 8888 (PID $ACTIVE_PID)"
        else
            echo "[PROCESS] Rotator process: STOPPED (not listening on port 8888)"
        fi

        if command -v launchctl >/dev/null 2>&1 && [ -n "$(launchctl getenv CLOUD_CODE_URL 2>/dev/null)" ]; then
            echo "[ENV] CLOUD_CODE_URL: $(launchctl getenv CLOUD_CODE_URL 2>/dev/null) (active for Antigravity desktop & CLI)"
        fi

        python3 -c "
import json
from config import IDE_SETTINGS_FILE
if IDE_SETTINGS_FILE.exists():
    try:
        s = json.loads(IDE_SETTINGS_FILE.read_text())
        val = s.get('jetski.cloudCodeUrl')
        if val:
            print(f'[IDE SETTINGS] Linked to proxy: {val}')
        else:
            print('[IDE SETTINGS] Direct connection to Google Cloud Code (default)')
    except Exception:
        print('[IDE SETTINGS] Could not parse settings.json')
else:
    print('[IDE SETTINGS] settings.json not found')
"
        echo ""
        python3 account_manager.py list
        ;;
    logs)
        if [ -f "$LOG_FILE" ]; then
            tail -f "$LOG_FILE"
        else
            echo "[INFO] No log file found yet ($LOG_FILE)."
        fi
        ;;
    *)
        echo "[INFO] Starting Rotator in foreground mode (Ctrl+C to stop)..."
        echo "[TIP] To run in the background and close this terminal, use: ./run.sh start"
        if command -v launchctl >/dev/null 2>&1; then
            launchctl setenv CLOUD_CODE_URL "http://127.0.0.1:8888" 2>/dev/null || true
        fi
        python3 rotator.py
        ;;
esac

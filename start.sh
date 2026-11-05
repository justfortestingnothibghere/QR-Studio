#!/usr/bin/env bash
# QR Studio launcher.   sudo ./start.sh            install (first time) and start 24/7
#                       sudo ./start.sh stop|restart|status|logs|uninstall
#                       ./start.sh dev             run in the foreground for testing
# Uses systemd when available (auto-start on boot, auto-restart on crash). Without systemd it falls back to a
# supervised background process and tells you the @reboot cron line to add.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE="qrstudio"
RUN_USER="${QS_USER:-qrstudio}"
VENV="$ROOT/.venv"
CFG="$ROOT/backend/config.json"
PIDFILE="$ROOT/.qrstudio.pid"
LOGFILE="$ROOT/qrstudio.log"
CMD="${1:-start}"

say()  { printf '\033[1;36m[qrstudio]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[qrstudio]\033[0m %s\n' "$*" >&2; exit 1; }
have_systemd() { command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; }
need_root() { [ "$(id -u)" -eq 0 ] || fail "Run with sudo:  sudo ./start.sh $CMD"; }
cfg_get() { python3 - "$CFG" "$1" "$2" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
for k in sys.argv[2].split("."):
    d = d.get(k, {}) if isinstance(d, dict) else {}
print(d if d != {} else sys.argv[3])
PY
}

py_bin() { if [ "${QS_NO_VENV:-0}" = "1" ]; then command -v python3; else echo "$VENV/bin/python"; fi; }

setup_python() {
  command -v python3 >/dev/null 2>&1 || fail "python3 is not installed. On Debian/Ubuntu: apt install python3 python3-venv python3-pip"
  if [ "${QS_NO_VENV:-0}" != "1" ]; then
    if [ ! -x "$VENV/bin/python" ]; then
      say "Creating virtualenv"
      python3 -m venv "$VENV" || fail "venv failed. On Debian/Ubuntu: apt install python3-venv"
    fi
    if [ "${QS_SKIP_PIP:-0}" != "1" ]; then
      say "Installing dependencies (first run takes a minute)"
      "$VENV/bin/pip" install --quiet --upgrade pip
      "$VENV/bin/pip" install --quiet -r "$ROOT/requirements.txt"
    fi
  fi
}

setup_data() {
  mkdir -p "$ROOT/backend/data"
  if [ ! -f "$ROOT/backend/assets/themes/crimson-surge.json" ]; then
    say "Generating built-in themes (about 2 minutes, once)"
    (cd "$ROOT/backend" && "$(py_bin)" scripts/gen_themes.py)
  fi
}

fix_perms() {
  [ "$(id -u)" -eq 0 ] || return 0
  if ! id "$RUN_USER" >/dev/null 2>&1; then
    say "Creating service user '$RUN_USER'"
    useradd --system --home "$ROOT" --shell /usr/sbin/nologin "$RUN_USER" 2>/dev/null || adduser --system --no-create-home "$RUN_USER" >/dev/null
  fi
  chown -R "$RUN_USER" "$ROOT/backend/data" "$ROOT/backend/config.json"
  chmod 600 "$ROOT/backend/config.json"
  [ -f "$LOGFILE" ] || : > "$LOGFILE"; chown "$RUN_USER" "$LOGFILE"
}

write_unit() {
  local host port
  host="$(cfg_get server.host 0.0.0.0)"; port="$(cfg_get server.port 8000)"
  cat > "/etc/systemd/system/$SERVICE.service" <<EOF
[Unit]
Description=QR Studio by TeamDev
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$ROOT/backend
ExecStart=$(py_bin) -m uvicorn app.main:app --host $host --port $port --workers 2 --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=always
RestartSec=3
LimitNOFILE=65536
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=read-only
ReadWritePaths=$ROOT/backend/data $ROOT/backend/config.json $LOGFILE

[Install]
WantedBy=multi-user.target
EOF
}

# ---- fallback supervisor (no systemd) ----
fb_running() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }
fb_start() {
  fb_running && { say "Already running (pid $(cat "$PIDFILE"))"; return; }
  local host port py; host="$(cfg_get server.host 0.0.0.0)"; port="$(cfg_get server.port 8000)"; py="$(py_bin)"
  cd "$ROOT/backend"
  setsid nohup bash -c "while true; do $py -m uvicorn app.main:app --host $host --port $port --workers 2 --proxy-headers >>'$LOGFILE' 2>&1; echo \"[supervisor] crashed, restarting in 3s\" >>'$LOGFILE'; sleep 3; done" >/dev/null 2>&1 &
  echo $! > "$PIDFILE"
  say "Started in background (pid $(cat "$PIDFILE")). Logs: $LOGFILE"
  say "To survive reboots add this line to 'crontab -e':  @reboot cd $ROOT && ./start.sh"
}
fb_stop() {
  if fb_running; then
    local p; p="$(cat "$PIDFILE")"
    # the supervisor was started with setsid, so it leads its own process group: kill the whole group
    # (supervisor loop + uvicorn master + its workers), otherwise workers keep the port busy
    kill -TERM -- "-$p" 2>/dev/null || { pkill -P "$p" 2>/dev/null || true; kill "$p" 2>/dev/null || true; }
    sleep 1; kill -KILL -- "-$p" 2>/dev/null || true
    rm -f "$PIDFILE"; say "Stopped"
  else say "Not running"; fi
}

wait_health() {
  local port; port="$(cfg_get server.port 8000)"
  for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:$port/api/health" >/dev/null 2>&1; then say "Healthy on port $port"; return 0; fi
    sleep 1
  done
  say "Not healthy yet. Check logs:  ./start.sh logs"; return 1
}

case "$CMD" in
  start)
    setup_python; setup_data
    if have_systemd && [ "$(id -u)" -eq 0 ]; then
      fix_perms; write_unit
      systemctl daemon-reload; systemctl enable "$SERVICE" >/dev/null 2>&1; systemctl restart "$SERVICE"
      say "Service installed: starts on boot and restarts if it crashes"
    else
      [ "$(id -u)" -eq 0 ] || say "Not root, so no systemd service. Running as a supervised background process."
      fb_start
    fi
    wait_health || true
    say "Open: $(cfg_get server.public_url http://localhost:8000)"
    say "First steps: edit backend/config.json (payments.upi_id, admin.emails, server.public_url) then: sudo ./start.sh restart"
    ;;
  dev)
    setup_python; setup_data
    cd "$ROOT/backend"; exec "$(py_bin)" -m uvicorn app.main:app --host "$(cfg_get server.host 127.0.0.1)" --port "$(cfg_get server.port 8000)" --reload
    ;;
  stop)
    if have_systemd && [ -f "/etc/systemd/system/$SERVICE.service" ]; then need_root; systemctl stop "$SERVICE"; say "Stopped"; else fb_stop; fi ;;
  restart)
    if have_systemd && [ -f "/etc/systemd/system/$SERVICE.service" ]; then need_root; systemctl restart "$SERVICE"; wait_health || true; else fb_stop; fb_start; wait_health || true; fi ;;
  status)
    if have_systemd && [ -f "/etc/systemd/system/$SERVICE.service" ]; then systemctl --no-pager status "$SERVICE" || true; else fb_running && say "Running (pid $(cat "$PIDFILE"))" || say "Not running"; fi
    wait_health || true ;;
  logs)
    if have_systemd && [ -f "/etc/systemd/system/$SERVICE.service" ]; then journalctl -u "$SERVICE" -n 100 -f; else tail -n 100 -f "$LOGFILE"; fi ;;
  uninstall)
    need_root
    if have_systemd; then systemctl disable --now "$SERVICE" 2>/dev/null || true; rm -f "/etc/systemd/system/$SERVICE.service"; systemctl daemon-reload; fi
    fb_stop; say "Service removed. Your data in backend/data is untouched." ;;
  *) echo "Usage: sudo ./start.sh [start|stop|restart|status|logs|uninstall] | ./start.sh dev"; exit 1 ;;
esac

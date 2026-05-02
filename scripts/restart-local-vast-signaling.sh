#!/usr/bin/env bash
set -euo pipefail

# Use this mode when signaling runs on the Vast server and your laptop forwards:
# ssh -N -L 4001:127.0.0.1:4001 -p <VAST_SSH_PORT> root@<VAST_IP>
#
# Browser signaling URL -> ws://localhost:4001/ws (forwarded to Vast)
# Worker signaling URL  -> ws://127.0.0.1:4001/ws (local on Vast)

ROOT="/f/ai-creator-studio"
if [ ! -d "$ROOT" ]; then
  echo "Repo not found at $ROOT"
  exit 1
fi

SESSION_TOKEN_SECRET="${SESSION_TOKEN_SECRET:-dev-secret}"
SIGNALING_URL_BROWSER="${SIGNALING_URL_BROWSER:-ws://localhost:4001/ws}"
SIGNALING_URL_WORKER="${SIGNALING_URL_WORKER:-ws://127.0.0.1:4001/ws}"
OBS_BASE_URL="${OBS_BASE_URL:-http://localhost:3000}"
DEFAULT_WORKER_ENDPOINT="${DEFAULT_WORKER_ENDPOINT:-http://188.36.196.221:5807}"
DEFAULT_WORKER_ID="${DEFAULT_WORKER_ID:-worker-1}"
DEFAULT_WORKER_GPU="${DEFAULT_WORKER_GPU:-RTX_4090}"

echo "Using config:"
echo "  SIGNALING_URL_BROWSER=$SIGNALING_URL_BROWSER"
echo "  SIGNALING_URL_WORKER=$SIGNALING_URL_WORKER"
echo "  OBS_BASE_URL=$OBS_BASE_URL"
echo "  DEFAULT_WORKER_ENDPOINT=$DEFAULT_WORKER_ENDPOINT"
echo "  DEFAULT_WORKER_ID=$DEFAULT_WORKER_ID"
echo "  DEFAULT_WORKER_GPU=$DEFAULT_WORKER_GPU"

echo "[1/3] Kill anything on 4000/4001..."
powershell.exe -NoProfile -Command "
\$ports=@(4000,4001);
foreach(\$p in \$ports){
  \$conns=Get-NetTCPConnection -LocalPort \$p -State Listen -ErrorAction SilentlyContinue;
  if(\$conns){
    \$ids = \$conns | Select-Object -ExpandProperty OwningProcess -Unique;
    foreach(\$id in \$ids){
      Stop-Process -Id \$id -Force -ErrorAction SilentlyContinue;
      Write-Output ('killed pid ' + \$id + ' on ' + \$p);
    }
  }
}
"

echo "[2/3] Start gateway only (no local signaling)..."
powershell.exe -NoProfile -Command "
\$env:SIGNALING_URL='${SIGNALING_URL_WORKER}';
\$env:SIGNALING_URL_BROWSER='${SIGNALING_URL_BROWSER}';
\$env:SIGNALING_URL_WORKER='${SIGNALING_URL_WORKER}';
\$env:SESSION_TOKEN_SECRET='${SESSION_TOKEN_SECRET}';
\$env:OBS_BASE_URL='${OBS_BASE_URL}';
\$env:DEFAULT_WORKER_ENDPOINT='${DEFAULT_WORKER_ENDPOINT}';
\$env:DEFAULT_WORKER_ID='${DEFAULT_WORKER_ID}';
\$env:DEFAULT_WORKER_GPU='${DEFAULT_WORKER_GPU}';
\$proc = Start-Process cmd.exe -ArgumentList '/c','cd /d F:\\ai-creator-studio && npm --prefix apps/gateway run dev > tmp-gateway-local.log 2>&1' -WindowStyle Hidden -PassThru;
Write-Output ('gateway launcher pid=' + \$proc.Id);
"

echo "[3/3] Verify listeners..."
sleep 3
powershell.exe -NoProfile -Command "
\$g=Get-NetTCPConnection -LocalPort 4000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1;
\$s=Get-NetTCPConnection -LocalPort 4001 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1;
'4000=' + [bool]\$g;
'4001=' + [bool]\$s;
if (\$g) { 'gateway pid=' + \$g.OwningProcess }
if (\$s) { 'local-4001 pid=' + \$s.OwningProcess + ' (should be SSH tunnel process when you start ssh -L)' }
"

echo "[logs] tail gateway"
powershell.exe -NoProfile -Command "
if (Test-Path 'F:\\ai-creator-studio\\tmp-gateway-local.log') { Get-Content 'F:\\ai-creator-studio\\tmp-gateway-local.log' -Tail 20 }
"
echo "Done."

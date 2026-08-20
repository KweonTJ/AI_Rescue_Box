#!/usr/bin/env bash
set -euo pipefail
ACTION="${1:-plan}"
CONNECTION="${AI_RESCUE_HOTSPOT_CONNECTION:-AI-Rescue-Box}"
SSID="${AI_RESCUE_HOTSPOT_SSID:-AI-Rescue-Box}"
PASSWORD="${AI_RESCUE_HOTSPOT_PASSWORD:-}"
INTERFACE="${AI_RESCUE_HOTSPOT_INTERFACE:-}"
ADDRESS="${AI_RESCUE_HOTSPOT_ADDRESS:-192.168.50.1/24}"

find_interface() {
  if [[ -n "$INTERFACE" ]]; then printf '%s' "$INTERFACE"; return; fi
  nmcli -t -f DEVICE,TYPE device status | awk -F: '$2=="wifi" {print $1; exit}'
}

case "$ACTION" in
  plan)
    cat <<EOF
No network change was made.
Connection: $CONNECTION
SSID:       $SSID
Interface:  ${INTERFACE:-<auto at explicit up>}
Gateway:    $ADDRESS
Password:   $(if [[ -n "$PASSWORD" ]]; then echo '<configured>'; else echo '<not configured>'; fi)
Tablet URL: http://${ADDRESS%/*}:8001
EOF
    ;;
  status)
    command -v nmcli >/dev/null 2>&1 || { echo "nmcli is unavailable"; exit 1; }
    nmcli connection show "$CONNECTION" 2>/dev/null || { echo "$CONNECTION is not configured"; exit 0; }
    ;;
  up)
    command -v nmcli >/dev/null 2>&1 || { echo "nmcli is unavailable" >&2; exit 1; }
    (( ${#PASSWORD} >= 8 )) || { echo "Set AI_RESCUE_HOTSPOT_PASSWORD (minimum 8 characters)." >&2; exit 2; }
    iface="$(find_interface)"
    [[ -n "$iface" ]] || { echo "No Wi-Fi interface found; set AI_RESCUE_HOTSPOT_INTERFACE." >&2; exit 2; }
    if nmcli connection show "$CONNECTION" >/dev/null 2>&1; then nmcli connection delete "$CONNECTION" >/dev/null; fi
    nmcli connection add type wifi ifname "$iface" con-name "$CONNECTION" autoconnect no ssid "$SSID"
    nmcli connection modify "$CONNECTION" 802-11-wireless.mode ap 802-11-wireless.band bg ipv4.method shared ipv4.addresses "$ADDRESS" ipv6.method disabled
    nmcli connection modify "$CONNECTION" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PASSWORD"
    nmcli connection up "$CONNECTION"
    echo "Hotspot active. This action must be performed and verified in Stage 5B."
    ;;
  down)
    command -v nmcli >/dev/null 2>&1 || { echo "nmcli is unavailable" >&2; exit 1; }
    nmcli connection down "$CONNECTION" 2>/dev/null || true
    echo "Hotspot stopped."
    ;;
  *) echo "usage: $0 [plan|status|up|down]" >&2; exit 2 ;;
esac

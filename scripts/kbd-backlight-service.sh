#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
daemon_source="${script_dir}/kbd-backlight-daemon.sh"
daemon_target="/usr/local/libexec/kbd-backlight-service-daemon"
service_name="kbd-backlight-service.service"
service_path="/etc/systemd/system/${service_name}"
state_dir="/var/lib/kbd-backlight-service"

usage() {
    printf '%s\n' "Usage: $0 install | uninstall | status" >&2
}

die() {
    printf '%s\n' "$1" >&2
    exit 1
}

require_root() {
    [[ "$(id -u)" -eq 0 ]] || die "This script must run as root."
}

require_systemctl() {
    command -v systemctl >/dev/null 2>&1 || die "systemctl is missing."
}

require_install_tools() {
    command -v gdbus >/dev/null 2>&1 || die "gdbus is missing."
    command -v install >/dev/null 2>&1 || die "install is missing."
    command -v id >/dev/null 2>&1 || die "id is missing."
    command -v loginctl >/dev/null 2>&1 || die "loginctl is missing."
    command -v mktemp >/dev/null 2>&1 || die "mktemp is missing."
    command -v setpriv >/dev/null 2>&1 || die "setpriv is missing."
    [[ -f "${daemon_source}" ]] || die "Daemon source is missing: ${daemon_source}"
}

require_supported_hardware() {
    compgen -G '/sys/class/leds/*kbd_backlight*' >/dev/null || die "No keyboard backlight devices matched /sys/class/leds/*kbd_backlight*."
}

install_daemon() {
    install -D -m755 "${daemon_source}" "${daemon_target}"
    install -d -m755 "${state_dir}"
}

install_service() {
    local tmp
    tmp="$(mktemp)"
    cat >"${tmp}" <<EOF
[Unit]
Description=Keyboard backlight idle and lock service
After=systemd-logind.service
Wants=systemd-logind.service
ConditionPathExists=/sys/class/leds

[Service]
Type=simple
Environment=SEAT=auto
Environment=TIMEOUT_MS=6000
Environment=BOOT_LEVEL=1
Environment=POLL_INTERVAL=0.25
Environment=STATE_DIR=${state_dir}
ExecStart=${daemon_target}
Restart=always
RestartSec=1

[Install]
WantedBy=graphical.target
EOF
    install -D -m644 "${tmp}" "${service_path}"
    rm -f "${tmp}"
}

do_install() {
    install_daemon
    install_service
    systemctl daemon-reload
    systemctl enable "${service_name}"
    systemctl restart "${service_name}"
    systemctl --no-pager --full status "${service_name}"
}

do_uninstall() {
    systemctl disable --now "${service_name}" 2>/dev/null || true
    rm -f "${service_path}" "${daemon_target}"
    systemctl daemon-reload
}

do_status() {
    systemctl --no-pager --full status "${service_name}"
}

main() {
    local command="${1:-}"

    [[ -n "${command}" ]] || {
        usage
        exit 1
    }

    [[ "$#" -eq 1 ]] || {
        usage
        exit 1
    }

    case "${command}" in
        install)
            require_root
            require_systemctl
            require_install_tools
            require_supported_hardware
            do_install
            ;;
        uninstall)
            require_root
            require_systemctl
            do_uninstall
            ;;
        status)
            require_systemctl
            do_status
            ;;
        *)
            usage
            exit 1
            ;;
    esac
}

main "$@"

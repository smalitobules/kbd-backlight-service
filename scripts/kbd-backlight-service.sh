#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
daemon_source="${script_dir}/kbd-backlight-daemon.sh"
daemon_target="/usr/local/libexec/kbd-backlight-service-daemon"
service_name="kbd-backlight-service.service"
service_path="/etc/systemd/system/${service_name}"
state_dir="/var/lib/kbd-backlight-service"
device_glob="${DEVICE_GLOB:-/sys/class/leds/asus::kbd_backlight}"

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

require_configuration() {
    [[ "${state_dir}" == "/var/lib/kbd-backlight-service" ]] || die "STATE_DIR must be /var/lib/kbd-backlight-service."
    [[ ! -L "${state_dir}" ]] || die "STATE_DIR must not be a symlink."
    [[ "${device_glob}" == /sys/class/leds/* ]] || die "DEVICE_GLOB must point inside /sys/class/leds."
    [[ "${device_glob}" =~ ^/sys/class/leds/[[:alnum:]_:.*/+-]+$ ]] || die "DEVICE_GLOB contains unsupported characters."
    [[ "${device_glob}" != *..* ]] || die "DEVICE_GLOB must not contain '..'."
    [[ ! "${device_glob}" =~ [[:space:]] ]] || die "DEVICE_GLOB must not contain whitespace."
}

require_install_tools() {
    command -v gdbus >/dev/null 2>&1 || die "gdbus is missing."
    command -v install >/dev/null 2>&1 || die "install is missing."
    command -v id >/dev/null 2>&1 || die "id is missing."
    command -v loginctl >/dev/null 2>&1 || die "loginctl is missing."
    command -v mktemp >/dev/null 2>&1 || die "mktemp is missing."
    command -v setpriv >/dev/null 2>&1 || die "setpriv is missing."
    command -v date >/dev/null 2>&1 || die "date is missing."
    command -v sleep >/dev/null 2>&1 || die "sleep is missing."
    command -v chmod >/dev/null 2>&1 || die "chmod is missing."
    [[ -f "${daemon_source}" ]] || die "Daemon source is missing: ${daemon_source}"
}

require_supported_hardware() {
    local candidate=""

    while IFS= read -r candidate; do
        [[ -d "${candidate}" ]] || continue
        [[ -r "${candidate}/brightness" ]] || continue
        [[ -r "${candidate}/max_brightness" ]] || continue
        return 0
    done < <(compgen -G "${device_glob}")

    die "No usable keyboard backlight devices matched ${device_glob}."
}

install_daemon() {
    install -D -m755 "${daemon_source}" "${daemon_target}"
    install -d -m700 "${state_dir}"
    chmod 700 "${state_dir}"
}

install_service() {
    local tmp
    tmp="$(mktemp)"
    trap 'rm -f "${tmp}"' RETURN
    cat >"${tmp}" <<EOF
[Unit]
Description=ASUS keyboard backlight idle and lock service
After=systemd-logind.service
Wants=systemd-logind.service
ConditionPathExists=/sys/class/leds

[Service]
Type=simple
Environment=SEAT=auto
Environment=TIMEOUT_MS=6000
Environment=BOOT_LEVEL=1
Environment=POLL_INTERVAL=1
Environment=STATE_DIR=${state_dir}
Environment=DEVICE_GLOB=${device_glob}
ExecStart=${daemon_target}
Restart=always
RestartSec=1
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ProtectClock=yes
ProtectControlGroups=yes
ProtectHostname=yes
ProtectKernelLogs=yes
ProtectKernelModules=yes
ProtectSystem=strict
ReadWritePaths=/sys/class/leds ${state_dir}
ReadOnlyPaths=/run/user
RestrictAddressFamilies=AF_UNIX
RestrictNamespaces=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
LockPersonality=yes
SystemCallArchitectures=native
CapabilityBoundingSet=CAP_SETUID CAP_SETGID
UMask=0077

[Install]
WantedBy=graphical.target
EOF
    install -D -m644 "${tmp}" "${service_path}"
    trap - RETURN
    rm -f "${tmp}"
}

do_install() {
    require_configuration
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
            require_configuration
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

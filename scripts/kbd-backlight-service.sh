#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
daemon_source="${script_dir}/kbd_backlight_daemon.py"
core_source="${script_dir}/kbd_backlight_core.py"
daemon_target="/usr/local/libexec/kbd-backlight-service-daemon"
core_target="/usr/local/libexec/kbd_backlight_core.py"
service_name="kbd-backlight-service.service"
service_path="/etc/systemd/system/${service_name}"
state_dir="/var/lib/kbd-backlight-service"
dependency_state_file="${state_dir}/runtime-packages.installed"
device_glob="${DEVICE_GLOB:-/sys/class/leds/asus::kbd_backlight}"

usage() {
    printf '%s\n' "Usage: $0 install | disable | revert | uninstall | status" >&2
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
    command -v python3 >/dev/null 2>&1 || die "python3 is missing."
    command -v apt-get >/dev/null 2>&1 || die "apt-get is missing."
    command -v dpkg-query >/dev/null 2>&1 || die "dpkg-query is missing."
    command -v install >/dev/null 2>&1 || die "install is missing."
    command -v id >/dev/null 2>&1 || die "id is missing."
    command -v mktemp >/dev/null 2>&1 || die "mktemp is missing."
    command -v chmod >/dev/null 2>&1 || die "chmod is missing."
    [[ -f "${daemon_source}" ]] || die "Daemon source is missing: ${daemon_source}"
    [[ -f "${core_source}" ]] || die "Core source is missing: ${core_source}"
}

python_module_available() {
    local module="$1"

    python3 -c "import ${module}" >/dev/null 2>&1
}

package_installed() {
    local package="$1"
    local status=""

    require_package_name "${package}"
    status="$(dpkg-query -W -f='${Status}' "${package}" 2>/dev/null || true)"
    [[ "${status}" == "install ok installed" ]]
}

require_package_name() {
    local package="$1"

    [[ "${package}" =~ ^[a-z0-9][a-z0-9+.-]+$ ]] || die "Unsupported package name: ${package}"
}

prepare_dependency_state() {
    install -d -m700 "${state_dir}"
    chmod 700 "${state_dir}"
    [[ ! -L "${dependency_state_file}" ]] || die "Dependency state file must not be a symlink: ${dependency_state_file}"
    if [[ ! -e "${dependency_state_file}" ]]; then
        : >"${dependency_state_file}"
    fi
    chmod 600 "${dependency_state_file}"
}

package_tracked() {
    local package="$1"
    local tracked_package=""

    require_package_name "${package}"
    [[ -r "${dependency_state_file}" ]] || return 1
    while IFS= read -r tracked_package; do
        [[ "${tracked_package}" == "${package}" ]] && return 0
    done <"${dependency_state_file}"
    return 1
}

track_package() {
    local package="$1"

    require_package_name "${package}"
    prepare_dependency_state
    package_tracked "${package}" && return 0
    printf '%s\n' "${package}" >>"${dependency_state_file}"
    chmod 600 "${dependency_state_file}"
}

apt_install_package() {
    local package="$1"

    require_package_name "${package}"
    if ! DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${package}"; then
        DEBIAN_FRONTEND=noninteractive apt-get update
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${package}"
    fi
}

ensure_python_module() {
    local module="$1"
    local package="$2"
    local was_installed=0

    require_package_name "${package}"
    python_module_available "${module}" && return 0

    if package_installed "${package}"; then
        was_installed=1
    fi

    apt_install_package "${package}"
    python_module_available "${module}" || die "Python module ${module} is still missing after installing ${package}."

    if (( was_installed == 0 )); then
        track_package "${package}"
    fi
}

ensure_runtime_dependencies() {
    ensure_python_module "dbus_next" "python3-dbus-next"
    ensure_python_module "asyncinotify" "python3-asyncinotify"
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
    install -D -m644 "${core_source}" "${core_target}"
    install -d -m700 "${state_dir}"
    chmod 700 "${state_dir}"
}

install_service() {
    local tmp
    tmp="$(mktemp)"
    trap 'rm -f "${tmp}"' RETURN
    cat >"${tmp}" <<EOF
[Unit]
Description=ASUS keyboard backlight service
After=systemd-logind.service
Wants=systemd-logind.service
ConditionPathExists=/sys/class/leds

[Service]
Type=simple
Environment=SEAT=auto
Environment=TIMEOUT_MS=6000
Environment=BOOT_LEVEL=1
Environment=POLL_INTERVAL=10
Environment=STATE_DIR=${state_dir}
Environment=DEVICE_GLOB=${device_glob}
ExecStart=${daemon_target}
Restart=always
RestartSec=1
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=read-only
ProtectClock=yes
ProtectControlGroups=yes
ProtectHostname=yes
ProtectKernelLogs=yes
ProtectKernelModules=yes
ProtectSystem=strict
ReadWritePaths=/sys/class/leds ${state_dir}
ReadOnlyPaths=/run/user /run/dbus
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
    rm -f "${service_path}" "${daemon_target}" "${core_target}"
    systemctl daemon-reload
    remove_tracked_runtime_dependencies
}

do_disable() {
    systemctl disable --now "${service_name}" 2>/dev/null || true
}

do_revert() {
    do_uninstall
}

do_status() {
    systemctl --no-pager --full status "${service_name}"
}

read_tracked_packages() {
    local package=""

    [[ -r "${dependency_state_file}" ]] || return 0
    while IFS= read -r package; do
        [[ -n "${package}" ]] || continue
        require_package_name "${package}"
        printf '%s\n' "${package}"
    done <"${dependency_state_file}"
}

package_removal_is_scoped() {
    local package="$1"
    local action=""
    local removal=""
    local removed_package=""

    require_package_name "${package}"
    while IFS=' ' read -r action removal _; do
        [[ "${action}" == "Remv" ]] || continue
        require_package_name "${removal}"
        if [[ "${removal}" != "${package}" ]] && ! package_tracked "${removal}"; then
            printf '%s\n' "Refusing to remove ${package}; apt would also remove ${removal}." >&2
            return 1
        fi
        removed_package="${removal}"
    done < <(LC_ALL=C apt-get -s remove "${package}")

    [[ -n "${removed_package}" ]]
}

remove_tracked_runtime_dependencies() {
    local package=""
    local kept_packages=()

    [[ -e "${dependency_state_file}" ]] || return 0
    prepare_dependency_state

    while IFS= read -r package; do
        [[ -n "${package}" ]] || continue
        if ! package_installed "${package}"; then
            continue
        fi
        if package_removal_is_scoped "${package}"; then
            DEBIAN_FRONTEND=noninteractive apt-get remove -y "${package}"
        else
            kept_packages+=("${package}")
        fi
    done < <(read_tracked_packages)

    : >"${dependency_state_file}"
    for package in ${kept_packages[@]+"${kept_packages[@]}"}; do
        printf '%s\n' "${package}" >>"${dependency_state_file}"
    done
    chmod 600 "${dependency_state_file}"
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
            ensure_runtime_dependencies
            do_install
            ;;
        disable)
            require_root
            require_systemctl
            do_disable
            ;;
        revert)
            require_root
            require_systemctl
            do_revert
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

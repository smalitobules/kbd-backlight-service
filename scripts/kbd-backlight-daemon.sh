#!/usr/bin/env bash
set -euo pipefail

seat="${SEAT:-auto}"
timeout_ms="${TIMEOUT_MS:-6000}"
boot_level="${BOOT_LEVEL:-1}"
poll_interval="${POLL_INTERVAL:-1}"
state_dir="${STATE_DIR:-/var/lib/kbd-backlight-service}"
device_glob="${DEVICE_GLOB:-/sys/class/leds/asus::kbd_backlight}"

declare -a devices=()
declare -A boot_levels=()
declare -A desired_levels=()
declare -A dimmed_flags=()
declare -A last_nonzero_levels=()
declare -A managed_levels=()
declare -A manual_off_flags=()
declare -A pending_login_levels=()
declare -A seen_levels=()
declare -A manual_activity_until_ms=()

last_session_uid=""
last_allow_manual_off=-1
active_seat=""
resume_uid=""

require_tools() {
    command -v gdbus >/dev/null 2>&1 || {
        printf '%s\n' "gdbus is missing." >&2
        exit 1
    }
    command -v id >/dev/null 2>&1 || {
        printf '%s\n' "id is missing." >&2
        exit 1
    }
    command -v loginctl >/dev/null 2>&1 || {
        printf '%s\n' "loginctl is missing." >&2
        exit 1
    }
    command -v install >/dev/null 2>&1 || {
        printf '%s\n' "install is missing." >&2
        exit 1
    }
    command -v setpriv >/dev/null 2>&1 || {
        printf '%s\n' "setpriv is missing." >&2
        exit 1
    }
    command -v sleep >/dev/null 2>&1 || {
        printf '%s\n' "sleep is missing." >&2
        exit 1
    }
    command -v date >/dev/null 2>&1 || {
        printf '%s\n' "date is missing." >&2
        exit 1
    }
    command -v chmod >/dev/null 2>&1 || {
        printf '%s\n' "chmod is missing." >&2
        exit 1
    }
}

die() {
    printf '%s\n' "$1" >&2
    exit 1
}

require_positive_integer() {
    local name="$1"
    local value="$2"

    [[ "${value}" =~ ^[0-9]+$ ]] || die "${name} must be a positive integer."
    (( value > 0 )) || die "${name} must be greater than 0."
}

require_poll_interval() {
    [[ "${poll_interval}" =~ ^[0-9]+([.][0-9]+)?$ ]] || die "POLL_INTERVAL must be a positive number."
    [[ ! "${poll_interval}" =~ ^0+([.]0+)?$ ]] || die "POLL_INTERVAL must be greater than 0."
}

require_configuration() {
    require_positive_integer "TIMEOUT_MS" "${timeout_ms}"
    require_positive_integer "BOOT_LEVEL" "${boot_level}"
    require_poll_interval
    [[ "${state_dir}" == "/var/lib/kbd-backlight-service" ]] || die "STATE_DIR must be /var/lib/kbd-backlight-service."
    [[ ! -L "${state_dir}" ]] || die "STATE_DIR must not be a symlink."
    [[ "${device_glob}" == /sys/class/leds/* ]] || die "DEVICE_GLOB must point inside /sys/class/leds."
    [[ "${device_glob}" =~ ^/sys/class/leds/[[:alnum:]_:.*/+-]+$ ]] || die "DEVICE_GLOB contains unsupported characters."
    [[ "${device_glob}" != *..* ]] || die "DEVICE_GLOB must not contain '..'."
    [[ ! "${device_glob}" =~ [[:space:]] ]] || die "DEVICE_GLOB must not contain whitespace."
}

read_value() {
    local path="$1"
    local fallback="$2"
    local value=""

    if [[ -r "${path}" ]]; then
        value="$(<"${path}")"
    fi

    if [[ "${value}" =~ ^[0-9]+$ ]]; then
        printf '%s\n' "${value}"
    else
        printf '%s\n' "${fallback}"
    fi
}

now_ms() {
    date +%s%3N
}

state_key() {
    local uid="$1"
    local device="$2"

    printf '%s|%s\n' "${uid}" "${device}"
}

manual_deadline_for_uid() {
    local uid="$1"

    printf '%s\n' "${manual_activity_until_ms["${uid}"]:-0}"
}

session_bus_path_for_uid() {
    local uid="$1"

    printf '/run/user/%s/bus\n' "${uid}"
}

state_file_for_device() {
    local device="$1"
    local name="${device##*/}"

    name="${name//[^[:alnum:]._-]/_}"
    printf '%s/%s.level\n' "${state_dir}" "${name}"
}

clamp_boot_level() {
    local requested="$1"

    if [[ ! "${requested}" =~ ^[0-9]+$ ]]; then
        requested="${boot_level}"
    fi

    if (( requested < 1 )); then
        requested=1
    fi

    printf '%s\n' "${requested}"
}

refresh_devices() {
    local candidate=""

    devices=()
    while IFS= read -r candidate; do
        [[ -d "${candidate}" ]] || continue
        [[ -r "${candidate}/brightness" ]] || continue
        [[ -r "${candidate}/max_brightness" ]] || continue
        devices+=("${candidate}")
    done < <(compgen -G "${device_glob}")
}

require_devices() {
    refresh_devices
    [[ "${#devices[@]}" -gt 0 ]] || {
        printf '%s\n' "No keyboard backlight devices matched ${device_glob}." >&2
        exit 1
    }
}

load_boot_levels() {
    local device=""
    local file=""
    local value=""

    install -d -m700 "${state_dir}"
    chmod 700 "${state_dir}"

    for device in "${devices[@]}"; do
        file="$(state_file_for_device "${device}")"
        value=""
        if [[ -r "${file}" ]]; then
            [[ ! -L "${file}" ]] || die "State file must not be a symlink: ${file}"
            chmod 600 "${file}"
            value="$(<"${file}")"
        fi
        boot_levels["${device}"]="$(clamp_boot_level "${value:-${boot_level}}")"
    done
}

save_boot_level() {
    local device="$1"
    local requested="$2"
    local normalized=""
    local file=""

    normalized="$(clamp_boot_level "${requested}")"
    if [[ "${boot_levels["${device}"]:-}" == "${normalized}" ]]; then
        return 0
    fi

    install -d -m700 "${state_dir}"
    chmod 700 "${state_dir}"
    file="$(state_file_for_device "${device}")"
    [[ ! -L "${file}" ]] || die "State file must not be a symlink: ${file}"
    printf '%s\n' "${normalized}" >"${file}"
    chmod 600 "${file}"
    boot_levels["${device}"]="${normalized}"
}

remember_visible_level() {
    local uid="$1"
    local device="$2"
    local current="$3"
    local key=""

    (( current > 0 )) || return 0

    key="$(state_key "${uid}" "${device}")"
    desired_levels["${key}"]="${current}"
    last_nonzero_levels["${device}"]="${current}"
}

target_level_for_uid() {
    local uid="$1"
    local device="$2"
    local key=""
    local target=""

    key="$(state_key "${uid}" "${device}")"
    target="${desired_levels["${key}"]:-${last_nonzero_levels["${device}"]:-${boot_levels["${device}"]:-${boot_level}}}}"
    printf '%s\n' "${target}"
}

write_level() {
    local uid="$1"
    local device="$2"
    local requested="$3"
    local max_level
    local current_level
    local actual_level
    local key=""

    max_level="$(read_value "${device}/max_brightness" 1)"
    current_level="$(read_value "${device}/brightness" 0)"
    if [[ -n "${uid}" ]]; then
        key="$(state_key "${uid}" "${device}")"
    fi

    if (( requested > max_level )); then
        requested="${max_level}"
    fi

    if (( requested < 0 )); then
        requested=0
    fi

    if [[ -n "${uid}" ]] && set_user_gnome_brightness "${uid}" "${requested}" "${max_level}"; then
        actual_level="$(read_value "${device}/brightness" 0)"
        if (( actual_level == requested )); then
            if [[ -n "${key}" ]]; then
                managed_levels["${key}"]="${actual_level}"
            fi
            return 0
        fi
        current_level="${actual_level}"
    fi

    if (( current_level != requested )); then
        if echo "${requested}" >"${device}/brightness"; then
            if [[ -n "${key}" ]]; then
                managed_levels["${key}"]="${requested}"
            fi
        else
            printf '%s\n' "Failed to write brightness ${requested} to ${device}." >&2
        fi
    elif [[ -n "${key}" ]]; then
        managed_levels["${key}"]="${requested}"
    fi

    if [[ -n "${uid}" ]]; then
        set_user_gnome_brightness "${uid}" "${requested}" "${max_level}" >/dev/null 2>&1 || true
    fi
}

force_level_all() {
    local requested="$1"
    local device=""

    for device in "${devices[@]}"; do
        write_level "" "${device}" "${requested}"
    done
}

restore_boot_level() {
    refresh_devices
    if [[ "${#devices[@]}" -gt 0 ]]; then
        force_boot_levels
    fi
}

force_boot_levels() {
    local device=""
    local target=""

    for device in "${devices[@]}"; do
        target="${boot_levels["${device}"]:-${boot_level}}"
        write_level "" "${device}" "${target}"
    done
}

resolved_seat() {
    local configured_seat="${seat}"
    local seat_name=""
    local active_sid=""

    if [[ -n "${configured_seat}" ]] && [[ "${configured_seat}" != "auto" ]]; then
        printf '%s\n' "${configured_seat}"
        return 0
    fi

    if [[ -n "${active_seat}" ]]; then
        active_sid="$(loginctl show-seat "${active_seat}" -p ActiveSession --value 2>/dev/null || true)"
        if [[ -n "${active_sid}" ]]; then
            printf '%s\n' "${active_seat}"
            return 0
        fi
    fi

    while read -r seat_name _; do
        [[ -n "${seat_name}" ]] || continue
        active_sid="$(loginctl show-seat "${seat_name}" -p ActiveSession --value 2>/dev/null || true)"
        if [[ -n "${active_sid}" ]]; then
            active_seat="${seat_name}"
            printf '%s\n' "${seat_name}"
            return 0
        fi
    done < <(loginctl list-seats --no-legend 2>/dev/null || true)

    while read -r _ _ _ seat_name _; do
        if [[ -n "${seat_name}" ]] && [[ "${seat_name}" != "-" ]]; then
            active_seat="${seat_name}"
            printf '%s\n' "${seat_name}"
            return 0
        fi
    done < <(loginctl list-sessions --no-legend 2>/dev/null || true)

    return 1
}

active_session_id() {
    local current_seat=""

    current_seat="$(resolved_seat || true)"
    [[ -n "${current_seat}" ]] || return 0
    loginctl show-seat "${current_seat}" -p ActiveSession --value 2>/dev/null || true
}

session_properties() {
    local sid="$1"

    loginctl show-session "${sid}" -p User -p Class -p LockedHint --value 2>/dev/null || true
}

user_gdbus_call() {
    local uid="$1"
    local bus_path=""
    local gid=""

    shift
    [[ -n "${uid}" ]] || return 1
    bus_path="$(session_bus_path_for_uid "${uid}")"
    [[ -S "${bus_path}" ]] || return 1
    gid="$(id -g "${uid}" 2>/dev/null || true)"
    [[ -n "${gid}" ]] || return 1

    setpriv \
        --reuid "${uid}" \
        --regid "${gid}" \
        --clear-groups \
        env \
        XDG_RUNTIME_DIR="/run/user/${uid}" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=${bus_path}" \
        gdbus call \
        --session \
        "$@"
}

idle_ms_for_uid() {
    local uid="$1"
    local output=""

    output="$(
        user_gdbus_call \
            "${uid}" \
            --dest org.gnome.Mutter.IdleMonitor \
            --object-path /org/gnome/Mutter/IdleMonitor/Core \
            --method org.gnome.Mutter.IdleMonitor.GetIdletime \
            2>/dev/null || true
    )"

    [[ "${output}" =~ uint64[[:space:]]+([0-9]+) ]] || return 1
    printf '%s\n' "${BASH_REMATCH[1]}"
}

set_user_gnome_brightness() {
    local uid="$1"
    local level="$2"
    local max_level="$3"
    local percent=0

    if (( max_level > 0 )); then
        percent=$(( (level * 100) / max_level ))
    fi

    if (( percent < 0 )); then
        percent=0
    elif (( percent > 100 )); then
        percent=100
    fi

    user_gdbus_call \
        "${uid}" \
        --dest org.gnome.SettingsDaemon.Power \
        --object-path /org/gnome/SettingsDaemon/Power \
        --method org.freedesktop.DBus.Properties.Set \
        org.gnome.SettingsDaemon.Power.Keyboard \
        Brightness \
        "<int32 ${percent}>" \
        >/dev/null 2>&1
}

activate_uid() {
    local uid="$1"
    local allow_manual_off="$2"
    local device=""
    local key=""
    local current_level=""
    local target_level=""

    for device in "${devices[@]}"; do
        key="$(state_key "${uid}" "${device}")"
        if (( allow_manual_off == 1 )) && [[ -n "${pending_login_levels["${device}"]:-}" ]]; then
            desired_levels["${key}"]="${pending_login_levels["${device}"]}"
            last_nonzero_levels["${device}"]="${pending_login_levels["${device}"]}"
            save_boot_level "${device}" "${pending_login_levels["${device}"]}"
            unset 'pending_login_levels["'"${device}"'"]'
        fi
        current_level="$(read_value "${device}/brightness" 0)"
        target_level="$(target_level_for_uid "${uid}" "${device}")"

        if (( allow_manual_off == 1 )); then
            if [[ "${manual_off_flags["${key}"]:-0}" == "1" ]]; then
                write_level "${uid}" "${device}" 0
            else
                write_level "${uid}" "${device}" "${target_level}"
            fi
        fi

        current_level="$(read_value "${device}/brightness" 0)"
        seen_levels["${key}"]="${current_level}"
        if (( current_level > 0 )); then
            remember_visible_level "${uid}" "${device}" "${current_level}"
        fi
        dimmed_flags["${key}"]=0
    done
}

observe_session_state() {
    local uid="$1"
    local timestamp_ms="$2"
    local allow_manual_off="$3"
    local capture_login_level="$4"
    local device=""
    local current_level=""
    local previous_level=""
    local managed_level=""
    local max_level=""
    local key=""

    for device in "${devices[@]}"; do
        key="$(state_key "${uid}" "${device}")"
        current_level="$(read_value "${device}/brightness" 0)"
        previous_level="${seen_levels["${key}"]:-}"
        managed_level="${managed_levels["${key}"]:-__unset__}"

        if [[ -n "${previous_level}" ]] && [[ "${current_level}" != "${previous_level}" ]] && [[ "${current_level}" != "${managed_level}" ]]; then
            manual_activity_until_ms["${uid}"]=$(( timestamp_ms + timeout_ms ))
            if (( capture_login_level == 1 )) && (( current_level > 0 )); then
                pending_login_levels["${device}"]="${current_level}"
                if [[ -n "${resume_uid}" ]]; then
                    desired_levels["$(state_key "${resume_uid}" "${device}")"]="${current_level}"
                    last_nonzero_levels["${device}"]="${current_level}"
                    save_boot_level "${device}" "${current_level}"
                    max_level="$(read_value "${device}/max_brightness" 1)"
                    set_user_gnome_brightness "${resume_uid}" "${current_level}" "${max_level}" >/dev/null 2>&1 || true
                fi
            fi
        fi

        seen_levels["${key}"]="${current_level}"

        if (( current_level > 0 )); then
            remember_visible_level "${uid}" "${device}" "${current_level}"
            dimmed_flags["${key}"]=0
            if (( allow_manual_off == 1 )); then
                manual_off_flags["${key}"]=0
            fi
        elif (( allow_manual_off == 1 )) && [[ "${dimmed_flags["${key}"]:-0}" != "1" ]]; then
            manual_off_flags["${key}"]=1
        fi
    done
}

dim_for_idle() {
    local uid="$1"
    local device=""
    local current_level=""
    local key=""

    for device in "${devices[@]}"; do
        key="$(state_key "${uid}" "${device}")"
        current_level="$(read_value "${device}/brightness" 0)"
        if [[ "${manual_off_flags["${key}"]:-0}" == "1" ]]; then
            dimmed_flags["${key}"]=0
            continue
        fi
        if (( current_level > 0 )); then
            remember_visible_level "${uid}" "${device}" "${current_level}"
            write_level "${uid}" "${device}" 0
            dimmed_flags["${key}"]=1
        fi
    done
}

restore_for_activity() {
    local uid="$1"
    local allow_manual_off="$2"
    local device=""
    local current_level=""
    local target_level=""
    local key=""

    for device in "${devices[@]}"; do
        key="$(state_key "${uid}" "${device}")"
        current_level="$(read_value "${device}/brightness" 0)"
        target_level="$(target_level_for_uid "${uid}" "${device}")"

        if [[ "${dimmed_flags["${key}"]:-0}" == "1" ]]; then
            if (( current_level > 0 )); then
                remember_visible_level "${uid}" "${device}" "${current_level}"
            else
                write_level "${uid}" "${device}" "${target_level}"
            fi
            dimmed_flags["${key}"]=0
            if (( allow_manual_off == 1 )); then
                manual_off_flags["${key}"]=0
            fi
            continue
        fi

        if (( current_level > 0 )); then
            remember_visible_level "${uid}" "${device}" "${current_level}"
            if (( allow_manual_off == 1 )); then
                manual_off_flags["${key}"]=0
            fi
        elif (( allow_manual_off == 1 )); then
            manual_off_flags["${key}"]=1
        else
            write_level "${uid}" "${device}" "${target_level}"
        fi
    done
}

update_boot_levels_for_uid() {
    local uid="$1"
    local device=""
    local current_level=""
    local candidate=""
    local key=""

    for device in "${devices[@]}"; do
        key="$(state_key "${uid}" "${device}")"
        current_level="$(read_value "${device}/brightness" 0)"

        if (( current_level > 0 )); then
            candidate="${current_level}"
        elif [[ "${manual_off_flags["${key}"]:-0}" == "1" ]]; then
            candidate="1"
        else
            candidate="$(target_level_for_uid "${uid}" "${device}")"
        fi

        save_boot_level "${device}" "${candidate}"
    done
}

main() {
    local sid=""
    local session_class=""
    local locked_hint=""
    local uid=""
    local idle_ms=""
    local current_time_ms=0
    local manual_deadline_ms=0
    local allow_manual_off=0
    local capture_login_level=0
    local -a session_values=()

    require_tools
    require_configuration
    require_devices
    load_boot_levels
    trap restore_boot_level EXIT

    while :; do
        refresh_devices

        if [[ "${#devices[@]}" -eq 0 ]]; then
            sleep "${poll_interval}"
            continue
        fi

        sid="$(active_session_id)"
        if [[ -z "${sid}" ]]; then
            force_boot_levels
            last_session_uid=""
            last_allow_manual_off=-1
            sleep "${poll_interval}"
            continue
        fi

        mapfile -t session_values < <(session_properties "${sid}")
        uid="${session_values[0]:-}"
        if [[ -z "${uid}" ]]; then
            force_boot_levels
            last_session_uid=""
            last_allow_manual_off=-1
            sleep "${poll_interval}"
            continue
        fi

        session_class="${session_values[1]:-}"
        locked_hint="${session_values[2]:-}"
        allow_manual_off=0
        capture_login_level=0
        if [[ "${session_class}" == "user" ]] && [[ "${locked_hint}" != "yes" ]]; then
            allow_manual_off=1
            resume_uid="${uid}"
        else
            capture_login_level=1
        fi

        current_time_ms="$(now_ms)"

        if [[ "${uid}" != "${last_session_uid}" ]] || (( allow_manual_off != last_allow_manual_off )); then
            if (( allow_manual_off == 1 )); then
                manual_activity_until_ms["${uid}"]=$(( current_time_ms + timeout_ms ))
            fi
            activate_uid "${uid}" "${allow_manual_off}"
            last_session_uid="${uid}"
            last_allow_manual_off="${allow_manual_off}"
        fi

        observe_session_state "${uid}" "${current_time_ms}" "${allow_manual_off}" "${capture_login_level}"
        manual_deadline_ms="$(manual_deadline_for_uid "${uid}")"

        idle_ms="$(idle_ms_for_uid "${uid}" || true)"
        if [[ -z "${idle_ms}" ]]; then
            restore_for_activity "${uid}" "${allow_manual_off}"
        elif (( manual_deadline_ms > current_time_ms )); then
            restore_for_activity "${uid}" "${allow_manual_off}"
        elif (( idle_ms >= timeout_ms )); then
            dim_for_idle "${uid}"
        else
            restore_for_activity "${uid}" "${allow_manual_off}"
        fi

        if [[ "${session_class}" == "user" ]]; then
            update_boot_levels_for_uid "${uid}"
        fi

        sleep "${poll_interval}"
    done
}

main

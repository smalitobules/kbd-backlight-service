# Keyboard Backlight Service

Single `systemd` service for Linux laptop keyboard backlights.

## Features

- Detects keyboard backlight devices via `/sys/class/leds/*kbd_backlight*`
- Detects the active seat automatically
- Persists the last relevant brightness for boot and shutdown
- Dims after idle and restores on activity
- Respects a manual brightness of `0` in the active user session
- Carries manual positive brightness changes from lock screen or greeter into the next active session
- Keeps all logic in one root service without per-user autostart helpers

## Requirements

- Linux with keyboard backlight devices exposed under `/sys/class/leds/*kbd_backlight*`
- `systemd`
- `gdbus`
- `id`
- `install`
- `loginctl`
- `mktemp`
- `setpriv`
- GNOME or another desktop environment exposing `org.gnome.Mutter.IdleMonitor` on the active session bus

## Usage

```bash
sudo ./scripts/kbd-backlight-service.sh install
./scripts/kbd-backlight-service.sh status
sudo ./scripts/kbd-backlight-service.sh uninstall
```

## Default Service Settings

- `SEAT=auto`
- `TIMEOUT_MS=6000`
- `BOOT_LEVEL=1`
- `POLL_INTERVAL=0.25`
- `STATE_DIR=/var/lib/kbd-backlight-service`

## License

GNU General Public License v3.0. See [LICENSE](LICENSE).

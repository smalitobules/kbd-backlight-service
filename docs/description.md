# Keyboard Backlight Service

This project provides a single systemd service for Linux laptop keyboard backlights.

## Scope

- auto-detects keyboard backlight devices through `/sys/class/leds/*kbd_backlight*`
- auto-detects the active seat instead of assuming `seat0`
- persists the last relevant user brightness for boot and shutdown, clamped to at least `1`
- dims the active session's keyboard backlight after a configurable idle timeout
- restores the remembered non-zero brightness after user activity returns
- respects a manual brightness level of `0` inside the active user session
- tracks remembered brightness state per active user ID inside the running daemon
- carries a manual positive brightness change from the lock screen or greeter into the next active user session
- uses idle-based auto behavior on the lock screen and greeter instead of forcing a permanent minimum level
- avoids per-user autostart helpers and keeps the logic in one root service

## Files

- `scripts/kbd-backlight-daemon.sh`: runtime daemon
- `scripts/kbd-backlight-service.sh`: installer, uninstaller, and status helper

## Requirements

- Linux with keyboard backlight devices exposed under `/sys/class/leds/*kbd_backlight*`
- systemd
- `id`
- `loginctl`
- `gdbus`
- `setpriv`
- GNOME or another environment exposing `org.gnome.Mutter.IdleMonitor` on the active session bus for idle-based dimming

## Usage

```bash
sudo ./scripts/kbd-backlight-service.sh install
./scripts/kbd-backlight-service.sh status
sudo ./scripts/kbd-backlight-service.sh uninstall
```

## Behavior

If the active unlocked session exposes Mutter's idle monitor, the service dims the keyboard backlight after the configured timeout and restores the last visible level on activity.

If the user manually turns the keyboard backlight down to `0` inside the unlocked session, the service keeps that explicit choice and does not force it back on. The normal idle behavior resumes as soon as the user sets the brightness back to `1` or higher.

If the active session is locked or at the greeter, the service keeps using idle-based auto behavior instead of forcing a permanent minimum level. If there is no active session at all, such as during boot or shutdown, it restores the persisted brightness from the last relevant user session and clamps it to at least `1`.

If the brightness is manually changed to a positive level at the lock screen or greeter, that level is adopted for the next active user session instead of snapping back to the previously remembered session value.

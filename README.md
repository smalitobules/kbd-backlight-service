# ASUS Keyboard Backlight Service

Ein einzelner `systemd`-Dienst für ASUS-Tastaturbeleuchtung unter GNOME.

Aktuell validiert ist `/sys/class/leds/asus::kbd_backlight` mit GNOME Shell 50 auf Ubuntu 26.04 LTS. Andere Laptop-Hersteller und abweichende Keyboard-Backlight-Geräte sind noch nicht als unterstützt dokumentiert.

## Features

- erkennt ASUS-Keyboard-Backlight-Geräte über `/sys/class/leds/*kbd_backlight*`
- erkennt den aktiven Seat automatisch
- persistiert die letzte relevante Helligkeit für Start und Herunterfahren
- dimmt nach Inaktivität und stellt bei Aktivität wieder her
- respektiert manuelle Helligkeit `0` in der aktiven Benutzer-Sitzung
- übernimmt positive manuelle Änderungen vom Sperrbildschirm oder Greeter in die nächste aktive Sitzung
- hält die Logik in einem root-eigenen Dienst ohne Benutzer-Autostart

## Voraussetzungen

- ASUS-Laptop mit Keyboard-Backlight unter `/sys/class/leds/asus::kbd_backlight`
- `systemd`
- `gdbus`
- `id`
- `install`
- `loginctl`
- `mktemp`
- `setpriv`
- GNOME mit `org.gnome.Mutter.IdleMonitor` und `org.gnome.SettingsDaemon.Power.Keyboard` auf dem aktiven Benutzerbus

## Nutzung

```bash
sudo ./scripts/kbd-backlight-service.sh install
./scripts/kbd-backlight-service.sh status
sudo ./scripts/kbd-backlight-service.sh uninstall
```

`uninstall` stoppt und deaktiviert den Dienst, entfernt die installierte Service-Datei und den installierten Daemon und lädt `systemd` neu. Der State unter `/var/lib/kbd-backlight-service` bleibt erhalten.

Ein separates `disable`-Kommando zum Stoppen ohne Datei-Entfernung und ein separates `revert`-Kommando existieren aktuell nicht. Rückkehr zum normalen GNOME-/Systemverhalten erfolgt derzeit über `uninstall`.

## Standardkonfiguration

- `SEAT=auto`
- `TIMEOUT_MS=6000`
- `BOOT_LEVEL=1`
- `POLL_INTERVAL=1`
- `STATE_DIR=/var/lib/kbd-backlight-service`
- `DEVICE_GLOB=/sys/class/leds/asus::kbd_backlight`

## Lizenz

GNU General Public License v3.0. Siehe [LICENSE](LICENSE).

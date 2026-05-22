# ASUS Keyboard Backlight Service

Der Dienst verwaltet die ASUS-Tastaturbeleuchtung unter GNOME als einzelne root-eigene `systemd`-Unit. Validiert ist `/sys/class/leds/asus::kbd_backlight` mit GNOME Shell 50 auf Ubuntu 26.04 LTS.

## Umfang

- aktiver Seat über logind
- User-DBus-Integration über pro Sitzung gestartete Worker
- GNOME-Helligkeit als primärer Schreibpfad in entsperrten Benutzersitzungen
- sysfs als Fallback und Systemzustandspfad
- Idle- und Aktivitätsereignisse über Mutter IdleMonitor
- Helligkeitsereignisse über GNOME SettingsDaemon Power Keyboard
- manuelle sysfs-Änderungen über inotify
- Konto-Persistenz unter `/var/lib/kbd-backlight-service`
- automatische Runtime-Paketinstallation für `python3-dbus-next` und `python3-asyncinotify`

## Laufzeitdateien

- `scripts/kbd_backlight_daemon.py`: root-Daemon und User-DBus-Worker
- `scripts/kbd_backlight_core.py`: Mapping- und Zustandslogik
- `scripts/kbd-backlight-service.sh`: Installation und Lifecycle

Installierte Dateien:

- `/usr/local/libexec/kbd-backlight-service-daemon`
- `/usr/local/libexec/kbd_backlight_core.py`
- `/etc/systemd/system/kbd-backlight-service.service`
- `/var/lib/kbd-backlight-service`

## Verhalten

Entsperrte Benutzersitzungen verwenden den pro Konto gespeicherten positiven Helligkeitswert. Bei Idle wird auf `0` gedimmt; bei Aktivität wird der letzte sichtbare Konto-Wert wiederhergestellt.

Eine manuelle Helligkeit `0` in einer entsperrten Benutzersitzung bleibt erhalten. Der Dienst schaltet in diesem Zustand nicht automatisch wieder ein.

Beim Eintritt in Greeter oder Sperrbildschirm wird einmal `BOOT_LEVEL` gesetzt. Änderungen im Greeter oder Sperrbildschirm bleiben bis zum nächsten Sitzungswechsel erlaubt und überschreiben keine Konto-Persistenz.

Boot, Herunterfahren und fehlende aktive Sitzungen verwenden `BOOT_LEVEL`.

## Lifecycle

- `install`: installiert Runtime-Abhängigkeiten, Daemon und Unit, aktiviert und startet den Dienst
- `status`: zeigt den systemd-Status
- `disable`: stoppt und deaktiviert den Dienst, behält Dateien und State
- `uninstall`: stoppt und deaktiviert den Dienst, entfernt Unit und Daemon-Dateien, behält State
- `revert`: Alias für `uninstall`

`uninstall` entfernt nur Runtime-Pakete, die `install` neu installiert und in `/var/lib/kbd-backlight-service/runtime-packages.installed` vermerkt hat. Wenn `apt` dabei fremde Pakete entfernen würde, bleibt das Runtime-Paket installiert.

## Produktionsprüfung

```bash
systemctl --no-pager --full status kbd-backlight-service.service
journalctl -u kbd-backlight-service.service -b --no-pager -n 120
cat /sys/class/leds/asus::kbd_backlight/brightness
cat /sys/class/leds/asus::kbd_backlight/max_brightness
```

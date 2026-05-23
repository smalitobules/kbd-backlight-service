# ASUS Keyboard Backlight Service

Ein root-eigener `systemd`-Dienst für ASUS-Tastaturbeleuchtung unter GNOME.

Der Dienst ist für `/sys/class/leds/asus::kbd_backlight` auf einem ASUS-Laptop mit GNOME Shell 50 unter Ubuntu 26.04 LTS validiert. Andere Gerätepfade, mehrere Keyboard-Backlights und andere Hersteller sind nicht als unterstützt freigegeben.

## Verhalten

- dimmt die Tastaturbeleuchtung nach Inaktivität und stellt sie bei Aktivität wieder her
- hält GNOME `Brightness` und den sysfs-Wert nach Dienstschreibvorgängen synchron
- speichert die letzte positive Helligkeit pro Benutzerkonto
- stellt beim Konto-Eintritt den gespeicherten Konto-Wert wieder her
- respektiert manuell gesetzte Helligkeit `0` in entsperrten Kontositzungen
- setzt Boot, Herunterfahren und fehlende aktive Sitzungen auf `BOOT_LEVEL`
- setzt Sperrbildschirm und Greeter beim Eintritt einmal auf `BOOT_LEVEL`
- erlaubt Änderungen im Greeter oder Sperrbildschirm bis zum nächsten Sitzungswechsel, ohne sie ins Konto zu übernehmen
- läuft ohne Benutzer-Autostart und ohne schnelle Polling-Schleife

## Voraussetzungen

- ASUS-Laptop mit `/sys/class/leds/asus::kbd_backlight`
- GNOME-Kontositzung mit Mutter IdleMonitor und SettingsDaemon Power Keyboard
- `systemd`
- `systemctl`
- `python3`
- `apt-get`
- `dpkg-query`
- `id`
- `install`
- `mktemp`
- `chmod`

`install` installiert fehlende Runtime-Pakete automatisch:

- `python3-dbus-next`
- `python3-asyncinotify`

Pakete, die vom Installer neu installiert wurden, werden bei `uninstall` oder `revert` wieder entfernt, sofern `apt` dabei keine fremden Pakete mit entfernen würde.

## Installation

```bash
sudo ./scripts/kbd-backlight-service.sh install
```

Das Kommando installiert:

- `/usr/local/libexec/kbd-backlight-service-daemon`
- `/usr/local/libexec/kbd_backlight_core.py`
- `/etc/systemd/system/kbd-backlight-service.service`

Danach wird die Unit aktiviert, neu gestartet und der aktuelle Status ausgegeben.

## Bedienung

```bash
./scripts/kbd-backlight-service.sh status
sudo ./scripts/kbd-backlight-service.sh disable
sudo ./scripts/kbd-backlight-service.sh install
sudo ./scripts/kbd-backlight-service.sh revert
sudo ./scripts/kbd-backlight-service.sh uninstall
```

`status` zeigt den systemd-Status.

`disable` stoppt und deaktiviert den Dienst, lässt installierte Dateien, State und Runtime-Pakete unverändert.

`uninstall` stoppt und deaktiviert den Dienst, entfernt Unit und installierte Daemon-Dateien, lädt `systemd` neu und entfernt nur vom Installer neu installierte Runtime-Pakete.

`revert` ist ein Alias für `uninstall`.

Der State unter `/var/lib/kbd-backlight-service` bleibt bei `disable`, `uninstall` und `revert` erhalten.

## Konfiguration

Die installierte Unit nutzt diese Standardwerte:

- `SEAT=auto`
- `TIMEOUT_MS=6000`
- `BOOT_LEVEL=1`
- `POLL_INTERVAL=10`
- `STATE_DIR=/var/lib/kbd-backlight-service`
- `DEVICE_GLOB=/sys/class/leds/asus::kbd_backlight`

`TIMEOUT_MS` ist die Inaktivitätszeit bis zum Dimmen. `BOOT_LEVEL` ist die Helligkeit für Boot, Greeter-Eintritt, Sperrbildschirm-Eintritt, Herunterfahren und fehlende aktive Sitzungen. `POLL_INTERVAL` steuert den langsamen Sicherheitsabgleich für Geräte, Sitzungen und verpasste GNOME-Idle-Ereignisse. `STATE_DIR` ist fest auf `/var/lib/kbd-backlight-service` begrenzt.

`DEVICE_GLOB` kann beim Installieren gesetzt werden:

```bash
sudo DEVICE_GLOB=/sys/class/leds/asus::kbd_backlight ./scripts/kbd-backlight-service.sh install
```

`SEAT`, `TIMEOUT_MS`, `BOOT_LEVEL` und `POLL_INTERVAL` werden nach der Installation direkt in `/etc/systemd/system/kbd-backlight-service.service` geändert. Danach:

```bash
sudo systemctl daemon-reload
sudo systemctl restart kbd-backlight-service.service
```

Ein erneutes `install` schreibt die Unit mit den Standardwerten neu.

## Prüfung

```bash
systemctl --no-pager --full status kbd-backlight-service.service
journalctl -u kbd-backlight-service.service -b --no-pager -n 120
cat /sys/class/leds/asus::kbd_backlight/brightness
cat /sys/class/leds/asus::kbd_backlight/max_brightness
```

GNOME-Wert in der aktiven Benutzersitzung, falls `gdbus` vorhanden ist:

```bash
gdbus call --session \
  --dest org.gnome.SettingsDaemon.Power \
  --object-path /org/gnome/SettingsDaemon/Power \
  --method org.freedesktop.DBus.Properties.Get \
  org.gnome.SettingsDaemon.Power.Keyboard Brightness
```

## State

Der Dienst speichert Konto-Helligkeiten unter `/var/lib/kbd-backlight-service`. Die Dateien gehören root, der Ordner ist nicht für normale Benutzer lesbar. Fehlender oder ungültiger Konto-State fällt auf `BOOT_LEVEL` zurück.

Der State wird bei `uninstall` nicht gelöscht. Dadurch bleibt die Konto-Persistenz bei einer späteren Neuinstallation erhalten.

## Fehlerbehebung

Wenn die Installation mit `No usable keyboard backlight devices matched ...` abbricht, ist das validierte ASUS-Gerät nicht unter `DEVICE_GLOB` vorhanden.

Wenn im Journal für den Greeter `GNOME idle unavailable` erscheint, ist das nicht automatisch ein Dienstfehler. Manche Greeter-Sitzungen stellen Mutter IdleMonitor nicht bereit. Der Dienst setzt den Greeter beim Eintritt trotzdem auf `BOOT_LEVEL` und lässt danach Greeter-Änderungen bis zum Sitzungswechsel zu.

Wenn Konto-Helligkeiten nicht wiederhergestellt werden, zuerst diese Werte prüfen:

```bash
systemctl --no-pager --full status kbd-backlight-service.service
journalctl -u kbd-backlight-service.service -b --no-pager -n 120
cat /sys/class/leds/asus::kbd_backlight/brightness
```

## Entwicklung

Vor Änderungen an Skripten oder Daemon ausführen:

```bash
shellcheck scripts/*.sh
bash -n scripts/*.sh
python3 -m unittest discover
```

## Lizenz

GNU General Public License v3.0. Siehe [LICENSE](LICENSE).

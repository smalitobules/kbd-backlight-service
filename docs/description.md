# ASUS Keyboard Backlight Service

Dieses Projekt stellt einen einzelnen `systemd`-Dienst für ASUS-Tastaturbeleuchtung unter GNOME bereit.

## Umfang

- validiert für `/sys/class/leds/asus::kbd_backlight`
- erkennt den aktiven Seat automatisch statt `seat0` vorauszusetzen
- persistiert die letzte relevante Helligkeit pro Benutzerkonto, begrenzt auf mindestens `1`
- dimmt die Tastaturbeleuchtung der aktiven Sitzung nach konfigurierbarem Idle-Timeout
- stellt die gemerkte positive Helligkeit bei Benutzeraktivität wieder her
- respektiert manuelle Helligkeit `0` innerhalb der aktiven entsperrten Benutzer-Sitzung
- merkt Helligkeitszustand pro aktiver Benutzer-ID
- setzt Sperrbildschirm und Greeter beim Eintritt auf `BOOT_LEVEL`
- setzt fehlende aktive Sitzungen immer auf `BOOT_LEVEL`
- vermeidet Benutzer-Autostart-Helfer und hält die Logik in einem root-eigenen Dienst
- nutzt GNOME-, logind- und sysfs-Ereignisse statt schnellem Polling

## Dateien

- `scripts/kbd_backlight_daemon.py`: Laufzeit-Daemon
- `scripts/kbd_backlight_core.py`: reine Mapping- und Zustandslogik
- `scripts/kbd-backlight-service.sh`: Installer und Lifecycle-Helfer

## Voraussetzungen

- ASUS-Laptop mit Keyboard-Backlight unter `/sys/class/leds/asus::kbd_backlight`
- `systemd`
- `python3`
- `apt-get`
- `dpkg-query`
- `id`
- `install`
- `mktemp`
- GNOME mit `org.gnome.Mutter.IdleMonitor` und `org.gnome.SettingsDaemon.Power.Keyboard` auf dem aktiven Benutzerbus

## Nutzung

```bash
sudo ./scripts/kbd-backlight-service.sh install
./scripts/kbd-backlight-service.sh status
sudo ./scripts/kbd-backlight-service.sh disable
sudo ./scripts/kbd-backlight-service.sh revert
sudo ./scripts/kbd-backlight-service.sh uninstall
```

`install` installiert fehlende Runtime-Pakete, installiert den Daemon nach `/usr/local/libexec/kbd-backlight-service-daemon`, schreibt die Unit nach `/etc/systemd/system/kbd-backlight-service.service`, aktiviert den Dienst und startet ihn neu.

`status` zeigt den systemd-Status des Dienstes.

`disable` stoppt und deaktiviert den Dienst ohne Datei-Entfernung.

`uninstall` stoppt und deaktiviert den Dienst, entfernt die installierte Unit und den installierten Daemon, führt `systemctl daemon-reload` aus und entfernt Runtime-Pakete, die durch `install` neu installiert wurden. Der State unter `/var/lib/kbd-backlight-service` bleibt erhalten.

`revert` ist ein Alias für `uninstall`.

## Verhalten

Wenn die aktive entsperrte Sitzung Mutter IdleMonitor bereitstellt, dimmt der Dienst die Tastaturbeleuchtung nach dem konfigurierten Timeout und stellt bei Aktivität die letzte sichtbare Helligkeit wieder her.

Wenn der Benutzer die Tastaturbeleuchtung in der entsperrten Sitzung manuell auf `0` setzt, bleibt diese explizite Entscheidung erhalten. Das normale Idle-Verhalten läuft weiter, sobald der Benutzer wieder eine Helligkeit ab `1` setzt.

Wenn die aktive Sitzung gesperrt wird oder der Greeter aktiv wird, setzt der Dienst die Tastaturbeleuchtung einmal auf `BOOT_LEVEL`. Danach bleiben Greeter- und Sperrbildschirmänderungen bis zum Sitzungswechsel erlaubt, überschreiben aber keine Konto-Persistenz. Wenn keine aktive Sitzung existiert, setzt der Dienst die Tastaturbeleuchtung auf `BOOT_LEVEL`.

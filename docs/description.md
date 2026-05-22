# ASUS Keyboard Backlight Service

Dieses Projekt stellt einen einzelnen `systemd`-Dienst für ASUS-Tastaturbeleuchtung unter GNOME bereit.

## Umfang

- validiert für `/sys/class/leds/asus::kbd_backlight`
- erkennt den aktiven Seat automatisch statt `seat0` vorauszusetzen
- persistiert die letzte relevante Benutzerhelligkeit für Start und Herunterfahren, begrenzt auf mindestens `1`
- dimmt die Tastaturbeleuchtung der aktiven Sitzung nach konfigurierbarem Idle-Timeout
- stellt die gemerkte positive Helligkeit bei Benutzeraktivität wieder her
- respektiert manuelle Helligkeit `0` innerhalb der aktiven entsperrten Benutzer-Sitzung
- merkt Helligkeitszustand pro aktiver Benutzer-ID im laufenden Daemon
- übernimmt positive manuelle Helligkeitsänderungen vom Sperrbildschirm oder Greeter in die nächste aktive Benutzer-Sitzung
- nutzt am Sperrbildschirm und Greeter idle-basiertes Verhalten statt dauerhaft eine Mindesthelligkeit zu erzwingen
- vermeidet Benutzer-Autostart-Helfer und hält die Logik in einem root-eigenen Dienst

## Dateien

- `scripts/kbd-backlight-daemon.sh`: Laufzeit-Daemon
- `scripts/kbd-backlight-service.sh`: Installer, Uninstaller und Status-Helfer

## Voraussetzungen

- ASUS-Laptop mit Keyboard-Backlight unter `/sys/class/leds/asus::kbd_backlight`
- `systemd`
- `id`
- `loginctl`
- `gdbus`
- `setpriv`
- GNOME mit `org.gnome.Mutter.IdleMonitor` und `org.gnome.SettingsDaemon.Power.Keyboard` auf dem aktiven Benutzerbus

## Nutzung

```bash
sudo ./scripts/kbd-backlight-service.sh install
./scripts/kbd-backlight-service.sh status
sudo ./scripts/kbd-backlight-service.sh uninstall
```

`install` installiert den Daemon nach `/usr/local/libexec/kbd-backlight-service-daemon`, schreibt die Unit nach `/etc/systemd/system/kbd-backlight-service.service`, aktiviert den Dienst und startet ihn neu.

`status` zeigt den systemd-Status des Dienstes.

`uninstall` stoppt und deaktiviert den Dienst, entfernt die installierte Unit und den installierten Daemon und führt `systemctl daemon-reload` aus. Der State unter `/var/lib/kbd-backlight-service` bleibt erhalten.

Separate Kommandos `disable` und `revert` existieren aktuell nicht. Der aktuelle Rückweg zum normalen GNOME-/Systemverhalten ist `uninstall`.

## Verhalten

Wenn die aktive entsperrte Sitzung Mutter IdleMonitor bereitstellt, dimmt der Dienst die Tastaturbeleuchtung nach dem konfigurierten Timeout und stellt bei Aktivität die letzte sichtbare Helligkeit wieder her.

Wenn der Benutzer die Tastaturbeleuchtung in der entsperrten Sitzung manuell auf `0` setzt, bleibt diese explizite Entscheidung erhalten. Das normale Idle-Verhalten läuft weiter, sobald der Benutzer wieder eine Helligkeit ab `1` setzt.

Wenn die aktive Sitzung gesperrt ist oder der Greeter aktiv ist, nutzt der Dienst weiterhin idle-basiertes Verhalten statt dauerhaft eine Mindesthelligkeit zu erzwingen. Wenn keine aktive Sitzung existiert, etwa beim Start oder Herunterfahren, wird die persistierte Helligkeit der letzten relevanten Benutzer-Sitzung auf mindestens `1` begrenzt wiederhergestellt.

Wenn die Helligkeit am Sperrbildschirm oder Greeter manuell positiv geändert wird, übernimmt der Dienst diese Helligkeit für die nächste aktive Benutzer-Sitzung.

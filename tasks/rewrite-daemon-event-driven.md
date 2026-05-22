# Tastaturbeleuchtungs-Daemon ereignisgetrieben umbauen

## Ziel

Die Bash-Polling-Schleife durch einen ereignisgetriebenen Daemon ersetzen. Der neue Daemon muss unter Ubuntu 26.04 LTS mit GNOME 50 sauber laufen und das bestehende Verhalten vollständig erhalten.

## Kontextdateien

Vor der Umsetzung lesen:

- `docs/asus-keyboard-backlight-gnome-50.md`
- `docs/roadmap.md`
- `README.md`
- `scripts/kbd-backlight-daemon.sh`
- `scripts/kbd-backlight-service.sh`

## Vorgaben

- Eine root-eigene `systemd`-Unit bleibt der einzige Dienst.
- `scripts/kbd-backlight-service.sh` bleibt der Installer, Uninstaller, Disable-, Revert- und Status-Einstiegspunkt.
- GPL-3.0 bleibt die Lizenz.
- Abhängigkeiten werden explizit geprüft.
- Fehler werden im Journal sichtbar oder führen zu einem klaren Dienstfehler.
- sysfs bleibt Fallback für fehlende GNOME-Sitzungen.
- Der GNOME-DBus-Schreibpfad bleibt primär für aktive GNOME-Sitzungen.

## Runtime

Python ist der verbindliche Pfad für dieses Arbeitspaket.

Erforderliche Fähigkeiten:

- DBus-Client mit Signal-Unterstützung
- inotify-Unterstützung
- Logging über stdout/stderr für `journald`
- saubere Signalbehandlung für `SIGTERM` und `SIGINT`
- keine Build-Kette für die Installation

Zu verwendende Ubuntu-Pakete:

- `python3-dbus-next`
- `python3-asyncinotify`

Wenn ein Paket auf dem Zielsystem fehlt, muss der Installer mit einer klaren Fehlermeldung abbrechen.

Importnamen für die Abhängigkeitsprüfung:

- `dbus_next`
- `asyncinotify`

## Funktionsumfang

Der neue Daemon muss:

- Tastaturbeleuchtungen über `/sys/class/leds/*kbd_backlight*` erkennen
- den aktiven Seat automatisch erkennen, wenn `SEAT=auto` gesetzt ist
- `SEAT`, `TIMEOUT_MS`, `BOOT_LEVEL`, `POLL_INTERVAL`, `STATE_DIR` und `DEVICE_GLOB` lesen
- den gespeicherten Boot-Wert auf mindestens `1` begrenzen
- aktive entsperrte Benutzer-Sitzungen erkennen
- gesperrte Sitzungen und Greeter-Zustände erkennen
- Idle-Zustände über GNOME Mutter erkennen
- Aktivität über GNOME Mutter erkennen
- GNOME-Helligkeitsänderungen über `BrightnessChanged` erkennen
- sysfs-Helligkeitsänderungen über `inotify` erkennen
- GNOME-Prozentwerte und sysfs-Rohwerte synchron halten
- manuelle Benutzerentscheidung `0` in entsperrten Sitzungen respektieren
- positive Änderungen am Sperrbildschirm oder Greeter in die nächste entsperrte Sitzung übernehmen
- Boot- und No-Session-Zustände nie dauerhaft mit `0` persistieren

## Prozessmodell

Der root-Daemon bleibt zuständig für:

- systemweite logind-DBus-Verbindung
- sysfs-Lesen und sysfs-Schreiben
- State-Dateien unter `STATE_DIR`
- Gerätesuche unter `/sys/class/leds`
- Start und Stop von Benutzerbus-Workern
- Beenden aller Worker bei `SIGTERM` und `SIGINT`

Für jede aktive relevante Benutzer-Sitzung startet der root-Daemon einen Benutzerbus-Worker mit Ziel-UID und Ziel-GID. Der Worker ist zuständig für:

- Verbindung zu `unix:path=/run/user/<uid>/bus`
- GNOME Mutter IdleMonitor Watches
- GNOME Power Keyboard `BrightnessChanged`
- GNOME Power Keyboard `Brightness`-Schreibvorgänge, wenn der root-Daemon sie anfordert

Der Worker darf nicht:

- sysfs-Dateien schreiben
- State-Dateien lesen oder schreiben
- eigene Helligkeitsentscheidungen treffen

Die Kommunikation zwischen root-Daemon und Worker muss strukturiert sein. Zulässig sind JSON-Zeilen über stdin/stdout oder ein Unix-Domain-Socket. Textausgaben, die nicht zum Protokoll gehören, gehen nach stderr.

Wenn JSON-Zeilen verwendet werden, muss jede Nachricht mindestens `type`, `session_id`, `uid` und `timestamp_ms` enthalten. Befehle vom root-Daemon an Worker und Ereignisse vom Worker an root-Daemon müssen getrennte `type`-Werte verwenden.

## Ereignisquellen

Implementiere diese Ereignisquellen:

- `org.gnome.Mutter.IdleMonitor.AddIdleWatch`
- `org.gnome.Mutter.IdleMonitor.AddUserActiveWatch`
- `org.gnome.SettingsDaemon.Power.Keyboard.BrightnessChanged`
- logind-DBus-Signale für Seat-, Session- und Property-Änderungen
- `inotify` auf jede erkannte `brightness`-Datei

Ein langsamer Abgleich darf als Schutzmechanismus bestehen bleiben. Er darf nicht der primäre Steuerpfad sein.

Konkrete logind-Quellen:

- Systembus `org.freedesktop.login1`
- Manager-Objekt `/org/freedesktop/login1`
- Manager-Signale `SessionNew`, `SessionRemoved`, `SeatNew`, `SeatRemoved`, `PrepareForShutdown`, `PrepareForSleep`
- Session-Objekte über `GetSession(<sid>)`
- Session-Eigenschaften `User`, `Seat`, `Class`, `Type`, `Active`, `State`, `LockedHint`
- Session-Signale `Lock`, `Unlock`
- Session-Property-Signal `org.freedesktop.DBus.Properties.PropertiesChanged`

Konkrete GNOME-Quellen:

- `org.gnome.Mutter.IdleMonitor` auf `/org/gnome/Mutter/IdleMonitor/Core`
- `AddIdleWatch(timeout_ms)` für Idle
- `AddUserActiveWatch()` für Aktivität
- `WatchFired(id)` zur Zuordnung der Watches
- `org.gnome.SettingsDaemon.Power.Keyboard` auf `/org/gnome/SettingsDaemon/Power`
- `BrightnessChanged(i brightness, s source)` für GNOME-Helligkeitsänderungen
- `org.freedesktop.DBus.Properties.Set` für `Brightness` als `int32`

## Umsetzungsschritte

1. Neue Daemon-Quelle unter `scripts/` oder in einem kleinen Paketverzeichnis anlegen.
2. `scripts/kbd-backlight-service.sh` auf den neuen Daemon umstellen.
3. Install, Disable, Revert, Uninstall und Status sauber implementieren.
4. Bestehendes State-Dateiformat beibehalten.
5. Abhängigkeitsprüfung für Runtime, DBus und inotify ergänzen.
6. Rohwert-Prozentwert-Mapping testbar isolieren.
7. Zustandsübergänge für Idle, Aktivität, Lock, Greeter und Session-Wechsel testbar isolieren.
8. Root-Daemon mit logind-Systembus und sysfs/inotify implementieren.
9. Benutzerbus-Worker mit GNOME IdleMonitor und GNOME Power Keyboard implementieren.
10. Strukturiertes IPC-Protokoll zwischen Root-Daemon und Worker implementieren.
11. Langsamen Reconcile-Timer über `POLL_INTERVAL` implementieren.
12. Lint-, Syntax- und Integrationstests ausführen.
13. Dienst lokal installieren und Journal prüfen.

## Lifecycle-Kommandos

Der Umbau muss diese Kommandos bereitstellen:

- `install`: Daemon installieren, Unit schreiben, `systemctl daemon-reload`, Dienst aktivieren und starten
- `status`: systemd-Status anzeigen
- `disable`: Dienst stoppen und deaktivieren, installierte Dateien und State unverändert lassen
- `uninstall`: Dienst stoppen und deaktivieren, installierte Unit und installierten Daemon entfernen, `systemctl daemon-reload` ausführen, State erhalten
- `revert`: dokumentierter Rückweg zum normalen GNOME-/Systemverhalten

`revert` muss fachlich eindeutig sein:

- entweder Alias für `uninstall`
- oder `uninstall` plus definierter Helligkeitswiederherstellung vor dem Stoppen

State unter `/var/lib/kbd-backlight-service` darf durch `disable`, `uninstall` und `revert` nicht entfernt werden.

Ein späteres `purge`-Kommando darf nur mit separater Bestätigung eingeführt werden, weil es State löscht.

## Mapping-Regeln

Rohwert zu GNOME-Prozent:

```text
percent = (level * 100) / max_brightness
```

GNOME-Prozent zu Rohwert:

```text
level = (percent * max_brightness + 50) / 100
```

Zusätzliche Regeln:

- `percent <= 0` ergibt Rohwert `0`.
- `percent > 0` ergibt mindestens Rohwert `1`.
- Rohwerte werden auf `0..max_brightness` begrenzt.
- Prozentwerte werden auf `0..100` begrenzt.
- Nach jedem GNOME-Schreibvorgang muss sysfs gelesen werden.
- Ein GNOME-Schreibvorgang gilt nur als erfolgreich, wenn sysfs danach den Zielrohwert enthält.

## Tests

Mindestens diese reinen Tests ergänzen:

- Rohwert `0` zu Prozent `0`
- Rohwert `1` bei `max_brightness=3` zu Prozent `33`
- Rohwert `2` bei `max_brightness=3` zu Prozent `66`
- Rohwert `3` bei `max_brightness=3` zu Prozent `100`
- Prozent `0` bei `max_brightness=3` zu Rohwert `0`
- Prozent `33` bei `max_brightness=3` zu Rohwert `1`
- positiver Prozentwert unterhalb der Rundungsschwelle zu Rohwert `1`
- manuelles `0` in entsperrter Sitzung bleibt erhalten
- Idle-Übergang dimmt genau einmal
- Aktivitäts-Übergang stellt genau einmal wieder her
- gesperrte Sitzung übernimmt positive Änderung für die nächste entsperrte Sitzung

## Akzeptanzkriterien

- Kein schnelles Polling im GNOME-Normalbetrieb.
- GNOME `Brightness` und sysfs `brightness` bleiben nach Dienstschreibvorgängen synchron.
- Idle-Dimming passiert genau einmal pro Idle-Übergang.
- Aktivitäts-Restore passiert genau einmal pro Aktivitäts-Übergang.
- Manueller Wert `0` bleibt in entsperrten Benutzer-Sitzungen erhalten.
- Positive Sperrbildschirm- oder Greeter-Änderungen werden übernommen.
- Dienstneustart stellt den gespeicherten positiven Boot-Wert wieder her.
- No-Session-Zustände persistieren nie `0`.
- `systemctl status` zeigt den Dienst als laufend.
- `journalctl -u kbd-backlight-service.service -b` zeigt keine wiederkehrenden Fehler.
- Shell-Skripte bestehen `shellcheck`.

## Prüfung

```bash
shellcheck scripts/*.sh
bash -n scripts/*.sh
python3 -m unittest discover
sudo ./scripts/kbd-backlight-service.sh install
sudo ./scripts/kbd-backlight-service.sh disable
sudo ./scripts/kbd-backlight-service.sh install
sudo ./scripts/kbd-backlight-service.sh revert
sudo ./scripts/kbd-backlight-service.sh install
sudo ./scripts/kbd-backlight-service.sh uninstall
systemctl --no-pager --full status kbd-backlight-service.service
journalctl -u kbd-backlight-service.service -b --no-pager -n 120
```

```bash
cat /sys/class/leds/*kbd_backlight*/brightness
cat /sys/class/leds/*kbd_backlight*/max_brightness
gdbus call --session --dest org.gnome.SettingsDaemon.Power --object-path /org/gnome/SettingsDaemon/Power --method org.freedesktop.DBus.Properties.Get org.gnome.SettingsDaemon.Power.Keyboard Brightness
```

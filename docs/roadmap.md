# Roadmap

## Zielbild

Der Dienst besteht aus einem kleinen root-eigenen `systemd`-Service mit ereignisgetriebenem Daemon. GNOME-Sitzungen werden über User-DBus integriert, systemweite Sitzungszustände über logind, Tastaturbeleuchtungen über sysfs und manuelle sysfs-Änderungen über inotify.

## Phase 1: Stabiler GNOME-50-Betrieb

Zielzustand:

- GNOME `Brightness` ist der primäre Schreibpfad in aktiven GNOME-Sitzungen.
- sysfs bleibt Fallback und Boot-/No-Session-Pfad.
- `DEVICE_GLOB=/sys/class/leds/asus::kbd_backlight` begrenzt den aktuellen Support auf das validierte ASUS-Gerät.
- `XDG_RUNTIME_DIR` und `DBUS_SESSION_BUS_ADDRESS` werden für Benutzerbus-Aufrufe explizit gesetzt.
- `POLL_INTERVAL=10` steuert nur den langsamen Reconcile-Timer.
- logind wird über den Systembus abgefragt.

Prüfung:

```bash
shellcheck scripts/*.sh
bash -n scripts/*.sh
sudo ./scripts/kbd-backlight-service.sh install
systemctl --no-pager --full status kbd-backlight-service.service
journalctl -u kbd-backlight-service.service -b --no-pager -n 120
```

## Phase 2: Zustandsmodell isolieren

Zielzustand:

- Rohwert-Prozentwert-Mapping ist als isolierte Funktion testbar.
- Session-Zustände sind als explizite Zustände modelliert.
- Helligkeitsentscheidungen sind von DBus- und sysfs-I/O getrennt.
- Konto-Persistenz ist separat testbar.

Ergebnis:

- klare State-Transition-Funktionen
- keine I/O-Seiteneffekte in reiner Entscheidungslogik
- Tests für Mapping, manuelles `0`, Idle, Aktivität, Lock, Greeter und Session-Wechsel

## Phase 3: Ereignisgetriebener Daemon

Zielzustand:

- neuer Daemon in Python
- Abhängigkeiten: `python3-dbus-next`, `python3-asyncinotify`
- Root-Prozess für sysfs, State-Dateien und logind-Systembus
- Benutzerbus-Worker pro aktiver Benutzer-Sitzung mit Ziel-UID und Ziel-GID
- IPC zwischen Root-Prozess und Benutzerbus-Worker für GNOME-Ereignisse

Ereignisquellen:

- logind `SessionNew`
- logind `SessionRemoved`
- logind Session `Lock`
- logind Session `Unlock`
- logind `PropertiesChanged`
- GNOME Mutter `WatchFired`
- GNOME Power Keyboard `BrightnessChanged`
- inotify auf sysfs-`brightness`

## Phase 4: Langsamer Reconcile-Pfad

Zielzustand:

- Normalbetrieb läuft ohne schnelles Polling.
- `POLL_INTERVAL` steuert nur noch einen langsamen Abgleich.
- Der Abgleich erkennt verlorene DBus-Signale, neu erschienene sysfs-Geräte und entfernte sysfs-Geräte.
- Der Abgleich korrigiert divergierende GNOME-/sysfs-Zustände ohne manuelle Benutzerentscheidungen zu überschreiben.

Empfohlener Standard:

- `POLL_INTERVAL=10`

## Phase 5: Installation und Dokumentation

Zielzustand:

- `scripts/kbd-backlight-service.sh install` installiert den neuen Daemon.
- `scripts/kbd-backlight-service.sh disable` stoppt und deaktiviert den Dienst, lässt installierte Dateien und State aber unverändert.
- `scripts/kbd-backlight-service.sh uninstall` entfernt Service-Datei und Daemon-Datei.
- `scripts/kbd-backlight-service.sh revert` führt den definierten Rückweg zum normalen GNOME-/Systemverhalten aus.
- `scripts/kbd-backlight-service.sh status` zeigt den Dienststatus.
- README beschreibt nur Installation, Betrieb und Konfiguration.
- Detaildokumentation bleibt unter `docs/`.
- ausführbare Arbeitspakete bleiben unter `tasks/`.

Lifecycle-Regeln:

- `disable` darf keine Dateien entfernen.
- `uninstall` darf installierte Unit und installierten Daemon entfernen, erhält aber `/var/lib/kbd-backlight-service`.
- `revert` muss eindeutig dokumentieren, ob es ein Alias für `uninstall` ist oder zusätzliche Helligkeitswiederherstellung ausführt.
- State-Entfernung ist kein Teil von `disable`, `uninstall` oder `revert`.

## Phase 6: Abschlusskriterien

Der Umbau ist abgeschlossen, wenn:

- GNOME- und sysfs-Helligkeit nach Dienstschreibvorgängen synchron bleiben
- Idle-Dimming genau einmal pro Idle-Übergang passiert
- Aktivitäts-Restore genau einmal pro Aktivitäts-Übergang passiert
- manuelles `0` in entsperrten Benutzer-Sitzungen erhalten bleibt
- Sperrbildschirm und Greeter beim Eintritt `BOOT_LEVEL` verwenden
- Dienstneustart den gespeicherten positiven Konto-Wert wiederherstellt
- No-Session-Zustände `BOOT_LEVEL` verwenden
- Normalbetrieb keine schnelle Polling-Schleife verwendet
- `journalctl -u kbd-backlight-service.service -b` keine wiederkehrenden Fehler zeigt

## Phase 7: Geräteabdeckung erweitern

Zielzustand:

- weitere Laptop-Hersteller und Keyboard-Backlight-Geräte werden explizit validiert
- mehrere passende `/sys/class/leds/*kbd_backlight*`-Geräte werden korrekt behandelt
- Geräte mit anderer `max_brightness`-Skala werden über Tests abgedeckt
- README und Doku benennen unterstützte Geräte konkret
- nicht validierte Geräte werden nicht als unterstützt beworben

Abnahmekandidaten:

- ASUS mit `asus::kbd_backlight`
- Geräte mit `platform::kbd_backlight`
- Geräte mit mehreren Keyboard-LED-Einträgen
- Geräte mit `max_brightness` größer als `3`

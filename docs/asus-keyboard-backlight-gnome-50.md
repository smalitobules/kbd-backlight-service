# ASUS Keyboard Backlight unter GNOME 50

## Zielzustand

Der Dienst läuft als root-eigene `systemd`-Unit und verwaltet die ASUS-Tastaturbeleuchtung über Geräte unter `/sys/class/leds/*kbd_backlight*`.

Zielplattform ist der aktuell geprüfte ASUS-Laptop unter Ubuntu 26.04 LTS mit GNOME Shell 50. Direkte sysfs-Schreibzugriffe bleiben für Start, Herunterfahren, fehlende GNOME-Sitzungen und nicht verfügbare DBus-Endpunkte erhalten.

Der aktive GNOME-Schreibpfad ist:

- DBus-Ziel: `org.gnome.SettingsDaemon.Power`
- Objektpfad: `/org/gnome/SettingsDaemon/Power`
- Interface: `org.freedesktop.DBus.Properties`
- Eigenschaft: `org.gnome.SettingsDaemon.Power.Keyboard Brightness`
- Werttyp: `int32`

Der Aufruf läuft im Kontext der aktiven Benutzer-ID mit:

- `XDG_RUNTIME_DIR=/run/user/<uid>`
- `DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/<uid>/bus`

Damit bleiben GNOMEs prozentualer Helligkeitszustand und der rohe Kernel-LED-Wert synchron.

Der Dienst bewirbt keinen allgemeinen Laptop-Support. Generische Geräteerkennung ist technische Vorbereitung, nicht fachliche Gerätefreigabe.

## Gerätescope

Aktuell validiert ist:

- sysfs-Gerät: `/sys/class/leds/asus::kbd_backlight`
- sysfs-Maximum: `3`
- GNOME `Brightness=33` entspricht sysfs `brightness=1`
- GNOME `Brightness=0` entspricht sysfs `brightness=0`
- Default-Geräteauswahl: `DEVICE_GLOB=/sys/class/leds/asus::kbd_backlight`

Andere Hersteller, mehrere Keyboard-Backlight-Geräte und abweichende Helligkeitsstufen sind noch nicht validiert. Die Implementierung darf generisch über `*kbd_backlight*` suchen, die fachliche Abnahme dieser Doku bezieht sich aber auf das ASUS-Gerät.

## Schnittstellen

GNOME Mutter IdleMonitor:

- Bus: aktive Benutzer-Session
- Ziel: `org.gnome.Mutter.IdleMonitor`
- Objektpfad: `/org/gnome/Mutter/IdleMonitor/Core`
- Interface: `org.gnome.Mutter.IdleMonitor`
- Methoden: `GetIdletime`, `AddIdleWatch`, `AddUserActiveWatch`, `RemoveWatch`
- Signal: `WatchFired`

GNOME Settings Daemon Power Keyboard:

- Bus: aktive Benutzer-Session
- Ziel: `org.gnome.SettingsDaemon.Power`
- Objektpfad: `/org/gnome/SettingsDaemon/Power`
- Interface: `org.gnome.SettingsDaemon.Power.Keyboard`
- Methoden: `StepUp`, `StepDown`, `Toggle`
- Signal: `BrightnessChanged(i brightness, s source)`
- Eigenschaft: `Brightness` als `int32`
- Eigenschaft: `Steps` als `int32`

logind Manager:

- Bus: Systembus
- Ziel: `org.freedesktop.login1`
- Objektpfad: `/org/freedesktop/login1`
- Interface: `org.freedesktop.login1.Manager`
- Methoden: `ListSeats`, `ListSessions`, `GetSeat`, `GetSession`
- Signale: `SeatNew`, `SeatRemoved`, `SessionNew`, `SessionRemoved`, `PrepareForShutdown`, `PrepareForSleep`

logind Session:

- Bus: Systembus
- Objektpfad: aus `GetSession(<sid>)`
- Interface: `org.freedesktop.login1.Session`
- Eigenschaften: `User`, `Seat`, `Class`, `Type`, `Active`, `State`, `LockedHint`
- Signale: `Lock`, `Unlock`
- Property-Änderungen: `org.freedesktop.DBus.Properties.PropertiesChanged`

## Zustandsmodell

Der Dienst unterscheidet diese Zustände:

- keine aktive Sitzung
- aktive Benutzer-Sitzung entsperrt
- aktive Benutzer-Sitzung gesperrt
- Greeter oder Login-Bildschirm
- GNOME-DBus verfügbar
- GNOME-DBus nicht verfügbar
- sysfs-Gerät verfügbar
- sysfs-Gerät vorübergehend nicht verfügbar

Für aktive entsperrte GNOME-Sitzungen schreibt der Dienst zuerst über GNOME DBus. Danach wird der sysfs-Wert geprüft. Wenn GNOME den Zielwert nicht anwendet, schreibt der Dienst über sysfs und synchronisiert GNOME erneut.

Für Sitzungen ohne nutzbaren GNOME-DBus schreibt der Dienst direkt über sysfs.

Die aktive Sitzung wird über logind bestimmt:

- Bei `SEAT=auto` den Seat mit aktiver grafischer Sitzung wählen.
- Bei gesetztem `SEAT` nur diesen Seat betrachten.
- Nur Sitzungen mit `Active=true` verwenden.
- Eine entsperrte Benutzersitzung ist `Class=user` und `LockedHint=false`.
- Gesperrte Benutzersitzungen haben `Class=user` und `LockedHint=true`.
- Greeter-, Manager- und Login-Zustände sind nicht als entsperrte Benutzersitzung zu behandeln.

## Helligkeitsregeln

Der Dienst verwaltet rohe sysfs-Werte im Bereich `0..max_brightness`. GNOME verwaltet Prozentwerte im Bereich `0..100`.

Die Umrechnung erfolgt deterministisch:

- sysfs-Zielwert `0` wird als GNOME `Brightness=0` geschrieben
- positive sysfs-Zielwerte werden mit Ganzzahldivision prozentual zu `max_brightness` geschrieben
- Prozentwerte werden auf `0..100` begrenzt
- sysfs-Zielwerte werden auf `0..max_brightness` begrenzt

Formel für Rohwert zu Prozent:

```text
percent = (level * 100) / max_brightness
```

Formel für Prozent zu Rohwert:

```text
level = (percent * max_brightness + 50) / 100
```

Bei `percent > 0` wird das Ergebnis zusätzlich auf mindestens `1` begrenzt. Dadurch wird GNOME `Brightness=33` bei `max_brightness=3` korrekt zu sysfs-Wert `1`.

Beim Schreiben ist der rohe sysfs-Zielwert maßgeblich. Nach einem GNOME-DBus-Schreibvorgang muss sysfs erneut gelesen werden. Nur wenn der sysfs-Wert dem Zielwert entspricht, gilt der Schreibvorgang als erfolgreich.

Ein manueller Wert `0` in einer entsperrten Benutzer-Sitzung bleibt eine explizite Benutzerentscheidung. Der Dienst erzwingt in diesem Zustand kein Wiederanschalten.

Positive manuelle Änderungen am Sperrbildschirm oder Greeter werden für die nächste entsperrte Benutzer-Sitzung übernommen.

Für Start, Herunterfahren und fehlende aktive Sitzungen wird der gespeicherte Boot-Wert auf mindestens `1` begrenzt.

## Polling

Die aktuelle Bash-Implementierung verwendet weiterhin Polling. Der Standardwert ist:

- `POLL_INTERVAL=1`

Pro Schleife prüft der Dienst:

- aktive Seat- und Session-ID über `loginctl`
- Benutzer-ID, Session-Klasse und Sperrstatus über einen gebündelten `loginctl show-session`-Aufruf
- Idle-Zeit über `org.gnome.Mutter.IdleMonitor.GetIdletime`
- sysfs-Helligkeit für manuelle Änderungen und Persistenz

Dieser Zustand ist für den laufenden Betrieb akzeptabel, aber nicht der Zielzustand.

## Dienst-Lifecycle

Aktuelle Skriptkommandos:

- `install`: installiert Daemon und Unit, aktiviert den Dienst und startet ihn neu
- `status`: zeigt den systemd-Status
- `uninstall`: stoppt und deaktiviert den Dienst, entfernt installierte Unit und installierten Daemon, lädt `systemd` neu

`uninstall` entfernt den State unter `/var/lib/kbd-backlight-service` nicht. Damit bleibt der letzte persistierte positive Helligkeitswert erhalten, falls der Dienst später erneut installiert wird.

Nicht vorhanden:

- `disable`: Stoppen und Deaktivieren ohne Entfernen installierter Dateien
- `revert`: expliziter Rückbau auf System-/GNOME-Verhalten mit definierter Helligkeitswiederherstellung
- `purge`: Entfernen von Dienst, Daemon und State

Der aktuelle Rückweg zum normalen GNOME-/Systemverhalten ist `sudo ./scripts/kbd-backlight-service.sh uninstall`.

## Zielarchitektur

Der Zielzustand ist ein ereignisgetriebener Daemon mit einem langsamen Abgleich nur als Schutzmechanismus.

Benötigte Ereignisquellen:

- `org.gnome.Mutter.IdleMonitor.AddIdleWatch`
- `org.gnome.Mutter.IdleMonitor.AddUserActiveWatch`
- `org.gnome.SettingsDaemon.Power.Keyboard.BrightnessChanged`
- logind-DBus-Signale für aktive Sitzung, Seat und Sperrstatus
- `inotify` auf jede `brightness`-Datei der erkannten Tastaturbeleuchtungen

Die Implementierung soll mehrere Ereignisquellen sauber koordinieren können. Dafür wird Python mit DBus- und inotify-Unterstützung verwendet.

Die konkrete Umsetzung verwendet:

- `python3-dbus-next`
- `python3-asyncinotify`

Der root-Daemon darf nicht davon ausgehen, dass er direkt auf die Benutzer-Session-Busse zugreifen kann. Für Benutzerbus-Verbindungen muss ein pro aktiver Benutzer-Sitzung laufender Prozess oder Teilprozess mit Ziel-UID und Ziel-GID gestartet werden. Dieser Prozess verbindet sich mit `DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/<uid>/bus` und meldet GNOME-Ereignisse an den root-Daemon zurück. Der root-Daemon bleibt zuständig für sysfs-Schreibzugriffe, State-Dateien und systemweite logind-Ereignisse.

Der Benutzerbus-Worker darf keine sysfs-Dateien schreiben und keine State-Dateien verändern. Er kapselt ausschließlich GNOME-DBus-Kommunikation im Benutzerkontext.

`DEVICE_GLOB` begrenzt den aktuellen Dienst bewusst auf das validierte ASUS-Gerät. `POLL_INTERVAL` bleibt bis zur Umbenennung ein Kompatibilitätswert und steuert im ereignisgetriebenen Zielzustand nur noch den langsamen Reconcile-Timer. Der Reconcile-Timer darf nicht der normale Steuerpfad sein.

## Akzeptanzkriterien

- GNOME- und sysfs-Helligkeit bleiben nach Dienstschreibvorgängen synchron.
- Idle-Dimming passiert genau einmal pro Idle-Übergang.
- Aktivitäts-Restore passiert genau einmal pro Aktivitäts-Übergang.
- Manueller Wert `0` bleibt in entsperrten Benutzer-Sitzungen erhalten.
- Positive Änderungen am Sperrbildschirm oder Greeter werden in die nächste entsperrte Benutzer-Sitzung übernommen.
- Session-Wechsel erzwingen keine veraltete Helligkeit auf andere Benutzer.
- Boot- und No-Session-Zustände verwenden nie dauerhaft `0`.
- sysfs bleibt der Fallback für nicht verfügbare GNOME-Sitzungen.
- Normalbetrieb in GNOME läuft ohne schnelles Polling.
- Fehler erscheinen im Journal oder führen zu einem klaren Dienstfehler.

## Prüfung

```bash
shellcheck scripts/*.sh
bash -n scripts/kbd-backlight-daemon.sh scripts/kbd-backlight-service.sh
systemctl --no-pager --full status kbd-backlight-service.service
journalctl -u kbd-backlight-service.service -b --no-pager -n 120
```

```bash
cat /sys/class/leds/*kbd_backlight*/brightness
cat /sys/class/leds/*kbd_backlight*/max_brightness
gdbus call --session --dest org.gnome.SettingsDaemon.Power --object-path /org/gnome/SettingsDaemon/Power --method org.freedesktop.DBus.Properties.Get org.gnome.SettingsDaemon.Power.Keyboard Brightness
gdbus call --session --dest org.gnome.Mutter.IdleMonitor --object-path /org/gnome/Mutter/IdleMonitor/Core --method org.gnome.Mutter.IdleMonitor.GetIdletime
```

# ASUS Keyboard Backlight unter GNOME 50

## Plattform

Der Dienst ist für diesen Scope freigegeben:

- Gerät: `/sys/class/leds/asus::kbd_backlight`
- Maximale Rohhelligkeit: `3`
- Desktop: GNOME Shell 50
- Distribution: Ubuntu 26.04 LTS
- Unit: `kbd-backlight-service.service`

Andere Hersteller, andere LED-Namen, mehrere Keyboard-Backlights und abweichende Helligkeitsskalen sind nicht validiert.

## Systemarchitektur

Der root-Daemon verwaltet:

- logind-Systembus
- sysfs-Lesen und sysfs-Schreiben
- State unter `/var/lib/kbd-backlight-service`
- Gerätesuche über `DEVICE_GLOB`
- User-DBus-Worker
- Reconcile-Timer

Der User-DBus-Worker läuft mit Ziel-UID und Ziel-GID der aktiven relevanten Sitzung. Er verbindet sich mit:

- `XDG_RUNTIME_DIR=/run/user/<uid>`
- `DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/<uid>/bus`

Der Worker meldet GNOME-Ereignisse per JSON-Zeilen an den root-Daemon zurück und führt GNOME-Helligkeitsschreibvorgänge aus. Er liest oder schreibt keinen State und keine sysfs-Dateien.

## DBus-Schnittstellen

GNOME Mutter IdleMonitor:

- Ziel: `org.gnome.Mutter.IdleMonitor`
- Objektpfad: `/org/gnome/Mutter/IdleMonitor/Core`
- Interface: `org.gnome.Mutter.IdleMonitor`
- Methoden: `GetIdletime`, `AddIdleWatch`, `AddUserActiveWatch`
- Signal: `WatchFired`

GNOME SettingsDaemon Power Keyboard:

- Ziel: `org.gnome.SettingsDaemon.Power`
- Objektpfad: `/org/gnome/SettingsDaemon/Power`
- Interface: `org.gnome.SettingsDaemon.Power.Keyboard`
- Signal: `BrightnessChanged(i brightness, s source)`
- Eigenschaft: `Brightness` als `int32`

logind Manager:

- Ziel: `org.freedesktop.login1`
- Objektpfad: `/org/freedesktop/login1`
- Interface: `org.freedesktop.login1.Manager`
- Methoden: `ListSessions`, `GetSession`
- Signale: `SessionNew`, `SessionRemoved`, `SeatNew`, `SeatRemoved`, `PrepareForShutdown`, `PrepareForSleep`

logind Session:

- Interface: `org.freedesktop.login1.Session`
- Eigenschaften: `User`, `Seat`, `Class`, `Type`, `Active`, `State`, `LockedHint`
- Signale: `Lock`, `Unlock`
- Property-Änderungen: `org.freedesktop.DBus.Properties.PropertiesChanged`

## Sitzungslogik

Bei `SEAT=auto` wählt der Dienst eine aktive grafische Sitzung auf einem Seat. Bei gesetztem `SEAT` wird nur dieser Seat betrachtet.

Eine entsperrte Kontositzung ist:

- `Class=user`
- `LockedHint=false`
- `Active=true`

Gesperrte Kontositzungen, Greeter- und Login-Zustände sind keine entsperrten Kontositzungen.

## Helligkeitsregeln

Der Dienst speichert und entscheidet in sysfs-Rohwerten. GNOME verwaltet Prozentwerte.

Rohwert zu Prozent:

```text
percent = (level * 100) / max_brightness
```

Prozent zu Rohwert:

```text
level = (percent * max_brightness + 50) / 100
```

Zusätzliche Regeln:

- `percent <= 0` ergibt Rohwert `0`.
- `percent > 0` ergibt mindestens Rohwert `1`.
- Rohwerte werden auf `0..max_brightness` begrenzt.
- Prozentwerte werden auf `0..100` begrenzt.
- Nach GNOME-Schreibvorgängen wird sysfs geprüft.
- Wenn GNOME den Zielwert nicht in sysfs abbildet, schreibt der root-Daemon sysfs und synchronisiert GNOME erneut.

## Zustandsregeln

Entsperrte Kontositzung:

- nutzt den pro Konto gespeicherten positiven Wert
- dimmt bei Idle auf `0`
- stellt bei Aktivität den letzten sichtbaren Konto-Wert wieder her
- respektiert manuelles `0`
- persistiert positive manuelle Änderungen pro UID

Sperrbildschirm und Greeter:

- werden beim Eintritt einmal auf `BOOT_LEVEL` gesetzt
- erlauben danach Änderungen bis zum Sitzungswechsel
- persistieren keine Helligkeitsänderungen
- überschreiben keine Konto-Werte

Keine aktive Sitzung, Boot und Herunterfahren:

- verwenden `BOOT_LEVEL`
- persistieren nie `0`

## State

Der State-Ordner ist:

- `/var/lib/kbd-backlight-service`
- Modus `0700`

Konto-Helligkeiten werden pro UID und Gerät gespeichert. Der Dateiname besteht aus dem bereinigten Gerätenamen und der UID, zum Beispiel:

- `/var/lib/kbd-backlight-service/asus__kbd_backlight.uid-1000.level`

Fehlende oder ungültige Konto-Dateien fallen auf `BOOT_LEVEL` zurück. Runtime-Pakete, die durch den Installer neu installiert wurden, stehen in:

- `/var/lib/kbd-backlight-service/runtime-packages.installed`

`disable`, `uninstall` und `revert` löschen keine Konto-Helligkeiten.

## Unit-Härtung

Die installierte Unit nutzt unter anderem:

- `NoNewPrivileges=yes`
- `PrivateTmp=yes`
- `ProtectSystem=strict`
- `ProtectHome=read-only`
- `ReadWritePaths=/sys/class/leds /var/lib/kbd-backlight-service`
- `ReadOnlyPaths=/run/user /run/dbus`
- `RestrictAddressFamilies=AF_UNIX`
- `CapabilityBoundingSet=CAP_SETUID CAP_SETGID`
- `UMask=0077`

## Konfiguration

Standardwerte:

- `SEAT=auto`
- `TIMEOUT_MS=6000`
- `BOOT_LEVEL=1`
- `POLL_INTERVAL=10`
- `STATE_DIR=/var/lib/kbd-backlight-service`
- `DEVICE_GLOB=/sys/class/leds/asus::kbd_backlight`

`STATE_DIR` ist absichtlich fest auf `/var/lib/kbd-backlight-service` begrenzt. `DEVICE_GLOB` muss unter `/sys/class/leds` liegen und darf keine Leerzeichen, kein `..` und keine nicht unterstützten Zeichen enthalten.

## Betrieb

Status:

```bash
systemctl --no-pager --full status kbd-backlight-service.service
```

Journal:

```bash
journalctl -u kbd-backlight-service.service -b --no-pager -n 120
```

sysfs:

```bash
cat /sys/class/leds/asus::kbd_backlight/brightness
cat /sys/class/leds/asus::kbd_backlight/max_brightness
```

GNOME-Helligkeit in der aktiven Sitzung, falls `gdbus` vorhanden ist:

```bash
gdbus call --session \
  --dest org.gnome.SettingsDaemon.Power \
  --object-path /org/gnome/SettingsDaemon/Power \
  --method org.freedesktop.DBus.Properties.Get \
  org.gnome.SettingsDaemon.Power.Keyboard Brightness
```

## Journalhinweise

`GNOME idle unavailable` in einer Greeter-Sitzung ist zulässig, wenn GDM dort keinen Mutter IdleMonitor anbietet. Der Greeter wird beim Eintritt auf `BOOT_LEVEL` gesetzt; danach werden Greeter-Änderungen nicht vom Konto-State übernommen.

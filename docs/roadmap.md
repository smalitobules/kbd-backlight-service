# Roadmap

## Produktionsstatus

Der Dienst ist für diesen Scope produktionsbereit:

- ASUS-Gerät `/sys/class/leds/asus::kbd_backlight`
- GNOME Shell 50
- Ubuntu 26.04 LTS
- einzelne aktive grafische GNOME-Sitzung pro Seat
- sysfs-Maximum `3`

## Abnahmekriterien

- Installation über `sudo ./scripts/kbd-backlight-service.sh install`
- Service-Status `active (running)`
- Journal ohne wiederkehrende Fehler
- Idle-Dimming genau einmal pro Idle-Übergang
- Aktivitäts-Restore genau einmal pro Aktivitäts-Übergang
- GNOME `Brightness` und sysfs `brightness` nach Dienstschreibvorgängen synchron
- manuelles `0` in entsperrten Kontositzungen bleibt erhalten
- Konto-Helligkeit wird pro UID wiederhergestellt
- Greeter und Sperrbildschirm starten mit `BOOT_LEVEL`
- Greeter- und Sperrbildschirmänderungen überschreiben keine Konto-Werte
- Boot, Herunterfahren und fehlende aktive Sitzungen verwenden `BOOT_LEVEL`
- `disable`, `uninstall` und `revert` löschen keine Konto-Persistenz

## Nächste Ziele

### Paketierung

- Debian-Paket mit postinst/prerm-Integration
- Versionierung der installierten Dateien
- automatische Unit-Aktualisierung ohne manuelles Entfernen alter Dateien

### Konfiguration

- separate Konfigurationsdatei unter `/etc`
- Installer-Unterstützung für `TIMEOUT_MS`, `BOOT_LEVEL` und `POLL_INTERVAL`
- validierte Statusausgabe für wirksame Konfiguration

### Geräteabdeckung

- Validierung weiterer ASUS-Modelle
- Validierung von Geräten mit `platform::kbd_backlight`
- Tests für `max_brightness` größer als `3`
- explizite Behandlung mehrerer Keyboard-Backlight-Geräte

### Betrieb

- kompakte Diagnoseausgabe im Lifecycle-Skript
- optionales `purge`-Kommando mit expliziter State-Löschbestätigung
- dokumentierte Recovery-Schritte für beschädigte State-Dateien

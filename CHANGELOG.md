# Änderungen

Alle nennenswerten Änderungen an diesem Projekt. Versionen nach [Semantic Versioning](https://semver.org/lang/de/).

## [0.1.0] – 2026-11-08

### Neu
- **Weltkugel mit Pinnadeln:** Fotos aus Synology Photos erscheinen an ihren Aufnahmeorten auf einem drehbaren 3D-Globus.
  Nahe Fotos werden zu einer Nadel mit Zahl zusammengefasst; grün = meine Fotos, rot = gemeinsame.
- **Galerie** pro Nadel (nach Tag oder Monat gruppiert) und **Großansicht** mit Blättern, Aufnahmedaten,
  „Auf dem Globus zeigen“ und Original-Download.
- **Filter** nach Zeitraum (Jahre) und Bereich (alle / meine / gemeinsame).
- **Fotoordner durchsuchen:** gemeinsame Fotos (`/volume*/photo`) und persönliche Fotos (`/volume*/homes/<benutzer>/Photos`),
  Exif aus JPEG, HEIC/HEIF, PNG, TIFF, DNG, NEF, ARW und CR2 in reinem Python. Nächtliche Suche plus „Jetzt suchen“,
  ab dem zweiten Mal nur neue und geänderte Dateien.
- **Rechte wie in DSM:** persönliche Fotos nur für den Besitzer, gemeinsame nach den Ordnerrechten
  (`synoacltool -get-perm`), Ausweichlösung „alle DSM-Benutzer“, Rechte-Test in den Einstellungen.
- **Vorschaubilder** von Synology Photos (`@eaDir`), notfalls aus den Exif-Daten.
- **Offline-Kugel** mit Ländergrenzen, wenn der Kartendienst (Standard: OpenFreeMap) nicht erreichbar ist.
- DSM-Fenster mit Single Sign-on, Anmeldung mit DSM-Konto (inkl. 2FA), vier Designs, Firmenname und Logo,
  nächtliche Sicherung mit Wiederherstellen, Änderungsprotokoll, Updates übers Paket-Zentrum, Port änderbar.

[0.1.0]: https://github.com/rinkelzz/foto-globus/releases/tag/v0.1.0

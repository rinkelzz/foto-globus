# Änderungen

Alle nennenswerten Änderungen an diesem Projekt. Versionen nach [Semantic Versioning](https://semver.org/lang/de/).

## [0.2.0] – 2026-11-08

### Neu
- **Ortsnamen** wie „Palma, Spanien“ – offline aus GeoNames (alle Orte ab 1.000 Einwohnern), nichts verlässt die NAS.
  Bekannte Orte heißen deutsch (München, Rom, Tokio, Kapstadt …), Stadtteile verlieren gegen die Großstadt
  („New York“ statt „Hell's Kitchen“), abgelegene Orte bekommen wenigstens das Land. Vorhandene Fotos erhalten ihre
  Ortsnamen nach dem Update automatisch.
- **Suche nach Ort oder Land** oben im Globus: Treffer fliegen hin und öffnen die Galerie.
- **Statistik „Meine Welt“** (📊): Länder, Orte, Fotos und Videos, Balken pro Jahr (Klick filtert), Top-Orte und
  Länderliste – jeweils mit Klick zum Hinfliegen. Berücksichtigt die gesetzten Filter.
- **Besuchte Länder** werden auf dem Globus eingefärbt (abschaltbar).
- **Videos** (MP4, MOV, M4V, 3GP): Aufnahmeort und -zeit von iPhone, Android und Kameras (`©xyz`, Apple-Metadaten,
  3GPP `loci`), Vorschaubild mit ▶ und Länge, **Abspielen in der Großansicht** mit Spulen. Verwendet Synologys
  kleinere Videofassung, wenn vorhanden.
- Galerie zeigt den Ortsnamen als Titel und Fotos/Videos getrennt gezählt.

### Geändert
- Anleitung zu den Ordnerrechten (README, Installations-Assistent, Einstellungen) an die Begriffe in DSM angepasst:
  „Interner Systembenutzer“ → bei `fotoglobus` **Schreibgeschützt** (= nur lesen).
- Tests für Python 3.9 laufen auf Ubuntu 22.04 (ubuntu-latest bietet 3.9 nicht mehr an).

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

[0.2.0]: https://github.com/rinkelzz/foto-globus/releases/tag/v0.2.0
[0.1.0]: https://github.com/rinkelzz/foto-globus/releases/tag/v0.1.0

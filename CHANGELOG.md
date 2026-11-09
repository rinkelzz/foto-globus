# Änderungen

Alle nennenswerten Änderungen an diesem Projekt. Versionen nach [Semantic Versioning](https://semver.org/lang/de/).

## [0.5.1] – 2026-11-09

### Sicherheit
- **Schlüssel fürs DSM-Fenster** (`.proxy_secret`) ist nur noch für den Paketbenutzer lesbar (vorher für alle
  lokalen Benutzer der NAS). Wer ihn lesen konnte, hätte sich gegenüber der App als beliebiger DSM-Benutzer ausgeben
  können – allerdings nur von der NAS selbst aus.
- **Nur noch auf der NAS selbst erreichbar** (127.0.0.1) statt im ganzen Netzwerk. DSM-Fenster, Reverse Proxy und
  Paket-Zentrum funktionieren wie bisher. Direkter Zugriff über `http://nas:8790` lässt sich unter Einstellungen →
  Karte & Anmeldung wieder einschalten (gilt nach Neustart des Pakets).
- CSRF-Schutz vertraut `X-Forwarded-Host` nicht mehr.
- Entzogene Ordnerrechte gelten nach spätestens **5 Minuten** (vorher 30).
- Anmeldungen per Passwort laufen nach **7 Tagen** ab (vorher 30).
- **Datensicherung ohne Sitzungen und ohne Fotoindex** (Pfade und Aufnahmeorte aller, auch persönlicher Fotos).
  Nach dem Wiederherstellen startet die Suche automatisch; angemeldete Benutzer bleiben angemeldet.

## [0.5.0] – 2026-11-09

### Neu
- **Doppelte Fotos nur einmal:** Exakte Kopien (gleiche Größe und Prüfsumme) erscheinen auf dem Globus, in Galerie,
  Statistik, Suche und Reisen nur einmal. Liegt ein Foto auch im eigenen Bereich, zählt die eigene Kopie, sonst die
  älteste Datei. Die Dateien selbst bleiben unberührt.
- Prüfsummen werden nur für Dateien berechnet, deren Größe mehrfach vorkommt (nur die können Kopien sein); große
  Videos über Stichproben. Nach dem Update läuft das einmal im Hintergrund, danach bei jeder Suche nur für Neues.
- Unter Einstellungen → Suche steht, wie viele doppelte Dateien es gibt.

## [0.4.0] – 2026-11-09

### Neu
- **Reise nachspielen** (▶ in der Reise): Titelkarte, dann fliegt die Kamera von Halt zu Halt, die Route zeichnet sich
  mit, an jedem Halt laufen bis zu 6 seiner Fotos als Diashow. Steuerung wie ein Player: Pause/Weiter (Leertaste),
  Zurück/Weiter (Pfeiltasten), Tempo Langsam/Normal/Schnell, Vollbild (F), Beenden (Esc). Wer die Karte anfasst,
  pausiert die Fahrt.
- **Jahresrückblick:** alle Reisen eines Jahres nacheinander (▶ Jahresrückblick in der Reiseliste).
- **Heatmap** (🔥): Umschalter zwischen Pinnadeln und Heatmap; Zeitraum- und Bereichsfilter gelten weiter.

## [0.3.0] – 2026-11-09

### Neu
- **Reisen** (🧳): werden automatisch erkannt – Fotos mehr als 100 km von Zuhause, mit höchstens 2 Tagen ohne Fotos
  dazwischen, mindestens 3 Fotos. Namen wie „Italien, Mai 2023“ oder „Hamburg, März 2025“.
- **Zuhause** wird automatisch bestimmt (Ort mit den meisten Fototagen) und lässt sich per Klick auf den Globus
  selbst setzen.
- **Route:** Eine Reise zeigt ihren Weg als Linie von Halt zu Halt (Tag 1 Rom → Tag 4 Florenz → Tag 6 Venedig),
  dazu nur ihre Fotos auf dem Globus und in der Galerie.
- Reisen **umbenennen, teilen, zusammenführen, ausblenden** – Änderungen bleiben bei jeder neuen Suche erhalten;
  „Alle Änderungen zurücksetzen“ erkennt neu.
- **Satellitenbild** (🛰️): Esri ohne Schlüssel oder MapTiler mit eigenem Schlüssel, einstellbar unter
  Karte & Anmeldung. Die Wahl merkt sich der Browser.
- **In Synology Photos öffnen** in der Großansicht: im DSM-Fenster direkt im Ordner des Fotos, sonst im richtigen
  Bereich (Adresse von Synology Photos in den Einstellungen).

### Behoben
- Direkt nach „Jetzt nach Fotos suchen“ zeigte die Suche manchmal kurz „läuft nicht“ an.

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

[0.5.1]: https://github.com/rinkelzz/foto-globus/releases/tag/v0.5.1
[0.5.0]: https://github.com/rinkelzz/foto-globus/releases/tag/v0.5.0
[0.4.0]: https://github.com/rinkelzz/foto-globus/releases/tag/v0.4.0
[0.3.0]: https://github.com/rinkelzz/foto-globus/releases/tag/v0.3.0
[0.2.0]: https://github.com/rinkelzz/foto-globus/releases/tag/v0.2.0
[0.1.0]: https://github.com/rinkelzz/foto-globus/releases/tag/v0.1.0

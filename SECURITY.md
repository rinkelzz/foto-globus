# Sicherheit

Bitte Sicherheitslücken **nicht** als öffentliches Issue melden, sondern über
[GitHub → Security → Report a vulnerability](https://github.com/rinkelzz/foto-globus/security/advisories/new).
Ich melde mich so schnell wie möglich.

Unterstützt wird jeweils die neueste Version unter [Releases](https://github.com/rinkelzz/foto-globus/releases).

## Wie der Foto-Globus Fotos schützt

- **Fotos nur mit DSM-Konto:** Welche Fotos jemand sieht, hängt am DSM-Konto, das DSM selbst bestätigt hat – per
  Single Sign-on im DSM-Fenster oder per Anmeldung mit dem DSM-Passwort. Das lokale Konto `admin` sieht keine Fotos.
- **Persönliche Fotos** (`homes/<benutzer>/Photos`) sieht nur der Besitzer.
- **Gemeinsame Fotos** nur, wenn DSM für den Ordner und alle Ordner darüber Leserechte meldet
  (`synoacltool -get-perm`). Unklare Antworten zählen als „kein Zugriff“.
- Vorschaubilder und Originale werden nur über die Foto-ID ausgeliefert, nach derselben Rechteprüfung – es gibt keine
  Pfad-Parameter. Fremde Fotos antworten mit „nicht gefunden“, damit nichts über ihre Existenz verraten wird.
- Der Foto-Globus liest die Fotoordner nur; er schreibt dort nichts.

## Hinweise für den Betrieb

- Die App lauscht standardmäßig nur auf **127.0.0.1** (DSM-Fenster, Reverse Proxy und Paket-Zentrum auf der NAS).
  Direkten Zugriff aus dem Netzwerk nur einschalten, wenn nötig – er ist unverschlüsselt (http).
- Nach außen nur per **HTTPS** (Reverse Proxy mit Zertifikat) freigeben, nie Port 8790 direkt.
- Der Reverse Proxy sollte der von DSM auf derselben NAS sein: Nur Anfragen von 127.0.0.1 dürfen die echte
  Absenderadresse (`X-Forwarded-For`) mitliefern. Bei einem Proxy auf einem anderen Gerät greift die Login-Sperre
  (5 Fehlversuche pro Adresse, 10 pro Benutzername in 15 Minuten) nur noch pro Benutzername.
- DSM-Passwörter werden nur an DSM auf der NAS selbst geschickt (127.0.0.1/localhost/::1, ohne Proxy-Variablen und
  ohne Weiterleitungen) und nirgends gespeichert.
- Änderungen per Login-Cookie werden nur von der eigenen Seite angenommen (Schutz vor CSRF über `Sec-Fetch-Site`
  bzw. `Origin`). Läuft die App hinter einem Proxy, der den `Host`-Header umschreibt, die **Öffentliche Adresse**
  in den Einstellungen eintragen.
- Der Schlüssel für das DSM-Fenster (`.proxy_secret` im Paketordner) ist nur für den Paketbenutzer lesbar (`0600`)
  und wird nur von Verbindungen über 127.0.0.1 ohne `X-Forwarded-For` angenommen, also nur von `app.cgi` auf der
  NAS selbst.
- Gemeinsame Fotos werden nach den DSM-Ordnerrechten gezeigt; das Ergebnis wird höchstens 5 Minuten
  zwischengespeichert. Anmeldungen per Passwort laufen nach 7 Tagen ab.
- Die Kartenbilder lädt der Browser vom eingestellten Kartendienst (Standard: OpenFreeMap). Der sieht, welche Gegend
  angezeigt wird, aber keine Fotos und keine Foto-Koordinaten. Wer das nicht möchte, lässt „Kartenstil“ leer – dann
  zeigt der Globus nur die eingebaute Offline-Kugel.
- Updates kommen aus den GitHub-Releases dieses Repos. Sie sind nicht zusätzlich signiert – geschützt sind sie durch
  HTTPS und das (per Zwei-Faktor gesicherte) GitHub-Konto des Maintainers.
- Der Foto-Globus speichert keine Zugangsdaten (kein Mailversand). Die Datensicherungen enthalten Einstellungen,
  Benutzer (lokales Admin-Passwort nur als PBKDF2-Hash), Zuhause und bearbeitete Reisen – **keine** Sitzungen und
  **keinen** Fotoindex. Den Sicherungsordner trotzdem nur für Admins freigeben.

# Security (English)

Please report vulnerabilities privately via GitHub's *Report a vulnerability* button, not as a public issue.

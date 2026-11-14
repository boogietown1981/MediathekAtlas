# API v1 (seit 0.6.2)

Stand: 14.11.2026, Phase C aus `docs/REVIEW_05107.md`. Die Schnittstelle ist für Abspieler und Apps außerhalb des Browsers gedacht (Fernseher, Telefon, Skripte). Die Weboberfläche nutzt weiter ihre eigenen Adressen.

## Zugang

| Wer | Nachweis | Gilt für |
|---|---|---|
| Gerät oder App | Kopfzeile `Authorization: Bearer <Geräteschlüssel>` | alle Adressen unter `/api/v1` |
| Videoplayer ohne Kopfzeilen | `?ticket=<ticket>` aus `/api/v1/play` | nur `/api/v1/stream` und `/api/v1/file` |
| Weboberfläche | Anmeldung und `X-Atlas-Token` | alle Adressen unter `/api/v1` |

- Geräteschlüssel entstehen unter **Verwaltung → System → Geräte und Apps**. Der Schlüssel wird einmal angezeigt. Gespeichert wird nur sein SHA-256-Wert in `api_keys.json` (nur für den Besitzer lesbar), dazu Name, Erstelldatum und letzte Nutzung.
- Ein Geräteschlüssel öffnet nichts außerhalb von `/api/v1`: keine Einstellungen, keine Katalogabrufe, keine Schlüsselverwaltung, nicht die Seite selbst.
- Löschen des Eintrags entzieht den Zugriff sofort. Ein bereits ausgegebenes Ticket läuft weiter, höchstens zwölf Stunden und nur bis zum nächsten Neustart.
- Ohne Schlüssel antwortet jede Adresse unter `/api/v1` mit 401. Unbekannte Adressen werden ohne Schlüssel nicht verraten.
- Im Netzwerkmodus zählen falsche Schlüssel wie falsche Passwörter: nach 10 Fehlversuchen ist die Adresse des Aufrufers zehn Minuten gesperrt.
- Im Einzelplatzmodus (nur 127.0.0.1) gilt zusätzlich die Host-Prüfung wie bisher; Geräte im Netz erreichen den Server dort ohnehin nicht.
- Die Verbindung ist unverschlüsselt (HTTP), solange kein HTTPS davor steht. Im Heimnetz vertretbar, von außen nur über VPN oder einen Reverse-Proxy mit HTTPS. Eigenes HTTPS ist der nächste Schritt in Phase C.

## Adressen

`GET /api/v1` liefert diese Liste maschinenlesbar (`endpoints` mit `method`, `path`, `summary`, `parameters`) und die Version des Servers.

| Methode | Adresse | Zweck | Parameter bzw. Eingabe | Modell wie |
|---|---|---|---|---|
| GET | `/api/v1` | Beschreibung, Version | | |
| GET | `/api/v1/catalog` | Katalog aller Quellen, zusammengeführt | `kind` (movies, series), `q`, `genre`, `sort`, `collection`, `offset` | `/api/unified` |
| GET | `/api/v1/title` | Titelseite eines Plattform-Titels | `source`, `id` | `/api/portal-title` |
| GET | `/api/v1/show` | Serie der Mediatheken mit Staffeln | `show`, `archive` | `/api/show` |
| GET | `/api/v1/live` | Live-Sender, nach Sender zusammengeführt | `q`, `provider`, `group` | `/api/live-tv` |
| GET | `/api/v1/play` | Wiedergabe-Auskunft mit Ticket | eine Kennung (`offer`, `job`, `netzkino`, `pluto`, `justwatch`, `rakuten`, `joyn`, `toggo`, `crunchyroll`, `samsung`, `plex`, `servustv`, `rtlplus`, `youtube`), `quality` | `/api/play` |
| GET | `/api/v1/stream` | Videodaten (MP4; mit `raw=1` die lokale Datei) | wie `play`, dazu `t`, `session`, `quality`, `raw`, `ticket` | `/api/stream` |
| GET | `/api/v1/file` | Fertigen Download laden oder abspielen | `id`, `inline`, `ticket` | `/api/download-file` |
| GET | `/api/v1/downloads` | Fertige Downloads | | eigene, schlanke Liste |
| GET | `/api/v1/watch` | Merkliste, Weiterschauen, Positionen | | `/api/watch` |
| POST | `/api/v1/watch-progress` | Abspielposition melden | `key`, `pos`, `duration`, `done`, `info` | `/api/watch-progress` |
| POST | `/api/v1/watch-mark` | Merken oder Anheften | `key`, `favorite`, `pinned`, `info` | `/api/watch-mark` |
| POST | `/api/v1/watch-forget` | Aus Weiterschauen entfernen | `key` | `/api/watch-forget` |

POST-Eingaben sind JSON-Objekte bis 100 kB. Fehler kommen als `{"error": "…"}` mit 400, 401, 404, 429, 502 oder 503.

## Wichtige Felder

- **`/api/v1/catalog`**: `items` (je Titel `title`, `year`, `offers` mit `source` und `item`), `total`, `offset`, `page`, `counts`, `genre_counts`, `names` (Anzeigenamen der Quellen), `errors`, `pending`.
- **`/api/v1/play`**: `mode` (z. B. `direct`), `origin` (`local` oder online), `src`, `remux`, `levels`, `hls`, `live`, `ticket`. Beginnt `src` oder `remux` mit `/api/v1/stream`, hängt der Client `&ticket=<ticket>` an. Externe Adressen (direkter Stream des Anbieters) bleiben unverändert. Titel mit Kopierschutz liefern keinen Stream, sondern den Link zum Anbieter.
- **`/api/v1/downloads`**: `items` mit `id`, `title`, `year`, `kind`, `source`, `file`, `size_bytes`, `stored_at`, `watched_done`, `favorite`, `pinned`, `watch_key`, `offline_until`, `play`. Keine Ordner des Servers.
- **`/api/v1/watch`**: `continue`, `marked`, `progress`, `marks`. Der Schlüssel `key` hat die Form `<quelle>:<kennung>`, wie ihn die Weboberfläche vergibt.

## Beispiel

```
curl -H "Authorization: Bearer atlas_…" http://nas:8730/api/v1/catalog?kind=movies&q=kino
curl -H "Authorization: Bearer atlas_…" "http://nas:8730/api/v1/play?job=<id>"
# Antwort: {"src": "/api/v1/stream?job=<id>&raw=1", "ticket": "1794700000.ab12…", …}
# Player öffnet: http://nas:8730/api/v1/stream?job=<id>&raw=1&ticket=1794700000.ab12…
```

## Zusagen und Grenzen

- Adressen und die genannten Felder bleiben in v1 erhalten. Neue Felder können dazukommen; Clients ignorieren Unbekanntes.
- Die Modelle sind die der Weboberfläche. Felder, die oben nicht genannt sind, können sich ändern.
- Noch nicht in v1: Downloads anstoßen, Suche über Anbietergrenzen mit Filtern je Gerät, Benutzerprofile. Bildadressen (`poster`) zeigen auf die Server der Anbieter.
- Nicht geprüft: echte Clients (tvOS, Android), Wiedergabe umgewandelter Streams über `/api/v1/stream` mit Ticket (gleicher Code wie `/api/stream`, getestet sind lokale Dateien).

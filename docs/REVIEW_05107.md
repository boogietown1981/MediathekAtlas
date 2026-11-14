# Review 0.5.107, Regressionstest und Architektur-Ausblick

Stand 14. November 2026. Ausführliche Fassung mit Schaubildern: https://claude.ai/artifact/CZBerM8ZA94wDN4nQp3xnf

## Regressionstest 0.5.107

1135 Unit-Tests bestanden (4 übersprungen: macOS-Build, yt-dlp), 104 Tests des alten Bausatzes, 4 UI-Smoketests, Klicktest Chromium ohne Befund; CI zu PR #50 in allen 10 Jobs grün (Firefox, WebKit, Python 3.9 bis 3.14, macOS 15, NAS-Pakete). Leerlauf: 52 Threads, rund 65 MB, Startseite 511 KB. Nicht geprüft: echtes Safari, NAS-Hardware, Windows, Live-Anbieter.

## Befunde

| Stufe | Befund | Stand |
| --- | --- | --- |
| 1 | Neuabruf nach Update nur bei Plex, ServusTV, RTL+ | behoben in 0.5.108 (alle Anbieter) |
| 1 | `:has()` ohne Rückfall | behoben in 0.5.108 |
| 1 | Ed25519 nimmt nicht-kanonische Punkte an | behoben in 0.5.108 |
| 1 | Ungenutzte Importe | behoben in 0.5.108 (Tests) |
| 2 | Elf Anbieter-Module kopieren dasselbe Gerüst (`_connect`, `_get/_set`, `state`, `start_sync`, `loop`, `_run`) | Phase B |
| 2 | 23 SQLite-Dateien, nur `catalog.db` und YouTube mit WAL | Phase B |
| 2 | Je Anbieter ein Schleifen-Thread (52 Threads im Leerlauf) | Phase B |
| 2 | `server.py` mit rund 130 Pfaden in einer if-Kette | Phase B |
| 2 | Startseite 511 KB, alle Skripte eingebettet (Notlösung aus 0.5.77) | Phase B |
| 2 | Netzwerkmodus nur HTTP, Sitzungen im Speicher | Phase C |
| 2 | `vendor/archivemedia` neben `vendor/archive_portals` (Überschneidung: `catalog_identity.py`, `media_probe.py`, verschiedene Fassungen in Gebrauch) | Phase B |
| 2 | Altbestand `integration/preview`, Workflow `assemble-053111.yml` | entfernt in 0.5.108 |
| 3 | `main` auf 0.5.40, sechs gestapelte PRs | erledigt 14.11.2026 |

## Phasen

- **A Konsolidieren (0.5.108):** `main` = Sammelstand, Altbestand raus, Kleinfixes.
- **B Anbieter-Rahmen (0.6.0):** `providers/base.py` (Datenbank mit WAL, Status, Abruf, Neuabruf nach Update, Pause), ein Planer-Thread mit Profil für schwache Hardware, Routen-Tabelle statt if-Kette, Skripte als Bündel mit Prüfsumme im Namen. Migration Anbieter für Anbieter, zuerst Plex, ServusTV, RTL+; vorhandene Tests müssen unverändert bestehen.
- **C Schnittstelle und Betrieb (0.6.x):** API v1 (Katalog, Wiedergabe, Downloads, Merkliste), HTTPS und dauerhafte Sitzungen im Netzwerkmodus, SRM-Paket, Test auf echter Synology- und QNAP-Hardware.
- **D Verbund und Clients (0.7):** HomeTube-Abgleich über das Verbund-Journal, tvOS-Abspieler auf API v1, danach Android/iOS; Serien-Abos, Untertitel, Besetzung (TMDB), eigene Videos mit Rechteangabe.

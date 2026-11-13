# Review 0.5.77 und Lückenanalyse gegen HomeTube und Archive Media

Stand 13. November 2026. Ausführliche Fassung mit allen Tabellen: https://claude.ai/artifact/T5o8N2wQKCHyWyGpKFTvnn

## Ergebnis des Reviews

849 Tests bestanden, alle Ansichten öffnen in Chromium ohne Skriptfehler, kein Aufruf der Oberfläche ohne Serverroute. Kein Befund blockiert den Betrieb.

| Stufe | Befund | Stand |
| --- | --- | --- |
| 1 | `backdrop-filter` ohne `-webkit-`-Vorsatz | behoben in 0.5.81 |
| 1 | `@container` ohne Rückfall für Safari vor 16 und Firefox vor 110 | behoben in 0.5.81 |
| 1 | `:has()` ohne Rückfall (Safari vor 15.4, Firefox vor 121) | offen; betrifft nur das Ausblenden einzelner Kachel- und Titelseitenteile |
| 1 | `/api/candidates` liest den Cache und verwirft das Ergebnis | behoben in 0.5.81 |
| 1 | 20 ungenutzte Importe | behoben in 0.5.81; `core.py` bleibt, dort sind es Weitergaben an andere Module |
| 1 | 4 Funktionen ohne Aufrufer, 4 ungenutzte Konstanten | offen |
| 2 | Je Plattform fünf fast gleiche Routen und ein eigener Thread-Start in `server.py` | offen (Plattform-Registratur) |
| 2 | `netzkino.js` und `netzkino_detail.js` neben dem gemeinsamen `portal_panel.js` | offen |
| 2 | `vendor/archivemedia` (0.10.12) und `vendor/archive_portals` (0.10.53) doppelt | offen |
| 2 | `netzkino_downloads` und `netzkino_enrichment.analyze` bedienen alle Plattformen | offen (neutrale Namen) |
| 2 | Netzwerkmodus: Sitzungen nur im Arbeitsspeicher, nur HTTP | offen |
| 2 | Kein Klicktest der Oberfläche in der CI, Safari und Firefox nie geprüft | offen |
| 3 | 44 Pakete (625 MB) in `downloads/` im Git, alter Bausatz in `integration/preview` | braucht Freigabe |
| 3 | Gestapelte offene Pull Requests, `main` bei 0.5.40 | braucht Freigabe |

## Fehlend aus Archive Media 0.10.53 (17 von 36 Modulen)

selection_matrix (Staffel-Auswahl), uploader_priority und discovery_queue (Uploader weiterverfolgen), series_merge, year_repair, anime_match, work_title_queries, clean_scan, scan_recovery, catalog_fallback, catalog_transfer, bluray_playlist, multi_catalog, catalog_taxonomy, catalog_enrichment (Audio, Bücher, Software), clean_rebuild, live_telemetry (entfällt, als Protokoll vorhanden). `container_tracks` liegt bei, wird aber nicht aufgerufen.

## Fehlend aus HomeTube 0.1.0-dev.1, MeshSync und Jellyfin Encoder

| Funktion | Stand |
| --- | --- |
| Favoriten, Anheften, zuletzt gesehen | übernommen in 0.5.81 (`watch_state.py`) |
| Speicherregeln mit Platzbudget und Aufräum-Vorschlag | übernommen in 0.5.81 (`storage_policy.py`), ohne selbsttätiges Löschen |
| Umwandeln in 1080p, 720p, 480p (Encoder) | offen |
| Signierter Archivnachweis je Datei, gezielte Übertragung an ein zweites System | offen |
| Eigene Videos mit Rechteangabe aufnehmen | offen |
| Systemmonitor, helles Design | offen |
| Paket für Synology-Router (SRM) | offen |

## Reihenfolge

1. Aufräumen und Merkliste (0.5.81)
2. Speicherübersicht (0.5.81)
3. Archive.org-Erkennung: Jahr, Suchtitel, Serien zusammenführen, Anime, Spuren vor dem Download
4. Staffel-Auswahl für Archive.org, Uploader weiterverfolgen
5. Plattform-Registratur, Netzkino auf das gemeinsame Panel
6. Umwandeln (Encoder)
7. Archivkopie im Verbund mit Prüfsumme und Nachweis
8. Helles Design, Systemmonitor, Klicktest in der CI mit Firefox und WebKit
9. Audio, Hörbücher und Bücher von Archive.org, Austausch des Bestands als Datei

# MediathekAtlas 0.5.31.11 – Mediatheken-Dashboard, Erkennungsgruppen, Queue (Test)

## Warum diese Version

In der gemeinsamen Katalogansicht der Vorversion wurden die bisherigen Scannerkennzahlen, „Letzte Erkennung“ und der Anbieterstatus hinter dem aufklappbaren „Erweiterten Mediatheken-Katalog“ verborgen. Der neue Patch rückt das tatsächliche Status-DOM (kein Snapshot, keine doppelt gepflegten Zähler) wieder an die Spitze der Hauptansicht. Er erscheint in **Mediatheken** und **Gesamt**, wobei die Kennzahlen ausdrücklich nur den **Mediatheken-Bestand** betreffen. In **Netzkino** bleibt der Mediatheken-Scanner ausgeblendet, Netzkino besitzt seine eigene Katalogdiagnose.

### Darstellung unter „Letzte Erkennung“

Die zehn bislang vertikal angeordneten Zähler werden in vier responsive Gruppen aufgeteilt:

- **Worker & Scan:** Hauptworker und Episodenworker, jeweils aktiv/konfiguriert.
- **Erkennungsqualität:** identifizierte und vollständig zugeordnete Werke/Serienepisoden seit Start.
- **Episoden & Senderbelege:** gesamte/fällige Queue, durchgeführte Prüfungen, Senderbelege, bestätigte Senderfolgen und Kurzvideos.
- **Fehler & Wiederholungen:** SQLite-Sperrkonflikte und aussagekräftiger Nullstatus.

Die zuletzt geprüfte Sendung inklusive Fehlerhinweis bleibt oben. Anbieter-/IMDb-Status sitzt daneben; bei schmalen Fenstern stapelt sich beides. Der alte Suchbaum samt Downloads und Scanneraktionen bleibt im erweiterten Bereich erhalten.

## Backendkorrekturen

- **Episodenwarteschlange:** Innerhalb eines beschränkten Fensters der 48 ältesten fälligen und nicht gesperrten Aufgaben priorisiert die App eindeutige Staffel-/Folgenangaben vor reinen Serienidentitäten. Eine manuell gesetzte Priorität gewinnt immer. Die App verändert deshalb **keine** `next_try`-Zeitstempel, `attempts`, `works.state` oder bestehenden Queue-Reihenfolgen in der Datenbank. Ein vorhandener Rückstand von über 200.000 Episoden ist damit nicht plötzlich abgearbeitet; eine Erfolgsquote darf erst nach längerem echten Lauf bewertet werden.
- **TMDB:** HTTP 404 einer einzelnen Staffel verwirft nicht mehr die gesamte Serienmetadatenantwort. Es entsteht ein `tmdb_season_unavailable`-Diagnoseereignis, die Staffel-/Folgenliste bleibt ausdrücklich unvollständig, Episoden werden nicht automatisch bestätigt. Andere Fehler wie 429/5xx gehen weiter an die etablierte Retry-/Pause-Logik.
- **OMDb:** Eine Pause zeigt ihren tatsächlichen Grund („Schlüssel abgelehnt“, „Schlüssel nicht aktiviert“, „Anfragelimit“ usw.) im Anbieterstatus. Kein API-Schlüssel oder Token wird angezeigt.
- **Netzkino:** Der HAR vom 11.11.2026 enthält Kategorieantworten mit 23, 26 und 31 Titeln. Die Kennzahl `category_cap_hits` ist deshalb keine Seitengröße; sie steht legacy-seitig für Anzahl Kategorien mit mindestens 20 Einträgen. Neu: `category_over_20` und `category_max_items` in Oberfläche, API und anonymisierter Offline-Diagnose. 29/29 erfolgreich bedeutet weiterhin nur **Startseiten-Abdeckung**.

## Bestandsschutz

Unverändert erhalten bleiben insbesondere ARD-/ZDF-/Arte-Katalog und MediathekView-Scanner, Film-/Serien- und Genresuche, Metadatenprüfung (lokales IMDb, TMDB, TVDB, OMDb, Wikidata), Netzkino-GraphQL, offizieller Netzkino-WebKit-Player, Videoaudit, vorhandene Downloadjobs, ArchiveMedia-Vollmodus (PR #24), PR #23 und die Plattformverwaltung. Auch Pluto TV wird noch **nicht** als vollständig implementierter Katalog ausgegeben.

## Installation

1. Das Paket in einen **lokalen Ordner** entpacken (bei iCloud-Downloads ggf. vorab vollständig synchronisieren).
2. Die aktuelle MediathekAtlas-App regulär beenden; für die gemeinsame Datenbank eine Sicherung anlegen.
3. `Netzkino-Testversion-bauen.command` starten. Es klont zwei Git-PRs **unabhängig** und bricht bei abweichenden Commit-IDs ab.
4. In **Schritt 12/16** wird der neue Patch vorab auf Einbaustellen geprüft und anschließend auf den neu erzeugten Quellstand angewendet.
5. Nach erfolgreich bestandenen Repo-/Erweiterungstests entsteht `MediathekAtlas-0.5.31.11-Integration-Test.app` (unsigniert) und ein gleichnamiges ZIP im Build-Ordner.

**Testfälle auf dem Mac:** Mediatheken-Scanner direkt sichtbar, „Letzte Erkennung“ mit vier Gruppen, Gesamt mit ausdrücklich Mediatheken-bezogenen Scanwerten; Netzkino mit Serie/Film/Genres und Player; `Live-Protokoll > Diagnoseexport` mit neuen Kategoriefeldern; Episode-Queue vor/nach längerer Laufzeit vergleichen.

## Verifikation und Grenzen

Lokale Tests umfassen Standalone-Buildpatch und synthetischen GraphQL-Kataloglauf mit 31 Titeln, Queue-Priorisierung ohne SQL-Schreibzugriffe, 404-Staffel gegen 429, Syntaxprüfung der gepatchten JavaScript-Dateien und Bestandsschutz der Module. Die **tatsächliche macOS-Anwendung** wurde in der Entwicklungsumgebung mangels macOS nicht ausgeführt; das Build-Skript prüft zusätzlich die vollständigen Tests des echten GitHub-Repositories. GitHub wird nicht verändert.

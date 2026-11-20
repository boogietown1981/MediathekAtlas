# Verbund mehrerer Systeme (Ereignisformat `mediathekatlas-events-v1`)

Mehrere MediathekAtlas-Installationen teilen sich die Metadatenerkennung und tauschen die Ergebnisse über einen synchronisierten Ordner aus. Bevorzugt ist ein MeshSync-Ordner; jeder andere Ordnerabgleich funktioniert mit demselben Format. Jede Installation behält ihre eigene SQLite-Datenbank. Die Datenbank selbst wird nie synchronisiert.

## Einrichtung

1. In MeshSync auf jedem NAS unter **Geräte → Weitere Ordner und Freigaben** einen Ordner mit demselben Namen verbinden, z. B. `MediathekAtlasSync`.
2. In MediathekAtlas unter **Einstellungen → Verbund mehrerer Systeme** den lokalen Pfad dieses Ordners und einen Namen für das System eintragen.
3. MediathekAtlas prüft den MeshSync-Marker `.meshsync-folder`. Fehlt er, wird der Ordner nur nach ausdrücklicher Bestätigung als Verbundordner eingerichtet. Ein fehlender Ordner (Laufwerk nicht verbunden) wird nie neu angelegt.

Ohne Verbundordner oder bei nicht erreichbarem Ordner erkennt jede Installation wie bisher alle Titel allein.

## Schnelleinrichtung über einen Cloud-Ordner (seit 0.6.53)

Für mehrere Macs (oder PCs) ohne NAS: **Einstellungen → Verbund & andere Systeme → „Über iCloud Drive verbinden“** auf jedem Gerät einmal wählen. Gefunden werden iCloud Drive, Dropbox, OneDrive, Google Drive und Synology Drive. Angelegt wird nur der Unterordner `MediathekAtlas-Verbund`; danach gilt alles wie beim Verbundordner. Kein offener Port, kein NAS nötig; ausgeschaltete Geräte holen beim nächsten Start nach.

- Das offene Segment liegt im Datenordner (`verbund-staging/<hash>/`) und wird erst fertig in den Cloud-Ordner geschrieben.
- Fehlt ein früheres Segment noch (Synchronisation läuft), wartet das Lesen dieses Knotens bis zu 6 Stunden darauf. Ausgelagerte iCloud-Dateien (`.events-NNNNNN.jsonl.icloud`) werden mit `brctl download` angefordert.
- Ereignisse tragen nur die Entscheidung (`share_meta`, rund 500 Byte), keine Beschreibungen oder Besetzung. Segmente höchstens 2 MB; komprimiert als `events-NNNNNN.jsonl.gz`, sobald jedes System im Ordner `gzip` in `shares` meldet. Bisherige Ergebnisse werden bis 300 MB eigenem Anteil geteilt (`mesh_journal_mb`).
- `node.json` enthält zusätzlich `host` (Hash aus Zufallswert und Rechnername) und `shares` (`["episodes"]`). Eine Datenbank, die auf einem anderen Rechner weiterläuft, bekommt eine eigene Knoten-ID.

## Direktverbindung ohne Sync-Ordner (seit 0.5.5)

Sind die Systeme nur über das Netzwerk verbunden (z. B. Mac und Synology über Tailscale), braucht es keinen gemeinsamen Ordner:

1. Auf dem NAS unter **Einstellungen → Verbund → Direktverbindung** „Dieses System freigeben“ wählen. Es erscheint ein Verbindungscode `http://<adresse>:8730#<schlüssel>`. Die Adresse ist die, über die der Browser das NAS gerade erreicht; die Tailscale-Adresse (100.x) wird zusätzlich angezeigt.
2. Am Mac den Code unter „Verbindungscode der Gegenstelle“ einfügen und „Verbinden“ wählen. Die Verbindung wird sofort geprüft.

Technik (`meshpeer.py`): Ohne eingetragenen Verbundordner liegt das Journal im Datenordner (`verbund/`). Der verbindende Rechner holt alle 30 Sekunden fehlende Segmente und neuere `node.json` der Gegenstelle (`GET /api/peer/index`, `GET /api/peer/file`) und lädt eigene hoch (`PUT /api/peer/file`). Nur der Rechner mit Gegenstelle baut Verbindungen auf; der Mac muss also nicht erreichbar sein. Alle Anfragen tragen den gemeinsamen Verbund-Schlüssel im Header `X-Atlas-Mesh-Key` (256 Bit). Niemand kann in das Knotenverzeichnis des Empfängers schreiben, veröffentlichte Segmente werden nie überschrieben, Pfade sind auf `nodes/<id>/events-NNNNNN.jsonl|node.json` beschränkt. Über Tailscale ist die Übertragung verschlüsselt; im offenen Netz ohne VPN nur im Heimnetz verwenden. Ein Verbundordner und eine Direktverbindung lassen sich kombinieren (das NAS gibt dann das Journal seines MeshSync-Ordners frei). Videodateien werden nicht übertragen; dafür gibt es „Herunterladen“ in der Download-Ansicht.

## Ordneraufbau

```
<Verbundordner>/
  .meshsync-folder              Marker von MeshSync, nur gelesen
  mediathekatlas-sync.json      {"format": "mediathekatlas-events-v1"}
  nodes/<knoten-id>/            32 Hex-Zeichen, nur dieser Knoten schreibt hier
    node.json                   Lebenszeichen alle 5 Minuten
    events-000001.jsonl         abgeschlossenes Segment, unveränderlich
    events-000002.jsonl.partial offenes Segment, MeshSync ignoriert es
```

Segmente werden nach 2 MiB oder 5 Minuten per Umbenennung veröffentlicht. Leser verarbeiten nur `.jsonl`-Dateien fremder Knoten und merken sich je Knoten Segment und Zeile.

## `node.json`

| Feld | Bedeutung |
| --- | --- |
| `format`, `node`, `name`, `version` | Format, Knoten-ID, Anzeigename, App-Version |
| `time` | Unix-Zeit des Lebenszeichens; älter als 15 Minuten = Knoten gilt als nicht erreichbar |
| `recognizing` | automatische Erkennung eingeschaltet |
| `rate` | gemessene Erkennungen pro Minute, gleitend gemittelt |
| `providers` | eingerichtete Anbieter (`TMDB`, `TVDB`, `OMDb`), nie Schlüssel |
| `seq` | letzte geschriebene Ereignisnummer |

## Ereignisse (eine JSON-Zeile je Ereignis)

```json
{"v":1,"id":"<knoten>:<seq>","node":"<knoten>","seq":17,"hlc":1793204402799,
 "type":"match.result","data":{"work":"<werk-id>","dest":"<id nach Zusammenführung>",
 "outcome":"matched","meta":{...},"providers":["TMDB"]}}
```

| `type` | `outcome` | Bedeutung |
| --- | --- | --- |
| `match.result` | `matched`, `identified`, `review` | automatisches Ergebnis; `review` enthält höchstens 10 Vorschläge |
| `match.manual` | `manual` | vom Nutzer bestätigte Zuordnung |

### Episodensuche (seit 0.6.53)

Eine bestätigte Episode wird als `match.result` mit `outcome` `matched` veröffentlicht (`work` = Werk-ID vor der Bestätigung und ursprüngliche Werk-IDs). „Keine Episode gefunden“:

| `type` | Felder in `data` | Bedeutung |
| --- | --- | --- |
| `episode.result` | `works` (≤ 8), `dest`, `outcome` = `unresolved`, `until`, `archive`, `sender` | bis `until` nicht erneut suchen, sofern das eigene IMDb-Archiv nicht neuer als `archive` ist und nicht nur hier die Senderabfrage (`sender`) aktiv ist |

Episoden-Bereiche werden nur unter Knoten mit `"episodes"` in `shares` aufgeteilt; ältere Knoten überspringen `episode.result`.

### Downloads (seit 0.5.2)

| `type` | Felder in `data` | Bedeutung |
| --- | --- | --- |
| `download.claim` | `key`, `works`, `title`, `until` | Download läuft, gilt bis `until` (2 h, alle 30 min verlängert) |
| `download.release` | `key`, `works`, `title` | abgebrochen oder fehlgeschlagen, Titel wieder frei |
| `download.done` | `key`, `works`, `title`, `path`, `size`, `sha256` | fertig; `path` relativ zum MeshSync-Ordner des Downloadziels, `null` wenn das Ziel nicht geteilt ist |

`key` ist `catalog.download_identity()` (bei eindeutiger Zuordnung die kanonische ID), `works` die lokalen Werk-IDs. Ein `done` bleibt maßgeblich; ein späterer `claim` oder ein `release` eines anderen Knotens ändert es nicht. Empfänger werten `path` nur innerhalb ihres eigenen MeshSync-Ordners aus und lehnen absolute Pfade und `..` ab.

`work` ist die aus der Filmliste abgeleitete Werk-ID (`catalog.identity`), auf allen Systemen gleich. `dest` ist die ID nach der Zusammenführung, bei eindeutiger Zuordnung die kanonische ID aus Anbieter und Referenz. `hlc` ist eine hybride logische Uhr in Millisekunden.

Ergebnisse mit Anbieterfehlern oder Pausen werden nicht verteilt. API-Schlüssel, lokale Pfade und Diagnosedaten stehen nie in Ereignissen.

## Bestand beim Beitritt (seit 0.5.9)

Beim ersten Verbinden veröffentlicht jedes System einmalig seine schon vorhandenen Zuordnungen (`manual` als `match.manual`, `matched`/`identified` als `match.result`), 1000 Werke je Runde. Als `work` dient jede ursprüngliche Werk-ID der Angebote des zusammengeführten Werks, als `dest` dessen ID. Ergebnisse, die ein System selbst aus dem Verbund übernommen hat, veröffentlicht es nicht erneut. Fortschritt im Zustand `mesh_backfill_<knoten>`.

## Aufteilung und Konflikte

- 256 Bereiche nach den ersten zwei Hex-Zeichen der Werk-ID. Zuteilung wie MeshSync `hubwork.owners()`: jeder aktive Knoten mindestens ein Bereich, Rest nach `rate`.
- Nutzerpriorisierte Titel werden immer lokal geprüft. Ist die eigene Warteschlange leer, hilft ein Knoten vom Ende der übrigen Bereiche aus. Treffen sich zwei Knoten, wird höchstens der gerade laufende Titel doppelt geprüft.
- Vorrang: `manual` > `matched` > `identified` > `review`; bei gleichem Rang mehr Anbieter, dann jüngere `hlc`, dann größere Knoten-ID. Alle Knoten kommen so zum selben Ergebnis.
- Eine lokale manuelle Zuordnung wird nie ersetzt, auch nicht durch eine fremde manuelle (seit 0.6.53). Eine abweichende fremde manuelle Zuordnung wird als Abweichung gemerkt (`mesh_conflicts`) und in der Oberfläche zur Entscheidung angeboten. Ein `review` eines Knotens mit weniger Anbietern blockiert einen besser ausgestatteten Knoten nicht.

## Grenzen dieser Version

- Noch nicht enthalten: Signaturen je Ereignis, Verdichtung alter Segmente, eigener Verbund-Reiter, bevorzugtes Download-NAS.
- Klicken zwei Personen innerhalb weniger Minuten auf zwei NAS denselben Titel an, bevor die Meldung übertragen ist, laden beide. Das Ergebnis bleibt korrekt, kostet aber einen Download.
- Die anderen Systeme prüfen nur die Dateigröße, nicht die Prüfsumme, damit schwache NAS nicht jedes Video neu einlesen müssen.
- MeshSync-Ordner sind keine Zugriffskontrolle: Alle Geräte im selben Mesh erhalten den Ordner.
- Wird ein Datenordner samt Datenbank auf ein zweites System kopiert, haben beide dieselbe Knoten-ID. Vor dem Kopieren den Verbund ausschalten oder auf dem Ziel die Datenbank neu anlegen.
- Getestet mit simulierten Instanzen in getrennten Datenordnern und gemeinsamem Ordner, nicht mit echtem MeshSync auf zwei NAS.

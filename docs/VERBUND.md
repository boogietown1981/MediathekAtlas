# Verbund mehrerer Systeme (Ereignisformat `mediathekatlas-events-v1`)

Mehrere MediathekAtlas-Installationen teilen sich die Metadatenerkennung und tauschen die Ergebnisse über einen synchronisierten Ordner aus. Bevorzugt ist ein MeshSync-Ordner; jeder andere Ordnerabgleich funktioniert mit demselben Format. Jede Installation behält ihre eigene SQLite-Datenbank. Die Datenbank selbst wird nie synchronisiert.

## Einrichtung

1. In MeshSync auf jedem NAS unter **Geräte → Weitere Ordner und Freigaben** einen Ordner mit demselben Namen verbinden, z. B. `MediathekAtlasSync`.
2. In MediathekAtlas unter **Einstellungen → Verbund mehrerer Systeme** den lokalen Pfad dieses Ordners und einen Namen für das System eintragen.
3. MediathekAtlas prüft den MeshSync-Marker `.meshsync-folder`. Fehlt er, wird der Ordner nur nach ausdrücklicher Bestätigung als Verbundordner eingerichtet. Ein fehlender Ordner (Laufwerk nicht verbunden) wird nie neu angelegt.

Ohne Verbundordner oder bei nicht erreichbarem Ordner erkennt jede Installation wie bisher alle Titel allein.

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

### Downloads (seit 0.5.2)

| `type` | Felder in `data` | Bedeutung |
| --- | --- | --- |
| `download.claim` | `key`, `works`, `title`, `until` | Download läuft, gilt bis `until` (2 h, alle 30 min verlängert) |
| `download.release` | `key`, `works`, `title` | abgebrochen oder fehlgeschlagen, Titel wieder frei |
| `download.done` | `key`, `works`, `title`, `path`, `size`, `sha256` | fertig; `path` relativ zum MeshSync-Ordner des Downloadziels, `null` wenn das Ziel nicht geteilt ist |

`key` ist `catalog.download_identity()` (bei eindeutiger Zuordnung die kanonische ID), `works` die lokalen Werk-IDs. Ein `done` bleibt maßgeblich; ein späterer `claim` oder ein `release` eines anderen Knotens ändert es nicht. Empfänger werten `path` nur innerhalb ihres eigenen MeshSync-Ordners aus und lehnen absolute Pfade und `..` ab.

`work` ist die aus der Filmliste abgeleitete Werk-ID (`catalog.identity`), auf allen Systemen gleich. `dest` ist die ID nach der Zusammenführung, bei eindeutiger Zuordnung die kanonische ID aus Anbieter und Referenz. `hlc` ist eine hybride logische Uhr in Millisekunden.

Ergebnisse mit Anbieterfehlern oder Pausen werden nicht verteilt. API-Schlüssel, lokale Pfade und Diagnosedaten stehen nie in Ereignissen.

## Aufteilung und Konflikte

- 256 Bereiche nach den ersten zwei Hex-Zeichen der Werk-ID. Zuteilung wie MeshSync `hubwork.owners()`: jeder aktive Knoten mindestens ein Bereich, Rest nach `rate`.
- Nutzerpriorisierte Titel werden immer lokal geprüft. Ist die eigene Warteschlange leer, hilft ein Knoten vom Ende der übrigen Bereiche aus. Treffen sich zwei Knoten, wird höchstens der gerade laufende Titel doppelt geprüft.
- Vorrang: `manual` > `matched` > `identified` > `review`; bei gleichem Rang mehr Anbieter, dann jüngere `hlc`, dann größere Knoten-ID. Alle Knoten kommen so zum selben Ergebnis.
- Eine lokale manuelle Zuordnung wird nie durch ein fremdes automatisches Ergebnis ersetzt. Ein `review` eines Knotens mit weniger Anbietern blockiert einen besser ausgestatteten Knoten nicht.

## Grenzen dieser Version

- Noch nicht enthalten: Signaturen je Ereignis, Verdichtung alter Segmente, eigener Verbund-Reiter, bevorzugtes Download-NAS.
- Klicken zwei Personen innerhalb weniger Minuten auf zwei NAS denselben Titel an, bevor die Meldung übertragen ist, laden beide. Das Ergebnis bleibt korrekt, kostet aber einen Download.
- Die anderen Systeme prüfen nur die Dateigröße, nicht die Prüfsumme, damit schwache NAS nicht jedes Video neu einlesen müssen.
- MeshSync-Ordner sind keine Zugriffskontrolle: Alle Geräte im selben Mesh erhalten den Ordner.
- Wird ein Datenordner samt Datenbank auf ein zweites System kopiert, haben beide dieselbe Knoten-ID. Vor dem Kopieren den Verbund ausschalten oder auf dem Ziel die Datenbank neu anlegen.
- Getestet mit simulierten Instanzen in getrennten Datenordnern und gemeinsamem Ordner, nicht mit echtem MeshSync auf zwei NAS.

# Externe Filmportale – erste Ausbaustufe

Die Portale sind ein **separater Katalog**, keine zusätzlichen Download- oder
Stream-Extractor-Backends. Sie dienen der Recherche nach legal zugänglichen
Angeboten, nicht als Nachweis von Download- oder Weiterverbreitungsrechten.

## Quellenadapter

| Portal | Zugriff | Ausgelöste Aktion | Speicherung | Download |
| --- | --- | --- | --- | --- |
| Internet Archive | dokumentierte Advanced-Search-Metadaten-API | nur auf Suchklick, max. 30 Ergebnisse | Titel, Jahr, Rechte-/Lizenz-Angaben, offizielle Detailseite | ausdrücklich **nein** |
| Netzkino | Filmseite vom Nutzer eingegeben | **keine** API, kein HTML-Abruf | Titel, Jahr, kanonisierte URL | ausdrücklich **nein** |

Die Internet-Archive-Metadaten und die dort angegebenen Lizenzen können von
Hochladenden stammen und müssen vor einer Dateinutzung unabhängig geprüft
werden. Ein Lizenzlink bedeutet nicht automatisch, dass das ganze Item unter
dieser Lizenz verwendbar ist. Filmseiten können verschwinden, regional
beschränkt oder kostenpflichtig werden; Verfügbarkeit ist zunächst
`unverified` und ein Ablaufdatum bleibt `null`.

Netzkino bietet werbefinanzierte Wiedergabe an, aber daraus folgt keine
Drittanbieter-Erlaubnis zum massenhaften Abruf. Ein Link bleibt ein
**externer Originalseiten-Verweis**, ohne Stream-Auflösung, Download,
Umgehung von Werbung, Anmeldung oder technischen Schutzmaßnahmen.

## Datenmodell / Migration

`portal_sources.initialize(connection)` legt nur `portal_items` und
`portal_source_state` an. Diese Tabellen sind bewusst von `works`,
`offers`, `jobs`, `episode_queue` und `scan_seen` isoliert.
Das Entfernen/Fehlschlagen einer Portalsuche verändert keine bestehende
MediathekView-Aufnahme. Ein erneut importierter identischer Quell-Identifier
aktualisiert die Metadaten statt Duplikate zu erzeugen.

Die API ist durch denselben lokalen/Netzwerk-Sitzungsschutz wie der restliche
MediathekAtlas abgesichert:

- `GET /api/portals` – Quellen, Möglichkeiten, Importzahlen
- `GET /api/portal-items` – gespeicherte externe Angebote, Filter und Seiten
- `POST /api/portal-search` – nur Internet Archive und explizite Suche
- `POST /api/portal-netzkino-add` – manuell bereitgestellte Filmseite

Der Abgleich zum lokalen Filmkatalog liefert zunächst nur einen Hinweis
bei **identischem Werktitel und bekanntem identischem Jahr**. Kein
automatischer Merge, kein automatischer Download und keine Änderung einer
bereits bestehenden Werkidentität.

## Sicherheit und Leistungsgrenzen

- Externe URLs sind auf exakt validierte HTTPS-Hosts beschränkt.
- Keine frei wählbaren Drittanbieter-API-Ziele; Archive-Anfragen werden mit
  einer fest kodierten HTTPS-Domain konstruiert.
- Die Archive-Suche setzt ein begrenztes, aus Suchwörtern zusammengesetztes
  Suchmuster ein; keine beliebigen Solr-Ausdrücke oder Massenindizierung.
- Maximal 30 Treffer pro API-Anfrage und 2 MiB Antwortdaten.
- Speicherung in SQLite erfolgt transaktional; frühere Treffer bleiben bei
  einer fehlgeschlagenen Abfrage erhalten.
- Die Oberfläche verwendet `textContent` für externe Beschreibungen und
  öffnet ausschließlich validierte Originalseiten im separaten Tab.
- Kein automatisches Polling, keine zeitgesteuerte Abfrage und keine
  Indexierung aller Internet-Archive-Filme.

## Nächste Schritte

1. Offizielle zusätzliche Schnittstellen oder genehmigte Katalog-Feeds
   evaluieren, etwa für Netzkino, ohne die bisherigen Rechte-Grenzen zu
   ändern.
2. Quellübergreifende Dublettenprüfung mit belegter Titel-, Jahr-, Laufzeit-
   und Original-ID-Übereinstimmung verbessern.
3. Für den Hauptkatalog eine öffentliche Quellenanzeige mit getrennten
   Rechten, regionaler Verfügbarkeit und bestätigten Ablauffristen bauen.
4. FTS5-Suche und »Letzte Chance« gesondert und mit Lasttests ergänzen.

Die portable macOS-Paketierung wird mit `portal_sources.py` ergänzt;
die NAS-Pakete sammeln ohnehin alle Laufzeit-Python-Module. Native macOS-
und NAS-Praxistests bleiben vor einer Freigabe erforderlich.

# Metadatenstrategie über mehrere Plattformen

Vergleichsstand: ArchiveMedia **0.10.53**, upstream `e1503fbe1bd285f752382964b45f1936c7df42d0`; MediathekAtlas **0.5.30 (main)**, vor der separaten PR-23-Freigabe. Neue Portaladapter im isolierten Entwicklungsbranch. Dieser Vergleich dokumentiert Codefunktionen, nicht einen Live-Probelauf an sämtlichen externen Portalen.

## 1. Zwei verschiedene Aufgaben

Ein Film oder eine Serienfolge kann auf einer Plattform verfügbar sein, ohne
dass die konkrete Videodatei verlässlich identifiziert wurde.

1. **Angebotsbeleg**: Original-URL, Quelle, Veröffentlichungs-/Ablaufdatum,
   Anbieterberechtigung und Zugriffsvoraussetzungen
2. **Werkreferenz**: IMDb/TMDB/TVDB/OMDb/AniList/Wikidata-ID und Erscheinungsjahr
3. **Datei-/Episodenzuordnung**: explizite Episodennummer, abgeleitete
   Fassungen, Container, ursprüngliche Datei, tatsächliche vs. erwartete Laufzeit
4. **Spurbeleg**: FFprobe-/Containerindex-Ton- und Untertitelspuren mit
   Herkunft; Dateiname/Upload-Sprachfeld sind lediglich unbestätigte Hinweise
5. **Medieninhalt**: Datei plausibel und technisch lesbar bedeutet
   **nicht**, dass Bild/Ton tatsächlich den angegebenen Film wiedergeben.

Diese Ebenen werden nicht durch eine einzige Zahl „Erkannt = 100 %“
zusammengeführt.

## 2. Welche vorhandene Implementierung ist maßgeblich?

| Funktion | ArchiveMedia 0.10.53 | MediathekAtlas 0.5.30 / 0.5.31 | Führende Implementierung |
| --- | --- | --- | --- |
| Archive.org-Uploadcontainer und einzelne Dateirollen | `catalog_identity`, `catalog_repair`, `unified_inventory` | Neu nur als Adapter | **ArchiveMedia** |
| Zusammenfassung von Original und Transcodes | `catalog_repair.family_key` | Für Archive-Angebote neu | **ArchiveMedia** |
| Original-/Derivative-/Extras-Erkennung | `catalog_repair.technical_role`, `video_triage` | Sender-Trailerregeln | **quellspezifisch** |
| Containerindex, Range-Probe, FFprobe, Sprachen | `media_probe`, `container_tracks`, `linguistics` | FFprobe beim tatsächlichen Download | **ArchiveMedia** für Archive, **MediathekAtlas** für lokale Dateien |
| Angegebene Sprache vs. nachgewiesene Tonspur | `linguistics`, `item_language_hints` | Sprache der Mediatheksender | **ArchiveMedia** als gemeinsame Evidenzregel |
| Werk-/Episodenkonflikte und Laufzeit | `work_validation.assessment` | `video_causality` in 0.5.31 und `matching` | **beide**, unterschiedliche Eingangsdaten |
| IMDb-Offline-TSV und Titelsuche | `external_metadata`, `imdb_archive` | `imdb_archive` inklusive Aliase und Episoden | **gemeinsamer IMDb-Datensatz**, aber unabhängige lokale Caches |
| Reihenfolge unabhängiger Werkreferenzen | `reference_pipeline`: IMDb → TVDB → TMDB → OMDb | `matching.ORDER`: IMDb → TVDB → TMDB → OMDb → Wikidata | **gemeinsamer Referenzkern**, Wikidata als ergänzende schwächere Quelle |
| Anime-Original-/Aliasnamen | `anime_match` (AniList) | Primär allgemeine Film-/Seriensuche | **ArchiveMedia**, ausdrücklich keine Schlussfolgerung auf Audio |
| ARD-/ZDF-Originalseite und Sendungsbeleg | Nicht führend | `broadcaster`, `metadata` | **MediathekAtlas** |
| Priorisierte Uploader / Clean Scan / Unterbrechungen | `uploader_priority`, `clean_scan`, `scan_recovery` | Neuer Portaladapter ist noch begrenzt | **ArchiveMedia unverändert** |
| Einheitliche Dateiablage, MKV/NFO/Sidecars | `package_media.canonical_target` | `core.target` nutzt bereits genau dieses Modul | **bestehender gemeinsam genutzter Dateinamen-Code** |
| Downloadrechte / Plattformbedingungen | Je Werk und Datenquelle | Je Mediathek-Angebot | **quellspezifisch** |

**Technisch umgesetzt:** `portal_metadata_policy` verwendet den originalen
ArchiveMedia-`work_validation.assessment` und dessen `reference_pipeline`
als unveränderte, MIT-lizenzierte Hilfen. Beide Funktionen sind **rein
analytisch** und verändern weder heruntergeladene Dateien noch
Arbeitseinträge. Zusätzliche Werkreferenzen sind erst nach echten
Anbieterprüfungen entscheidungsrelevant; derzeit importiert der
Light-Adapter keine pauschalen externen „bestätigt“-Belege.

## 3. Verschiedene Prüfpfade statt eines Universalcrawlers

### Deutsche Mediatheken

- Die bestehende Liste, der Senderdirektabgleich und die Warteschlange
  bleiben unverändert.
- ARD/ZDF-Metadaten stehen an erster Stelle; weitere Werkdaten aus dem
  Offline-IMDb-Archiv, TVDB, TMDB, OMDb und Wikidata.
- Episoden müssen konkret nachgewiesen sein; ein erkannter Serientitel
  genügt nicht.
- Bei abweichender Laufzeit bleibt der Serientitel erhalten, die
  Videofassung wird nicht als vollständige Episode bestätigt.

### Internet Archive

- Zuerst Uploadcontainer und alle relevanten Video-Dateifassungen erkennen,
  Herkunft und Derivative per Familie zusammenfassen.
- *Mittelwert der Uploads* ersetzt keine episodenspezifische Referenzdauer.
- Archive.org-Uploadtitel, Dateiname, Lizenzangabe und Uploadsprache
  sind zunächst **Quellenbehauptungen**.
- IMDB/TVDB/TMDB/OMDb prüfen unabhängige Werkreferenzen; AniList prüft
  Anime-Aliasnamen; TVmaze kann episodenspezifische Laufzeiten liefern.
- Bei Diskrepanzen über Werk, Erscheinungsjahr, Sprachspur oder
  Laufzeit wird der Status auf „zu prüfen“ gesetzt.
- Lokale Datei/Teilabrufprobe prüft tatsächliche Container- und
  Streammetadaten; unbeschriftete Spuren bleiben unbekannt.
- Der vollständige ArchiveMedia-Scan und alle bestehenden Funktionen
  bleiben weiterhin im separaten Originalprozess ausführbar.

### Netzkino

- Ausschließlich manuell gespeicherte Originalfilmseiten, keine
  automatisierten Crawler oder fremde Streams.
- Metadaten nur als unbestätigte Quellinformation. Kein Video-, Sprach-,
  Lizenz- oder Downloadnachweis durch den Link allein.

## 4. Einzelne Qualitätssignale und Prioritäten

`portal_metadata_policy.assess_references` berücksichtigt die
Unabhängigkeit der Quellen: Wikipedia + Wikidata werden als eine
Wikimedia-Familie gezählt; gleiche Werke haben nicht automatisch
gleiche Dateien. Ein stark abweichendes Erscheinungsjahr oder
widersprüchliche IMDb-IDs blockieren automatische Bestätigung.

Der reguläre IMDb-Offline-Abgleich hat bei passenden eindeutigen IDs
Vorrang. Fehlende Credentials oder Anbieterfehler dürfen nicht
still als erfolgreiche Negativprüfung gewertet werden. Zusatzdaten
wie Fanart sind *keine fünfte Werkreferenz*.

**Filename:** MediathekAtlas ruft bereits
`vendor/archivemedia/package_media.canonical_target` auf. Es soll keine
plattformabhängige zweite Implementierung entstehen. Die kanonische
Formatierung erfolgt nur bei erlaubtem Download und hinreichend
gesicherter Film-/Episodenidentität. Unbestätigte Tonsprachen erscheinen
nicht als bewiesener Teil des Dateinamens.

## 5. Vollständigkeit und Grenzen der Integration

Die ArchiveMedia-Vollversion ist eine eigenständige Anwendung mit eigener
Datenbank, UI, Clean Scan, Wiederaufnahme, Erkennung, Uploadernachlauf,
Metadaten-Worker, Datei-Diagnose, Sprachen, Downloadablage, Datenexport,
Backups und Diagnosen. Sie wird nicht durch den vereinfachten
MediathekAtlas-Adapter ersetzt oder migriert.

Der neue MediathekAtlas-Bereich hat drei getrennte Ebenen:

- **Vollmodus**: Read-only Verbindung zur optional lokal gestarteten
  ArchiveMedia-Instanz (127.0.0.1:8789); Öffnen der Original-UI im Browser.
  Dadurch bleiben alle bestehenden ArchiveMedia-Funktionen erreichbar.
  Die Integration startet/stoppt oder verändert diese App **nicht**.
- **Gezielter leichter Scan**: opt-in URL-, Collection- und öffentliche
  Uploader-ID-Suche, persistenter Cursor, maximal 25 Seiten pro Start.
  **Nicht gleichwertig** mit dem Clean Scan, der historischen
  Uploader-Priorisierung oder der Vollvalidierung.
- **Katalogansicht**: getrennte, eigene SQLite-Tabellen für
  Archive-Metadaten, Fassungen, Umfang, Sprachhinweise und optionale
  erlaubte technische Teilproben. Der deutsche Hauptkatalog wird
  weder überschrieben noch durch andere Sprachen verdeckt.

Der angezeigte Schalter „maximal 1–5 Plattformen“ ist eine
**Obergrenze für künftig angeschlossene unabhängige Adapter**. Zum Stand
dieses Branches ist **nur Internet Archive** als automatischer
Scanner angeschlossen; Netzkino bleibt manuell.

## 6. Sicherungs- und Regressionstests vor Releases

- ArchiveMedia in der bisherigen Installation starten und seine
  vollständige Oberfläche und Scan-/Uploader-/Downloadfunktionen
  unabhängig weiterhin ausführen
- MediathekAtlas allein starten; kein Archivscan läuft ohne
  ausdrückliche Aktivierung
- Import der Archiv-Dateiliste darf keine ursprüngliche Medien-
  oder Downloadwarteschlange verändern
- Mehrere Fassungen und Sprachspuren unter einem Werk, unbestätigte
  Hinweise getrennt von technischer Spurprüfung
- Alle auf eindeutige Werk-ID, Laufzeit, Film-/Serienart und
  Quellenbeleg bezogenen Konflikte nachvollziehbar darstellen
- Parallele unabhängige Plattformen, Cursor nach Neustart,
  Prioritäten und Fehlerbehandlung validieren
- macOS-, Linux- und NAS-Builds sowie reale Plattform-Praxistests
  vor einem Merge gegen `main` durchführen

Der Stand dieses Dokuments ist ein **Integrationsvertrag, kein
Versprechen einer bereits vollständig getesteten Parität**.

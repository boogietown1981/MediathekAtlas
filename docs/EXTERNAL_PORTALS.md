# Externe Plattformen – isolierter MediathekAtlas-Integrationsbranch

**Gültiger Stand:** Entwicklervorschau auf Basis `main` 0.5.30; der
unabhängige 0.5.31-PR ist noch nicht eingebaut. Die ArchiveMedia-Vollversion
0.10.53 wird unverändert weiterbetrieben. Keine Freigabe ohne zusätzliche
Regressionstests unter Linux, macOS und NAS.

## Architektur

- MediathekView-Scanner, Hauptkatalog (`works`, `offers`),
  Episodenprüfer und Downloadwarteschlange bleiben separat und unverändert.
- Internet Archive/Netzkino speichern ihre Links und Metadaten ausschließlich
  in `portal_items`, `portal_archive_details`, `portal_video_probes`.
- `portal_controls` speichert pro Plattform die Aktivierung,
  Metadatenworker und Sprachansicht. `portal_scopes` speichert
  die gezielten Archive-URLs/Collection-IDs/Uploader und ihren Cursor,
  Seitenzähler, priorisierten Scanstatus und Wiederholungszeitpunkt.
- Die Obergrenze 1–5 aktive Plattformen bereitet weitere Adapter vor.
  **Aktuell ist Internet Archive der einzige aktive automatische
  Fremdplattform-Scanner.** Netzkino bietet lediglich vom Nutzer
  eingegebene Originalseiten-Links an.
- Plattformunabhängige Bewertung von Film, Serie, Folge, Laufzeit,
  Qualität und Sprache erfolgt über konservative Werk-/Episodenregeln.
  Die Ausgabe verwendet die bisherige gemeinsame Funktion
  `vendor.archivemedia.package_media.canonical_target`.

## ArchiveMedia: voller Funktionsumfang

Das vollständige ArchiveMedia **0.10.53** mit Clean Scan, Uploader-Priorität,
Sammlungsfenstern, AniList, TVmaze, IMDb-Offline-Referenzen, technischen
Probe-Warteschlangen, Wiederaufnahme, Clip-Filtern, Backups, Export und
separaten Downloadregeln wird **nicht entfernt oder durch einen
Teilnachbau ersetzt**.

Wenn die bestehende ArchiveMedia-Anwendung lokal auf Port 8789 läuft,
zeigt MediathekAtlas ihren Read-only-Health-Status an und öffnet die
Originaloberfläche. Der Adapter sendet keinerlei Konfigurationsänderung
an ArchiveMedia und startet dort keine Scans oder Downloads. So können
beide Programme gleichzeitig ohne Datenbankmigration arbeiten.

Der im MediathekAtlas-Reiter integrierte Archive-Light-Scanner ist bewusst
begrenzter: explizite Archive-Item-URLs, konkrete Collection-IDs und
öffentliche Uploader-@IDs mit höchstens 25 Seiten pro Start, maximal
zwei parallelen Metadaten-Workern, Wiederaufnahme und Retry. Er führt
**keinen globalen unbeschränkten Scan** aus und übernimmt nicht
automatisch historische Uploader-Nachverfolgung oder Clean-Scan-Fenster.

## Sprach- und Videodarstellung

- Nur relevante Videofassungen werden in der Archive-Detailansicht gezeigt.
  Archive.org-Uploadcontainer sind **keine** einzelnen Filme.
- Kurze Clips und Segmente werden ausgeblendet, nicht gelöscht oder
  als falsche Trailer klassifiziert. Eine 2-Minuten-Animefolge ist
  möglicherweise ein zulässiger Kurzfilm; die Filterung ist ein
  Sichtbarkeitsfilter, keine Identitätsentscheidung.
- Original und abgeleitete Encodings teilen eine Filmfamilie.
  Verschiedene Ton-/Untertitelspuren und Dateiformate bleiben
  als unterschiedliche Varianten sichtbar.
- Die Quellangabe „Deutsch“ bleibt ein **unbestätigter Hinweis**, bis
  eine technische Spurprüfung valide Ton-/Untertitel-Metadaten liefert.
  Diese Prüfung geschieht nur nach ausdrücklicher Zustimmung und mit
  begrenztem Datenausschnitt; aus Metadaten folgt keine Downloadfreigabe.
- Für Archive gibt es einen eigenen Sprachfilter und eigene Ansichten.
  Der deutsche Mediathek-Katalog wird **niemals** dadurch ersetzt.

## Rechtliche Grenzen

- Internet Archive: dokumentierte Such- und Metadatenendpunkte;
  ein Lizenzfeld aus einem Upload ist **kein** bestätigtes Recht zur
  Medienübernahme. Individuelle Datei-/Lizenzberechtigungen prüfen.
- Netzkino: nur vom Nutzer gespeicherte HTTPS-Originalfilmseiten,
  keine automatische HTML-/Videoextraktion, keine Werbeumgehung.
- Der neue Katalog erteilt keinem Eintrag `download_allowed=True`.
  Es gibt weder eine plattformübergreifende Downloadwarteschlange
  noch Umgehung von Zugangsbeschränkungen.

## Aktuelle API-Oberfläche

- `GET /api/portals`: Quellenliste, Status, Plattformen und Cursor
- `GET /api/portal-items`: externer Katalog mit Such- und Sprachfilter
- `POST /api/portal-search`: explizite Internet-Archive-Suche
- `POST /api/portal-netzkino-add`: manuelle Filmlink-Erfassung
- `POST /api/portal-archive-inspect`: gezielte Dateiübersicht
- `POST /api/portal-archive-probe`: kontrollierte technische Teilprüfung
- `GET /api/portal-archive-detail`: zwischengespeicherte Dateiübersicht
- `GET /api/archive-companion`: Read-only-Status des lokalen ArchiveMedia
- `GET /api/portal-policy`: source-spezifische Metadatenrichtlinien
- `POST /api/portal-controls`: Quelle, Worker, Sprachansicht, Aktivierung
- `POST /api/portal-scope-add`: Item-/Collection-/Uploader-Scope
- `POST /api/portal-scope-control`: Start, Pause, Priorität, Löschen

Die API verwendet die bestehende MediathekAtlas-Authentifizierung;
ArchiveMedia besitzt weiterhin seine unabhängige Loopback-Sicherheitsgrenze.

## Quellvergleich und Abnahmekriterien

Die ausführliche Gegenüberstellung und die nicht zu verlierenden Funktionen
stehen in [METADATA_EVIDENCE_MATRIX.md](METADATA_EVIDENCE_MATRIX.md).
Aufträge müssen nach Neustart ohne Cursorverlust fortgesetzt werden,
nicht bestätigte Sprach- und Laufzeitinformationen bleiben als solche
ausgewiesen, und es dürfen keine deutschen MediathekView-Daten oder
Downloadaufträge verändert werden.

**Offene Aufgaben für spätere Releases**: vollständige Integration von
ArchiveMedia-Datenexporten, präzise Sprachfilter auf Basis bestätigter
Spurdaten, quellenübergreifende Verfügbarkeitsübersicht, FTS5-Suche,
„Letzte Chance“ und praxisnahe Lasttests mit großen Archiven.

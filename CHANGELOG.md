## 0.5.53 – YouTube: kostenlose Filme und Serien offizieller Kanäle
- Björn (12.11.2026): YouTube anbinden, weil Rechteinhaber wie Sony ganze Filme kostenlos auf ihren eigenen Kanälen hochladen; Darstellung im etablierten Format.
- `youtube.py`: Katalog über die YouTube Data API v3 (eigener Schlüssel, Einstellung `youtube`): `channels` (forHandle/id/forUsername), `playlists`, `playlistItems` (50 je Abfrage), `videos` (snippet, contentDetails, status; 50 je Abfrage, eine Woche zwischengespeichert). Quellenliste `youtube_sources` (Kanal, @Handle, Playlist; Art Filme/Serie; Mindestlänge; pausieren/entfernen). Filter: Mindestlänge, Ausschlusswörter (Trailer, Clip, Making-of …), Regionssperre DE, privat/Live. Titelbereinigung („Der Pate (Ganzer Film Deutsch, HD) | Krimi | 1972“ → „Der Pate“, 1972, Krimi), Staffel/Folge aus dem Videotitel oder der Playlist-Reihenfolge. Fehler je Quelle; Kontingent erschöpft → neuer Versuch nach 12 Stunden.
- Wiedergabe: `/api/play?youtube=` liefert den offiziellen Einbettungsplayer (youtube-nocookie.com, `referrerpolicy` strict-origin-when-cross-origin), Position über die IFrame-API; vorhandene Offline-Kopie spielt lokal.
- `youtube_downloads.py`: Offline-Schalter (Björns Entscheidung: Schalter, Standard aus; Zustimmung mit Zeitpunkt gespeichert), gemeinsame Warteschlange, 30 Tage, Download per yt-dlp (`MEDIATHEKATLAS_YTDLP`, PATH oder geprüfte offizielle Release-Datei), Zusammenführung mit ffmpeg, keine Cookies/Anmeldung.
- `youtube_enrichment.py` über die gemeinsame Abgleich-Engine; Titelseite mit „Angaben von YouTube“ (Kanal, Videotitel, Sprache, Upload-Datum, Wiedergabe).
- Oberfläche: Katalog-/Plattform-Reiter, Einrichtung (Schlüssel, Kanäle, Offline-Schalter, yt-dlp einrichten), Übersichtskarte mit Kanälen und Schlüsselstatus, Offline-Knopf nur bei eingeschaltetem Schalter.

## 0.5.52 – Alles in einem Paket; JustWatch: Nacht-Vormerkung nur bei echtem Zeitfenster, Kopierschutz benannt
- Björn (12.11.2026): Die Folgen von „Andromeda“ (ab 12) wurden als „erst nachts“ angezeigt, auf justwatch.com laufen sie aber sofort. Ursache laut Björns Mitschnitt: JustWatch spielt sie nur im eigenen Player mit Widevine/PlayReady/FairPlay ab (`getPlayInformation`, Lizenzserver `apis.justwatch.com/drm/license`, Playlists mit `SAMPLE-AES-CTR`); eine Adresse für externe Player (`streamUrlExternalPlayer`) gibt es dafür nicht. 0.5.48 hat jeden Titel ohne solche Adresse für ein Jugendschutz-Zeitfenster gehalten – das war falsch.
- Katalogabruf fragt jetzt `ageCertificationDetails { ageValue availableHours }` ab (FSK 16: 22–6 Uhr, FSK 18: 23–6 Uhr, sonst leer). Neue Spalte `night` in `justwatch_items`; Folgen übernehmen den Wert ihrer Serie. Lehnt JustWatch das Feld ab, läuft der Abruf ohne es und die Altersfreigabe (ab 16) entscheidet. Bestehende Bestände werden beim Start nach Altersfreigabe umgestellt.
- Nacht-Vormerkung nur noch mit Zeitfenster. Titel ohne Stream und ohne Zeitfenster: Hinweis „🔒 Kopiergeschützt (DRM): nur im JustWatch-Player, keine Offline-Kopie möglich“ in Kachel (Katalog und Plattform), Folgenzeile und Titelseite; `justwatch-download-add` lehnt sie mit dieser Begründung ab. Der Kopierschutz wird nicht umgangen.
- Katalogstatus zählt `night_only` und `protected`. Endet ein Nacht-Auftrag ohne Stream, nennt die Meldung den Grund (auch im Zeitfenster nur im geschützten Player).
- Offen: Ob JustWatch für Titel mit Zeitfenster nachts eine Adresse für externe Player liefert, ist weiterhin nicht live geprüft.
- **Zusammenführung:** Diese Korrektur war zunächst ebenfalls als 0.5.50 gebaut worden (gleiche Nummer wie „Live-TV nach Sendern“). 0.5.52 enthält alles: Live-TV (0.5.50), Rakuten TV (0.5.51) und diese JustWatch-Korrektur. Die Pakete 0.5.50 und 0.5.51 sind damit überholt.

## 0.5.51 – Rakuten TV: kostenlose Filme, Serien und Live-Sender
- **Rakuten TV** (Björn, 12.11.2026: „rakuten.tv anbinden … free Filme und Serien … bei Bedarf offline schauen … angepasste Ansicht im etablierten Format“): neue Module `rakuten.py`, `rakuten_downloads.py`, `rakuten_enrichment.py`, `web/rakuten.js`, aufgebaut wie JustWatch TV. Formate aus Björns HAR (12.11.2026): öffentliche Website-API `gizmo.rakuten.tv/v3` (Markt DE, `classification_id=307`, ohne Konto), Listen `free-all-movies` und `free-all-tv-shows` (Seite 1 `lists/<id>?contents[per_page]=24`, weitere `lists/<id>/contents?page=N`), Serien über `tv_shows/<id>/current_season` → `seasons/<id>` inkl. `other_seasons`, Live-Sender `live_channels` (seitenweise, mit laufender Sendung). IDs `m.`/`s.`/`e.`/`c.<slug>`. Nur Einträge mit Kaufart AVOD.
- **Kopierschutz:** Laut HAR liefert Rakuten kostenlose Filme und Folgen ausschließlich als `web:DASH-CENC:WVM` mit Widevine-Lizenz (Titelseiten nennen nur DASH-CENC und PlayReady). Diese Titel tragen `drm=1`: kein Player, kein Offline-Auftrag, keine Stream-Anfrage (also auch keine Werbesitzung); „Bei Rakuten TV ansehen“ und Hinweis auf der Titelseite. Nichts wird umgangen; ein ungeschütztes Profil wird nicht angefragt.
- **Live-Sender:** `avod/streamings` mit dem Live-Profil der Website (`web:HLS-NONE:NONE`), Adresse frisch, nur im Speicher; `hls_guard` prüft (Rakuten nutzt AES-128 mit Schlüsselformat identity wie Pluto). Im Plattform-Reiter „Live-TV“ und im Reiter Live-TV (`live_tv.rakuten_channels`, Anbieter „Rakuten TV“).
- Gleiche Behandlung wie die anderen Quellen: Katalog „Gesamt“/„Rakuten TV“, Übersichtskarte (mit „kopiergeschützt (nur beim Anbieter)“ und „Offline: nicht möglich“), gemeinsame Titelseite, einheitlicher Offline-Knopf (für Rakuten nicht angeboten), gemeinsamer Abgleich inkl. `reference_share`, Diagnose-Export `rakuten`, Netzprüfung `gizmo.rakuten.tv`.
- `unified_catalog.js`: Player und Anbieter-Link je Portal aus einer Tabelle statt Einzelabfragen (Pluto-Titel ohne Stream hießen dort fälschlich „Bei JustWatch ansehen“).

## 0.5.50 – Live-TV nach Sendern
- Björn (12.11.2026): Live-TV der Anbieter, wenn sie es anbieten, einmal beim Anbieter und einmal in einem neuen Reiter „Live-TV“ nach Sendern.
- Neues Modul `live_tv.py`: sammelt die Live-Sender aller Quellen aus den lokal gespeicherten Katalogen (kein zusätzlicher Netzabruf) und führt sie nach Sender zusammen (`station_name`, `station_key` mit Schreibvarianten wie ARD/Das Erste, ARTE.DE/arte). Quellen: ARD, ZDF & Co. (Filmliste, Thema „Livestream“ wie `ListeFilme.THEMA_LIVE` in MServer) und Pluto TV (`pluto.channels`). Weitere Anbieter (z. B. Rakuten-FAST-Kanäle) binden sich mit einer Ladefunktion in `live_tv.channels` an. Endpunkt `/api/live-tv?q=&provider=&group=`, Zähler im Diagnose-Export (`live_tv`, ohne Titel/Adressen).
- `catalog.mark_live`: Livestream-Einträge werden beim Import und einmal beim Start als `format` markiert, also nicht an TMDB/TVDB/IMDb geschickt; manuelle und bestätigte Zuordnungen bleiben.
- Wiedergabe: Livestreams der Sender liefern `live` (Titel = Sender, keine Länge); der Player speichert und nutzt für Live-Sender keine Fortsetzungsposition (`playLive`).
- Oberfläche: Reiter „Live-TV“ (`web/live_tv.js`), Live-Leiste im Katalog bei „ARD, ZDF & Co.“ und „Pluto TV“, Sprung aus Plattformen → Pluto TV → Live-TV.

## 0.5.49 – Plattform-Ansicht wie der Katalog, JustWatch-Folgen je Staffel, geteilter Abgleich
- **Plattform-Reiter** (Björn, 12.11.2026: der Katalog im Dashboard bleibt, unter „Plattformen“ wirkt es nicht so; Ansicht normalisieren, erkannte und gescannte Titel wie bei den Mediatheken): Netzkino, Pluto TV und JustWatch TV zeigen oben dieselbe Karte „Bestand & Werkzuordnung“ wie der Katalog (eine Umsetzung, `AtlasPlatformBoard.mount`), mit „↻ Katalog jetzt laden“ und „Im Katalog anzeigen“. Der gespeicherte Bestand ist damit auch dort sofort sichtbar.
- **Reiter umbenannt:** „Mediatheken“ → „ARD, ZDF & Co.“ (Katalog-Reiter, Überschriften, Statuszeile).
- **JustWatch-Folgen** (Björn: bei „Andromeda“ keine Folgen, obwohl sie bei JustWatch im Free-Paket sind): Die eigene Sammelabfrage (alle Staffeln mit allen Folgen) ist nie live bestätigt worden. Liefert sie nichts oder lehnt JustWatch sie ab, lädt `justwatch.load_episodes` jetzt die Staffeln einzeln über ihre eigenen Seiten – die Form aus Björns Mitschnitt (`…/Andromeda/Staffel-1`), erst mit der Folgenzahl der Staffel, sonst mit 20 wie die Website. Ereignis `justwatch_episodes_loaded` (Weg, Anzahl) im Diagnose-Export.
- **Abgleich teilen** (Björn: bereits abgeglichene Filme nicht bei einer anderen Plattform erneut abfragen): neue `reference_share.py`. Die Anbieterantwort für ein Werk (Art, normalisierter Titel, Jahr) wird einmal gespeichert; Netzkino, Pluto TV und JustWatch TV werten sie mit ihren eigenen Katalogangaben aus, statt IMDb/TVDB/TMDB erneut zu fragen. Nur vollständige Antworten, nur Titel mit Jahr, 30 Tage; „Jetzt abgleichen“ fragt immer neu. Weitere Quellen binden sich über `reference_share.wrap` an.

## 0.5.48 – Geplanter Nacht-Download (JustWatch, Jugendschutz-Zeitfenster)
- Björn (12.11.2026): „Bad Lieutenant“ ist im Paket Free, hatte aber keinen Offline-Knopf. Grund (von Björn auf justwatch.com gefunden): „Ab 00:00 Uhr verfügbar (Jugendschutz) … von 00:00 Uhr bis 06:00 Uhr“. Tagsüber liefert JustWatch für solche Titel keinen Stream; der Katalog wird meist tagsüber geladen. Wunsch: geplanter Download mit Startzeit.
- Warteschlange: Aufträge können eine Startzeit tragen (`not_before`); `job_queue.next_job` überspringt sie bis dahin, andere Downloads werden nicht blockiert.
- JustWatch-Titel ohne Stream bekommen in Kachel (Katalog und Plattform), Folgenzeile und Titelseite „🌙 Heute Nacht offline speichern (30 Tage)“. Der Auftrag startet um 00:10 Uhr (Europe/Berlin; zwischen 00:10 und 05:00 Uhr sofort) und holt die Stream-Adresse dann frisch. Anzeige „Vorgemerkt für … Uhr“ mit „Abbrechen“, in „Downloads“ „Geplant für …“. Startet ein solcher Auftrag außerhalb des Fensters (Wiederholen, Rechner nachts aus), wartet er auf die nächste Nacht.
- Es wird nichts umgangen: Geladen wird nur, wenn JustWatch den Stream freigibt; die Kopierschutz-Prüfung (`hls_guard`) bleibt. Liefert JustWatch auch nachts keinen Stream, endet der Auftrag mit einer klaren Meldung.
- Titelseite: Der Abschnitt „Offline ansehen“ nutzt jetzt dasselbe Bedienelement wie die Kacheln.

## 0.5.47 – „30 Tage offline speichern“ einheitlich in jeder Kachel
- Björn (12.11.2026): Der Download bei Pluto und JustWatch funktioniert nicht sauber und ist nicht einheitlich dargestellt; der 30-Tage-Offline-Speicher gehört schon in die Kachelansicht.
- Befund: Den Knopf gab es nur in den Kacheln der Reiter Pluto TV und JustWatch TV. Katalog-Kacheln zeigten nur einen Hinweistext, Netzkino-Kacheln gar nichts; ein Fehler erschien in der Kachel ohne Grund und ohne Wiederholen.
- Neu `web/offline_button.js` (`AtlasOffline.control`): ein Bedienelement für alle drei Anbieter, in Katalog-Kacheln, Plattform-Kacheln (Netzkino, Pluto TV, JustWatch TV) und Folgenzeilen der Serienseite. Zustände: „⬇ Offline speichern (30 Tage)“, „Vorgemerkt“, „Lädt · x / y MiB“ mit „Abbrechen“, „MKV wird erstellt“, „✓ Offline verfügbar · bis <Datum> · noch n Tage“, bei Fehler/Abbruch der Grund und „↻ Erneut offline speichern“ (startet denselben Auftrag neu). Der Status aller sichtbaren Kacheln kommt in einer Anfrage je Anbieter und aktualisiert sich während eines Downloads alle 3 s.
- Die bisherige Kachel-Variante in `portal_panel.js` und die Folgen-Variante in `portal_title.js` entfallen (keine doppelte Umsetzung). Die Listen „Offline gespeichert“ je Plattform bleiben und laufen synchron.

## 0.5.46 – Katalogfehler mit Ursache, Netzprüfung im Diagnose-Export
- Björn (12.11.2026): „die Kataloge synchronisieren nicht mehr“ – Netzkino „Fehlgeschlagen · Netzkino-Katalogserver nicht erreichbar“, Pluto und JustWatch laden nicht. In der Testumgebung nicht nachstellbar (dort ist kein Anbieter erreichbar); die bisherige Meldung verriet die Ursache nicht.
- Neu `netcheck.py`: Die Fehlermeldung aller drei Kataloge nennt die Ursache (Name nicht auflösbar – DNS/Werbefilter/kein Internet, Zertifikat nicht prüfbar, Zeitüberschreitung, Verbindung abgelehnt/abgebrochen, Proxy), ohne Adressen oder Schlüssel. Die Ereignisse `…_sync_failed` tragen die Fehlerart.
- Diagnose-Export: Abschnitt `network` mit DNS-, Verbindungs- und TLS-Prüfung je Katalogserver (Netzkino, Pluto, JustWatch, zum Vergleich die Mediathek-Liste) und dem Stand des Zertifikatsspeichers.
- Hat Python gar keine Stammzertifikate (python.org-Installation ohne „Install Certificates“), nutzt die App den Systemspeicher (`/etc/ssl/cert.pem`) – die Prüfung bleibt eingeschaltet.

## 0.5.45 – Serienseiten mit allen Folgen, für jeden Anbieter gleich
- Björn (12.11.2026): „bei Serien sollen die Folgen dann auch unter der erkannten Serie dargestellt [werden] … unabhängig des Anbieters gleich“; bei Pluto führte „21 Jump Street“ auf eine schlecht dargestellte Seite und von dort in die Episodenliste unter „Plattformen“.
- Die gemeinsame Titelseite (`portal_title.js`) zeigt bei Serien „Staffeln & Folgen · n“ wie die Mediathek-Serienseite: Staffel-Reiter (ab zwei Staffeln), je Folge Bild mit SxxEyy, Titel, Laufzeit, Inhalt, ▶ Abspielen bzw. „Beim Anbieter ansehen“, ⬇ Offline speichern direkt in der Zeile (Status „Vorgemerkt/Lädt/Offline verfügbar · noch n T.“) und Details.
- Die Folgen kommen jetzt mit dem Serienmodell (`portal_title.model` → `episodes`, gleiche Felder für alle Anbieter); keine zweite Episodenabfrage im Browser. Downloadstatus aller Folgen in einer Anfrage (`…-downloads?ids=a,b,…`).
- „Folgen anzeigen“ in den Plattform-Reitern Pluto TV und JustWatch TV, Netzkino-Serien im Katalog und im Netzkino-Reiter öffnen diese Serienseite; „Zurück“ führt dorthin, wo man herkam.
- Netzkino: zusammengefasste Serien (aus einzelnen Titeln wie „Acapulco H.E.A.T. Staffel 1 - 1. …“) haben eine eigene Serienseite mit fehlenden Folgennummern unter „Angaben von Netzkino“. Eine einzelne Folge zeigt Serie · SxxEyy · Folgentitel und „Zur Serie“ (`netzkino.series_id`, dieselbe ID wie die Gruppierung).

## 0.5.44 – IMDb-Zuordnung nutzt das Erscheinungsjahr der Plattform
- Björn (12.11.2026, „#Roxy“ bei Netzkino): Die Plattform liefert das Filmjahr (2018), trotzdem blieb der Titel „widersprüchlich“, weil IMDb sechs Filme dieses Namens kennt – einer davon (tt12786268) ohne Jahr, dadurch zwei „passende“ IMDb-IDs.
- Regel jetzt (`netzkino_enrichment.analyze`, gilt für Netzkino, Pluto TV und JustWatch TV): Ist das Jahr bekannt, gewinnt je Datenbank der Treffer mit genau diesem Jahr, dann ±1 Jahr, erst dann Treffer ohne Jahr. ±1 Jahr (Festival-/Kinostart, deutscher Start) ist kein Widerspruch mehr. Zwei Treffer mit demselben Jahr bleiben „zu prüfen“; ohne Jahr der Plattform ändert sich nichts.
- Vorhandene Berichte im Status „zu prüfen“ aus älteren Regeln werden vom Hintergrundabgleich automatisch erneut geprüft (`analysis`-Version im Bericht), vor anderen Titeln.

## 0.5.43 – Dateinamen mit Auflösung und Codecs, Bilder je Datei (alle Quellen); Warteschlange aufgeräumt
- Björn (12.11.2026, Screenshot seiner Bibliothek): Dateiname mit Auflösung und Metadaten in einem eigenen Ordner, „genauso wie beim Mediathek-Download“ – dort war es auch noch nicht so. Jetzt für **alle** Downloads gleich (eine Pipeline: `core.target` → `downloads.run`):
  - Ordner wie bisher: `Filme/<Titel> (<Jahr>)/`, `Serien/<Serie> (<Jahr>)/Season NN/`.
  - Datei: `<Titel> - (<Jahr>) - <Auflösung> - <Videocodec> <Audiocodec>.mkv`, z. B. `Spellbound - (2024) - 1080p - H264 E-AC-3.mkv`; Folgen `<Serie> - (<Jahr>) - S01E02 - 720p - H264 AAC.mkv`. Auflösung (2160p/1080p/720p/…, Cinemascope zählt nach Breite) und Codecs (H264, HEVC, AV1 · AAC, AC-3, E-AC-3, MP2, Opus …) misst ffprobe nach dem Download; erst dann wird veröffentlicht.
  - Daneben `….nfo`, `….metadata.json`, `…-poster.jpg`, `…-backdrop.jpg` (Filme). Serien behalten poster/fanart/tvshow.nfo im Serienordner. Logo-/Landscape-Bilder gibt es nur, wenn eine Quelle sie liefert (bisher keine) – es werden keine Platzhalter erzeugt.
  - Cover von Pluto TV und Netzkino werden jetzt mitgespeichert (Hosts bisher nicht zugelassen).
  - Doppelte Downloads werden weiterhin erkannt – auch Dateien im alten Schema `<Titel> (<Jahr>).mkv` (`core.existing_download`, Serien-Sammeldownload, Abos). Ablauf nach 30 Tagen löscht auch die neuen Bilddateien.
  - Bereits vorhandene Dateien werden nicht umbenannt.
- **Download-Warteschlange aufgeräumt** (Björn: Fehler bleiben stehen und lassen sich nicht löschen, derselbe Titel taucht mehrfach auf):
  - Neuer Knopf „Aus Liste entfernen“ für fehlgeschlagene, abgebrochene und unterbrochene Aufträge (`/api/job-remove`; Mediendateien gibt es für solche Aufträge nicht).
  - „Erneut versuchen“ startet denselben Auftrag neu statt einen zweiten anzulegen; ein neuer Auftrag für dieselbe Datei ersetzt frühere fehlgeschlagene. Beim Start werden vorhandene Doppelungen einmal bereinigt (`job_queue.py`).
  - Pluto „Download unvollständig: 86 von 98 Minuten“: Die Katalog-Laufzeit enthielt Werbepausen. Pluto-Laufzeit jetzt ohne Werbung (`originalContentDuration`), und werbefinanzierte HLS-Streams gelten ab 85 % der Katalog-Laufzeit als vollständig.
  - Netzkino „URL can't contain control characters“ ist seit 0.5.42 behoben – betroffene Aufträge mit „Erneut versuchen“ neu starten.

## 0.5.42 – Eine Titelseite für Netzkino, Pluto TV und JustWatch TV; Netzkino-Download mit Leerzeichen
- **Einheitliche Detailansicht** (Björn, 12.11.2026: Darstellung „egal bei welcher Plattform durchgängig“, „die spezifischen Informationen je Anbieter nicht verlieren“, „Backend und Frontend gleich“; die JustWatch-Details waren zerschossen – Cover über dem Text). Netzkino, Pluto TV und JustWatch TV öffnen jetzt dieselbe Titelseite wie die Mediathek-Werke (`titleview.js`: Hintergrund, Cover, Art · Anbieter, Jahr, Laufzeit, Altersfreigabe, ★ Bewertung, Kategorien, Aktionen, Inhalt, Infoliste, Besetzung) – aus dem Katalog und aus den Plattform-Reitern gleich; „Zurück“ führt dorthin, wo man herkam. Darunter für jede Quelle dieselben Abschnitte: „Staffeln & Folgen“ (Serien, mit Abspielen und Details je Folge), „Offline ansehen · 30 Tage“ (Speichern, Fortschritt, Abbrechen, Erneut versuchen, Jetzt löschen), „Werkzuordnung · IMDb / TVDB / TMDB / OMDb / Wikidata“ (Status, Referenzen, Abgleich auf Knopfdruck) und „Angaben von <Anbieter>“ (eigene Genres/Kategorien, IMDb-Angaben von JustWatch, Paket, Sendernummer, Zugangshinweise, Datenstand …).
- Neues Servermodell `portal_title.py` + `/api/portal-title`: gleiche Felder für alle Quellen, Anbieterangaben getrennt. Die alten Pluto-/JustWatch-Dialoge entfallen (keine doppelte Detailansicht mehr); die Netzkino-Expertenansicht (yt-dlp-Gegenprüfung, separat lizenzierte Datei) bleibt über „Angaben von Netzkino“ erreichbar.
- **Netzkino-Offline-Download repariert** (Björn: „URL can't contain control characters … 'Teil 1.mp4' (found at least ' ')“): Netzkino liefert Dateiadressen mit Leerzeichen. Download und Player kodieren solche Zeichen jetzt (`downloads.safe_url`, vorhandene %-Kodierung bleibt). Betroffene Aufträge mit „Erneut versuchen“ neu starten.

## 0.5.41 – Kataloge von Netzkino, Pluto und JustWatch bleiben nach dem Neustart sichtbar
- Björn (12.11.2026): Nach einem Neustart sah es so aus, als müssten die Kataloge neu geladen werden. Geprüft: Die Titel liegen dauerhaft in SQLite (`netzkino_links.sqlite3`, `pluto.sqlite3`, `justwatch.sqlite3` im Datenordner) und sind nach einem Neustart vollständig da (Neustart-Test mit eingespieltem Bestand). Irreführend war die Statusanzeige.
- **Statusanzeige:** Ein durch Beenden/Neustart abgebrochener Abruf blieb als „läuft“ gespeichert und erschien nach dem Start als „Noch nicht geladen“ (Pluto/JustWatch) bzw. „HAR-Startbestand“ (Netzkino). Jetzt: „Abruf unterbrochen · gespeicherter Bestand“; ist ein Bestand vorhanden, steht „Gespeicherter Bestand“ mit Stand-Datum und „bleibt nach Neustart erhalten“, auch auf den Dashboard-Karten.
- **Teilweise Abrufe** (JustWatch: einzelne Seiten, Pluto: Live-Sender nicht erreichbar) blenden ältere Titel nicht mehr aus; erst ein vollständiger Abruf nimmt nicht mehr angebotene Titel heraus.
- **Katalog-Übersicht je Quelle** (Björn: „im Dashboard ist bei Pluto und JustWatch noch die Übersicht für ARD/ZDF … genauso wie bei ARD/ZDF, aber spezifisch je Katalog, es sei denn man ist in der Gesamtansicht“): Im Katalog zeigen Netzkino, Pluto TV und JustWatch TV statt der ARD/ZDF-Übersicht eine eigene Karte mit Bestand, Live-Sendern bzw. abspielbaren Titeln, Stand, Werkzuordnung (eindeutig zugeordnet, zu prüfen, ohne Treffer, Anbieter nicht erreichbar, noch offen) mit Fortschrittsbalken, Offline-Kopien sowie „↻ Katalog jetzt laden“ und „Plattform öffnen“. „Mediatheken“ zeigt nur die ARD/ZDF-Übersicht, „Gesamt“ beide. Neuer schlanker Endpunkt `/api/film-platforms`.
- **Plattform-Reiter hingen bei „Katalogstatus wird geladen …“** (Björns Screenshots): Lädt die Liste länger, zeigt die Statuszeile jetzt die Wartezeit und welche anderen Anfragen noch offen sind; ein Fehler erscheint direkt in der Statuszeile mit automatischem neuen Versuch nach 15 s. Der Menüpunkt „Plattformen“ lädt den zuletzt gewählten Reiter beim Zurückkehren neu (vorher blieb er auf dem alten Stand).
- **Diagnose:** Jede Anfrage an den lokalen Dienst wird gemessen (`http_timing.py`): laufende Anfragen mit Alter und langsame Endpunkte (ab 5 s, nur Pfad, keine Suchbegriffe) stehen im Diagnose-Export unter `http`, Ereignis `http_slow_request` höchstens einmal pro Minute und Endpunkt.
- **Erststart:** Wurde ein Katalog noch nie abgerufen, lädt MediathekAtlas ihn einmal automatisch (etwa eine Minute nach dem Start). Danach wird nur mit „Alle 24 Stunden automatisch aktualisieren“ oder per Knopf neu geladen.

## 0.5.40 – JustWatch TV: eigene Filme und Serien, Wiedergabe und 30 Tage offline
- **Neue Quelle JustWatch TV** (Björn, 12.11.2026: „nur für die eigenen Filme und Serien“, 30 Tage offline). Geladen wird ausschließlich das kostenlose Paket „JustWatch TV Free“ (`jwt`); JustWatch Plus (Abo), Leihtitel (Store) und Angebote anderer Streamingdienste werden nicht übernommen. Katalog über die öffentliche GraphQL-Schnittstelle der Website (keine Anmeldung, keine Cookies), Abruf auf Knopfdruck oder alle 24 Stunden, Seiten mit Cursor, Bestand bleibt bei Fehlern erhalten. Formate nach Björns HAR-Mitschnitt vom 12.11.2026.
- **Gleich behandelt wie Netzkino und Pluto:** Plattform-Reiter „JustWatch TV“ (Filme, Serien → Folgen auf Abruf), Katalogquelle „JustWatch TV“ und Teil von „Gesamt“, Karte in der Plattformübersicht, Kategorienleiste mit Anzahl, Bewertung (★, zunächst die von JustWatch veröffentlichte IMDb-Bewertung, nach dem Abgleich die Referenz), „Großes Kino“/„Serienfavoriten“, Detailansicht mit Referenzabgleich, Hintergrundabgleich mit IMDb/TVDB/TMDB/OMDb/Wikidata.
- **Wiedergabe im MediathekAtlas-Player** für Titel, die JustWatch für externe Player freigibt (`streamUrlExternalPlayer`, HLS). Die signierte Adresse wird erst beim Abspielen bzw. Download frisch geholt und nie gespeichert. Titel ohne solchen Stream erhalten „Bei JustWatch ansehen“ (offizielle Seite).
- **Kopierschutz-Prüfung (`hls_guard.py`):** Vor Wiedergabe und Download werden Master- und erste Varianten-Playlist gelesen. Widevine/PlayReady/FairPlay/SAMPLE-AES → Abbruch mit Hinweis, keine Umgehung. Normales HLS (auch AES-128 mit Standard-Schlüsselformat) bleibt erlaubt.
- **30 Tage offline** (`justwatch_downloads.py`): gleiche Warteschlange, Ordner, Namen, MKV/NFO/metadata.json, Ablauf und „Jetzt löschen“ wie bei Pluto; Lizenz `justwatch_offline`. NFO erhält die IMDb-ID von JustWatch (`uniqueid imdb`), auch ohne Referenzabgleich. Die Datei enthält die Werbung, die JustWatch ausliefert.
- **Zusammengeführt statt verdoppelt:** Pluto und JustWatch teilen sich die Oberfläche (`web/portal_panel.js`, `pluto.js`/`justwatch.js` konfigurieren nur noch) und den Referenzabgleich (`portal_enrichment.py`, `pluto_enrichment` behält seine Funktionen). Doppelte-Auftrag-Prüfung gemeinsam in `netzkino_downloads.portal_duplicate`.
- Bilder von `images.justwatch.com` als Cover zugelassen.

## 0.5.39 – Mediathek-Genres und „Großes Kino“/„Serienfavoriten“ wieder im Katalog
- **Genre-Zuordnung wie früher sichtbar** (Björn, 12.11.2026): Der gemeinsame Katalog zeigt über den Karten wieder die Genres des Mediathek-Katalogs mit Anzahl, getrennt nach Filmen und Serien (dieselben Zahlen wie der frühere Baum „Filme, Serien & Genres“). Klick filtert, erneuter Klick hebt den Filter auf. Netzkino und Pluto TV liefern ihre Kategorien in dieselbe Leiste, im „Gesamt“-Katalog werden die Zahlen zusammengezählt.
- **„Entdecken“: Großes Kino und Serienfavoriten** wieder direkt im Katalog (vorher nur in der eingeklappten klassischen Ansicht). Gleiche Regel wie bisher: mindestens 7,5/10 bei mindestens 10.000 IMDb- oder 1.000 TMDB-Stimmen, nur bestätigte Werke. Gilt jetzt für alle Quellen (Netzkino und Pluto über ihren IMDb-/TMDB-Abgleich). Karten zeigen das Abzeichen „Großes Kino“/„Serienfavorit“ und die Bewertung (★) auch bei Mediathek-Werken.
- Die klassische Katalogansicht (Genre-Baum, Zuordnungsfilter, Downloadfilter) bleibt unverändert erhalten; der Klappbereich heißt jetzt „Klassische Katalogansicht (Genre-Baum, Zuordnung, Großes Kino), Scanner und Diagnose“, damit sie auffindbar ist.
- Genre „Krieg & Militär“ (JustWatch, TVDB) wird zu „Kriegsfilm“ vereinheitlicht wie IMDb „War“.
- Intern: `portal_reference.is_pick`/`in_collection`, Parameter `collection` für `/api/pluto` und `/api/netzkino-grouped`; die Kategorienleiste lädt den Genre-Baum nach, wenn er beim Start noch berechnet wird.

## 0.5.38 – Kategorien und Bewertungen für Netzkino und Pluto, Pluto-Details, Download-Metadaten wie ARD/ZDF
- **Pluto TV offline: 30 Tage** (Björn, 12.11.2026: die 20 Tage aus 0.5.37 waren ein Versehen). Bestehende Aufträge aus 0.5.37 behalten die beim Einreihen gespeicherte Frist.
- **Kategorien wie im Mediathek-Katalog** für Netzkino und Pluto: einheitliche deutsche Genre-Namen (`metadata.genre_names`), vorrangig aus der eindeutigen IMDb-/TVDB-/TMDB-Referenz, sonst aus den Angaben des Anbieters; „Unbekannt“ wenn nichts passt. Kategorienleiste mit Anzahl über der Liste, Filter per Klick, Sortierung nach Titel, Jahr oder Bewertung. Karten zeigen Bewertung (★ 7,9 IMDb) und Kategorien. Gemeinsames Modul `portal_reference.py` + `web/portal_categories.js` für alle Quellen.
- **Pluto-Abgleich mit IMDb/TVDB/TMDB/OMDb/Wikidata** (`pluto_enrichment.py`): dieselbe Anbieterkette und vorsichtige Auswertung wie bei Netzkino, automatisch im Hintergrund (ein Titel alle 6 s, gemeinsam mit den übrigen Anbieterabfragen begrenzt, Schalter „Metadaten automatisch“), Folgen nutzen die Prüfung ihrer Serie. Ergebnis wird verworfen, wenn sich Titel oder Jahr ändern.
- **Pluto-Detailansicht:** Cover, Inhaltsangabe, Art, Jahr, Laufzeit, Altersfreigabe, Bewertung, Kategorien, Pluto-Genre/-Kategorie, Referenzen mit Besetzung, „▶ Ansehen“, „⬇ Offline speichern (30 Tage)“, „Mit IMDb, TVDB, TMDB und Co. abgleichen“; bei Serien „Folgen anzeigen“.
- **Downloads wie bei ARD/ZDF:** Vor dem Einreihen eines Netzkino- oder Pluto-Titels läuft der Referenzabgleich (zwischengespeichert, höchstens 7 Tage alt). Der Auftrag erhält einheitliche Genres, Besetzung, Regie, Drehbuch, Cover, NFO-ID (IMDb/TVDB/TMDB) samt `source_provider`, Bewertung; fehlende Cover/Hintergründe ergänzt wie bisher der Download-Worker über TMDB/TVDB. Ein Anbieterfehler verhindert den Download nicht. Mehrdeutige Treffer setzen keine fremde ID.
- **Pluto im Katalog-Dashboard:** Quellenwahl „Pluto TV“ und Pluto im „Gesamt“-Katalog (Suche, Genre, Bewertung, Details, Ansehen). Plattformübersicht mit eigenen Karten für Netzkino und Pluto (Titel, Stand, Abgleich, Offline-Kopien, „Öffnen“).

## 0.5.37 – Pluto TV offline speichern (20 Tage)
- **Freigabe von Pluto TV (Björn, 12.11.2026): 20 Tage Offline-Nutzung.** Pluto-Filme und einzelne Folgen haben jetzt „⬇ Offline speichern (20 Tage)“. Umgesetzt wie bei Netzkino: Der Titel wird ein normaler Auftrag in der gemeinsamen Download-Warteschlange (gleicher Worker, gleiche Ordner und Namen `Filme/Titel (Jahr)/…` bzw. `Serien/Serie/Season NN/Serie - SxxEyy.mkv`, MKV mit eingebetteten Metadaten, NFO, metadata.json, Cover, `.partial`-Zwischenstände). Folgen ohne Staffel-/Folgennummer landen als „Serie - Folgentitel“ unter Filme, es wird keine Staffel erfunden.
- **Ablauf:** 20 Tage nach Fertigstellung entfernt die stündliche Prüfung Datei, NFO und metadata.json (nur eigene Dateien, nie außerhalb des Downloadordners). „Jetzt löschen“ entfernt früher. Offline-Kopien werden nicht im Verbund geteilt, nicht als Mediathek-Werk markiert und lassen sich nur in MediathekAtlas abspielen. Danach kann der Titel erneut gespeichert werden.
- **Technik:** Unmittelbar vor dem Download holt MediathekAtlas die offizielle HLS-Adresse mit frischer Sitzung; ffmpeg kopiert die beste Variante ohne Neukodierung. Die Adresse mit Sitzungsschlüssel wird nirgends gespeichert (metadata.json enthält nur Host und Pfad). Abbrechen beendet ffmpeg sofort, auch bei stehender Verbindung. Ist der Stream deutlich kürzer als die Katalog-Laufzeit, gilt der Download als unvollständig.
- Die Datei enthält, was Pluto ausliefert, inklusive Werbung; es wird nichts herausgeschnitten. Live-Sender und ganze Serien (statt einzelner Folgen) werden abgelehnt.
- Pluto-Bereich: neue aufklappbare Liste „Offline-Kopien von Pluto TV“ mit Fortschritt, Resttagen, Abbrechen, Erneut versuchen und Jetzt löschen; Karten zeigen den Offline-Stand. Downloadkarten unterscheiden „Netzkino offline bis …“ und „Pluto TV offline bis …“.
- Intern: Die Offline-Verwaltung (`netzkino_downloads`) kennt mehrere Portale mit eigener Frist; neue Endpunkte `/api/pluto-download-add`, `/api/pluto-downloads`, gemeinsamer `/api/offline-download-action` (der Netzkino-Endpunkt bleibt).

## 0.5.36 – Pluto TV: Filme, Serien und Live-Sender
- **Pluto TV ist jetzt eine aktive Quelle** (Plattformen → Pluto TV) statt des bisherigen Platzhalters: Filme, Serien mit Staffeln/Folgen und Live-Sender, durchsuchbar nach Titel, Genre und Kategorie.
- **Wiedergabe im MediathekAtlas-Player**, wie bei Mediathek- und Netzkino-Titeln: „▶ Ansehen“ bzw. „▶ Live ansehen“. Gespielt wird der offizielle HLS-Stream von Pluto TV inklusive Werbung (nativ in Safari, sonst über ffmpeg). Live-Sender ohne Zeitleiste.
- **Katalog:** anonyme Website-Sitzung von Pluto TV (keine Anmeldung, keine Cookies; Sitzungsschlüssel nur im Arbeitsspeicher). Abruf auf Knopfdruck oder optional alle 24 Stunden. Folgen einer Serie werden beim Öffnen geladen und sechs Stunden zwischengespeichert. Titel, die Pluto aus dem Angebot nimmt, verschwinden beim nächsten Abruf; ein fehlgeschlagener Abruf lässt den Bestand stehen.
- **Grenzen:** Downloads siehe 0.5.37. Den Länderkatalog bestimmt Pluto anhand der Internetverbindung; keine Geo-Umgehung, kein Entfernen von Werbung.
- Diagnoseexport enthält Pluto-Zähler und letzten Fehler (ohne Sitzungsschlüssel und Adressen).

## 0.5.35 – Netzkino-Gesamtkatalog über den Kategoriebaum
- **Auswertung deines Netzkino-Mitschnitts (12.11.2026):** Kategorieseiten sind nicht seitenweise begrenzt („Starkino“ lieferte 214 Titel, „Halloween“ 60), die Startseite zeigt nur Auszüge („…-frontpage“, rund 20 Titel). Jeder Film nennt in seinen Details seine vollständigen Kategorien samt Oberkategorie (z. B. `krimi` → `thrillerkino`, `sozialdrama` → `dramakino`, `joyn-netzkino` → `joyn`).
- Der Katalogabgleich fragt deshalb zusätzlich den Kategoriebaum ab: Wurzeln `netzkino-genre`, `themenkino-genre`, Action, Thriller, Drama, Komödien, Kinder, Starkino und die Partnerkataloge (inkl. deren Unterkategorien), 15 im Mitschnitt gesehene Volllisten sowie alle Kategorien, die beim Laden von Filmdetails (automatische Anreicherung, Detailfenster, Mitschnitt-Import) auftauchen. Höchstens 400 zusätzliche Kategorien, 0,7 s Abstand, Zeitbudget 15 Minuten.
- Netzkino-Status zeigt die Zahl gemerkter Kategorien.
- CI: Die QPKG-Nutzdatenprüfung liest die Header-Offsets selbst (`build_nas.py --list-qpkg`). `qbuild --extract` kopiert per `dd` aus einer Pipe und war zufällig um einige Bytes zu kurz; das Paket selbst war in Ordnung.

## 0.5.34 – Netzkino direkt im App-Player, Katalog über die Startseite hinaus
- **Netzkino-Filme direkt abspielen wie bei der ARD-Mediathek:** „▶ Ansehen“ (Netzkino-Katalog, Gesamtkatalog, Detailfenster) öffnet den eingebauten MediathekAtlas-Player, kein WebKit-Zusatzfenster mehr. Eine vorhandene 30-Tage-Offlinekopie wird bevorzugt, sonst ermittelt ytdl-nightly die MP4-Datei von Netzkino; der Browser spielt sie direkt, bei Problemen springt ffmpeg als Stream ein (Spulen inklusive, Adresse 15 Minuten zwischengespeichert). Wiedergabeposition wird wie bei Mediathek-Videos gemerkt. DRM-, Geo- und Netzwerkfehler werden deutsch gemeldet. Die Meldung „WebKit-Player nicht installiert“ entfällt; NAS-Installationen können Netzkino jetzt ebenfalls abspielen.
- **Ursache „nur 808 Titel“:** Netzkino veröffentlicht keine Film-Sitemap (am 12.11.2026 geprüft: `/sitemap.xml` liefert die Startseite, `/api/sitemap` nur 4 Infoseiten). Die 808 Titel sind alles, was die rund 30 Startseiten-Kategorien zeigen. Die Sitemap-Ergänzung aus 0.5.33 bleibt, bringt derzeit aber nichts.
- **Neue Wege zu weiteren Titeln:** (1) Der Abgleich folgt Kategorien, die in Kategorieantworten genannt werden (höchstens 160 zusätzliche, Zeitbudget 7 Minuten). (2) Titel, die in Netzkino-Filmdetails mitgeliefert werden (z. B. Empfehlungen), kommen automatisch dazu; die Hintergrund-Anreicherung besucht nach und nach alle Titel. (3) „Weitere Titel aus einem Netzkino-Mitschnitt übernehmen“: HAR-Datei aus dem Browser wählen, MediathekAtlas übernimmt alle darin enthaltenen Titel. Nur Antworttexte von netzkino.de verlassen den Browser, keine Cookies oder Kopfzeilen.
- Diagnose und Netzkino-Status zeigen entdeckte Kategorien, Seitenhinweise der Kategorien (`pageInfo`/`totalCount`), über Details ergänzte Titel, Mitschnitt-Titel, beobachtete Netzkino-Abfragen und die Anzahl je Quelle. Behoben: Sitemap-Kennzahlen fehlten im Diagnoseexport.

## 0.5.33 – Netzkino-Gesamtkatalog, automatische Metadaten, Dashboard-Aufteilung
- **Mehr Netzkino-Titel:** Der Abgleich las bisher nur die kuratierten Startseiten-Kategorien (rund 450 von über 2.500 Titeln); eine Anpassung dafür gab es weder im Repository noch in ytdl-nightly. Neu ergänzt jeder Abgleich fehlende Titel aus der Netzkino-Sitemap (`/sitemap.xml`, Sitemap-Index, `/api/sitemap`). Die Sitemap-Erkennung kennt jetzt die aktuelle Route `netzkino.de/details/<slug>`. GraphQL-Daten bleiben vorrangig, nichts wird gelöscht. Details (Cover, Jahr, Beschreibung) lädt die App für solche Titel über den Seiten-Slug nach.
- Netzkino-Status und Diagnoseexport zeigen „Startseite + Sitemap“, Anzahl Sitemap-Titel und neue Titel bzw. warum die Sitemap nicht erreichbar war.
- **Automatische Metadaten:** IMDb (offline), TVDB, TMDB, OMDb und Wikidata werden für alle Netzkino-Titel im Hintergrund abgefragt, nicht mehr nur per Klick. Ein Titel alle 6 Sekunden, höchstens zwei Anbieteranfragen gleichzeitig, abschaltbar über „Metadaten automatisch“. Ergebnisse erscheinen beim Öffnen des Titels; Netzkino-eigene Angaben haben Vorrang.
- Netzkino-Offline-Downloads übernehmen diese Metadaten (Genres, Besetzung, Bewertung) und bei eindeutiger Zuordnung die IMDb-/TMDB-/TVDB-ID in die NFO.
- **Dashboard:** „Verarbeitung & Warteschlangen“ ohne gestreckte Leerflächen; Episoden & Senderbelege breiter, kleine Gruppen kompakt. Unter 1450 px stehen „Letzte Erkennung“ und „Anbieter“ untereinander, die Kennzahlen bleiben fünfspaltig.
- main (PR #26) ist zusammengeführt.

## 0.5.32 – Netzkino offline (ytdl-nightly), Integrationsstand im Repository
- **Netzkino offline ansehen:** Im Netzkino-Detailfenster lädt „Offline herunterladen (30 Tage)“ den Titel herunter. Die Dateiadresse ermittelt das mitgelieferte **ytdl-nightly** (github.com/boogietown1981/ytdl-nightly, Stand 2026.11.06) mit einem aktuellen Netzkino-Extraktor für `netzkino.de/details/…`; der alte ytdl-Netzkino-Extraktor nutzt eine abgeschaltete API.
- **Ein Download-Weg für alles:** Netzkino-Titel laufen durch dieselbe Warteschlange und denselben Worker wie Mediathek-Videos: gleiche Ordner und Namen (`Filme/Titel (Jahr)/Titel (Jahr).mkv`, `Serien/Serie/Season NN/Serie - SxxEyy.mkv`), MKV mit eingebetteten Metadaten, NFO, metadata.json, Cover und `.partial`-Zwischenstände. Die bisher getrennte Netzkino-Downloadwarteschlange (eigene SQLite + eigener Worker) entfällt; offene Altaufträge werden beim Start übernommen.
- **30 Tage offline:** Die Frist beginnt mit dem fertigen Download. Detailfenster und Downloadliste zeigen „offline bis … · noch n Tage“. Danach entfernt MediathekAtlas stündlich geprüft genau die Dateien dieses Auftrags (Video, NFO, metadata.json, nur dazugehörige Bilder/leere Ordner). „Jetzt löschen“ entfernt früher. Netzkino-Offlinekopien werden nur in MediathekAtlas abgespielt, nicht per Browser auf andere Geräte kopiert und nicht im Verbund geteilt.
- **Grenzen:** DRM-geschützte Titel und reine HLS/DASH-Angebote werden abgelehnt; keine Geo-Umgehung, keine Konten oder Cookies. Netzkino liefert nur innerhalb Deutschlands aus.
- **Eigene Lizenzdateien** (0.5.31.9) bleiben als aufklappbare Option erhalten, nutzen jetzt aber ebenfalls die gemeinsame Warteschlange und Benennung (ohne Ablauf).
- **Architektur:** Der Stand 0.5.31.1–0.5.31.11 lag nur als Kette lokaler Patch-Skripte vor und ist jetzt regulärer Quellcode im Repository. Behoben dabei: (1) Build-Abbruch in Schritt 12 (Versionsprüfung verglich die ganze `version.py` statt des VERSION-Werts), (2) QNAP/Synology-Pakete enthielten Module mit Dateirechten 0600, der NAS-Dienst brach beim Start mit „Permission denied“ ab, (3) die Erweiterungstests des Integrationspakets prüften veraltete Modulkopien statt des ausgelieferten Codes, sie laufen jetzt im Repository und in CI, (4) ein fehlendes Statusboard ließ den gemeinsamen Katalog komplett abbrechen, (5) das Netzkino-WebKit-Fenster wurde nur vom Integrationsskript gebaut, jetzt von `build_macos.py`, (6) Netzkino-Dateien waren auf dem NAS gar nicht ladbar (Worker nur im lokalen macOS-Modus).
- Startprotokoll und Bundle-Version zeigen wieder die tatsächliche Version.

## 0.5.31.11 – Mediatheken-Dashboard, Episoden-Queue und Diagnose (Test)
- Die Scanner-/Erkennungsübersicht ist im Mediatheken- und Gesamtkatalog wieder direkt sichtbar, nicht mehr im eingeklappten Expertenbereich. Die Zahlen bleiben ausdrücklich auf den Mediathekenbestand bezogen.
- Unter „Letzte Erkennung“: getrennte responsive Bereiche für Worker, Qualität, Episoden & Senderbelege sowie Fehler/Wiederholungen. Jeder bisherige Statuszähler bleibt sichtbar.
- Episoden-Worker priorisieren innerhalb der **48 ältesten fälligen Aufgaben** Fälle mit expliziten Staffel-/Folgenhinweisen; weder Aufgaben noch Wartezeiten werden gelöscht oder umgeschrieben. Manuelle Priorität hat weiterhin Vorrang.
- TMDB-HTTP-404 für einzelne Staffeln verwirft keine bereits erkannten Serienmetadaten; die Episodenliste bleibt als unvollständig gekennzeichnet, ohne falsche Bestätigung.
- OMDb-Anbieterstatus zeigt auch den konkreten Grund einer Pause (z. B. Schlüssel abgelehnt), ohne Schlüssel anzuzeigen.
- Netzkino-Kategoriediagnose unterscheidet >=20 Einträge, >20 Einträge und größte beobachtete Kategorie. Eine feste 20er-API-Grenze wird nicht mehr behauptet. Auch 29/29 Kategorien bedeutet nicht vollständigen Gesamtkatalog.
- ArchiveMedia-Vollmodus, Netzkino-Wiedergabe, deutsche Metadatenprovider, Videoaudit und bestehende Downloads bleiben erhalten. Keine Änderung an Live-Daten oder GitHub.

## 0.5.31.10 – In-App-Wiedergabe und ehrliche Katalogabdeckung (Test)
- „Ansehen“ ruft den offiziellen Netzkino-Player in einem nativen WebKit-Fenster innerhalb der lokalen macOS-Anwendung auf. Es erfolgt kein automatischer Browser-Redirect mehr. Fehlende WebKit-Unterstützung wird verständlich gemeldet; „Beim Anbieter öffnen“ bleibt eine separate manuelle Aktion.
- Im gemeinsamen Hauptkatalog und im Plattformkatalog wird „▶ Ansehen“ direkt angeboten. Eine Serienkarte führt weiterhin zur Folgenübersicht.
- Der Netzkino-Abgleich wird nicht mehr als vollständiger Gesamtkatalog bezeichnet: Der aktuelle Adapter kennt kuratierte Startseitenkategorien mit oftmals 20 Elementen. Diagnose zählt Kategorien am beobachteten Anzeigelimit. Es wird keine unbelegte GraphQL-Paginierung erfunden, keine fehlenden 1.700 Titel behauptet und kein Katalogeintrag entfernt.
- Die separate Verwaltung ausdrücklich lizenzierter Dateien bleibt im aufklappbaren Expertenbereich erhalten, wird aber nicht mehr als regulärer Netzkino-Filmdownload dargestellt. Weiterhin keine Freigabe zur Aufzeichnung werbefinanzierter Streams/Umgehung von Schutzmaßnahmen.
- Bestehende Mediatheken-, IMDb/TMDB/TVDB-, Videoaudit-, Serien- und ArchiveMedia-Funktionen bleiben erhalten. Keine automatische GitHub-Schreiboperation.

## 0.5.31.9 – Gesondert berechtigte Datei-Downloads (Test)
- Netzkino-Titeldetails zeigen den offiziellen Weg zur Offline-Nutzung in der Netzkino-App und zusätzlich eine **separat lizenzierte** Direktdatei-Option. Netzkino AVOD-/Plus-Angebote erhalten **keinen** automatischen Downloadstatus; die Filmlizenz und der erlaubte Datei-Endpunkt müssen unabhängig vorliegen.
- Eigene persistente SQLite-Warteschlange für ausdrücklich freigegebene HTTPS-MP4/MKV/WebM/MOV-Dateien. Ein Worker, Fortschritt, Pause, Retry und Range-Wiederaufnahme mit Datei-Validator; atomare Veröffentlichung und No-Overwrite. Keine `yt-dlp`-Downloads, keine HLS/DASH-, DRM-, Werbe- oder Geo-Umgehung.
- Ausführliche lokale Fehlermeldungen ohne Medien-URL/Token in UI oder Diagnose. Filmdatenbank/ArchiveMedia/öffentlich-rechtliche Jobs bleiben getrennt und unverändert.
- Quellcode-Freigabe ist keine Kopierlizenz für Inhalte: Die in der App angegebene Rechtebasis wird **nicht unabhängig verifiziert**. Automatische Dateiausleitung für den normalen Netzkino-Katalog bleibt deaktiviert.

## 0.5.31.8 – Einheitliche Katalognavigation und Detailfenster (Test)
- **Ursachenbehebung Netzkino-Modal:** Globale `aside`-Navigation wirkte ungewollt auf die Detail-Sidebar und versetzte das Cover an den Fensterrand; Sidebar nun `div`, Root-Navigation auf `body > aside` begrenzt. Vollbreiter, responsiver Infobereich mit zweispaltigen Fakten und unverändertem Provenienz-Abgleich.
- **Einheitliche Hauptansicht:** Gesamt / Mediatheken / Netzkino über eine Such-, Genre- und Sortierleiste; gleiche Film-/Serienkarten und Detailaktionen, gemeinsame Ergebnissicht ohne Vermischen der Datenbanken. Serienfolgen von Netzkino bleiben innerhalb des Hauptkatalogs navigierbar.
- **Bestandsschutz:** Der vollständige öffentlich-rechtliche Katalog mit Scanner, Fortschritt, Suchbaum und bisherigen Aktionen bleibt als erweiterter aufklappbarer Bereich erhalten; ArchiveMedia PR #24, Videoaudit PR #23, Netzkino GraphQL, Referenzprüfung und offizieller Player bleiben unverändert.
- **Präzision:** Katalogtreffer pro Quelle paginiert; globale Sortierung über Hunderttausende Werke und automatische Cross-Provider-Werkidentität werden nicht als erledigt behauptet. Pluto TV bleibt eine nicht aktive Quelle.

## 0.5.31.7 – Anbieterübergreifende Netzkino-Metadatenprüfung (Preview)
- Kompakter Netzkino-Detaildialog: Kurzdaten (Jahr, FSK, Laufzeit, Land, Sprache, Zugang) links als zweispaltige Kacheln; Beschreibung und vollständige Credits rechts. Responsive ohne versteckte Felder.
- Netzkino-Titeldetails können die bestehende ARD/ZDF-Kette IMDb Offline, TVDB, TMDB, OMDb und Wikidata verwenden. Nur auf Nutzerauswahl; Ergebnisse werden sieben Tage lokal zwischengespeichert, unvollständige Providerergebnisse kürzer.
- Datenprovenienz je ergänztem Feld; vorhandene Netzkino-Titel, Covers, Beschreibungen und Rechte bleiben maßgeblich. Film-/Serienidentitäten werden nicht automatisch als bestätigt markiert; widersprüchliche Referenzen erfordern Prüfung.
- Ausdrückliche Serien-/Folgen-Trennung: Ein bestätigter Serientitel weist noch keine konkret verfügbare Episode nach.
- Diagnose: aggregierte Referenzstatus-Zähler ohne Film-IDs, Titel, Streamingadressen oder API-Schlüssel.
- Deutsche Mediathek, PR #23 Videoaudit, PR #24 ArchiveMedia, Netzkino-GraphQL, yt-dlp-Metadatenprobe und offizielle WebKit-Wiedergabe unverändert.

## 0.5.31.6 – Quellennavigation, Netzkino-Details, optionaler yt-dlp-Check (Preview)
- Hauptansicht: Gesamt / Mediatheken / Netzkino ohne Verschmelzen der beiden Datenbanken oder unerwiesene Dubletten-Zusammenführung. Netzkino wird zusätzlich im Hauptkatalog mit Filmen/Serien angezeigt.
- Detailfenster analog zur Mediatheken-Titelseite: Beschreibung, Originaltitel, Jahr, Genres, FSK, Laufzeit, Land, Originalsprache, Besetzung, Regie, Drehbuch und Anbieterkategorie – nur soweit vorhanden; fehlende Daten bleiben sichtbar als unbekannt.
- Bei manuellem Öffnen werden öffentlich sichtbare Netzkino MovieDetails-Metadaten per im HAR beobachteter GraphQL-Operation geladen und sieben Tage datensparsam zwischengespeichert; keine Streamadressen und keine massenhaften Filmseitenaufrufe.
- Optionaler yt-dlp-Metadatencheck nur nach Nutzerklick. Ausgabe-Whitelist, Zeit-/Größenlimits, kein Mediendownload, kein Übernehmen von Streaming-URLs und keine Verfügbarkeits- oder Rechtebestätigung.
- Native macOS-Wiedergabe im separaten, selbst erzeugten WKWebView-Fenster über die offizielle Netzkino-Seite, sofern Swift auf dem Ziel-Mac vorhanden; sonst Browserlink. Keine Werbung/DRM umgehen.
- Pluto-TV-Reiter als ausdrücklich noch nicht aktiver Platzhalter. Keine Behauptung eines vorhandenen Extraktors oder Downloadrechts.
- Diagnose ergänzt Zahl öffentlicher gecachter Details und gesperrter Wiederholungsversuche; keine Nutzerdaten, Titel oder URL-Export.
- PR #23 Videoaudit und PR #24 ArchiveMedia-Vollmodus sowie getrennte Downloadwarteschlangen unverändert; vollständiger nativer Build auf dem Mac erforderlich.

## 0.5.31.5 – Netzkino: Filme / Serien / Folgen (lokale Testversion)
- Öffentliche Netzkino-Katalogeinträge getrennt nach Filmen und Serien anzeigen. Explizit mit Staffel- oder Folgennummer gekennzeichnete ContentMovie-Einträge werden als einzelne Episoden eingeordnet, ohne die Rohdaten umzuschreiben.
- Serien erhalten eine stabile, zusammengefasste Karte; Folgen sortiert nach Staffel und Folgennummer, jede Folge behält ihre offizielle Netzkino-URL. Unklare Film-Mehrteiler und Filmreihen werden nicht automatisch zu Serien.
- Nummerierungslücken werden als Kataloghinweise angezeigt, nicht als Verfügbarkeitsbehauptung. Manuelle Verknüpfungen bleiben erhalten.
- Diagnoseexport enthält getrennte Film-/Serien-/Episodenzähler, ohne Titel, URLs oder Nutzerdaten. Keine Veränderung des Download-, Werk- oder ArchiveMedia-Katalogs.
- ArchiveMedia-Vollmodus, Internet-Archive-Adapter, Netzkino-GraphQL-Abgleich, Warteschlangen-Fix und fortsetzbares Videoaudit bleiben erhalten.

## 0.5.31.4 – Netzkino-Kategoriefehler / Plattformanzeige (Teststand)
- Leere Netzkino-Kategorien werden von echten GraphQL-/Netzwerkfehlern unterschieden; bei Kategoriefehlern bleibt ein vorhandener gültiger Homepage-Katalog als ausdrücklich unvollständiger Teilabgleich verfügbar.
- Rate-Limits (429) und Zugangsfehler (401/403) stoppen weitere Kategorieabfragen. Rückzug statt Umgehung. Vollständigkeitsstatus und letzter vollständiger Abgleich werden separat persistiert.
- Diagnose enthält nun Anzahl leerer Kategorien, Fehlerarten und letzten Teil-/Voll-Abgleich; keine Filmnamen, Medienlinks, HAR-Header oder Sitzungstokens.
- Ein UI-Ladefehler erscheint neben dem Katalog-Knopf statt nur unterhalb der Trefferliste. Beim Wechsel auf den Netzkino-Reiter werden Einträge neu geladen.
- Netzkino blendet ArchiveMedia-Companion, Archivscanner, alte Netzkino-Doppelformulare und gemischte Portal-Trefferliste aus. Der ArchiveMedia-Vollmodus bleibt im Archiv-Reiter erhalten.
- Isolierte Portaldaten, bestehende Arbeitsdatenbank und 0.5.31.1-Altbestandsprüfung bleiben unverändert. Kein automatischer Video-Download.
- Öffentliche GraphQL-Endpunkte sind anhand eines HAR verifiziert, die rechtliche Freigabe und dauerhafte Live-Nutzbarkeit nicht; Test-Build, noch kein offizielles Release.

## 0.5.31.3 – integrierter Plattform- und Fehlerdiagnose-Teststand
- Einheitliche Testversion aus 0.5.31 + Netzkino-GraphQL/HAR-Katalog + 0.5.31.1-Korrekturen + ArchiveMedia-Companion/Portaladapter aus PR #24.
- Diagnoseexport und Offline-CLI protokollieren nun Netzkino-Bestände, GraphQL/HAR-Herkunft, Kategoriestatus, Letztfehler, Metadatenvollständigkeit, Altbestandsprüfung und Archive-Portalscopes; ohne Medien-URLs, Titel oder Zugangsdaten.
- Netzkino-Katalogabgleich protokolliert Start, erfolgreiche Kategorien, neue/geänderte Titel und HTTP-Fehlerklasse datensparsam.
- ArchiveMedia bleibt als eigenständige vollständige Anwendung erhalten; ihre Mediathek- und Download-Daten werden nicht verändert.
- Abgleich gegen GitHub-PRs #23 und #24; Voll-Tests und nativer macOS-Build sind auf Zielgerät nachzuholen.

## In Arbeit – Isolierte externe Filmportale (noch keine Release-Freigabe)

- **Plattformtrennung:** Deutscher Mediathekkatalog und seine Download-/Episodenwarteschlangen bleiben unberührt. Internet Archive und Netzkino erhalten eigene SQLite-Daten, eine eigene Übersicht, Sprachfilter und Quellstatus.
- **ArchiveMedia 0.10.53:** Vollständige ArchiveMedia-Anwendung bleibt unabhängig erreichbar; Read-only-Companion über localhost zeigt Zustand und öffnet die Original-Oberfläche. Der begrenzte neue URL-/Uploader-/Collection-Scanner ist kein Ersatz für Clean Scan, die historische Uploader-Priorisierung oder die komplette ArchiveMedia-Pipeline.
- **Metadatenvergleich:** Herkunft, unabhängige Werkreferenzen, Episoden- und tatsächliche Videolaufzeit sowie technische Ton- und Untertitelspuren bleiben getrennte Belege. Originaler ArchiveMedia-Referenzpfad und die Werkvalidierung werden MIT-lizenziert wiederverwendet. Gemeinsame Dateibenennung bleibt `package_media.canonical_target`.
- **Internet Archive:** Vom Nutzer ausgelöste Suche, originale Film-/Serien- und Fassungsgruppen, Clip-Filter, optionale gezielte 8-MiB-Teilproben, kein pauschaler Download. Scopes werden mit Cursor und Retry gespeichert und können parallel zu den deutschen Scan-Workern laufen.
- **Netzkino:** Nur vom Nutzer eingegebene Filmseiten; kein Scraping, keine Stream-Extraktion und keine Umgehung der Werbewiedergabe.
- **Freigabe:** Getrennter Entwicklungsbranch; native macOS-, Linux- und NAS-Tests und reale Archivetests vor einem Merge erforderlich.



## 0.5.31.2 – Netzkino-Katalogimport (lokale Preview)
- Die im Netzwerkmitschnitt vom 11.11.2026 beobachteten lesenden GraphQL-Katalogoperationen AllContent und CategoryDataBySlug ersetzen die ungeeignete Sitemap als Standardquelle.
- Bereinigter HAR-Startbestand: 449 unterscheidbare Film- und Serienobjekte; keine HTTP-Header, Sitzungen, Player-Streams oder Tokens enthalten. Der Snapshot ist ausdrücklich kein Live-Verfügbarkeitsnachweis.
- Katalogdaten je Film: Quelltitel, Jahr, Genre-Hinweise, FSK, Cover, Quellkategorie und AVOD-/Plus-Hinweis, soweit vom Anbieter geliefert.
- Begrenzte Kategorienabfragen, Timeouts, vorübergehende Fehler und HTTP-429-Rückzug. Keine automatischen Filmseiten-Massenabfragen und keine Medien-Downloads.
- Die bestehende SQLite-Netzkino-Datenbank wird verlustfrei um zusätzliche Felder erweitert. Bestehende manuelle Links, Downloads und MediathekView-Katalog bleiben erhalten.
- Eine Nutzungserlaubnis für automatisierten Abruf ist nicht bestätigt. Die Schnittstelle kann sich ändern; vollständige Filmabdeckung wird nicht behauptet.

## 0.5.31.1 – Netzkino + sichere Altbestands-Klassifizierung (lokale Testversion)
- Sichere Episoden-Trigger: Duplicate-Guard statt INSERT OR IGNORE innerhalb von UPSERT-Triggern; Bestandsjobs bleiben erhalten.
- Einmaliger fortsetzbarer lokaler Videorollen-Audit mit eigenem Cursor, kleiner Batchgröße, Persistenz und Fortschrittsanzeige. Auch bereits erkannte und automatisch bestätigte Werke werden geprüft.
- Manuell bestätigte Zuordnungen und fertige Downloads bleiben unverändert; automatische Treffer mit Laufzeitkonflikt erhalten eine Prüfmarkierung statt einer stillen Herabstufung.
- Separater Netzkino-Streaming-Katalog mit Link-Speicherung, opt-in Sitemap-Prüfung und offiziellem Player (kein Mediendownload).
- Die Live-Katalogquelle und macOS-Ausführung müssen auf dem Zielgerät noch überprüft werden.

## Unreleased: Netzkino-Streaming-Preview (lokaler Patch, Basis v0.5.31)
- Separater Netzkino-Reiter: manuell geprüfte Filmseiten als Streaming-Verknüpfungen speichern und über den offiziellen Webplayer öffnen.
- Isolierte lokale SQLite-Datenbank `netzkino_links.sqlite3`; kein Einfluss auf den Senderkatalog, Downloadjobs, MeshSync oder bestehende Metadaten.
- Nur HTTPS auf `netzkino.de`, keine fremden URLs, keine Stream-Extraktion, kein Video-Download und keine DRM-Umgehung.
- Regressionsprüfungen für URL-Validierung, Dubletten, Persistenz, Löschung und Suchfilter.
- Ausstehend: offizieller Katalogimport, Metadatenreferenzen und native macOS-/NAS-Integrationstests.

# Änderungsverlauf – MediathekAtlas

## 0.5.31 – 10. November 2026 (Preview, Kausalitätsprüfung & Einstellungen)

- Folgekorrektur nach Diagnose 10.11.: Episodenprüfungen erfassen jetzt auch frühe Kurzvideo-Abbrüche und explizite Trailer als eigene Sitzungszähler; Zählung erst nach erfolgreichem DB-Commit. Prüfungen, bestätigte Episoden, Verdachtsfälle, Extras, Retries und Rückstellungen werden getrennt angezeigt.
- Laufzeitbelege enthalten die beim Sender importierte tatsächliche Dauer, die Referenzlaufzeit, deren Herkunft (Metadatenanbieter oder Serien-Katalogmedian) und einen präzisen Begründungstext; Details, Prüfdialog und Katalogkarten machen diese Felder sichtbar. Verdachtsfälle sind keine endgültigen Trailerbeweise.
- TMDB und Wikidata öffnen bei zwei transportbedingten Fehlern innerhalb eines kurzen Fensters eine anbieterspezifische Netzwerkpause (anfangs 3, maximal 15 Minuten). Unabhängige Anbieter und IMDb Offline bleiben verfügbar, es werden keine falschen Negativtreffer gecacht; Wiederholungsaufträge behalten ihre SQLite-Wiedervorlagen. Pausenzustände sind im Dashboard und der Anbieterstatistik sichtbar.
- Zähler-, Laufzeitquellen- und Ausfallregressionstests ergänzen die bisherige 0.5.31-Suite; bei vielen Kurzvideos bleibt die Ereignisprotokollierung begrenzt.

- Kausalitätsprüfung nach dem Prinzip aus ArchiveMedia: Serienidentität und vollständige Episodenidentität werden getrennt behandelt; offenkundige Trailer, Teaser, Openings, Extras und Ausschnitte werden bereits beim Import anhand eindeutiger Titelmarkierungen als Kurzformate geführt.
- Unabhängige IMDb-, TMDB- und TVDB-Laufzeiten werden mit der vom Sender bereits angegebenen tatsächlichen Dauer verglichen. Beispiel: 2 Minuten statt 20 Minuten → Verdacht auf Ausschnitt, keine automatisierte vollständige Episodenbestätigung.
- Zwei-Minuten-Episoden echter Kurzformatserien bleiben möglich, wenn die Referenzdauer ebenfalls kurz ist oder keine unabhängige Soll-Laufzeit bekannt ist. Auf Basis der Laufzeit allein wird nichts definitiv als Trailer deklariert.
- Bereits identifizierte Serien behalten ihre Werkidentität, während auffällig kurze einzelne Videofassungen als überprüfungsbedürftig markiert und aus der Episodenwarteschlange genommen werden. Explizit als Trailer bezeichnete automatische Alteinträge werden im regulären Erkennungslauf als Sonderformat eingeordnet.
- Persistente SQLite-Trigger werden bei bestehenden Katalogen einmalig migriert. Manuelle und bereits endgültig bestätigte Zuordnungen werden nicht automatisch verändert.
- Download-Kontrolle: vorhandene Sender-Laufzeitdaten werden vor jedem Download genutzt, ohne FFprobe oder FFmpeg auszuführen. FFprobe misst eine tatsächlich heruntergeladene Datei vor der Veröffentlichung; erst danach wird FFmpeg für verlustfreies Remuxing eingesetzt. Kein FFprobe-Massenscan.
- Einstellungen auf responsive Kacheln und ausklappbare Menüs umgestellt: Erkennung & Worker, Bibliothek, API-Schlüssel, IMDb, Werkzeuge sowie NAS/Verbund. Die vorhandenen Formularfelder und Sicherheitsfunktionen bleiben bestehen.
- Regressionstests für Anime-Beispiele, Trailer-Ausnahmen, kurze echte Episoden, Neustart-Persistenz, Download-Vorprüfung und Einstellungen.
- Die geplante FTS5-Suche und Kategorie „Letzte Chance“ sind eigene weitere Arbeitspakete und nicht Bestandteil dieses Teils der Preview.


## 0.5.30 – 10. November 2026 (Preview)

- Sender-First-Episodenprüfung: Der Episodenworker übernimmt bereits importierte, eindeutig zugehörige ARD-/ZDF-Senderlinks und ihre Quellidentitäten, bevor IMDb Offline nach einer Episode sucht.
- Unnummerierte Beiträge bekommen einen separat ausgewiesenen Senderbeleg; eine bekannte Video-ID allein ist keine bestätigte Staffel- oder Folgennummer. Vorhandene lokal vermutete Episodennummern werden nicht mehr als angebliche Senderbestätigung übernommen.
- Optionaler Direktabgleich über bestehende ARD-/ZDF-Seitenadapter nur bei ausdrücklicher Aktivierung durch Personen mit entsprechender Berechtigung; standardmäßig ausgeschaltet. Automatische Abfragen auf 120 pro Stunde und Anbieter begrenzt, gecachte Antworten werden ohne zusätzliche Anfrage wiederverwendet.
- Bei Berechtigung und eindeutigen Original-Senderdaten können nummerierte Folgen vollständig zugeordnet werden. IMDb Offline dient als unabhängiger Fallback; bei Anbieterfehlern bleibt die Episode in der persistenten Warteschlange.
- Getrennte Diagnosezähler für importierte Senderbelege, bestätigte Original-Senderseiten, nummerierte Senderfolgen und zurückgestellte Direktanfragen.
- Testabdeckung für Offline-Betrieb, Berechtigungsschalter, sichere Nummernverifikation, Budgetbegrenzung, Fehlerwiederholung, IMDb-Fallback und manuelle Konkurrenzänderungen.
- Keine automatische Massensuche auf internen ARD-/ZDF-Schnittstellen ohne Freigabe; keine Umgehung technischer Schutzmaßnahmen.


## 0.5.29 – 10. November 2026 (Preview)

- Dashboard-Kennzahlen passen sich automatisch der tatsächlichen Fenster- bzw. Inhaltsbreite an (fünf, vier, drei, zwei oder eine Spalte); große Fenster zeigen zwei gleichmäßige Reihen mit je fünf statt acht plus zwei Kennzahlen.
- Gleichmäßige Abmessungen und angeglichene Höhen für Kacheln und Statusbereiche, verbesserte Schriftgrößen und Zeilenumbrüche für große Katalogzahlen.
- Zwei gleich breite Statusbereiche für aktuelle Erkennung und Metadatenanbieter (bei geringer Breite untereinander); anpassbare Anbieterkacheln.
- Eigenständige Statuschips für Haupt- und Episodenworker, offene/bereite Episoden sowie bestätigte Werke/Folgen anstelle einer langen schlecht lesbaren Textzeile.
- Suchfeld und Schaltflächen reagieren auf Fenstergrößenänderungen ohne unnötige Maximalbreite oder überlappende Bedienfelder.
- Keine Änderungen an Katalog, Datenbank, Downloadvorgang, Worker-Scheduling oder Erkennungslogik.


## 0.5.28 – 10. November 2026 (Preview)

- Unabhängige Episodenwarteschlange in SQLite. Bereits identifizierte Serien mit eindeutiger Anbieter-ID werden ohne erneute komplette Serienidentifikation von eigenen Episodenworkern geprüft.
- Automatische, einmalige Migration alter identifizierter Serien; Trigger halten die Warteschlange bei neu erkannten Werken, Katalogzusammenführungen, manuellen Bestätigungen und Formatklassifikationen aktuell.
- Hauptworker überspringen die Episodenwarteschlange. Gemeinsame atomare Metadaten-Leases verhindern parallele Doppelbearbeitung, auch nach Neustarts; eigene Retry-Zeitpunkte und Ergebniszustände bleiben in SQLite erhalten.
- Episodenworker prüfen zunächst nur das lokale IMDb-Archiv und vergeben Staffel/Folge nur mit eindeutigem Beleg. Keine zusätzlichen API-Anfragen für Tausende Folgen einer Sendung; unsichere Zuordnungen bleiben `identified`.
- Unabhängige Episoden-Metriken, Anzahl wartender und bereiter Folge-Aufträge, konfigurierbare 1/2/4 Episodenworker im UI.
- Erkannte Episoden werden aus der separaten Queue entfernt; erfolglose Prüffälle erhalten einen 30-Tage-Nachprüftermin, temporäre Archivfehler eine kürzere Wiederholung.
- Die ETA für neue Werkidentitäten zählt keine bereits in der Episodenwarteschlange liegenden Beiträge mehr.
- Tests für Queue-Routing, Konkurrenz, Neustart-Wiederaufnahme, eindeutige Episodenbelege und manuelle Priorisierung.


## 0.5.27 – 10. November 2026 (Preview / Diagnose-Fixes)

- TVDB-Anfragen erhalten ein separates Zeitlimit von zwölf Sekunden statt der bisherigen 35 Sekunden; andere Anbieter behalten ihren bisherigen Standard.
- TVDB-Ausfälle, Zeitüberschreitungen, ungültige Antworten und HTTP-5xx öffnen eine anbieterschlüsselbezogene Ausfallsperre mit 60/120/240/480/900 Sekunden Wartezeit. HTTP 401/403/429 behalten eine längere Sperre.
- Diagnose unterscheidet TVDB-Fehlerursachen ohne API-Schlüssel, Tokens oder Antwortinhalte offenzulegen.
- Bei vorübergehend gesperrtem TVDB werden gültige IMDb-/TMDB-Ergebnisse weiterhin gespeichert. Fehlende Zusatzprüfungen bleiben pro Werk markiert und werden später mit Backoff nachgeholt.
- Serienvorlagen dürfen einen explizit gespeicherten ausstehenden Anbieterabgleich nicht als bereits erledigt überspringen; bestätigte Episoden werden nicht herabgestuft.
- Regressionstests für Timeouts, Schlüsselseparation, Circuit Breaker, erfolgreiche Wiederaufnahme und persistierte Teilergebnisse.
- Offen: End-to-End-Performance und Erkennungsrate müssen am realen Katalog validiert werden; keine automatische Episodenverifikation allein aus einer Serienidentität.


## 0.5.26 – 10. November 2026 (Testbuild)

- Bis zu acht Erkennungsworker, externes API-Limit bleibt zwei; konfigurierbar mit Rücksicht auf schwache NAS.
- IMDb Offline erkennt bei eindeutigem Beleg auch Episodentitel mit ausdrücklich getrenntem Serienpräfix.
- SQLite-Leases: Kandidaten außerhalb der Schreibtransaktion auswählen, Busy-Wiederholungen statt Worker-Abbrüchen.
- Cover-Prüfungen: kurze Reservierungen statt ganztägigem Aussetzen nach einem Fehler.
- Kataloglisten tolerieren während des Aufbaus zusammengeführte/entfernte Datensätze.
- Neue Qualitätskennzahlen: vollständige Trefferquote, bestätigte Werke pro Stunde, SQLite-Busy-Zähler.
- 11 gezielte Regressionstests; Pakete technisch geprüft, reale Performance-/Gerätetests offen.

## 0.5.25.1 – 10. November 2026

- Alle sieben PRs #9–#15 für 0.5.19–0.5.25 in korrekter Reihenfolge nach main zusammengeführt; vollständige Historie erhalten.
- Verbund: korrigierte Verbindungscodes für NAS-Dienstport/Tailscale, editierbare erreichbare Adresse und bestätigte Schlüsselrotation. Bestehende ausgehende Partnerverbindungen und Journalstände bleiben erhalten.
- IMDb-Offline: kurze Wiederholungen bei vorübergehenden Netzfehlern und fortsetzbare Teil-Downloads; erfolgreich heruntergeladene Zwischenstände bleiben beim gescheiterten Erstimport bis sieben Tage nutzbar. Diagnosestatus zeigt Dateigrößen.
- Regressionstests: alter Verbundschlüssel wird nach Rotation abgelehnt, neuer funktioniert, andere Verbindungen bleiben bestehen; HTTP-Range nach Timeout setzt IMDb-Download fort.



## 0.5.25 Preview – 9. November 2026
- Konfigurierbarer Pool mit 1, 2 oder 4 parallelen Erkennungsworkern und SQLite-Leases pro Werk. Ausgelaufene Claims lassen sich nach Neustart wieder übernehmen; doppelte parallele Bearbeitung wird verhindert.
- Gemeinsame Limitierung externer Metadatenprüfketten auf zwei gleichzeitig, damit mehr Worker nicht alle API-Quoten überlasten.
- Neues Download-Abo-System für Filme und Serien mit „sobald verfügbar“ oder wöchentlichen Prüfungen mit einem 48-Stunden-Nachprüffenster. Aktive Abos beschleunigen den inkrementellen Filmlistenabgleich auf maximal etwa zwei Stunden. Abo-Persistenz, Pause/Fortsetzen/Löschen, manuelle Prüfung und automatische Aufnahme in die bestehende Downloadwarteschlange.
- Serienepisoden erfordern eindeutige, überprüfte Staffel-/Folgeninformationen; unsichere Kandidaten und nicht direkt unterstützte Links werden ausgelassen.
- Schutz vor doppelten Downloads durch Abonnement-Schlüssel, gespeicherte Downloadhistorie, vorhandene Zielpfade und laufende/abgeschlossene Aufträge.
- Neue Regressionstests für sichere Abos und parallele Auftragsreservierung.



## 0.5.24 Preview – 9. November 2026

- Diagnose 09.11.: Sehr hoher Aufwand für wiederkehrende Nachrichtensendungen („heute journal“, „heute in Europa“, „hallo deutschland“). Explizit bekannte Nachrichtenformate werden vor der externen Metadatenerkennung sicher als Sendungsbeiträge gruppiert.
- Schutz vor Fehlklassifizierung: keine generische Schlüsselworterkennung aus beliebigen Titeln, keine automatische Änderung bestätigter Filme, manueller Zuordnungen oder verifizierter Episoden. Manueller Abgleich hat Vorrang.
- Persistierter Filmhinweis-Index für unbekannte Werke mit eindeutigen Senderinformationen. „Filme zuerst“ prüft diese vor anderen noch unbekannten Inhalten; kein ungeprüftes Auto-Matching.
- Resumierbare Hintergrund-Nachprüfung bestehender Filmhinweise und Ergänzung beim späteren Import.
- Gebündelte Statuszählung nach Werkart und Erkennungszustand statt mehrfacher vollständiger SQLite-Scans.
- Eigener Diagnosezähler für ohne externe API gruppierte Nachrichtenbeiträge; keine Verfälschung der Netto-Erstprüfungsquote.
- Regressionstests für bekannte News-Formate, Filmhinweise, negative Titelbeispiele, manuelle Prioritäten und Zustandszahlen.



## 0.5.23 Preview – 8. November 2026
- Build 47: IMDb Offline im Katalog-/Metadaten-Dashboard mit letztem erfolgreichem Archivaufbau, nächstem Versuch und letztem Fehler. Aufklappbare Übersicht über alle sieben IMDb-Dateien inklusive Datensatzumfang und Übernahmezeitpunkt.
- Nach erfolgreichem IMDb-Aufbau werden die Einzelzahlen und Dateizeitpunkte in der Snapshot-Datenbank persistiert, auch über Anwendungsneustarts hinweg.
- Vorhandene ältere IMDb-Archive bleiben ohne vollständigen Reimport verwendbar; damals nicht gespeicherte Datensatzdetails werden nicht geschätzt.
- Neue Regressionstests für erfolgreiche/fehlgeschlagene Updates und Kompatibilität alter IMDb-Snapshots.
- Build 46: Kompakte Statuskarten ohne Mindesthöhe, acht Kennzahlen in einer Reihe bei breiten Inhaltsflächen; Anbieter als horizontale Statusfelder und dichtere Importleiste. Tablet-/Fensterbreiten wechseln automatisch auf vier bzw. zwei Spalten.
- Katalog-/Metadatenstatus als responsive Kennzahl-Karten und kompakte Anbieterfelder, statt langer Statuszeilen.
- Download-Dateiprüfung: „Datei am ursprünglichen Pfad nicht gefunden“ ist ein wiederherstellbarer Verfügbarkeitszustand, **kein** Downloadfehler.
- Benutzerinitiierte Suche nach verschobenen Videos in freigegebenen Ordnern und sichere Neuverknüpfung mit Dateigrößenprüfung.
- Downloadhistorie, Metadaten, Angebote und Auftragsstatus bleiben auch bei nicht verbundenen oder verschobenen Datenträgern erhalten.
- Zusätzliche Bibliotheksordner in den Einstellungen. Die automatische Suche ist begrenzt, überprüft keine beliebigen Verzeichnisse und folgt keinen Verzeichnis-Symlinks.
- Regressionstests für verlorene Speicherorte, wiederhergestellte Dateiverknüpfungen und Schutz vor falschen Verknüpfungen.



## 0.5.22 Preview – 8. November 2026
- Nutzerauswahl: ausgewogene Film-/Serienprüfung, Filme zuerst oder Serien zuerst; manuelle Prioritäten bleiben vorrangig.
- Serienvervollständigung: begrenzter Fokus auf bis zu 24 weitere fällige Folgen, ohne unbegrenzte Massenanfragen.
- Ungenutzte automatische Serienpriorisierung beim Öffnen der Serienseite entfernt.
- Erstprüfungen vor regulären Wiederholungen, persistente Versuchszähler auch bei Zusammenführungen, echte Erstprüfungsrate und Restlaufzeit in der Statusanzeige.
- Dauerhafter, anbieterspezifischer Nichttreffer-Cache (nur erfolgreiche leere Antworten, niemals Anbieterstörungen); manuelle Suchvorgänge umgehen den Cache.
- Identische Senderangebote werden nur bei exakter technischer Medienidentität gemeinsam angezeigt. Unterschiedliche Medien und Audiodeskription bleiben getrennt.
- Neu: automatisierte Tests der Scheduler-Modi, Caches, Medienidentität und Netto-Statistik.



## 0.5.21 Preview – 7. November 2026
- Konservative Filmdubletten-Erkennung über eindeutige Anbieterkennung oder bestätigten Titel, Produktionsjahr und vergleichbare Laufzeit.
- Beim Zusammenführen bleiben verfügbare Genres aus geprüften Quellen, Senderangebote, Downloadbelege und manuelle Änderungen erhalten.
- Bestehende bestätigte Dubletten werden in kleinen, fortsetzbaren Batches nachbereinigt; neue bestätigte Treffer sofort geprüft.
- Keine automatischen Zusammenführungen bei widersprüchlichen Jahren, Referenzen oder Laufzeiten sowie bei zwei voneinander abweichenden manuellen Bearbeitungen.
- Regressionstests und Diagnosezähler.



## 0.5.20 Preview – 7. November 2026
- Inkrementeller Vergleich vollständiger MediathekView-Filmlisten: unveränderte Angebote werden nicht erneut in den Werk- und Angebotstabellen geschrieben.
- Getrennte IDs während des Importlaufs verhindern, dass ein abgebrochener Import bisher gelistete Angebote deaktiviert.
- Importstatistik mit Neu, Geändert, Unverändert, Wiederaufgetaucht und Entfallen; im Katalogstatus und Diagnoseprotokoll sichtbar.
- Neue oder geänderte Werke werden gezielt zur Formatprüfung vorgemerkt. Eine abgeschlossene Erstklassifikation wird nicht bei jedem Import zurückgesetzt.
- Wiederverwendung einer einzigen eindeutig bestätigten Serienidentität für Bestandsfolgen ohne Episodennummer. IMDb Offline versucht die individuelle Folge zu bestätigen; keine Übernahme der Episodennummer oder -bestätigung von Geschwisterfolgen.
- Optionales, belegtes Ablaufdatum aus der Quelle, falls vorhanden. ARD/ZDF-Senderabfrage erst im Download-Dialog; angebotsbezogener Cache und Hinweis in Serien-Sammeldownload und Details.
- Kein erfundenes Ablaufdatum aus Sendedatum, API-Token-Ablauf oder geschätzter Verweildauer.
- Neue Regressionstests und Paketvalidierung im GitHub-Actions-Workflow.

## 0.5.19 Preview – 7. November 2026
- IMDb-Offline-Abfragen: schreibgeschützte Verbindung pro Worker, begrenzte Titel-/Episoden- und Credits-Caches, Neustart der Verbindung nach Datenbank-Snapshotwechsel.
- Hochkonfidente IMDb-Treffer benötigen für einen frühen Abschluss keine Genreangaben.
- Eindeutiger IMDb-Episodennachweis anhand vorhandener Staffel-/Folgenummer möglich.
- Frühzeitige Speicherprüfung vor IMDb-Datensatzdownloads.
- Bereits wartende Downloadjobs bleiben nach dem Neustart in der Warteschlange.
- Cache-Messwerte in der Diagnose.

## 0.5.18 Preview – 6. November 2026
- Filme und Serien im Browser abspielen, Direktdateien/HLS und ffmpeg-Remux bei Bedarf.
- Eigene Film- und Serientitelseiten und Folgenavigation.
- Siehe README.md und VALIDATION.md für frühere Versionsschritte.

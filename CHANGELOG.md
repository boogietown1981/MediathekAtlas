## 0.5.94 – Umwandeln auf 1080p/720p/480p (Encoder, ffmpeg)
- Schritt 6 aus `docs/REVIEW_0577.md`, auf dem Sammelstand 0.5.93 (Zweig cp5lly). Entscheidung ffmpeg statt HandBrake: bereits als Werkzeug vorhanden (`runtime_tools`), keine weitere Abhängigkeit.
- `encoder.py` (neu): eigene Datenbank `encoder.sqlite3` (`encode_jobs`). Profile 1080/720/480 (CRF 21/22/23), Tempo `fast` (veryfast) und `balanced` (medium). `plan` lehnt Hochrechnen ab; `command`: libx264, `scale=-2:H`, `-c:a copy`, Untertitel kopiert (mov_text → srt), Matroska, `-progress pipe:1`; `verify`: Bildhöhe, Laufzeit (±2 %, mindestens 2 s), Zahl der Tonspuren. `add` lehnt ab: fehlende Werkzeuge, fehlende Quelle, vorhandenes Ziel, zu wenig freien Platz, doppelten Auftrag, mehr als 200 wartende.
- `Worker`: ein Auftrag zur Zeit, `os.nice(10)`, schreibt `<Ziel>.partial`, prüft, benennt um. Bei „Original ersetzen“: erst nach bestandener Prüfung; `server.encoder_replaced` trägt den neuen Pfad im Download-Auftrag ein und verwirft die Listen-Zwischenspeicher. Nach Neustart gehen laufende Aufträge zurück in die Warteschlange.
- Routen: `GET /api/encoder`, `POST /api/encoder-add` (`replace` nur mit `confirm: true`), `/api/encoder-cancel`, `/api/encoder-clear`.
- UI: `web/storage.js` (Knopf „Umwandeln“ je Datei, Dialog, Warteschlange mit Fortschritt), `web/index.html`, `web/style.css`.
- Tests: `tests/test_v0594_encoder.py` (12, davon 4 mit echtem ffmpeg).
## 0.5.93 – Videostart: Play-Knöpfe ohne Beschriftung (TOGGO, JustWatch), SAT.1 als Joyn+
- Björn (13.11.2026, Test von 0.5.91): Joyn startet direkt; „sat 1 ist ein joyn+“; TOGGO landet auf der Folge, aber der pinke Play-Knopf muss noch geklickt werden; JustWatch zeigt den Mini-Player, Play muss noch geklickt werden.
- `autostart.js`: `clickOverlay()` nach 1,5 s, höchstens 3 Klicks im Abstand von 3 s, nicht innerhalb von 2,5 s nach einem anderen Klick oder Startversuch: zuerst bekannte Player-Knöpfe (`.vjs-big-play-button`, `.jw-icon-display`, `.bmpui-ui-hugeplaybacktogglebutton`, `.shaka-play-button`, `.plyr__control--overlaid` …) und Elemente mit „play“ als Wortteil in Klasse/ID/Test-ID/aria-label (nicht „player“, „display“, „playlist“), höchstens 260 px groß und auf einem Player; nach 3 s sonst `elementFromPoint` in der Mitte des größten Players (nie Link oder iframe, eigene Beschriftung ohne Kauf/Abo usw.). `press()` sendet pointer-/mouse-Ereignisse und click (auch für SVG). `startVideo()` startet auch Videos ohne geladene Daten (preload="none"), wenn eine Quelle gesetzt ist. `all_frames: true` (nur die vier Hosts).
- `joyn.py`: `PLUS_CHANNELS = {'sat.1'}` (genauer Sendername) – `channel_from`, `channels`, `listing('live')` und `item` kennzeichnen den Sender als Joyn+, auch bei gespeicherten Katalogen. Joyns Navigation im Mitschnitt: SAT.1 `liveStreamGroups: ['PUBLIC_VALUE']`, `markings: []`.
- Tests: `tests/test_v0593_videostart_plus.py` (3).
## 0.5.92 – Restliche Archive-Media-Module: sicherer Scan, Listen-Austausch, Blu-ray-Playlists, weitere Inhalte
- Schritt 5 aus `docs/REVIEW_0577.md`, auf dem Sammelstand 0.5.91 (Zweig cp5lly).
- `archive_scan_recovery.py` (neu; ArchiveMedia `clean_scan`, `scan_recovery`, `catalog_fallback`), eingebunden in `portal_control`:
  - `portal_scopes` bekommt `mode` (1 = vor 0.5.92 begonnener Scan in alter, unsortierter Seitenfolge; 2 = geprüft), `last_identifier`, `provider_total`, `generation`. Migration: nur Scans mitten im Lauf (`cursor>1`, nicht fertig) bleiben Modus 1, damit die gespeicherte Seitennummer gültig bleibt.
  - Modus 2: `sort[]=identifier asc`; `check` verlangt `response.start` = angefragte Position, erste Kennung hinter der letzten gesehenen, keine leere Seite bei gemeldeten weiteren Treffern (sonst `Stalled`).
  - Mehr als 9500 Treffer (`RESULT_LIMIT`): Quelle wird über `publicdate`-Zeitfenster gelesen (`portal_scope_windows`), beginnend mit 1996 bis Folgemonat, Halbierung bei Bedarf bis auf eine Sekunde; neueste Fenster zuerst. Ein nicht weiter teilbares Fenster wird als Fehler vermerkt statt endlos geteilt.
  - `plan`/`kind_of`: vorübergehend (Zeitüberschreitung, 408/425/429/5xx, Netz) → `retry` bis 8 Fehler in Folge, dann `error`; kein belegbarer Fortschritt → `retry` bis 3, dann `fallback`: Seiten-Scan stellt auf Zeitfenster um, ein Fenster wird halbiert; sonst `stalled`; alles andere (4xx, ungültige Antwort) → `error`. `failures` zählt Fehler in Folge und wird bei Erfolg und bei „Start“ zurückgesetzt. Bisher wurde jeder Fehler unbegrenzt wiederholt.
  - `rescan` (Aktion `rescan` in `POST /api/portal-scope-control`): Zähler und Fensterstände nach `portal_scope_history` (letzte 20), dann von vorn in Modus 2; `portal_items` bleibt unberührt.
  - `coverage`: je Quelle `provider_total`, gelesen, Fenster, Urteil (`unknown`/`in_progress`/`count_plausible`/`needs_review`); in `list_scopes` als `coverage`. Im geprüften Modus zählt `imported` die gelesenen Uploads der Suchseite.
- `archive_transfer.py` (neu; ArchiveMedia `catalog_transfer`): `GET /api/archive-list-export` (ZIP mit `manifest.json`, `items.jsonl`, `files.jsonl`, Format `archivemedia-file-list` Version 1), `POST /api/archive-list-import` (ZIP als Anfragekörper, höchstens 256 MB). Vollständige Prüfung vor der ersten Änderung (Dateiliste, Manifest, jede Zeile, Zeilenzahl); `INSERT OR IGNORE` in `portal_items`, bestehende Einträge bleiben unverändert; übernommene Einträge tragen `transferred` und `evidence=transferred_archive_list`. Dateizeilen werden geprüft und je Upload gezählt, aber nicht gespeichert (der Dateibestand wird weiterhin bei Bedarf von Archive.org gelesen).
- `archive_extras.py` (neu) mit unverändert übernommenen `vendor/archive_portals/bluray_playlist.py`, `catalog_taxonomy.py`, `catalog_enrichment.py`:
  - `collect` (aus `archive_detail_document`): `bluray` (Playlists bis 256 KiB, Clip-Größen), `other_media` (Audio, Dokumente, Programme mit Unterart und Begründung, bis 12 Beispieldateien mit Archive.org-Link), `external_ids` (ISBN, MusicBrainz-Veröffentlichung aus den Metadaten).
  - `POST /api/archive-bluray-playlist` (`id`, `filename`): liest eine Playlist des gespeicherten Dateibestands, gleicht die Clips mit dem Upload ab, merkt das Ergebnis im Dateibestand; `main_playlist` = längster Titel mit allen Clips.
  - `POST /api/archive-external-id` (`id`, `provider`): Abfrage nur über die genannte Kennung bei openlibrary.org bzw. musicbrainz.org.
- Nicht als eigenes Modul übernommen: `clean_rebuild` (Prüfkopie der Datenbank; abgedeckt durch `db_backup.py` aus 0.5.56 und „Neu durchsuchen“), ein eigener Audio-/Buch-/Programm-Katalog mit eigenen Scanquellen aus `multi_catalog` (MediathekAtlas durchsucht Archive.org weiterhin nur nach Filmen und Serien), das Laden und Zusammenfügen von Blu-ray-Clips.
- Detailansicht: „Dateibestand neu von Archive.org lesen“ (bisher blieb ein einmal gespeicherter Dateibestand für immer stehen, neue Felder wie Bildhöhe aus 0.5.88 kamen bei alten Einträgen nie an).
- Oberfläche (`web/app.js`, `web/index.html`): Scanquellen mit Klartext-Status, Abdeckung, Zeitfenstern und „Neu durchsuchen“; Listen-Austausch; `archiveExtrasPanel` in der Detailansicht.

## 0.5.91 – Videostart bei Anbietern mit Kopierschutz (direkter Player-Link, optionale Chrome-Erweiterung)
- Björn (13.11.2026): Rakuten & Co. laufen nur beim Anbieter; heute Seite öffnen → Ansehen klicken → bei Rakuten HDCP-Hinweis bestätigen. Wunsch: abkürzen.
- `web/direct_start.js` (neu, `window.AtlasDirect.href(source, url)`): Joyn-Detailseiten werden auf die Player-Routen der Joyn-Seite umgeschrieben (`PLAYER_MOVIE /play/filme/:slug`, `PLAYER_SERIES /play/serien/:serie/:folge`, `PLAYER_COMPILATION`, aus der Routentabelle im JavaScript-Bundle von Björns HAR vom 12.11.2026). Serien (`/serien/<serie>`), Sender und `/play/live-tv?channel_id=` (0.5.90) bleiben. Alle Links auf www.joyn.de, www.rakuten.tv, www.toggo.de, www.justwatch.com bekommen das Fragment `#mediathekatlas-autostart` (bleibt im Browser). Rakuten-Player-Adresse nicht belegt → keine Umschreibung. Schalter `localStorage['atlas.directStart']` (Standard an).
- Eingebunden in `portal_title.js` (Titel-, Serien- und Folgenlinks), `unified_catalog.js` (Kachel), `portal_panel.js` (Plattform-Reiter), `live_tv.js` (Sender ohne eigenen Stream).
- `web/browser-extension/chrome/` (neu, Manifest V3, Berechtigung nur `storage`, Content-Script nur auf den vier Hosts, `document_start`): reagiert nur auf das Fragment (danach `sessionStorage`, 90 s, entfernt das Fragment per `history.replaceState`). Klickt den Abspielknopf nach Beschriftung (Kostenlos ansehen, Jetzt ansehen, Abspielen, Play …; höchstens 4 Klicks, Abstand 2,5 s), nie Elemente mit Kauf/Leih/Abo/Plus/Anmeld/Cookie/Zustimm/Akzeptier/Trailer usw. und nie Links auf andere Hosts. Bestätigt Dialoge, deren Text „HDCP“ enthält, mit Weiter/OK/Fortfahren/Trotzdem (nie Abbrechen/Schließen). Startet ein geladenes, pausiertes Video; bei Autoplay-Sperre stumm, Ton beim ersten Klick. Popup mit zwei Schaltern (`chrome.storage.sync`). Keine Netzanfragen, kein Zugriff auf EME/Lizenzen.
- `browser_extension.py` (neu): `GET /api/browser-extension` (hinter dem Token) liefert ein reproduzierbares ZIP mit Ordner `MediathekAtlas-Videostart`, Erweiterungsversion = App-Version. Einstellungen → „Videostart bei Anbietern“: Schalter, Download, Installationsanleitung.
- Sammelstand: Zweige 6vl9fj (0.5.89, PR #44) und 7zoqtz (0.5.90, PR #45) zusammengeführt; Konflikte nur in Versionsdateien und Dokumentation.
- Tests: `tests/test_v0591_direct_start.py` (7), `tests/direct_start_smoke.cjs`.

## 0.5.90 – Joyn-Live-Sender verlinken den richtigen Sender
- Björn (13.11.2026): „joyn zeigt immer noch auf arte bei den tv sendern“. Ursache: `joyn.channel_from` setzte `web_url` auf die Markenseite (`/channels/…`, 14 von 128 Sendern in Björns Mitschnitt) oder, für alle anderen (Markenpfad `/mediatheken/…` oder leer), auf die nackte `https://www.joyn.de/play/live-tv`. Diese Seite spielt Joyns Standardsender. Alle Joyn-Knöpfe im Reiter Live-TV, in der Live-Leiste und auf der Senderseite führten damit zum selben Sender.
- Fix: `joyn.live_url(Brand.id)` baut den Link wie die Website (JavaScript-Bündel vom 12.11.2026: `"/play/live-tv?channel_id=".concat(id)` für jeden Eintrag von `liveTv`), z. B. arte `channel_id=1007`, Naruto `1104`, BBC Earth `bbc-earth`. Ohne gültige Marken-ID (`VALID_BRAND`) gibt es keinen Link.
- Bestehende Kataloge: `live_links_outdated` erkennt alte Links; `joyn.loop` ruft dann `refresh_live_links` auf (eine `Navigation`-Anfrage, ändert nur `web_url` der Sender, nach Fehler frühestens nach einer Stunde erneut, Ereignisse `joyn_links_refreshed`/`joyn_links_failed`). Bis dahin liefern `live_tv.joyn_channels`, `joyn.listing('live')` und die Senderseite keinen Link, sondern den Hinweis „Direktlink folgt nach dem nächsten Joyn-Abruf“.
- Übrige Sender geprüft: Pluto TV, Rakuten TV und ARD/ZDF & Co. spielen über die Kennung des Senders (`playLive({pluto|rakuten|offer: id})`), Rakuten-Links tragen den Sender-Slug; keine Sammel-Links. Alle 128 Joyn-Sender des Mitschnitts ergeben verschiedene Senderschlüssel, keine Kollision mit anderen Sendern. Alias `hessischerrundfunk` → hr-fernsehen.
- Tests: neu `tests/test_v0590_joyn_live_links.py` (5 Tests), `tests/test_v0565_joyn.py` erwartet die neuen Links.
## 0.5.89 – YouTube im eigenen Player in 720p/1080p statt 480p
- Björn (13.11.2026, nach 0.5.86): „Take My Breath Away“ läuft flüssiger, aber nur in 480p.
- Ursache: Die Formatangabe für `yt-dlp` (seit 0.5.78) verlangte in der ersten Alternative H.264-Bild als eigene HTTPS-Datei plus AAC. Ohne Anmeldung liefert YouTube solche Dateien oft nur bis 480p (itag 135); 720p/1080p gibt es als HLS (H.264 mit Ton, z. B. itag 95/96) oder VP9 (247/248). yt-dlp nimmt die erste Alternative, die überhaupt passt, also 480p. Mit `--load-info-json` nachgestellt: alte Angabe → `135+140` (480p), obwohl HLS 1080p vorhanden war.
- `youtube_downloads.FORMAT`/`SORT`: Bild H.264 oder VP9 (beide kopiert ffmpeg ohne Umrechnung in MP4), Ton AAC; Reihenfolge `-S res:<Grenze>,vcodec:h264,proto,acodec:aac` (höchste Auflösung bis zur Grenze, dann H.264 vor VP9, dann HTTPS vor HLS). Ergebnisse: nur HLS höher → `96` (1080p, HLS über ffmpeg), nur VP9 höher → `248+140`, H.264-Dateien bis 1080p → `137+140`, Video wirklich nur 480p → `135+140`.
- „Automatisch“ für YouTube bis 1080p (`AUTO_HEIGHT`), „Beste“ bis 2160p; seit 0.5.86 kommen die Stücke mit voller Geschwindigkeit an. `files` (von YouTube angebotene Höhen ≥ 240) füllt das Qualitätsmenü, auch bei HLS; `auto_height` geht an den Player (Beschriftung „Automatisch (bis 1080p)“). `server_only`: YouTube-Adressen (auch HLS) gehen nie an den Browser, hls.js versucht sie nicht.
- VP9 in MP4 nach dem Spulen in Chromium geprüft (Bild/Uhr ≤ 0,025 s, keine ausgelassenen Bilder).

## 0.5.88 – Staffel- und Folgenauswahl für Archive.org, Uploader erkannter Werke (aus Archive Media)
- Schritt 4 aus `docs/REVIEW_0577.md`. Sammelstand: die Zweige 6vl9fj (0.5.86, PR #43) und toma7t (0.5.87, PR #41) sind zusammengeführt; Konflikte nur in Versionsdateien, Modulliste (`build_macos.py`) und Dokumentation.
- `archive_selection.py` (neu, ArchiveMedia `selection_matrix`): `criteria` prüft die Wünsche (Tonsprache, Untertitel, je `all`/`any`, Auflösung `any`/`exact`/`at_least`/`at_most` mit 480–2160, Format, `verified`, `originals`, Staffel) und lehnt Unbekanntes ab. `facts` trennt belegte Sprachen (Spuren aus `portal_video_probes`, Untertiteldateien) von Hinweisen aus dem Dateinamen. `matrix`: eine Zeile je Staffel/Folge (bei Filmen je Dateifamilie) mit der besten passenden Datei (`score`: belegte Sprache, Nähe zur gewünschten Auflösung bzw. höchste, Original, Größe) und den Ablehnungsgründen der übrigen; Dateien ohne erkennbare Folge werden gezählt, nicht geraten. `enqueue` stellt nur Gewinner der Übersicht in die Warteschlange (`archive_downloads.enqueue`), höchstens 300 je Anfrage; angehakte Namen, die kein Gewinner sind, werden ignoriert.
- Routen: `POST /api/archive-selection` (`id`, `criteria`; nur Vorschau, kein Abruf), `POST /api/archive-selection-download` (`id`, `criteria`, `picks`), Ereignis `archive_selection_queued`.
- `portal_sources.archive_detail_document`: je Datei `height`/`width` aus dem Archive.org-Manifest (`_pixels`), je Upload `uploader_account`. Schon gespeicherte Dateibestände haben beides erst nach erneutem „Dateibestand prüfen“; bis dahin gilt die Auflösung als unbekannt.
- `archive_uploaders.py` (neu, ArchiveMedia `uploader_priority`): für Werke mit eindeutiger Referenz (`archive_recognition.selected`) wird das öffentliche Konto (`_uploader_useritem`, Form `@name`) der zugehörigen Uploads einmal als pausierte Scanquelle angelegt (`portal_control.add_scope`, Beschriftung „Uploader von „Titel““). Tabelle `archive_uploader_follow` merkt jedes Konto, damit ein vom Nutzer entferntes nicht wiederkommt; eine selbst angelegte Quelle behält Priorität und Zustand. Höchstens 25 neue Konten je Lauf; der Hintergrundlauf (im Werkerkennungs-Thread `enrich:archive`) höchstens alle 15 Minuten, ohne Netzabruf. Routen `GET /api/archive-uploaders`, `POST /api/archive-uploaders-follow`, Ereignis `archive_uploaders_noted`.
- Das Feld `_uploader_useritem` wird jetzt in der Archive.org-Suche und im Scan mit angefragt (`portal_sources.UPLOADER_FIELD`). Das Feld `uploader` (E-Mail) wird weiterhin nicht gelesen. Nicht übernommen: ArchiveMedias Nachschlagen des Kontos über den Suchindex für alte Einträge (`uploader_account_lookups`); bestehende Einträge bekommen das Konto beim nächsten Scan oder „Dateibestand prüfen“.
- Oberfläche (`web/app.js`): `archiveSelectionPanel` in der Detailansicht ab zwei Videodateien; Scanquellen zeigen die Beschriftung automatisch vorgemerkter Konten.

## 0.5.87 – TOGGO nach dem Mitschnitt von toggo.de (Serien und Filme, kostenlos/Abo, Kopierschutz bestätigt)
- Björn (13.11.2026): HAR von www.toggo.de (Chrome, nicht angemeldet). Ergebnis: kein Brightcove, keine brauchbare Sitemap-Ableitung. Katalog = `POST production-n.toggo.de/api/assetstore/vod/asset?expand=false` mit JSON-Filter (`{"filter":{"and":[{"type":["series"]}]},"sort":"title[asc]","size":500}`), Serie mit allen Folgen = `GET …/vod/asset/<u_name>?filter=rootParentTypes[not|hidden]`, Wiedergabe = `stus.player.streamingtech.de/movie-playout-variants/superrtl/<ASV…>?platform=web` mit vier Varianten, alle mit Lizenz (Widevine/PlayReady bzw. FairPlay), auch bei kostenlosen Titeln.
- `toggo.py` neu geschrieben: Tabelle `toggo_assets` (IDs `s.VSE…`, `m.MOV…`, `e.VEP…`), Serien **und Filme**, Felder Angebot (`offer` free/plus aus `available_packages`: fvod/catchup = kostenlos, nur svod = Abo), Altersbereich (`target_age_group`), Altersempfehlung, Staffelzahl, Ende der kostenlosen Zeit (`until`), Originaltitel, Video-Kennung. Titel ohne Paket und andere Typen (Hörspiele, Spiele, Live-Events, Marketing) werden nicht gelistet. Folgen einer Serie: eine Anfrage, 6 Stunden gespeichert.
- Entfernt: Sitemap-/robots-Abruf, Adressmuster, Asset-Abfrage je Folge, Brightcove (Policy-Key, Playback-API). Der Bestand aus 0.5.79–0.5.85 (`toggo_items`, Zustand, Werkzuordnungen) wird beim ersten Öffnen verworfen, weil die IDs andere sind.
- Wiedergabe: Standard ist jetzt „kopiergeschützt“ (vorher „ungeprüft = Player-Knopf“). Nach dem Katalogabruf werden bis zu drei kostenlose Filme über die Varianten-Auskunft geprüft; nur eine Variante ohne Lizenz mit HLS-Adresse, die `hls_guard` bestätigt, gilt als frei. Es gibt keine Anfrage an `entitlement/play` und keine an den Lizenzserver. Abo-Titel werden gar nicht angefragt.
- Kategorien nach 0.5.83: jeder Titel „Kinder & Familie“ plus Werkzuordnung; Angebot und Altersbereich sind Filterwerte (`genre=Kostenlos|Nur mit Abo|TOGGO|TOGGOLINO`), keine Kategorien. Neu `badge` („kostenlos“, „kostenlos bis TT.MM.“, „Nur mit Abo“) auf Kachel und Folgenzeile (`portal_panel.js`, `portal_title.py/.js`).
- Oberfläche: Reiter TOGGO mit „Serien“ und „Filme“, Auswahl „Angebot“ (`#toggo-pick`, `portal_panel.js` sendet sie als `genre`), Sortierung nach Jahr; `seriesOnly` entfernt; gemeinsamer Katalog fragt TOGGO auch für Filme ab. Titelseite: Angebot, Bereich, Empfohlen ab, Staffeln, „Kostenlos bis“, Stream.
- `artwork.py`: Bildhost `imgix.net` statt Brightcove; `netcheck.py`: nur noch `production-n.toggo.de`.
- Tests: `tests/test_v0587_toggo.py` (31 Tests, Antworten in den Formen des Mitschnitts mit erfundenen Werten) ersetzt `tests/test_v0579_toggo.py`.

## 0.5.86 – Flüssige Wiedergabe im eigenen Player (YouTube-Abruf in Stücken, exakter Start nach dem Spulen, kein Puffer-Halt bei umgewandelten Streams)
- Björn (13.11.2026, MacBook Air M3, Chrome): Videos im eigenen Player stottern, Bild und Ton versetzt, auch ein hochaufgelöstes YouTube-Video, das auf youtube.com sauber läuft; betrifft alle Videos im eigenen Player.
- Diagnose (0.5.82–0.5.84, 13.11. 00:21): `playback_stream` YouTube: erste Daten nach 8,26 s, 8,4 MB in 38,6 s (1816 kbit/s ≈ Abspielgeschwindigkeit bei 720p), der Stream nach dem Spulen lieferte in 20 s 0 MB.
- Ursache 1 (YouTube): ffmpeg holte Bild und Ton mit je einer offenen Anfrage; googlevideo liefert solche Anfragen gedrosselt (yt-dlp und youtube.com laden in Stücken ≤ 10 MB). Neu `range_relay.py`: Loopback-Relay (127.0.0.1, zufälliges Token, nur von MediathekAtlas registrierte Adressen) mit Range-Unterstützung, lädt in Stücken von 4 MB (erstes 1 MB), drei gleichzeitig, drei Versuche je Stück, kein Wiederholen bei 401/403/404/410/416. `youtube_downloads.play_source`: `-j` statt `-g` (Adressen, Bildhöhe und die von yt-dlp vorgesehenen Header User-Agent/Accept/Accept-Language/Origin/Referer, keine Cookies), Quelle `ranged`. `streaming.command` leitet `ranged`-Adressen über das Relay und setzt bei zwei Eingängen `-max_interleave_delta 0`. Messung gegen einen nachgebauten googlevideo-Server (Drosselung nach 1 MB auf 0,9× Bitrate): vorher 0,92× Echtzeit, nach dem Spulen 0,86×; nachher 9,5× bzw. 20,8×.
- Ursache 2 (alle umgewandelten Streams): das Ausgabe-`-ss 0` (seit 0.5.18) verwarf das Bild bis zum nächsten Keyframe, der Ton begann an der Position. Gemessen: Bild 3,6 s nach dem Ton (YouTube-Fall mit zwei Eingängen und HLS); Chromium zeigte 3,6 s ein stehendes Bild bei laufendem Ton. Jetzt ohne `-ss 0`: Bild ab dem Keyframe davor mit negativen Zeiten, die MP4-Editliste lässt den Browser den Vorlauf still dekodieren; gemessen in Chromium erstes gezeigtes Bild bei 0,00 s, Abweichung Bild/Uhr ≤ 0,03 s (YouTube-Fall und HLS).
- Ursache 3 (alle umgewandelten Streams): der Startpuffer aus 0.5.77 (8 s Start, 4 s Spulen, 5 s nach jedem Stocken) wartete auf `video.buffered`. Chrome meldet bei einem umgewandelten Stream nur ca. 2,3 s, auch nach 8 s Pause (gemessen 2,26 s), also wartete jeder Start bis 3 s ohne Zuwachs, und jedes kurze `waiting` hielt das Bild wieder mindestens 3 s an. `gate()` gilt jetzt nur noch für hls.js und direkte Dateien (dort meldet der Browser den echten Vorrat).
- `web/app.js`: `refresh`, `refreshLog`, `loadProviderStats` pausieren, solange der Player offen ist. `web/style.css`: kein Weichzeichner hinter dem Player. `playback_stats` meldet zusätzlich `frames`, `dropped_frames` (getVideoPlaybackQuality) und `gates`.
- Gemessen im echten Player (Chromium, Seite von MediathekAtlas, umgewandelter Teststream 1080p, gedrosselte Quelle): vorher Start 7,1 s, nach dem Spulen 8,0 s, 9 ausgelassene Bilder, 2 Statusabfragen während der Wiedergabe; nachher Start 0,7 s, nach dem Spulen 1,0 s, 0 ausgelassene Bilder, keine Statusabfragen.

## 0.5.85 – Joyn: fehlgeschlagene Genre-Seiten werden wiederholt
- Björns Diagnose vom 13.11.2026: `joyn_sync_progress` Schritt 2 von 15 dauerte 85 s und setzte `partial`; Ergebnis 1430 statt 1500 Filme, `last_error` ohne Grund. `_load_genre` gab bei einem Fehler ab Seite 2 nur `False` zurück.
- `joyn._page`: eine fehlgeschlagene Seite wird nach 5 s einmal wiederholt. `_load_genre` liefert den Grund (`Seite N: …` oder Seitengrenze). `sync`: abgebrochene Genres laufen am Ende noch einmal (`joyn_sync_retry`); nur was dann noch fehlt, macht den Katalog `partial`. `last_error` nennt Genre-Schritt und Grund; `joyn_sync_completed` meldet `failed_steps` und `reasons`; nächster Versuch bei `partial` nach 1 h statt 24 h.

## 0.5.84 – TOGGO-Sitemap, Plattform-Registratur, Installationspakete aus dem Git, enthält 0.5.83
- Björns Diagnose vom 13.11.2026 (0.5.82): `toggo_sitemap` mit 10 Sitemaps, 16475 Adressen, 0 Serien; Formen `*/serien/*/folge/*` (10605) und `toggolino/*/serien/*/folge` (4542). `toggo.classify` erwartete `/[toggolino/]<serie>/folge/<folge>`. Jetzt: Serie = Teil vor `folge`/`video`, davor höchstens zwei Bereichsteile; die gelistete Adresse wird behalten (`entry['url']`, für den Link kodiert) statt neu zusammengesetzt. Sonst zeigte die Diagnose seit 0.5.81 keine Fehler; die `logging`-Fehler (22–23 Uhr) stammen aus 0.5.72/0.5.73 und sind seit 0.5.74 behoben.
- Enthält 0.5.83 (einheitliche Kategorien, Zweig 8whd4k, PR #42).
- Björn (13.11.2026): „was soll der mehrfach kopierte Code, müssen wir da bereinigen?“ Ja. `platform_registry.py` (neu): je Plattform ein `Platform`-Eintrag (Modul, Werkzuordnung, Offline-Modul, Schalter je Route). `handle_get` beantwortet `/api/<key>`, `/api/<key>-details`, `/api/<key>-downloads`; `handle_post` `-sync`, `-auto`, `-enrich`, `-download-add`; `start_background` startet je Plattform Werkzuordnung und Katalogabruf (Thread-Namen unverändert). Ereignisnamen unverändert (`<key>_reference_check`, `<key>_download_enqueued`, `<key>_download_enrich_failed`).
- `server.py`: 38 ausgeschriebene Routen und 14 Thread-Starts entfernt (178 Zeilen), dafür `platform_context()` und drei Aufrufe. In `server.py` bleibt, was nur eine Plattform hat: Netzkino (eigene Links, Mitschnitt, gruppierte Ansicht), YouTube-Katalogseite (Titel einer Playlist, aussortierte Uploads), YouTube-Download (Playlists), Quellen, Schlüssel, Offline-Schalter. `_PORTAL_MODULES` und die Plattformlisten kommen aus der Registratur.
- Eine neue Plattform braucht jetzt einen Eintrag in `platform_registry.PLATFORMS` und in `task_control.PORTALS` statt rund vierzig kopierter Zeilen.
- `downloads/` (44 Pakete, 625 MB) aus dem Git genommen und in `.gitignore`; 43 lagen bereits byte-gleich unter `releases/<Version>/`, das macOS-Paket 0.4.7 liegt jetzt unter `releases/aus-dem-git/`. Die Historie ist nicht umgeschrieben; das Repository wird dadurch erst nach einer Bereinigung der Historie kleiner.
- Tests: `tests/_wiring.py` (die bisherigen Verdrahtungstests suchten den Routentext in `server.py`; sie akzeptieren jetzt den Text oder dieselbe Route aus der Registratur), `tests/test_v0584_platform_registry.py`.

## 0.5.83 – Einheitliche deutsche Kategorien für Filme und Serien aller Quellen
- Björn (13.11.2026): Jeder Anbieter bringt eigene Genres mit, die Kategorie-Chips waren unübersichtlich (Dubletten wie „Fantasie“/„Fantasy“, „Krimi“/„Kriminalfilms“, „Science-Fiction“/„Sciencefiction“, Englisch/Deutsch gemischt, viele Einzeltreffer, „Joyn (kostenlos)“ als Kategorie, große Gruppe „Unbekannt“). Wunsch: Kategorie erst nach der Metadaten-Klassifizierung, vorher „unklassifiziert“.
- `categories.py` (neu): feste Liste aus 32 deutschen Kategorien (19 Spielfilm-Genres, 13 Sachthemen und Fernsehformate) plus `Unklassifiziert` (Abgleich noch nicht gelaufen) und `Sonstige` (abgeglichen, kein Genre passt). `of_label` ordnet jedes Roh-Label über Schlüsselwort-Regeln zu (mehrere Treffer möglich, z. B. „Romantische Komödie“ → Komödie + Romantik); reine Formatangaben (TV-Film, Miniserie, Kurzfilm, Spielfilm) und Plattform-Etiketten ergeben keine Kategorie. `classify`: Referenz-Genres (IMDb/TMDB/TVDB) zuerst, Anbieter-Genres nur als Ergänzung.
- Plattformen (`portal_reference`): `categories`/`summary` nutzen die feste Liste; als abgeglichen gilt ein Bericht mit Status `candidate`, `review` oder `no_match` (`partial` wird später erneut geprüft und bleibt unklassifiziert). Die Rohgenres stehen weiter in den Plattform-Datenbanken, in `source_genres` und in den Anbieterangaben der Titelseite. `matches` versteht alte Filterwerte („Unbekannt“ → Unklassifiziert, Roh-Labels wie „Kriminalfilms“ → Krimi). Download-Metadaten (NFO-Genres) unverändert über `metadata.genres` (`portal_reference.genre_names`).
- JustWatch TV: Titel mit IMDb-ID von JustWatch gelten als identifiziert (JustWatch ist selbst ein Metadatendienst). Joyn: „Joyn (kostenlos)“/„Joyn+“ ist keine Kategorie mehr (`offer_label`), bleibt aber Filterwert. TOGGO: immer „Kinder & Familie“; TOGGO/TOGGOLINO als Marke (`brand_label`), weiter filterbar.
- ARD, ZDF & Co. (`catalog.py`): `category_tree` zählt je Medienart und fester Kategorie (Serien einmal je Sendung, eine abgeglichene Folge klassifiziert die Sendung), `category_clause` filtert danach; abgeglichen = `attempts>0` oder Zustand matched/manual/identified/review/format. Der klassische Genre-Baum (Verwaltung → Werkkatalog) zeigt und filtert weiter die gespeicherten Roh-Genres. Kacheln zeigen die festen Kategorien (`categories` je Eintrag).
- `/api/catalog-tree` liefert zusätzlich `categories` und `category_names`. `web/unified_catalog.js`: Chips und Genre-Auswahl nur aus der festen Liste in fester Reihenfolge, Sonderwerte am Ende (gestrichelt, mit Erklärung als Tooltip, `web/portal_categories.js`).
- Migration: keine Schemaänderung, alle Roh-Genres bleiben erhalten; die Zuordnung wird beim Lesen berechnet. Gespeicherte Plattform-Ansichten (`portal_snapshot.FORMAT` 3) werden einmal neu aufgebaut.

## 0.5.82 – Sammelstand 0.5.78–0.5.81, Werkerkennung für Archive.org (aus Archive Media)
- Sammelstand: Zweige uvmg6u (0.5.80), toma7t (0.5.79) und osfgh2 (0.5.81) zusammengeführt, alle auf vtbjm6 (0.5.78). Konflikte nur in Versionsdateien, Modulliste (`build_macos.py`), Importzeile, `SCRIPTS` und Diagnose-Export in `server.py`, Skriptliste in `web/index.html`. TOGGO in `watch_state.SOURCES`/`REF_KEYS` und `web/watchlist.js` ergänzt.
- Schritt 3 aus `docs/REVIEW_0577.md`. `archive_recognition.py` (neu): Werke über den Uploads aus `portal_items` (Quelle `internet_archive`), eigene Datei `archive_works.sqlite3` (`archive_works`, `archive_work_items`, `archive_reference_checks`, `archive_anime`, `archive_meta`). Die Uploads selbst werden nie geändert.
  - `query_title`/`parse` (ArchiveMedia `work_title_queries.provider_query_title`, `catalog_repair.release_title`, `catalog_identity.normalize_title`/`EPISODE`): Suchtitel, Jahr aus dem Titel vor dem Jahr des Uploads, Serie nur bei ausdrücklicher Folgen- oder Staffelangabe mit Namen davor.
  - `rebuild`/`sync`: ein Werk je Film (Titel + Jahr) oder Serie (Titel); Neuaufbau nur, wenn sich Anzahl oder letzter Änderungszeitpunkt der Uploads ändert.
  - `SPEC` für `portal_enrichment`: dieselbe Prüfung wie Pluto TV und die anderen Plattformen (`core.candidates`, `netzkino_enrichment.analyze`, `reference_share`).
  - `enrich`: Jahresreparatur (ArchiveMedia `year_repair`, hier über die Titelsuche statt über vorhandene Kennungen): bei `no_match`/`review` einmal ohne Jahr, nur ein eindeutiger Treffer zählt (`year_state` 2), sonst bleibt das Jahr (`year_state` 1). Anime-Hinweis (Wort im Titel/in der Beschreibung oder japanische Schrift) ohne Treffer → `vendor/archive_portals/anime_match.py` (neu übernommen, AniList GraphQL, Treffer 30 Tage, kein Treffer 6 Stunden, Netzfehler nicht gemerkt).
  - `_groups` (ArchiveMedia `series_merge`): Werke mit derselben Kennung sind ein Werk. `annotate`, `overview`, `members_of`, `summary`.
- `server.py`: `/api/portal-items` liefert je Archive.org-Upload `work` und kennt `work=<id>`; `GET /api/archive-works`, `POST /api/archive-work-check`; Hintergrundprüfung `archive_auto_enrichment`; Aufgabe `enrich:archive` (`task_control.py`); Diagnose-Export `archive_works` (nur Anzahlen). `portal_sources.listing(ids=…)`.
- `web/app.js`: `portalWorkLine`, `portalWorkCard`, Ansicht „Werke (Archive.org)“ (`#portal-view`), Filter auf ein Werk (`#portal-work-filter`).
- Befund: `container_tracks` (Tonspuren und Untertitel vor dem Download) war bereits über `vendor/archive_portals/media_probe.py` in „Fassungen, Folgen und Sprachen prüfen“ aktiv; nichts zu tun.

## 0.5.81 – Merkliste, Weiterschauen auf dem Server, Speicherübersicht (aus HomeTube), Aufräumen nach dem Review
- Björn (12.11.2026): komplettes Review aller Funktionen, dazu alle Funktionen aus HomeTube und Archive Media integrieren (All-in-one). Review und Lückenanalyse: `docs/REVIEW_0577.md`. Dies ist Schritt 1 und 2 der dort genannten Reihenfolge. 0.5.79 und 0.5.80 gehören anderen Threads.
- `watch_state.py` (neu, aus hometube/catalog.py: favorite, pinned, last watched): `watch.sqlite3` im Datenordner, eine Zeile je Player-Schlüssel (`<plattform>:<id>`, `job:<id>`, Werk-ID). `progress`, `mark`, `forget`, `overview`, `states`, `summary`. Routen `GET /api/watch`, `POST /api/watch-progress`, `/api/watch-mark`, `/api/watch-forget`. Live-Sender werden nicht gespeichert; unter 20 s gilt ein Titel nicht als begonnen, die letzten 45 s beenden ihn (wie im Player).
- `web/player.js`: `save()` meldet den Stand zusätzlich an den Server (`push`), „Von vorn“ löscht ihn dort; `window.AtlasPlayerSync` übernimmt neuere Stände des Servers in den Browser, `window.playRef(ref,label,key)` öffnet einen Titel über seine gespeicherte Referenz.
- `web/watchlist.js` (neu): `window.AtlasWatch.button(item)` in jeder Kachel (`makeCard` in `web/unified_catalog.js`, damit auch in den Plattform-Reitern), Bereiche „Weiterschauen“ und „Merkliste“ über dem Katalog (`#atlas-watch`), Öffnen der Titelseite je Quelle.
- `storage_policy.py` (neu, aus hometube/policy.py): reine Funktionen `protection`, `can_free`, `cleanup_plan`; `overview` (fertige Downloads, Größe, Quelle, Schutzgrund, Vorschlag, freier Platz), `delete` (genau eine Datei samt Begleitdateien über `netzkino_downloads.remove_files`, angeheftete Titel und Dateien außerhalb des Auftragsordners werden abgelehnt), Einstellungen in `storage.json` (`budget_gb`, `protect_days`). Routen `GET /api/storage`, `POST /api/storage-settings`, `/api/storage-delete` (nur mit `confirm:true`). Abweichung vom Original: HomeTube verlangt zwei belegte Archivkopien; diesen Beleg gibt es hier noch nicht, deshalb löscht MediathekAtlas nie selbst.
- `web/storage.js` (neu), Reiter „Speicher“ in der Verwaltung (`#storage`).
- Review, Stufe 1: 20 ungenutzte Importe entfernt; `/api/candidates` liest den Metadaten-Cache nicht mehr umsonst; `-webkit-backdrop-filter`; Rückfall für `@container` über `@supports not (container-type:inline-size)`.
- Diagnose-Export: Abschnitt `watch` (nur Anzahlen), Ereignisse `watch_mark`, `storage_settings`, `storage_delete`.

## 0.5.80 – Besetzung mit Fotos, Clips bei ihrer Sendung, Erkennungsrate je Medienart, Windows/Linux-Pakete
- Björn (12.11.2026): liegengebliebene Punkte abarbeiten. Baut auf 0.5.78 (YouTube, Zweig vtbjm6) auf; 0.5.79 ist vom TOGGO-Thread reserviert.
- Live-TV: Björns Diagnose (0.5.72) zeigte dutzende `live_tv_overview`-Warnungen „total 0, filtered“ mit `joyn: 0`. Ursache: die Live-Leiste der Plattform Joyn fragt `provider=joyn`, Joyn hatte vor dem ersten vollständigen Abruf keine Sender. `live_tv.overview_problem` meldet nur noch echte Fälle (ungefiltert leer, Anbieterfilter leer obwohl der Anbieter Sender hat, langsam, Fehler); das Ereignis nennt jetzt `provider`, `group_set`, `query_set`.
- `cast_photos.py` (neu), `POST /api/cast-photos`: Fotos über TMDB (`movie/<id>/credits`, `tv/<id>/aggregate_credits`, `find/nm…`). Titel-ID direkt (TMDB), über IMDb-/TVDB-ID oder einen eindeutigen Suchtreffer mit Jahr ±1; keine Namenssuche. Zwischenspeicher `people.sqlite` (Treffer 90 Tage, keine Treffer 14 Tage, Netzfehler nicht). `web/titleview.js` `castPhotos()` ersetzt Initialen nach dem Laden; `portal_title` liefert `cast_ref` für Plattform-Titelseiten.
- `catalog.format_contribution`: Clips (`kind=other`) mit Format-Wort im Thema gehören auch als einzige Ausgabe zur Sendung, kurze Clips (< 20 min) ab zwei Ausgaben; Ausgaben mit gleichem Titel wie die Sendung ab zwei Ausgaben (Folgentitel + Sendedatum). `FORMAT_REV=4` startet einen Durchlauf.
- `catalog.recognition`: je Sender `kinds` (movie/series/unknown/other) und `clips`; `recognition_totals` für die Tabelle „Nach Medienart“ (`/api/recognition` → `kinds`).
- `build_desktop.py`, `packaging/windows` (NSIS-Installer, `start.ps1`), `packaging/linux` (Starter, .desktop, systemd-Benutzerdienst, install/uninstall). Standard-Downloadordner unter Windows/Linux `~/Videos/MediathekAtlas`, wenn kein `~/Movies` existiert. Diagnose-Export öffnet unter Windows den Explorer.

## 0.5.79 – TOGGO (Kinderserien von toggo.de, mit TOGGOLINO)
- Björn (12.11.2026): „Integriere mir als nächstes TOGGO für meine Tochter.“
- Grundlage: toggo.de, die TOGGO-API und Brightcove sind aus der Bauumgebung gesperrt, ein HAR lag nicht vor. Verwendet werden nur öffentlich dokumentierte Formate: Sitemap-Standard, Adressmuster und Asset-API laut yt-dlp-Extraktor (`/[toggolino/]<serie>/folge|video/<folge>`, `production-n.toggo.de/api/assetstore/vod/asset/<folge>`), Brightcove Playback API (Konto 6057955896001, Policy-Key aus `config.json` bzw. `index.min.js`). Nichts davon ist live bestätigt.
- `toggo.py`: Katalog aus robots.txt → Sitemaps → Adressen der Folgen und Clips, gruppiert je Serie (`toggo.sqlite3`). Serientitel und Bild aus der ersten Folge (Zwischenspeicherung während des Abrufs), Folgendetails beim Öffnen der Serie (4 parallele Abrufe, höchstens 10 s, Rest beim nächsten Öffnen). Nur feste Hosts, Größenlimits, IDs als Hash (Adressteile können Sonderzeichen enthalten).
- Wiedergabe: nur eine Quelle, die die Playback API selbst ohne Schlüsselsystem nennt (HLS, sonst MP4 bis 1080p); HLS zusätzlich durch `hls_guard`. Keine Adresse wird umgeschrieben (der bei yt-dlp beschriebene Wechsel von `/cenc/` auf `/clear/` wird ausdrücklich nicht benutzt). Ergebnis je Folge gemerkt (`drm`), Stichprobe nach dem Katalogabruf (`probe`, bis zu drei Serien) setzt `protection` = `drm`/`clear`.
- `toggo_enrichment.py` (gemeinsame Abgleich-Engine), Einbindung in `server.py` (`/api/toggo`, `-details`, `-downloads`, `-sync`, `-auto`, `-enrich`, `/api/play?toggo=`), `streaming.resolve(toggo=…)`, `unified_index`, `portal_title` (Fakten, kein Offline), `task_control`, `ui_prefs`, `netcheck`, `artwork`, Paketliste macOS.
- Oberfläche: `web/toggo.js` (gemeinsames Panel mit `startView`/`seriesOnly`), Reiter in Katalog und Plattformen, `window.playToggo`, Titelseite zeigt bei TOGGO neben „Abspielen“ immer auch „Bei TOGGO ansehen“.
- Diagnose: `toggo_sitemap` (Anzahl Sitemaps/Adressen/Serien und Pfadformen ohne Titel), `toggo_sync_*`, `toggo_playback` (clear/protected/no_source).

## 0.5.78 – YouTube: gesperrte Einbettung im eigenen Player, Musikvideos im Katalog
- Björn (13.11.2026, 0.5.75): Musikvideos zeigen im eingebetteten Player „nicht verfügbar“, laufen aber auf youtube.com; der Download geht. Im Katalog fehlt „Musikvideos“ neben Filmen und Serien. Frage: Browser im Rahmen (Frame in Frame) oder andere Wege?
- Bewertung: youtube.com selbst lässt sich nicht in einen Rahmen laden (YouTube verbietet das per `X-Frame-Options`/`frame-ancestors`, der Browser setzt es durch). Viele Musiklabels erlauben die Einbettung nur auf ausgewählten Seiten. Tragfähig ist der eigene Player.
- `youtube_downloads.play_source`: yt-dlp löst die Stream-Adressen auf (wie beim Offline-Speichern: keine Anmeldung, keine Cookies, nichts Kopiergeschütztes; H.264 + AAC bis zur gewählten Qualität, sonst eine fertige Datei). Nur mit eingeschaltetem YouTube-Offline-Schalter; ohne ihn wird yt-dlp nicht gestartet. Adressen 20 Minuten gemerkt (Spulen ohne neue Auflösung).
- `streaming.py`: `resolve(youtube=…)`, Quelle mit `remux` (nur der Server darf die Adressen abrufen) und `audio_url`; `command` hängt den Ton als zweite Eingabe an (`-map 0:v:0 -map 1:a:0`). `/api/play?youtube=…&direct=1`, `/api/stream?youtube=…`.
- `web/player.js`: Fehlermeldung des eingebetteten Players (`onError` 101/150/152/153) wird erkannt. Mit Schalter: automatisch eigener Player, auch für die folgenden Videos der Playlist. Ohne Schalter: zweiter Versuch über youtube.com/embed, dann Hinweis. Unter dem eingebetteten Player steht immer „Auf YouTube ansehen“, mit Schalter zusätzlich „▶ Im eigenen Player abspielen“ und „⬇ Kurz laden und hier abspielen“ (lädt, zeigt den Fortschritt, spielt die Kopie). Offline gespeicherte Videos laufen wie bisher immer lokal.
- Katalog (Dashboard): dritter Knopf „Musikvideos“ neben „Filme“ und „Serien“ (`web/unified_catalog.js`, `view=music`); eine Playlist öffnet sich im YouTube-Bereich (`openAlbum`), einzelne Videos spielen direkt.

## 0.5.77 – Skripte in der Seite, Startpuffer
- Björn (12.11.2026, 0.5.73, Chrome): Videos starten, bei Netzkino „Integrierte Wiedergabe: Cannot read properties of undefined (reading 'play')“, unter „Plattform“ wird nichts angezeigt. `window.AtlasNetzkinoDetail` fehlte, also kam `netzkino_detail.js` nicht an (zuvor `player.js`). Warum einzelne Anfragen in seinem Browser scheitern, ist weiter offen; die Diagnose (0.5.72) enthält dazu nichts.
- `page_scripts.py` (neu): `inline_scripts()` setzt die eigenen Skripte beim Ausliefern von `/` in die Seite (je Datei ein eigenes `<script data-file>`, gleiche Reihenfolge, `//# sourceURL` für Dateinamen in Fehlermeldungen, `</script` im Code maskiert). `web/index.html` und die Einzeladressen bleiben unverändert; hls.js wird weiter bei Bedarf geladen (sonst ffmpeg).
- Björn (13.11.2026): „Abspielen nicht richtig smooth, vorher mehr buffern bis sich der Stream fängt; auf der Website deutlich flüssiger“. `web/player.js`: `gate()` hält Online-Streams (hls.js, ffmpeg-Weg, direkte Datei) an, bis `ahead()` Sekunden Vorrat da sind: `GATE={start:8,seek:4,stall:5,max:15}`; nach dem ersten `playing` und bei jedem `waiting`. Ein `play` des Nutzers beendet das Warten. `playback_stats` unverändert.
- `web/unified_catalog.js`: klare Meldung, falls die Netzkino-Wiedergabe fehlt.
- Sammelstand mit 0.5.75 (YouTube-Thread; dort auch das Diagnose-Feld `quality_level` statt `level`) und 0.5.76 (JustWatch-Thread, claude/project-thread-xr83m3). 0.5.74 ist nie erschienen.

## 0.5.76 – JustWatch: Download startet, sobald JustWatch den Titel freigibt
- Björn (12.11.2026, 0.5.73): Jugendschutz-Filme lassen sich bei JustWatch TV jetzt direkt ansehen, der Download funktioniert aber nicht; Frage, ob der Link vorher neu geholt werden muss. Die Diagnose von 23:09 UTC enthält keinen JustWatch-Download (weder eingereiht noch fehlgeschlagen), die genaue Fehlermeldung ist nicht bekannt.
- Gefundene Abweichung zwischen Wiedergabe und Download: Die Wiedergabe fragt JustWatch live, der Download entschied nach dem gespeicherten Katalogwert und einer festen Uhrzeit (00:10–05:00). JustWatch gibt aber ab 16 von 22 bis 6 Uhr und ab 18 von 23 bis 6 Uhr frei. Folge: Zwischen 22/23 Uhr und 00:10 lief der Film, der Download wurde nur „vorgemerkt“; tagsüber startete ein Download mit nachts gelesenem Katalogwert sofort und schlug fehl.
- `justwatch.released_now`: Live-Frage nach dem Stream. `justwatch_downloads.build_job` und der Warteschlangen-Arbeiter (`justwatch_downloads.released`) richten sich danach: freigegeben → sofort laden, nicht freigegeben → für die Nacht vormerken.
- `justwatch_downloads.resolve` verwirft die fünf Minuten gemerkte Adresse und holt bei jedem Start eine neue (die signierte Adresse stand nie im Auftrag).
- Offen: Ob das Björns Fehler war, ist nicht belegt. Bleibt der Download bei abspielbaren Titeln stehen, wird die Meldung unter der Kachel bzw. ein Diagnose-Export direkt nach dem Fehlversuch gebraucht.
- Nebenbefund aus der Diagnose (nicht Teil dieser Version): `playback_stats` wirft `AttributeError: module 'logging' has no attribute ''` (server.py, `diagnostics.event(..., level=…)`).

## 0.5.75 – YouTube: neue Quellen sofort einlesen, Fortschritt, Musikvideos auf der Plattformkarte
- Björn (12.11.2026, 0.5.73, Diagnose 0.5.72): Playlist mit 80 Musikvideos eingetragen, Musikvideos erscheinen nicht, YouTube zeigt unter Plattformen nichts, unklar ob der Abruf läuft. Ursache laut Diagnose: Nach dem Eintragen wurde kein Abruf gestartet (letzter Lauf 22:21, nächster automatisch erst nach 24 h, `music: 0`); der Hinweis auf „↻ Katalog jetzt laden“ war leicht zu übersehen.
- `server.py`: Hinzufügen oder Aktivieren einer YouTube-Quelle startet den Abruf sofort (mit Schlüssel). Läuft gerade einer, folgt direkt danach genau ein weiterer (`youtube.start_sync(queue=True)`, `_AGAIN`).
- `youtube.py`: Fortschritt `progress` im Status („Quelle 3 von 10: Meine Hits · 80 Videos werden geprüft“), sichtbar in der Statuszeile des YouTube-Bereichs und auf der Plattformkarte. Datenbank im WAL-Modus, damit Reiter und Dashboard während eines langen Abrufs ohne Warten lesen.
- Plattformkarte YouTube: eigene Kachel „Musik-Playlists & -Videos“ (Musik zählt nicht unter „Filme & Serien“). Leerer Musik-Reiter erklärt, was zu tun ist bzw. dass der Abruf läuft.
- `diagnostics.event`: Ein Feld namens `level` (Qualitätsstufe „1.6 Mbit/s“ in `playback_stats` und beim Stream-Ende) brach die Anfrage mit `AttributeError: module 'logging' has no attribute …` ab (Diagnose 0.5.72, 3×). Aufrufe nutzen jetzt `quality_level`; ungültige Stufen werden als Feld `level_value` mit INFO protokolliert.
## 0.5.73 – Skripte der Seite kommen zuverlässig an
- Björn (12.11.2026, 0.5.72, Chrome): „Der Player ist nicht geladen (Ursache: Skript nicht ladbar (player.js))“ bei Filmen und Live-TV; soll in Chrome, Safari und Firefox laufen. Die Datei ist im Paket und wird fehlerfrei ausgeliefert; die Anfrage selbst scheitert also im Browser. Wahrscheinlichste Ursache: `ThreadingHTTPServer` mit Standard-Warteschlange 5 bei 21 gleichzeitig geöffneten Verbindungen (HTTP/1.0, eine je Skript); nicht nachgestellt. Möglich bleibt eine Sperre durch Erweiterung/Schutzprogramm.
- `server.py`: `Server.request_queue_size=128`, `daemon_threads=True`; `SCRIPTS` als eine Liste; zweite Adresse `/code/<name>` und `/code/~<name rückwärts>` (ohne Dateinamen in der Adresse).
- `web/app.js`: ein nicht geladenes eigenes Skript wird bis zu dreimal nachgeladen (`/code/…`, 0,3/0,6/0,9 s Pause), Erfolg als `client_error` „Skript nachgeladen“ in der Diagnose; nach dem letzten Fehlversuch prüft `fetch`, ob der Server antwortet oder der Browser ablehnt, und die Meldung nennt das.

## 0.5.72 – Player startet zuverlässig, letzter Klick gewinnt
- Björn (12.11.2026, 0.5.70): „Der Player ist nicht geladen; Seite neu laden.“ beim Live-TV, Wiedergabe aus dem Katalog (Pluto) startet nicht, „arte startet, obwohl ein anderer Sender angeklickt“. Das Paket 0.5.70 ist vollständig, in Chromium ließ sich der fehlende Player nicht nachstellen; die Ursache in Björns Browser ist offen (Diagnose mit `client_error` nötig).
- `web/index.html`: kein blockierendes `<script src="/hls.min.js">` mehr. `web/player.js`: `loadHls()` lädt die Bibliothek bei Bedarf (8 s Frist), `hlsWanted()`; ohne Bibliothek ffmpeg-Weg. Qualitätsfeld wird angelegt, falls es in der Seite fehlt.
- `web/player.js`: `S.call` zählt die Aufrufe von `open()`; eine verspätete Antwort von `/api/play` für einen früheren Klick wird verworfen (Ursache für „falscher Sender“), `close()` bricht einen laufenden Start ab.
- `/api/play?levels=0`: `streaming.plan(levels=False)` fragt den Anbieter nicht mehr nach den Stufen (liest hls.js selbst); `/api/play?probe=1` liefert nur die Stufen für den ffmpeg-Weg (`probeLevels()`), ohne `playback_start`-Ereignis.
- `web/app.js`: `window.atlasScriptErrors` (auch nicht ladbare Skripte), `window.atlasPlayerMissing()` nennt die Ursache; verwendet in live_tv.js, portal_panel.js, portal_title.js, netzkino_detail.js, unified_catalog.js (dort zeigte „▶ Ansehen“ bisher nichts an).
- Zusammengeführt mit 0.5.71 (YouTube-Musikvideos, claude/project-thread-vtbjm6).

## 0.5.71 – YouTube: Musikvideos
- Björn (12.11.2026): Neben Filmen und Serien Musikvideos bei YouTube; Playlists oder einzelne Videos hinterlegen, online oder offline abspielen; eine Playlist mit einem Klick ganz oder als Auswahl herunterladen.
- `youtube.py`: Quellenart `music` (Playlist, Kanal oder einzelnes Video). `parse_ref` erkennt Videoadressen (`watch?v=`, `youtu.be/`, `/shorts/`, `/live/`, `music.youtube.com`) als `v:ID`; enthält die Adresse `list=`, gilt die Playlist. Keine Mindestlänge, kein Werbe-/Trailerfilter; nur nicht verfügbare Videos (gesperrt, privat, live) fallen weg. Playlist bzw. Kanal = `album` (`m.<Playlist>`), Video = `track` (`t.<Video>`), Reihenfolge in der neuen Tabelle `youtube_album_tracks`. Titel ohne „(Official Video)“ u. Ä.; „Lyric Video“, „Live“ bleiben. Keine Film-Abgleiche (IMDb/TMDB) für Musik, Musik erscheint nicht unter Filmen/Serien oder im Dashboard.
- Ansicht `view=music` (Playlists und einzelne Videos, Suche findet eine Playlist auch über ihre Lieder), `view=tracks&album=…` (Videos in Playlist-Reihenfolge). Status: `music`, `tracks`.
- Offline: weiterhin nur mit eingeschaltetem YouTube-Offline-Schalter. `youtube_downloads.enqueue_many`: ganze Playlist (`album`) oder Auswahl (`ids`, nur Videos dieser Playlist), höchstens 500 je Klick, jedes Video ein eigener Auftrag (Pause, Wiederholen, 30 Tage je Video), bereits gespeicherte/eingereihte zählen als vorhanden. Ablage `<Download>/Musikvideos/<Playlist oder Kanal>/NNN - <Titel>.mkv`, einzelne Videos ohne Nummer. Auflösung wählbar wie bei Filmen.
- Oberfläche: Reiter „Musikvideos“ im YouTube-Bereich, Playlist-Seite mit „▶ Playlist abspielen“ (ein Video nach dem anderen, „Nächstes Video“), „⬇ Ganze Playlist offline speichern“, Auswahlkästchen, „Alle auswählen“, „⬇ Auswahl offline speichern (n)“ und Auflösung. Quellenformular mit Art „Musikvideos“ (ohne Mindestlängenfeld).

## 0.5.70 – hls.js-Wiedergabe, einheitliche Kacheln, Fassungen
- Björn (12.11.2026, 0.5.66): Live-Sender ruckeln, Ton verspätet; auf den Anbieterseiten deutlich flüssiger. Messung in Chromium mit Blitz/Piepton-Testfilm: der ffmpeg-Umweg ist auf ca. 20 ms synchron (auch mit den alten Schaltern nach dem Spulen), die Ursache liegt also nicht im Versatz, sondern im fehlenden Puffer des Umwegs bzw. in Chromes neuem eingebautem HLS-Player, den `nativeHls()` seit dessen Einführung automatisch wählte.
- Björn (Entscheidungskarte 12.11.2026): hls.js einbauen. `web/hls.min.js` (hls.js 1.7.4, Apache-2.0, `web/hls.LICENSE.txt`, sha256 cfc70cc9…), Route `/hls.min.js`. `web/player.js`: `hlsJs()`, `startHls()` (Puffer 30 s, Live 3 Segmente hinter der Kante, `startPosition` fürs Fortsetzen), `hlsLevel()` für die Qualitätswahl ohne Neustart, Rückfall auf ffmpeg bei fatalem Fehler (kein CORS, Manifest nicht ladbar), `nativeHls()` nur noch bei Apple-Browsern. `playback_stats` mit `mode=hls`, `fallback`, `switches`.
- Björn (12.11.2026, Bildschirmfoto 0.5.67): Kacheln je Anbieter verschieden. `web/unified_catalog.js`: Mediathek-Kacheln mit „⬇ Herunterladen“ (öffnet den Prüfdialog) bzw. „✓ Heruntergeladen“, kein Kopierschutz-Hinweis mehr in der Kachel, externer Link als Knopf.
- Fassungen: `AtlasOffline.versions()` (web/offline_button.js) und Abschnitt „Fassungen zum Herunterladen“ in web/portal_title.js; `downloadVersions()` (web/app.js) in web/titleview.js; `edit(item, quality)` wählt die Fassung im Dialog vor.

## 0.5.69 – Joyn: Katalog erscheint schon während des ersten Abrufs
- Björn (12.11.2026, Diagnose 0.5.66): Joyn bleibt bei Sendern und Filmen/Serien komplett leer. Befund: kein Fehler, `api.joyn.de` erreichbar; der erste Katalogabruf lief zum Zeitpunkt der Diagnose seit 3,5 Minuten (`joyn_sync_started`, `last_result=running`). Bis 0.5.65 wurde erst am Ende gespeichert, also blieb alles leer, bis jede Genre-Seite geladen war (1 s Pause je Seite).
- `joyn.py`: Live-Sender werden direkt nach der Senderliste gespeichert, Filme und Serien nach jeder Genre-Seite (`_save_progress`, `last_loaded` erneuert die gespeicherte Plattform-Ansicht); Fortschritt „Genre-Seite n von m“ im Status und als Ereignis `joyn_sync_progress` (nur Zahlen). Pause 0,4 s statt 1 s. Eine Seite ohne neue Titel beendet die Genre-Seite (Schutz, falls Joyn `offset` ignoriert; sonst bis zu 60 gleiche Seiten je Genre).
- `web/portal_panel.js`: Fortschritt in der Statuszeile aller Plattformen, solange ein Abruf läuft.

## 0.5.67 – Live-TV-Reiter mit Zeitgrenze je Anbieter
- Björn (12.11.2026, Bildschirmfoto 0.5.61): Reiter Live-TV bleibt bei „Live-Sender werden geladen …“. Nicht nachstellbar; zwei mögliche Wege abgesichert: Darstellungsfehler (seit 0.5.66 abgefangen und gemeldet) und ein Anbieter, dessen Datenbank nicht antwortet.
- `live_tv.channels`: Pluto, Rakuten, Joyn in eigenen Threads mit `BUDGET = 4.0` s; späte oder fehlerhafte Anbieter liefern `_LAST` (letzter vollständiger Stand) und einen Fehlertext je Anbieter. Die Filmliste wird weiter in der Verbindung des Aufrufers gelesen.
- `server.py`: `pluto.state` in `/api/live-tv` darf fehlschlagen. `web/live_tv.js`: bei Fehler bleiben die Sender stehen, Knopf „Erneut versuchen“.

## 0.5.66 – Wiedergabe, Download-Auswahl, Dubletten, Live-TV
- Zusammenführung: enthält 0.5.61 (Archive.org, d3kpuk) und 0.5.65 (Joyn, b5yaql); 0.5.62–0.5.64 wurden nicht als Pakete ausgegeben.
- Björn (12.11.2026): Live-TV und Streams bei jedem Anbieter asynchron, zeitversetzt, zu langsam. Ursache 1: `-movflags empty_moov` schrieb den Dateikopf vor dem ersten Paket, der Startversatz zwischen Bild- und Tonspur ging verloren (gemessen 0,778 s → 0; nach Spulen Bild 1,0 s → 0). Jetzt `frag_keyframe+delay_moov+default_base_moof` (`streaming.command`). Ursache 2: ffmpeg bekam die Master-Liste, prüfte jede Stufe und spielte immer die höchste.
- Neu `hls_variants.py`: `parse`, `levels`, `choose` ('auto' ≤ 720p, 'max', Höhe), `single` (Liste mit einer Stufe samt Tonspur, nur http(s)-Adressen), `load` (45 s Cache). `streaming.prepare` schreibt die Liste nach `runtime/streams/hls-*.m3u8`, `command(..., playlist=)` nutzt `-protocol_whitelist file,http,https,tcp,tls,crypto` (ohne `-reconnect`, das kennt eine Datei-Eingabe nicht), `-max_reload 60` bei Live; `start(..., cleanup=)`/`finish` räumen auf. `resolve(..., quality=)` wählt bei Sender-Dateien die Datei nach Höhe; `plan` liefert `levels`.
- `server.py`: `/api/play` und `/api/stream` nehmen `quality`; Ereignisse `playback_start` (mit Wunsch und Stufen), `playback_stream` (Sekunden bis zu den ersten Daten, MB, kbit/s, Stufe), `POST /api/playback-stats` → `playback_stats` (Wartepausen, Stufe, ob der Browser selbst spielt).
- `web/player.js`, `web/index.html`: Auswahl „Qualität“ (`#player-quality`, localStorage `atlas-play-quality`), automatische Reduzierung (`stepDown`: > 6 s Warten in 60 s, frühestens alle 30 s), Statistik beim Schließen. Safari/WKWebView: „Automatisch“ = eigener HLS-Player des Browsers, feste Stufe = über ffmpeg.
- Björn (12.11.2026): „bei Download keine Qualitätsauswahl“. Neu `download_quality.py` (`normalize`, `hls_playlist`, `youtube_format`, `pick_format`, `mediathek_key`, `set_job`, `options`), `GET /api/download-options`, alle fünf `*-download-add` nehmen `quality` und speichern sie im Auftrag. `downloads.fetch_hls(..., playlist=)`, `youtube_downloads._format`, `ytdl_bridge.resolve(..., quality=)`. `web/offline_button.js`: Dialog `choose()` (Auflösung, bei mehreren Anbietern Anbieter; `opts.alternatives`), localStorage `atlas-download-quality`. `web/unified_catalog.js`: `canOffline`, gibt die anderen Angebote einer Kachel mit.
- Björn (12.11.2026, 0.5.61): „Ab ins Meer“ weiter doppelt. `portal_reference.summary` gibt Jahr und Titel der Referenz mit; `unified_index._same_work` großzügiger (gleiche Kennung, Referenztitel, Jahr ±1, Laufzeit ±2 min, ähnliche Beschreibung; dagegen: gleiche Datenbank mit anderem Eintrag, Jahre > 1 auseinander, Laufzeit > 15 % verschieden). `portal_snapshot.FORMAT = 2`, damit gespeicherte Ansichten die neuen Felder bekommen.
- Björn (12.11.2026, 0.5.61): Live-TV-Reiter ohne Sender. Hier nicht nachstellbar. `web/live_tv.js`: Darstellungsfehler je Sender abgefangen und gemeldet (`window.atlasReportError`), Hinweis und „Alle Sender zeigen“ bei Filter ohne Treffer, Suchfeld ohne Autovervollständigung; `server.py`: Ereignis `live_tv_overview` bei leerer, langsamer oder fehlerhafter Antwort.

## 0.5.65 – Joyn: Filme, Serien und Live-Sender (kostenlos und Joyn+)
- Björn (12.11.2026): „Free-Version von Joyn mit Live-TV und Mediatheken anbinden“; danach: hat ein Joyn-Konto und kann auch Bezahlangebote nutzen. Basis 0.5.60 (mwe89v @ 59b0db3); 0.5.61–0.5.64 sind anderen Arbeitssträngen zugeteilt.
- Grundlage: Björns HAR von www.joyn.de (Horror-Genreseite, nicht angemeldet). joyn.de und api.joyn.de sind aus der Bauumgebung gesperrt.
- `joyn.py` (neu): GraphQL `api.joyn.de/graphql` per GET mit Persisted Queries wie die Website (`Navigation`, `GenresPaths`, `PageOverviewGenre` mit path/first/offset, Hashes aus dem Website-Code vom 12.11.), Kopfzeilen der Website, keine Anmeldung. Katalog: Live-Sender aus `liveTv` (Radio und Marken ohne Livestream verworfen, Kennung PLUS → Joyn+), Filme/Serien aller Genre-Seiten von /filme, /serien, /plus/filme, /plus/serien (32 je Seite), Lizenz AVOD → kostenlos, SVOD/TVOD/Plus → Joyn+, Unbekanntes und Sammlungen verworfen; ein Titel auf mehreren Genre-Seiten wird ein Eintrag mit allen Genres. Eigene SQLite `joyn.sqlite3`, Rotation wie Rakuten (nur Titel des letzten erfolgreichen Abrufs), Automatik alle 24 h, `PersistedQueryNotFound` als verständliche Meldung.
- Kategorien „Joyn (kostenlos)“ und „Joyn+“ zusätzlich zu den IMDb/TVDB-Genres → Filter in Reiter und Dashboard.
- Wiedergabe: nicht mitgeschnitten. Joyn spielt im eigenen Player (Widevine nach bisherigem Kenntnisstand); bis ein Mitschnitt einen ungeschützten Stream zeigt, öffnen alle Titel und Sender joyn.de („Bei Joyn ansehen“), `play_source` lehnt mit Hinweis ab, kein Offline-Speichern. Folgenlisten (Abfrage `Season`) nicht mitgeschnitten → Serienseite mit Hinweis und Link.
- `joyn_enrichment.py`: IMDb/TVDB/TMDB/OMDb/Wikidata-Abgleich über die gemeinsame `portal_enrichment`-Engine (mit `reference_share`).
- `live_tv.py`: Anbieter Joyn; Quellen dürfen statt `play` einen `link` haben. `web/live_tv.js`: solche Quellen als „↗ Joyn“-Link (Reiter und Live-Leiste). Joyns öffentlich-rechtliche Sender landen beim selben Sender wie die ARD/ZDF-Livestreams.
- Einbindung wie Rakuten: `server.py` (`/api/joyn`, `-details`, `-downloads`, `-sync`, `-auto`, `-enrich`, Plattformkarte, Aufgaben, Diagnose, Hintergrund-Threads), `unified_index`, `portal_title` (Angebot, Sender, Staffeln, Hinweise; Live-Sender ohne Stream nicht abspielbar), `streaming`, `task_control`, `ui_prefs`, `artwork` (img.joyn.de), `netcheck` (api.joyn.de), `build_macos`; Oberfläche: Quelle „Joyn“ im Dashboard, Plattform-Reiter „Joyn“ (`web/joyn.js`, gemeinsames Plattform-Panel), Startansicht.

## 0.5.61 – Archive.org-Downloads wie in ArchiveMedia
- Björn (12.11.2026, Entscheidungskarte): Archive.org-Filme in MediathekAtlas herunterladbar, „alles wie in ArchiveMedia“ – jede Datei ladbar, Lizenz nur gespeichert und angezeigt.
- Neu `archive_downloads.py`: `build_job`/`enqueue` aus dem gespeicherten, gefilterten Item-Manifest (`portal_sources.archive_saved_detail`); nur dort gelistete Videodateien, Adresse aus Identifier + Dateiname (`_archive_video_url`), nie aus dem Browser. Metadaten: Film = normalisierter Upload-Titel (bei mehreren Dateien der Dateititel), Serie = Upload-Titel + Staffel/Folge der Datei; Korrektur über `metadata` (Titel, Jahr, Art, Staffel, Folge). Job `origin='internet_archive'`, `license.kind='archive_item'` mit `rights`/`license_url`, keine Ablauffrist. Dublettenschutz je Identifier + Datei und über das Ziel (`netzkino_downloads.insert`).
- `fetch_sidecars`: Untertiteldateien aus dem Manifest (max. 12, je 8 MiB, keine HTML-Antworten) neben das fertige Video, Sprachkürzel aus dem Dateinamen, nie überschreiben; ausgelöst in `server.put_job` bei Abschluss.
- `netzkino_downloads.LOCAL_ORIGINS`: `is_portal` gilt auch für `internet_archive` (kein Verbund, kein `mark_downloaded`); `_public` liefert `internet_archive_id`.
- `server.py`: `POST /api/archive-download`, `GET /api/archive-downloads?id=`. `web/app.js`: Knopf „⬇ Herunterladen“ je Datei in `showArchiveManifest` (fragt bei Folgen ohne Nummer nach Staffel/Folge), Hinweistext der Archive.org-Karte.

## 0.5.60 – Gespeicherte Plattform-Ansichten, ruhige Titelseiten, Untertitel-Dubletten
- Zusammenführung: 0.5.57 (mwe89v), 0.5.59 (5t9ycc, Rakuten-Livesender) und vtbjm6 @ a256f12 (YouTube: Werbevideos, Einrichtung öffnet sich). 0.5.58 wurde nicht vergeben.
- Björn (12.11.2026): 24-Stunden-Einstellung unter Plattformen „bleibt nicht erhalten“; Katalog dort teils nicht da oder spät, soll nach dem Scan gespeichert bleiben; unschöne Abgleich-Angaben auf Film-/Serienseiten, „IMDb offline“ soll dort nicht stehen (Bildschirmfoto #Roxy); Dublette „Ab ins Meer“.
- `portal_snapshot.py` (neu): vollständige aufbereitete Liste je Plattform/Ansicht/Filter im Speicher, ungefilterte zusätzlich in `snapshots/<plattform>-<ansicht>-<sortierung>.json`; sofortige Antwort, Erneuerung im Hintergrund nach 60 s, Neuaufbau bei beendetem Katalogabruf (Stempel aus `last_success`/`last_loaded`/`last_attempt`/`running`) und nach POST-Aktionen der Plattform; bei gesperrter Datenbank gespeicherte Ansicht und letzter Status statt Fehler.
- `server.py`: `portal_page()` für Pluto, JustWatch, Rakuten, YouTube; `/api/netzkino-grouped` für Filme/Serien; `_SnapshotSource` reicht dieselben Ansichten an `unified_index` weiter. YouTube mit `doubtful=1` liest direkt.
- Einstellung 24 h: Speicherung war in Tests intakt (alle fünf Plattformen, Neuladen). Zwei Schwächen behoben: der Schalter lag seit 0.5.55 nur im zugeklappten Block (jetzt Statuszeile `#<plattform>-brief` in `web/admin.js`), und `summary()` setzte ihn aus einer älteren Antwort zurück (`autoHold` in `web/portal_panel.js`, `web/netzkino.js`; Bestätigung bzw. Rücknahme bei Fehler).
- `web/portal_title.js`: „Technische Angaben · Abgleich und Anbieterdaten“ als zugeklappter Bereich (Abgleich, Kandidaten, Anbieterangaben, Expertenansicht); Zeile „Zuordnung“ entfällt; Knopf oben ist `AtlasOffline.control` (vorher scrollte er nur zum zweiten Knopf); Abschnitt „Offline ansehen“ nur mit vorhandenen Kopien. `web/titleview.js`: `matchInfo`/`providerLabel` („Datenquelle: IMDb · tt…“).
- `unified_index.py`: `_keys` (Upload-Titel zusätzlich mit vollem Originaltitel `raw_title`), `_same_work` (gleiche Kennung oder Laufzeit ±120 s ab 40 min; gleiche Datenbank mit verschiedenen Kennungen schließt aus), `merge(..., subtitles=)` nur für Filme.

## 0.5.59 – Rakuten TV: Livesender liefern wieder einen Stream
- Björn (12.11.2026, 0.5.56): bei jedem Rakuten-Livesender „Rakuten TV lieferte für diesen Sender keinen Stream“, dieselben Sender über Pluto TV laufen.
- Ursache (Analyse gegen Björns HAR, Rakuten ist aus der Bauumgebung gesperrt): Die Meldung entsteht, wenn `avod/streamings` mit HTTP 200 antwortet, aber `stream_info` keine Adresse zurückgibt. Zwei Stellen: (1) `stream_info` verwarf jede Adresse außerhalb von `*.rakuten.tv` und über 8.000 Zeichen; die Live-Adressen sind Werbe-Einfüge-Sitzungen (MediaTailor, im HAR ~1.900 Zeichen mit 50 `ads.*`-Parametern), Host und Länge hängen von den Werbeparametern ab. (2) Die Anfrage wich deutlich von der Website ab: ohne `unique_session_id`, ohne `device_stream_*`/`disable_dash_legacy_packages` in der Adresse, ohne `strict_video_quality`, `subtitle_formats`, `app_bundle`, `app_name`, `url`, ohne Einwilligungsfelder.
- `rakuten.py`: `_live_query`/`_live_body` wie die Website (neue Sitzungskennung je Abruf); `gdpr_consent_opt_out='1'`, `gdpr_consent=''`; weiterhin keine IP, kein Browserstring, keine Werbe-IDs (`publisher_provided_id`, `gam_correlator`, `requestedContent`). `stream_info` akzeptiert jede https-Adresse ohne Zugangsdaten bis 16.000 Zeichen; `hls_guard.check` bleibt vor jeder Wiedergabe.
- Fehlerfall: `_no_stream_reason` (Rakutens Fehlertext, fehlende Streamliste mit Feldnamen, fehlende oder abgelehnte Adresse), Diagnose-Ereignis `rakuten_live_no_stream`; HTTP-Fehler mit Rakutens Fehlertext (`_http_detail`).
- 0.5.57 und 0.5.58 sind von anderen Arbeitssträngen reserviert.
## 0.5.57 – Dashboard ohne Statusblöcke, Start ohne Warten auf den Katalog
- Björn (12.11.2026, Bildschirmfoto): Dashboard zeigt wieder Kennzahlen, „Aktuelle Erkennung“ und eine zweite Serien/Filme-Suchleiste; nach dem Start ist die App träge, besonders die Kataloge.
- Ursache Anzeige: Die Blöcke standen in `web/index.html` weiter im Abschnitt `#discover` und wurden erst von `arrangeAdvanced()` (unified_catalog.js, das 16. von 20 Skripten) in die Verwaltung verschoben. Bis dahin, oder falls das Skript nicht lief, zeigte das Dashboard den alten Aufbau. Kein Rückfall durch 0.5.56 (dort ist `unified_catalog.js` unverändert).
- `web/index.html`: Statusblock als `#atlas-main-dashboard` fest in `#status-boards`, klassischer Katalog fest in `#legacy-body`. `arrangeAdvanced()` ergänzt nur noch die Warteschlangen-Übersicht; der alte Verschiebeweg bleibt für ältere Seiten erhalten.
- `catalog.py`: gruppierte Listen überleben den Neustart (`load_listings`, `listing-cache.json`, nur langsame Listen ohne Suche, höchstens 6); `listing(..., wait=False)` rechnet die erste Gruppierung im Hintergrund und meldet `ListingPending`; ein Fehler im Hintergrund wird 30 s gemerkt und gemeldet statt wiederholt.
- `unified_index.py`: Mediatheken-Quelle mit `wait=False`, Feld `pending`; veralteter Index wird sofort geliefert und im Hintergrund erneuert; Sekunden je Quelle (`ON_BUILD` → Ereignis `unified_index_built` ab 1 s).
- `web/unified_catalog.js`: Hinweis „… wird noch eingelesen“ und selbstständiges Nachladen.
- `web/app.js`, `server.py`: Skriptfehler der Oberfläche als Ereignis `client_error` (höchstens 5 je Seite, 40 je Lauf).

## 0.5.56 – Archive Media Stufe 1: Fanart.tv und Datenbanksicherungen
- Björn (12.11.2026): HomeTube und Archive Media sollen in MediathekAtlas aufgehen; Archive Media ist noch nicht vollständig integriert. Plan: Doc „Integrationsplan: HomeTube und Archive Media in MediathekAtlas“.
- `vendor/archive_portals/fanart_client.py` (unverändert aus ArchiveMedia v0.10.53): Fanart.tv v3.2, Schlüssel nur in Kopfzeilen, ID-Gegenprüfung, Bildhosts nur `assets.fanart.tv`/`fanart.tv`.
- `artwork.py`: `fanart_lookup` nach TVDB/TMDB mit bekannter Kennung (Serien: TVDB → IMDb → TMDB, Filme: IMDb → TMDB); füllt nur fehlende `poster`/`fanart`, neu `logo`; `fanart_checked` verhindert Wiederholungen; Abruf über `core.open_url` (Weiterleitungsschutz). Bildabgleich startet auch, wenn nur Fanart.tv eingerichtet ist. Cache-Schlüssel `v0556`.
- `downloads.py`: Logo als `clearlogo` (Serienordner) bzw. `<Datei>-clearlogo` (Filme).
- `server.py`: Einstellungen `fanart`, `fanart_personal` (in Diagnosen geschwärzt, löschbar), `fanart_set` im Status. `web/`: Eingabefelder, `assets.fanart.tv` in `safeArt`, Logo auf der Titelseite (`.tv-logo`).
- `db_backup.py` + `vendor/archive_portals/backup_manager.py` (unverändert v0.10.53): `create` per SQLite-Backup-API in kleinen Schritten, `quick_check`, fsync, atomar veröffentlicht, Speicherreserve 256 MB; `rotate` löscht nur automatische Sicherungen über vier; gelöschte Namen werden nie neu angelegt. `/api/backups`, `/api/backup-create`, `/api/backup-delete` (Bestätigung „BACKUP LÖSCHEN“ und Fingerabdruck). Hintergrundschleife als Aufgabe `backup` (Gruppe Wartung) in `task_control`.
- `vendor/archivemedia/{catalog_identity,external_metadata,media_probe}.py` auf v0.10.53 (bisher v0.10.12, derzeit nicht importiert; `media_probe` mit vendor-Importpfaden wie in `archive_portals`).

## 0.5.55 – Dashboard nur mit Filmen und Serien, Verwaltung, zusammengeführter Index, schnelle Katalogseiten
- Björn (12.11.2026, mit Diagnose 0.5.53): läuft nicht rund; Oberflächen der Plattformen unterscheiden sich; Dashboard soll nur die Filme aller Plattformen zeigen; unter „Verwaltung“ Einstellungen, Darstellung je Film und Steuerung der Aufgaben; in „Gesamt“ stehen Filme mehrfach (je Anbieter); der obere Statusbereich ergibt im Katalog keinen Sinn; Rakuten/JustWatch zeigen unter „Plattformen“ keinen Katalog; Live-TV lädt sehr lange; Streams ruckeln.
- **Ursache der Hänger (Diagnose):** 239 `http_slow_request` für `/api/catalog` mit 7–31 s in sechs Stunden. `web/app.js` lud die klassische Katalogansicht bei jeder Änderung der Statuszähler neu (während der Erkennung alle paar Sekunden); jede Abfrage gruppierte und sortierte alle ~680.000 Werke. Der Browser hält nur sechs Verbindungen je Host offen: Plattform-Reiter, Live-TV und Stream-Start warteten dahinter. Zusätzlich wartete „Gesamt“ mit `Promise.allSettled` auf die langsamste Quelle.
- `catalog.py`: Index `work_listing(kind,show_key,id,title,year,state)` deckt Gruppierung und Genre-Baum ab; gruppierte Listen werden je Filter im Speicher gehalten (`_listing_groups`, 10 Minuten, bei langsamer Aggregation alte Seite sofort und Erneuerung im Hintergrund); `invalidate_listings` nach Import, Download und manuellen Änderungen; Vorwärmen beim Start (`catalog_listing_prewarmed`). Ohne Server (Tests, Werkzeuge) liest jeder Aufruf direkt.
- `web/app.js`: klassische Ansicht lädt nur noch, wenn „Verwaltung → Werkkatalog“ offen ist, höchstens einmal je Minute. `web/unified_catalog.js`: Genre-Baum löst kein wiederholtes Neuladen mehr aus.
- **`unified_index.py` + `/api/unified`:** ein zusammengeführter, über alle Quellen sortierter und geblätterter Index statt sechs Seitenabfragen im Browser. `merge`: gleicher Titelschlüssel (`title_key`; bei YouTube ohne Werbezusatz in Klammern), Jahr gleich, ±1 oder unbekannt (YouTube-Jahr = Upload-Jahr, zählt nicht), nie zwei Angebote derselben Quelle. Nur Darstellung, keine gespeicherte Identität. Portal-Listen akzeptieren dafür `limit='all'`, `catalog.listing(index_only=True)`.
- **`task_control.py` + `/api/tasks`, `/api/task-action`:** Register aller Hintergrundaufgaben (Filmliste, Werkerkennung, Folgenabgleich, Bilder, IMDb-Archiv, Katalogabruf und Werkzuordnung je Plattform, Downloads, Abos) mit Pause, „Jetzt starten“ und Priorität (Werkzuordnung je Plattform: Abstand ×0,35 / ×1 / ×3). Gespeichert in `task-control.json`. Die Schleifen prüfen kooperativ zwischen zwei Arbeitsschritten.
- `job_queue.py`: `next_job` nach Priorität, dann Alter; `control` (first/normal/raise/lower/hold/release/now), `summary`; `/api/job-control`.
- **`ui_prefs.py` + `/api/display`, `web/display.js`:** Darstellung (Kachelbestandteile, Kachelgröße, Titelseite, Startansicht, Zusammenfassen) in `display.json`, als Klassen am `<body>` angewendet.
- **Oberfläche:** Navigation Dashboard / Plattformen / Live-TV / Downloads / Verwaltung; `showView` in `web/app.js`; Verwaltungsreiter Aufgaben, Status & Abgleich, Darstellung, Zuordnung, Download-Abos, Werkkatalog, Protokoll, Einstellungen (`web/admin.js`). Statuskarten und klassische Ansicht werden als lebende Knoten verschoben (IDs und Handler bleiben). Eine Kachel für alle (`AtlasCards.card`), auch in den Plattform-Reitern und im Netzkino-Reiter; Plattform-Reiter mit Katalog oben und eingeklapptem Verwaltungsblock.
- `streaming.py`: Online-Quellen mit `-frag_duration 1000000 -flush_packets 1` (vorher ein Fragment je Schlüsselbild-Intervall, bei HLS oft 6–10 s).
- Nicht Teil dieser Version: Auflösung vor dem Download wählbar (Björn, 12.11.2026, folgt), YouTube-Mindestlänge für Serien (YouTube-Thread).

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

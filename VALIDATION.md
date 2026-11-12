# Validierung · MediathekAtlas 0.4.0 Preview

## 0.5.65 – Joyn (12. November 2026)
- Automatisch: gesamte Python-Suite grün (777 Tests), davon 9 neu in `tests/test_v0565_joyn.py` (Abfrageadresse und Kopfzeilen wie im HAR, Abruf mit kostenlosen und Joyn+-Titeln, Seitenwechsel bei 32 Einträgen, Genre-Pfade dedupliziert und geprüft, Sammlungen/unbekannte Lizenzen verworfen, Kostenlos schlägt Joyn+, Filter „Joyn+“, Live-Sender mit Plus-Kennung, Radio/ohne Livestream verworfen, PersistedQueryNotFound, Teilabruf, Rotation, Wiedergabe abgelehnt, Titelseite mit Link und Hinweis, Live-TV-Zusammenführung mit ARD, Bild-/Link-Prüfung, Abgleich-Spec). Drei ältere Verdrahtungstests um Joyn ergänzt. `node --check` aller geänderten Skripte.
- Nicht geprüft: echte Joyn-Antworten (api.joyn.de aus der Cloud gesperrt; Antwortformen aus Björns HAR), ob die Persisted-Query-Hashes nach dem nächsten Joyn-Update noch gelten, Geo-Sperre außerhalb Deutschlands, Wiedergabe und DRM (kein Mitschnitt), Folgenlisten, Mediatheken-Seiten der einzelnen Sender.

## 0.5.60 – Gespeicherte Plattform-Ansichten, Titelseiten, Dubletten (12. November 2026)
- Automatisch: gesamte Python-Suite grün (768 Tests), davon 16 neue in `tests/test_v0560_platform_views.py` (Seiten aus einer gespeicherten Liste, Neustart mit Datei und Erneuerung im Hintergrund, gefilterte Ansichten nur im Speicher, Neuaufbau nach Katalogabruf und Nutzeraktion, gesperrte Datenbank zeigt gespeicherte Ansicht, defekte Datei; Upload-Titel mit Untertitel, Kennung, Laufzeit, Gegenbeispiele „Alien“/„Alien: Covenant“, Serien ausgenommen, alte Regeln; Oberflächen-Verträge). `node --check` und UI-Smoke-Tests grün. Enthält die Tests aus 0.5.59 und dem YouTube-Zweig.
- Browser (Chromium, Testbestand): Schalter „alle 24 Stunden“ auf allen fünf Plattformen umgestellt, neu geladen, Wert bleibt; Statuszeile über dem Katalog zeigt an/aus und Stand, „Verwalten“ öffnet den Bereich. Netzkino-Titelseite: ein Offline-Knopf, kein „IMDb Offline“, keine Zeile „Zuordnung“, „Technische Angaben“ zugeklappt mit Abgleich und Anbieterangaben. Klickdurchlauf aus 0.5.55 ohne Skriptfehler; Ordner `snapshots` wird angelegt.
- Nicht nachgestellt: dass die 24-Stunden-Einstellung verloren geht (in jedem Versuch blieb sie gespeichert). Behoben sind die zwei Stellen, an denen es so aussehen konnte; ob das Björns Beobachtung erklärt, zeigt erst sein Test.
- Nicht geprüft: Björns Mac mit echtem Bestand; ob „Ab ins Meer“ bei ihm zusammengeht, hängt vom Originaltitel des YouTube-Uploads bzw. von Kennung oder Laufzeit beider Einträge ab (Daten liegen hier nicht vor). Echte Rakuten-/Pluto-Streams, Safari, NAS-Hardware. Besetzung mit Fotos ist nicht umgesetzt (IMDb-Daten enthalten keine Bilder; bräuchte TMDB-Abrufe).

## 0.5.59 – Rakuten-TV-Livesender (12. November 2026)
- Automatisch: gesamte Python-Suite grün (737 Tests), davon `tests/test_v0559_rakuten_live.py` (4 neu: Anfrage wie die Website mit gleicher Sitzungskennung in Adresse und Body, ~2.000 Zeichen lange Adresse angenommen, fremder CDN-Host angenommen, Grund bei fehlendem Stream in vier Varianten, HTTP-Fehler mit Rakutens Text); `tests/test_v0551_rakuten.py` angepasst (keine IP/Werbe-IDs im Body, http- und Zugangsdaten-Adressen abgelehnt).
- Nicht geprüft: echte Rakuten-Antwort auf die neue Anfrage (gizmo.rakuten.tv ist aus der Cloud gesperrt). Falls es weiter scheitert, nennt die Meldung jetzt den Grund.
## 0.5.57 – Dashboard ohne Statusblöcke, Start ohne Warten (12. November 2026)
- Grundlage: Björns Bildschirmfoto vom 12.11.2026 (0.5.55/0.5.56): neue Navigation, aber Kennzahlen, „Aktuelle Erkennung“ und klassische Suchleiste im Dashboard, keine Kacheln, Knopf „Zur Plattform“ sichtbar. Das ist der Zustand der Seite, bevor `unified_catalog.js` gelaufen ist. Ob das Skript bei ihm nur spät oder gar nicht lief, ist aus dem Bild nicht zu entscheiden; eine Diagnose von 0.5.55/0.5.56 lag nicht vor.
- Automatisch: gesamte Python-Suite grün (745 Tests), davon 13 neue in `tests/test_v0557_start.py` (Dashboard-Abschnitt enthält keinen Status- oder Altkatalog-Block, Blöcke stehen ohne Skript in der Verwaltung, jede ID nur einmal, Liste übersteht den Neustart und wird erneuert, Suchen werden nicht gespeichert, defekte Datei wird übergangen, erste Gruppierung blockiert nicht, Fehler im Hintergrund wird gemeldet statt wiederholt, andere Quellen erscheinen vor ARD/ZDF, veralteter Index wird sofort geliefert, Sekunden je Quelle). `node --check` für alle Skripte und die UI-Smoke-Tests grün.
- Browser (Chromium, 607.000 Werke, Plattformen in der Größe aus Björns Diagnose: Netzkino 418, Pluto 1.130, JustWatch 215, Rakuten 1.899, YouTube 3.807; Gruppierung künstlich auf 8 s gebremst): erster Start zeigt nach 1,4 s Kacheln der Plattformen mit dem Hinweis „ARD, ZDF & Co. wird noch eingelesen …“, nach 11,6 s vollständig (12.685 Titel, 1.613 zusammengefasst) ohne Zutun; zweiter Start mit gespeicherter Liste vollständig nach 0,4 s trotz Bremse. Im Dashboard kein Status- oder Altkatalog-Block; Verwaltung → Status & Abgleich und Klassischer Katalog zeigen sie. Gesamter Klickdurchlauf aus 0.5.55 (Suche, zusammengeführte Kachel, Titelseite, Serien, alle Quellen, Aufgaben, Darstellung, Live-TV) ohne Skriptfehler. Ein absichtlich ausgelöster Skriptfehler erscheint als `client_error` im Protokoll.
- Nicht geprüft: Björns Mac mit dem echten Bestand und laufenden Hintergrundaufgaben (dort dauerte die Gruppierung vor 0.5.55 etwa 25 s; wie lange mit dem Index aus 0.5.55, ist unbekannt), Safari, NAS-Hardware. Der Reiter „ARD, ZDF & Co.“ im Dashboard und der klassische Katalog warten beim allerersten Start nach dem Update weiterhin auf die Gruppierung.

## 0.5.56 – Archive Media Stufe 1 (12. November 2026)
- Automatisch: gesamte Python-Suite grün (733 Tests, 1 übersprungen), davon 16 neue in `tests/test_v0556_archivemedia_stage1.py` (Prüfsummen in PROVENANCE, kein Abruf ohne Schlüssel, Film-Logo/Poster/Hintergrund per IMDb-ID, Schlüssel nicht in der Adresse, vorhandene Bilder bleiben, widersprüchliche ID sperrt Bilder, Serie über TVDB-ID, fremde Bildhosts abgelehnt, clearlogo-Export, Verdrahtung; Sicherung konsistent bei offener WAL-Verbindung, Rotation behält eigene und die vier neuesten automatischen, Intervall, Löschen nur mit Bestätigung und Fingerabdruck, aktive DB geschützt, zu wenig Speicher, Aufgabe steuerbar, Schleife auf Anforderung). `node --check` für alle geänderten Skripte.
- Browser (Chromium, leerer Bestand): Einstellungen zeigen die Fanart.tv-Felder; Datenbanksicherungen aufklappen, „Jetzt sichern“ legt `catalog-<Zeit>.db` an und listet sie; Verwaltung → Aufgaben zeigt „Datenbanksicherung“ mit „Jetzt starten“/„Pausieren“; keine Skriptfehler.
- Nicht geprüft: echter Fanart.tv-Abruf (kein Schlüssel in der Bauumgebung), Logo-Darstellung mit echten Bildern im Browser, Sicherungsdauer bei Björns großer Datenbank (~680.000 Werke) und auf NAS-Hardware.

## 0.5.55 – Dashboard, Verwaltung, zusammengeführter Index (12. November 2026)
- Grundlage: Björns Diagnose `MediathekAtlas_Diagnose_2026-11-12T20-45-42` (0.5.52/0.5.53, macOS arm64, Python 3.14, 677.729 Werke): 239 langsame `/api/catalog`-Abfragen (7–31 s, im Mittel 25,6 s), `catalog_tree_complete` 31–34 s; sonst 17 Fehler (Netz-Zeitüberschreitungen der Anbieter, 4× „Adresse nicht erkannt“ beim Eintragen von YouTube-Quellen, 2 abgebrochene/unvollständige Downloads).
- Automatisch: gesamte Python-Suite grün (716 Tests), davon 26 neue in `tests/test_v0555_dashboard_admin.py` (Aufgabensteuerung mit Neustart, Pause in der Abgleich-Schleife, Download-Reihenfolge, Titelschlüssel und Zusammenführungsregeln, zusammengeführte Seite mit ausgefallener Quelle, Seiten-Cache mit Erneuerung im Hintergrund, Index deckt die Gruppierung ab, Darstellungseinstellungen, Stream-Parameter, Aufbau der Oberfläche). `tests/unified_catalog_ui_smoke.cjs` an das neue Dashboard angepasst; `node --check` für alle Skripte.
- Messung (synthetischer Bestand, 607.000 Werke in 30.000 Serien und 7.000 Filmen, Cloud-Container): Serienliste 0,59 s → 0,34 s mit Index, Folgeseiten aus dem Speicher < 5 ms; zusammengeführter Index Filme 0,18 s, Serien 0,69 s, Blättern 3 ms. Die absolute Zeit auf Björns Mac (25 s vorher) ist hier nicht nachstellbar, weil der echte Bestand deutlich größere Datensätze je Werk hat.
- Browser (Chromium, Testbestand mit allen sechs Quellen): Dashboard startet mit „Alle“/Filme aus einer Abfrage; Suche nach einem Titel bei drei Anbietern ergibt eine Kachel „ARD, ZDF & Co. · Pluto TV · YouTube“ mit „Auch bei …“; Titelseite öffnet und kehrt zum Dashboard zurück; Serien, Blättern, jede Einzelquelle; Verwaltung → Aufgaben (17 Zeilen, Pausieren einzeln/Gruppe/alle, Priorität), Darstellung (Beschreibung aus, kompakt, zurücksetzen), Status & Abgleich, Zuordnung, Download-Abos, Werkkatalog, Protokoll, Einstellungen; Plattform-Reiter Rakuten/JustWatch/Pluto/Netzkino mit Katalog oben; Live-TV zeigt Sender. Keine Skriptfehler.
- Streams: ffmpeg 6.1 mit lokalem HLS (6-s-Segmente): vorher 6 Fragmente in 36 s, jetzt 37; Datei vollständig und abspielbar laut ffprobe.
- Nicht geprüft: Wirkung auf Björns echtem Bestand und Rechner; Wiedergabe echter Pluto-/Rakuten-Streams (aus der Bauumgebung nicht erreichbar), insbesondere warum Rakuten-Live gar nicht startet; Safari/WKWebView (spielt HLS selbst, nutzt den Umwandlungsweg nicht); NAS-Hardware.

## 0.5.53 – YouTube (12. November 2026)
- Automatisch: gesamte Python-Suite grün, davon 14 neue Tests in `tests/test_v0553_youtube.py` (Titelbereinigung, Adressen, Katalog mit Filtern und Regionssperre, Serien-Playlist, Wochen-Zwischenspeicher, fehlender Schlüssel, Kontingent, unbekannter Kanal, Quellenverwaltung, Einbettung nur bei abspielbaren Videos, Offline-Schalter mit Bestätigung, Auftrag in der gemeinsamen Warteschlange, yt-dlp-Aufruf mit Fortschritt, Prüfsumme beim Einrichten, gemeinsamer Abgleich, Verdrahtung).
- Browser (Chromium, Testbestand aus synthetischen API-Antworten): Katalog-Reiter „YouTube“ und Plattform-Reiter zeigen die Filme, Übersichtskarte, Einrichtung mit Quellenliste; „▶ Ansehen“ öffnet den Einbettungsplayer mit korrekter Adresse; Offline-Schalter fragt nach Bestätigung und blendet danach den Offline-Knopf ein (ohne yt-dlp gesperrt mit Hinweis); Titelseite mit „Angaben von YouTube“; keine Skriptfehler.
- YouTube-Nutzungsbedingungen (Bewertung an Björn, 12.11.2026): Herunterladen nur über YouTube-eigene Funktionen oder mit schriftlicher Erlaubnis von YouTube und Rechteinhaber. Björn hat „Offline als Schalter, Standard aus“ gewählt.
- Nicht geprüft: Live-Abruf der YouTube Data API (ohne Schlüssel in der Bauumgebung; youtube.com ist dort gesperrt), ob die vorgeschlagenen Handles existieren, Einbettung aus der lokalen App heraus (Referrer bei 127.0.0.1), yt-dlp-Download gegen echtes YouTube (kann Deno/Node.js oder eine Anmeldung verlangen; MediathekAtlas meldet sich nicht an).

## 0.5.52 – JustWatch: Zeitfenster und Kopierschutz (12. November 2026)
- Automatisch: 677 Python-Tests und alle `.cjs`-Tests grün, darunter 10 neue in `tests/test_v0552_justwatch_protected.py` (Zeitfenster aus `availableHours`, Rückfall auf die Altersfreigabe, Rückfall auf die Abfrage ohne das Feld, Migration alter Bestände, Ablehnung geschützter Titel, Titelseite, Kacheln).
- Browser (Chromium, Testbestand): Titel ohne Stream und ohne Zeitfenster zeigt in Katalog und Plattform-Reiter „Bei JustWatch ansehen“ und den Kopierschutz-Hinweis, kein Offline-Knopf; keine Skriptfehler.
- Grundlage: Björns Mitschnitt von justwatch.com/de/Serie/Andromeda (12.11.2026, 16:46 UTC), ausgewertet, nicht im Repository.
- Nicht geprüft: Live-Abruf gegen JustWatch (aus der Bauumgebung nicht erreichbar), insbesondere ob das neue Abfragefeld angenommen wird und ob Titel mit Zeitfenster nachts einen Stream für externe Player bekommen.

## 0.5.51 – Rakuten TV (12. November 2026)

- HAR-Auswertung (Björn, 12.11.2026, 802 Anfragen): Katalog-, Serien- und Live-Formate übernommen; vier `avod/streamings`: Film „Meet Dave“ und Folge „Z Nation 1-1“ → `web:DASH-CENC:WVM` mit `license_url` (prod-widevine.rakuten.tv), MPD mit Widevine-`ContentProtection`; Live „Top Movies“ → `web:HLS-NONE:NONE`, AES-128/identity.
- Neue Tests `tests/test_v0551_rakuten.py` (14): Gratislisten mit Seiten, Leihtitel verworfen, Live-Sender mit laufender Sendung, Fehlertexte, gespeicherter Bestand bleibt, Live-Fehler lässt Filme stehen, Adressprüfung; alle Staffeln einer Serie, Zwischenspeicher; Filme/Folgen ohne Netzanfrage abgelehnt; Live-Sender mit Prüfung, Lizenz bzw. geschützte Liste abgelehnt, AES-128/identity erlaubt; Offline-Ablehnungen und gemeinsame Warteschlange; gemeinsamer Abgleich, Titelseiten, Live-TV-Reiter; Verdrahtung. Gesamte Suite: 667 Tests grün.
- Browser-Durchlauf (Playwright, Testbestand in HAR-Form): Katalog-Reiter, Plattform-Reiter mit Übersichtskarte, Filme nur „Details · Bei Rakuten TV ansehen“, Live-Sender „▶ Live ansehen“, Titelseite mit Kopierschutz-Hinweis, Reiter Live-TV mit Rakuten-Sendern; keine JavaScript-Fehler.
- **Nicht geprüft:** echte Abrufe von rakuten.tv (aus der Cloud gesperrt), ob Rakuten die Live-Anfrage ohne die Werbe-/Einwilligungsfelder der Website annimmt, Wiedergabe der Live-Sender.

## 0.5.50 – Live-TV nach Sendern (12. November 2026)

- Neue Tests `tests/test_v0550_live_tv.py` (11): Sendernamen aus Filmlisten-Titeln, Schreibvarianten, Regionalfenster nur bei Sendern, Livestreams nicht im Werkabgleich (auch Bestandsdatenbanken, manuelle Entscheidungen bleiben), Reihenfolge und Gruppen, inaktive Angebote und Nicht-HTTP-Adressen ausgeschlossen, Wiedergabe als Live ohne Länge, normale Angebote nicht live, Pluto-Sender in der Übersicht, Diagnose nur Zähler. Gesamte Testsuite lokal grün (ein bekannt lastabhängiger Launcher-Test lief einzeln grün).
- Browser-Durchlauf (Playwright, echter Server mit Testbestand: 5 Sender-Livestreams + 1 Pluto-Sender): Reiter Live-TV mit Gruppen Öffentlich-rechtlich (Das Erste, ZDF, 3sat) · Regional (BR Nord, WDR) · Pluto TV; Favorit springt nach oben; Anbieterfilter; „Live ansehen“ bei Das Erste → Player „Live-Stream des Senders“, ohne „Von vorn“; Plattformen → Pluto → Live-TV → Sprung in den Reiter; Live-Leiste im Katalog bei „ARD, ZDF & Co.“; keine JavaScript-Fehler.
- **Nicht geprüft:** echte Filmliste (aus der Cloud gesperrt; Thema „Livestream“ aus dem MServer-Quellcode belegt, Titelform „<Sender> Livestream“ angenommen), echte Wiedergabe der Sender-Livestreams und der Pluto-Sender.

## 0.5.49 – Plattform-Ansicht, JustWatch-Folgen, geteilter Abgleich (12. November 2026)

- Neue Tests `tests/test_v0549_platform_view.py` (9): zweite Plattform fragt nicht erneut (auch bei anderer Schreibweise), kein Teilen ohne Jahr / bei anderem Jahr / anderer Art, unvollständige Antworten werden nicht gespeichert, Ablauf, „Jetzt abgleichen“ fragt neu; JustWatch-Folgen: abgelehnte und leere Sammelabfrage → Staffelseiten (mit Rückfall auf 20 Folgen je Abfrage, fremde Pfade verworfen), Netzausfall nur eine Anfrage; Übersicht in den Plattform-Reitern, Reitername.
- Browser-Durchlauf (Playwright, Testbestand): Reiter „Gesamt · ARD, ZDF & Co. · Netzkino · Pluto TV · JustWatch TV“; Pluto, JustWatch und Netzkino unter „Plattformen“ zeigen je genau eine Übersichtskarte mit Bestand und Werkzuordnung; „Im Katalog anzeigen“ öffnet den Katalog mit der Quelle; keine JavaScript-Fehler.
- **Nicht geprüft:** ob die Staffelabfrage bei JustWatch live Folgen liefert (Form aus dem Mitschnitt übernommen, Angebotsfilter wie in der Serienabfrage der Website); echte Überschneidungen zwischen den Plattformen.

## 0.5.48 – Geplanter Nacht-Download (12. November 2026)

- Neue Tests `tests/test_v0548_night_download.py` (7): Zeitfenster (17:25 → 00:10, 01:30 → sofort, 05:30 → nächste Nacht), Titel ohne Stream wird vorgemerkt, Titel mit Stream nicht, vorgemerkter Auftrag blockiert die Warteschlange nicht und startet nach der Startzeit, Listing zeigt die Startzeit nur solange gewartet wird, Verdrahtung.
- Browser-Durchlauf (Playwright, Testbestand): JustWatch-Kachel ohne Stream → „🌙 Heute Nacht offline speichern“ → „🌙 Vorgemerkt für … Uhr“ im Katalog und im Plattform-Reiter, „Geplant für …“ unter Downloads, „Abbrechen“ in der Kachel; keine JavaScript-Fehler.
- **Nicht geprüft:** ob JustWatch den Stream nachts tatsächlich über dieselbe Abfrage liefert (kein Anbieterzugang in der Testumgebung, kein Nacht-Mitschnitt). Erst Björns erster Nachtlauf zeigt das.

## 0.5.47 – Offline speichern in jeder Kachel (12. November 2026)

- Neue Tests `tests/test_v0547_offline_tiles.py` (4): ein Bedienelement für alle Anbieter, alle Kachelansichten nutzen es, keine zweite Umsetzung, Auslieferung und Ladereihenfolge.
- Browser-Durchlauf (Playwright, Testbestand mit drei eingespielten Aufträgen): Katalog- und Plattform-Kacheln zeigen denselben Zustand – JustWatch „✓ Offline verfügbar · bis 12.12.2026 · noch 30 Tage“, Pluto „Unterbrochen“ mit Wiederholen, Netzkino „Fehlgeschlagen: <Grund>“; Wiederholen in der Netzkino-Kachel → „Vorgemerkt“; freie Titel „⬇ Offline speichern (30 Tage)“; keine JavaScript-Fehler.
- **Nicht geprüft:** echte Downloads von Pluto TV und JustWatch TV (kein Anbieterzugang in der Testumgebung). Was bei Björn „nicht sauber“ lief, ist ohne Fehlermeldung/Diagnose offen.

## 0.5.46 – Katalogfehler mit Ursache (12. November 2026)

- Neue Tests `tests/test_v0546_network_cause.py` (6): Ursachen unterschieden (DNS, Zertifikat, Zeitüberschreitung, abgelehnt, Proxy), keine Adressen in der Meldung, Pluto-/JustWatch-Meldung mit Ursache, Netzprüfung meldet Fehler ohne Ausnahme, Verdrahtung.
- Lokaler Lauf ohne Anbieterzugang: Abruf aller drei Kataloge → „… nicht erreichbar – <Ursache>“, gespeicherter Bestand bleibt.
- **Nicht geprüft / Ursache offen:** Warum die Abrufe auf Björns Mac scheitern; dafür Diagnose-Export aus 0.5.46 nötig.

## 0.5.45 – Serienseiten mit allen Folgen (12. November 2026)

- Neue Tests `tests/test_v0545_series_pages.py` (8): Pluto-Serienmodell mit sortierten Folgen (S1E1, S1E2, S2E1) und Serienbild als Ersatz, gleiche Folgenfelder für alle Anbieter, Netzkino-Serien-ID für Folge und Gruppe identisch, unbekannte Netzkino-Serie abgelehnt, Downloadstatus für mehrere Folgen-IDs, Verdrahtung (Reiter, Katalog, Netzkino-Reiter, Server).
- Browser-Durchlauf (Playwright, Testbestand): Pluto „Folgen anzeigen“ → Serienseite mit Reitern „Alle · 3 / Staffel 1 · 2 / Staffel 2 · 1“, Reiterwechsel filtert; JustWatch-Serie mit „Beim Anbieter ansehen“ für nicht freigegebene Folge; Netzkino-Serie „Acapulco H.E.A.T.“ mit 20 Folgen → Folge → „Zur Serie“ → zurück; „Zurück zur Plattform“; keine JavaScript-Fehler.
- **Nicht geprüft:** echte Pluto-/JustWatch-Serien live (kein Zugriff aus der Testumgebung).

## 0.5.44 – IMDb-Zuordnung mit Erscheinungsjahr (12. November 2026)

- Neue Tests `tests/test_v0543_reference_year.py` (7): Björns „#Roxy“-Fall mit den sechs IMDb-IDs aus dem Screenshot → genau tt5646082 (2018), ±1 Jahr kein Widerspruch, zwei Treffer gleichen Jahres bleiben „zu prüfen“, ±1 schlägt „ohne Jahr“, ohne Plattformjahr unverändert, alte „zu prüfen“-Berichte werden erneut eingeplant (auch per SQL-Auswahl).
- Volllauf `python3 -m unittest discover -s tests` → 608 Tests OK (nach Neubau des Bundles); alle `tests/*.cjs` OK.
- **Nicht geprüft:** Neuabgleich mit Björns echtem Bestand (IMDb-Datensatz liegt nur auf seinem Mac).

## 0.5.43 – Dateinamen mit Auflösung und Codecs (12. November 2026)

- `tests/test_v0542_portal_title.py` um 4 Tests erweitert (11): Qualitätskennung (1080p/Cinemascope/720p/540p/2160p, Codecnamen), geplante und gemessene Namen für Film und Folge, Erkennung vorhandener Dateien (neues und altes Schema), Bilder mit Punkt im Titel („Mr. Robot“), Ablauf löscht -poster/-backdrop und den leeren Ordner, Bild-Hosts von Pluto/Netzkino.
- Bestehende Ende-zu-Ende-Downloads (echtes ffmpeg: Mediathek-MP4, Netzkino, Pluto-HLS, JustWatch-HLS) auf das neue Schema umgestellt und grün, z. B. `Test & Film - (2020) - 64p - MPEG4.mkv` mit `.nfo` und `.metadata.json`; MeshSync sieht vor der Veröffentlichung weiterhin nur `.partial`.
- Neue Tests `tests/test_v0543_download_queue.py` (5): Doppelungen bereinigen (Björns Fall: zweimal „006 am Wolfgangsee“), Erneut versuchen behält den Auftrag, Entfernen nur für erfolglose Aufträge, neuer Portal-Auftrag ersetzt fehlgeschlagenen, Pluto-Laufzeit ohne Werbung und 85-%-Toleranz.
- Browser-Durchlauf mit gebautem Bundle: zwei Aufträge für „006 am Wolfgangsee“ (unterbrochen + Fehler) → nach dem Start nur noch eine Karte (Ereignis `download_queue_deduplicated`), „Aus Liste entfernen“ löscht sie; keine JavaScript-Fehler.
- Volllauf `python3 -m unittest discover -s tests` → 601 Tests OK (nach Neubau des Bundles); alle `tests/*.cjs` OK.
- **Nicht geprüft:** echte Downloads auf Björns Mac; Darstellung in Kodi/Jellyfin.

## 0.5.42 – Titelseite für alle Plattformen, Netzkino-Download (12. November 2026)

- Neue Tests `tests/test_v0542_portal_title.py` (7): Leerzeichen in Netzkino-Adressen (auch über den ytdl-Resolver, Request-Zeile ohne Leerzeichen, vorhandene %-Kodierung bleibt), gleiche Modellfelder für Pluto und JustWatch mit getrennten Anbieterangaben, JustWatch-Titel ohne externen Stream (kein Player/Offline, offizielle Seite), Ablehnung unbekannter Quellen/Kennungen, Einbindung (keine alten Dialoge mehr, alle Wege öffnen die Titelseite).
- Browser-Durchlauf (Playwright/Chromium, eingespielter Bestand): Katalog → JustWatch-Serie → Titelseite mit Folgen, Werkzuordnung, Anbieterangaben, „Zurück zum Katalog“; Plattformen → Pluto-Film → gleiche Titelseite mit Abspielen/Offline, „Zurück zur Plattform“ landet wieder im Pluto-Reiter; JustWatch-Reiter → Serie → gleiche Seite; Netzkino → Titelseite (Detailabruf in der Cloud gesperrt → gespeicherte Angaben). Keine JavaScript-Fehler (nur gesperrte Bildadressen in der Cloud).
- Volllauf `python3 -m unittest discover -s tests` → 592 Tests OK (nach Neubau des Bundles); alle `tests/*.cjs` OK.
- **Nicht geprüft:** echter Netzkino-Download auf Björns Mac (CDN aus der Cloud gesperrt); Darstellung mit echten Covern.

## 0.5.41 – Kataloge nach Neustart (12. November 2026)

- Neustart-Test: Server mit eingespieltem Bestand zweimal gestartet und beendet; `/api/pluto`, `/api/justwatch`, `/api/netzkino-grouped` liefern jeweils denselben Bestand (1 / 2 / 420 Filme), ohne neuen Abruf.
- Neue Tests `tests/test_v0541_catalog_persistence.py` (5): unterbrochener Abruf → „interrupted“ mit erhaltenem Bestand (JustWatch, Pluto), Teilabruf blendet ältere Titel nicht aus, Regel für den einmaligen Erstabruf, UI-Texte.
- Tests ergänzt auf 7: Anfrage-Messung (laufend/langsam, keine Suchbegriffe, Protokoll-Drosselung, Streams ausgenommen) und Einbindung in Server/Oberfläche/Bundle.
- Browser-Durchlauf (Playwright/Chromium, eingespielter Bestand): Plattform-Reiter Pluto/JustWatch/Netzkino zeigen Bestand und Stand; künstlich um 9 s verzögerte Pluto-Antwort → Statuszeile „wartet seit 6 s auf den lokalen Dienst · noch offen: pluto 6 s“, danach regulärer Stand. Katalog: Pluto/JustWatch je eigene Karte ohne ARD/ZDF-Übersicht, „Gesamt“ mit allen Karten und ARD/ZDF-Übersicht, „Mediatheken“ nur ARD/ZDF; keine JavaScript-Fehler.
- Volllauf `python3 -m unittest discover -s tests` → 585 Tests OK; alle `tests/*.cjs` OK.
- **Nicht geprüft:** auf Björns Mac/NAS; die eigentliche Ursache des Hängens bei Björn ist nicht nachgestellt (mit eingespieltem Bestand antworten alle Endpunkte in unter 0,1 s) – die neue Wartezeit-Anzeige und der Diagnose-Abschnitt `http` sollen sie beim nächsten Auftreten zeigen.

## 0.5.40 – JustWatch TV (12. November 2026)

- Parser gegen Björns echten HAR-Mitschnitt geprüft (GetPopularTitles-Antwort): 22 von 40 Titeln als JustWatch-TV-Free erkannt (die übrigen gehörten zu Plus/Store), 1 mit Stream für externe Player, Cover- und Seitenadressen gültig.
- Neue Tests `tests/test_v0540_justwatch.py` (20, Antworten im HAR-Format): nur Paket `jwt`, Paging per Cursor, Kategorien/Bewertung/Großes Kino, Bestandsschutz bei Fehlern, GraphQL-Fehlermeldung, Folgen nur von JustWatch TV, Adressprüfung (fremde Hosts, http, Benutzerdaten), frische Stream-Adresse mit DRM-Prüfung, Ablehnung kopiergeschützter Streams (auch in der Varianten-Playlist), Titel ohne externen Stream, Offline-Auftrag (Benennung, 30 Tage, IMDb-ID in der NFO, keine Stream-Adresse im Auftrag), **echter HLS-Download mit ffmpeg** gegen lokalen Server, Referenzabgleich über die gemeinsame Engine, Server-/UI-/Bundle-Einbindung.
- Browser-Durchlauf (Playwright/Chromium) mit eingespieltem JustWatch-Katalog: Katalogquelle „JustWatch TV“ mit Kategorien und „Großes Kino“-Abzeichen, Dashboard-Karte, Plattform-Reiter mit Kategorien, „▶ Ansehen“/„⬇ Offline speichern (30 Tage)“ nur bei freigegebenen Titeln, sonst „Bei JustWatch ansehen“, Detailansicht, Serie → Folgen, Player und Download-Worker melden in der Cloud korrekt „JustWatch ist nicht erreichbar“; Pluto-Reiter funktioniert unverändert über das gemeinsame Panel; keine JavaScript-Fehler.
- Volllauf `python3 -m unittest discover -s tests` → 578 Tests OK.
- **Nicht geprüft:** echte Abfragen an apis.justwatch.com (aus der Build-Umgebung gesperrt) – insbesondere ob JustWatch die schlanken MediathekAtlas-Abfragen genauso beantwortet wie die der Website; ob die externen Streams Werbung/Kopierschutz enthalten (im HAR wurde keine Wiedergabe mitgeschnitten); Lauf auf macOS/NAS.

## 0.5.39 – Mediathek-Genres und Entdecken im Katalog (12. November 2026)

- Neue Tests `tests/test_v0539_catalog_genres.py` (5): Schwellen für Großes Kino/Serienfavoriten identisch zum Mediathek-Katalog (7,5; 10.000 IMDb / 1.000 TMDB), Filter `collection` für Pluto und Netzkino, UI-Einbindung, bestehender Smoke-Test des gemeinsamen Katalogs.
- Browser-Durchlauf (Playwright/Chromium) mit eingespielten Mediathek-Werken (2 Serien, 3 Filme mit Genres und Bewertungen) sowie Netzkino-/Pluto-Bestand: Genre-Leiste Serien „Drama · 1, Krimi · 2“, Filme inkl. „Unbekannt“, Filter „Komödie“, „Serienfavoriten“ → nur Babylon Berlin, „Großes Kino“ → nur Das Boot, Abzeichen und ★ auf den Karten, „Gesamt“ summiert die Kategorien aller Quellen; keine JavaScript-Fehler (nur in der Cloud gesperrte Coverbilder).
- **Nicht geprüft:** mit Björns echtem Mediathek-Bestand.

## 0.5.38 – Kategorien, Pluto-Details, Download-Metadaten (12. November 2026)

- Neue Tests `tests/test_v0538_portal_categories.py` (10): Genre-Vereinheitlichung (Referenz vor Anbieter, „Unbekannt“), Kategorien-Zähler und Filter, Bewertung nur aus gültiger Referenz, Download-Metadaten wie ARD (NFO mit `uniqueid imdb`, Genres, Besetzung, Bewertung; mehrdeutige Treffer ohne ID; Seriensynopsis nicht als Folgeninhalt), Pluto-Abgleich über die Anbieterkette (Folge → Serie), Verwerfen bei Titeländerung, Netzkino-Katalog mit Referenzkategorien und Bewertungs-Sortierung, Server-/UI-Einbindung, 30 Tage.
- Browser-Durchlauf (Playwright/Chromium) mit eingespieltem Pluto-Katalog, einer Pluto- und einer Netzkino-Referenz: Katalog → „Pluto TV“ und „Gesamt“, Plattformübersicht mit Netzkino-/Pluto-Karten, Pluto-Kategorienleiste und Filter, Detailansicht Film und Serie → Folgen, Netzkino-Kategorien (21 Genres aus dem HAR-Bestand); keine JavaScript-Fehler (nur in der Cloud gesperrte Coverbilder).
- `node --check web/*.js`, `node tests/*.cjs` OK. Volllauf `python3 -m unittest discover -s tests` → 553 Tests OK.
- **Nicht geprüft:** Abgleich mit echten IMDb/TVDB/TMDB-Zugängen für Pluto-/Netzkino-Titel (Anbieterkette in Tests simuliert), Pluto live.

## 0.5.37 – Pluto TV offline, 20 Tage (12. November 2026)

- Neue Tests `tests/test_v0537_pluto_offline.py` (12): Benennung identisch zu `core.target` (Film und Folge), 20-Tage-Frist, Ablauf und erneutes Speichern, „Jetzt löschen“, getrennte Netzkino-/Pluto-Listen, Ablehnung von Live-Sendern, ganzen Serien und unbekannten Kennungen, keine Stream-Adresse/Sitzungsschlüssel im Auftrag, Resolver mit frischer Sitzung, **echter HLS-Download mit ffmpeg** gegen einen lokalen HTTP-Server (MKV mit Video+Audio, NFO, metadata.json ohne Schlüssel, keine `.partial`-Reste), Abbruch beendet ffmpeg, zu kurzer Stream wird als unvollständig gemeldet.
- Browser-Durchlauf (Playwright/Chromium) mit eingespieltem Katalog und laufendem Worker: „⬇ Offline speichern (20 Tage)“ nur bei Filmen und Folgen, nicht bei Live-Sendern und Serien; Auftrag erscheint in „Offline-Kopien von Pluto TV“; der Worker meldet in der Cloud korrekt „Pluto TV ist nicht erreichbar“ und bietet „Erneut versuchen“; keine JavaScript-Fehler.
- `node --check web/*.js`, `node tests/*.cjs` OK. Volllauf `python3 -m unittest discover -s tests` → 543 Tests OK (nach Neubau des App-Bundles).
- **Nicht geprüft:** echter Download von pluto.tv (aus der Build-Umgebung gesperrt), Verhalten des Pluto-Stitchers mit Werbeunterbrechungen in ffmpeg, Lauf auf macOS/NAS-Hardware.

## 0.5.36 – Pluto TV (12. November 2026)

- Neue Tests `tests/test_v0536_pluto.py` (8): Sitzung mit Installations-ID, Filme/Serien/Live aus synthetischen Antworten im Format der Pluto-Website-API, Rotation und Bestandsschutz bei Fehlern, Folgen auf Abruf mit Zwischenspeicher, Stitcher-Adresse mit Sitzung, Ablehnung fremder Hosts/Pfade, Einbindung in `/api/play`.
- Browser-Durchlauf (Playwright/Chromium) mit eingespieltem Katalog: Reiter Pluto TV, Filme, Serie → Folgen, Live-TV, „▶ Live ansehen“ öffnet den Player (meldet in der Cloud korrekt „Pluto TV ist nicht erreichbar“), Wechsel zu Netzkino blendet Pluto aus; keine JavaScript-Fehler.
- Volllauf `python3 -m unittest discover -s tests` → 531 Tests OK.
- **Nicht geprüft:** echter Abruf von pluto.tv (aus der Build-Umgebung gesperrt). Die API-Formate folgen der öffentlichen Pluto-Website und sind tolerant ausgewertet, aber nicht live bestätigt.

## 0.5.35 – Netzkino-Kategoriebaum (12. November 2026)

- `python3 -m unittest discover -s tests` → 522 Tests OK. `test_launcher_with_python_outside_standard_paths` brach im Volllauf einmal mit einem Zeitlimit ab und läuft einzeln grün (bekannte Lastabhängigkeit). Neu: Kategorien aus Filmdetails werden gemerkt und beim nächsten Abgleich vollständig geladen (150 Titel aus einer Kategorie).
- Abgleich gegen die echten Antworten aus Björns Mitschnitt (lokal ausgewertet, nicht ins Repository übernommen): Kategorie-Struktur, `CmsCategory.parent` und unbegrenzte Kategorielisten (214 Titel) werden erkannt; aus 3 Filmdetails ergeben sich 30 Kategorien.
- **Nicht geprüft:** Abgleich gegen die Live-API (aus der Build-Umgebung gesperrt), insbesondere ob `AllContent` für die Baumwurzeln Unterkategorien liefert.

## 0.5.34 – Netzkino-Wiedergabe und Katalogerweiterung (12. November 2026)

- Ausgeführt (Linux, Python 3.13): `python3 -m unittest discover -s tests` → 521 Tests, alle grün nach Neubau des App-Bundles. Neu: 8 Wiedergabetests (Direktwiedergabe der MP4, Offlinekopie hat Vorrang, Zwischenspeicher fürs Spulen, ungültige Kennungen, DRM-Meldung über ytdl-nightly, ffmpeg-Fallback) und 6 Katalogtests (Kategorie-Entdeckung mit Obergrenze, Seitenhinweise, Titel aus Filmdetails, HAR-Import nur von netzkino.de, Diagnoseexport).
- `node --check web/*.js`, `node tests/*.cjs` OK. Browser-Durchlauf (Playwright/Chromium): Netzkino → „▶ In MediathekAtlas ansehen“ öffnet den App-Player und meldet in der Cloud-Umgebung korrekt „Netzkino ist nicht erreichbar“; HAR-Import einer Testdatei übernimmt den Titel, ignoriert fremde Hosts, keine JavaScript-Fehler.
- Netzkino-Sitemaps am 12.11.2026 geprüft: `/sitemap.xml` liefert die HTML-Startseite, `/api/sitemap` 4 Infoseiten ohne Filme.
- **Nicht geprüft:** echte Netzkino-Wiedergabe und Kategorie-Entdeckung gegen die Live-API (aus der Build-Umgebung gesperrt), Wiedergabe auf macOS/NAS-Hardware.

## 0.5.32 – Netzkino offline und Integrationsstand (11. November 2026)

- Ausgeführt (Linux, Python 3.13): `python3 -m unittest discover -s tests` → 499 Tests OK (1 übersprungen), darunter 16 neue Netzkino-Offline-Tests (ytdl-nightly-Import, Extraktor gegen synthetische Next.js-Seite, DRM/HLS-Ablehnung, Benennung identisch zu `core.target`, Ende-zu-Ende-Download mit echtem FFmpeg-Remux, 30-Tage-Ablauf, Schutz fremder Dateien, Altauftrags-Übernahme, NAS-Dateirechte) und 29 aus dem Integrationspaket übernommene Netzkino-Tests.
- UI-Smoke-Tests (`node tests/*.cjs`) und `node --check web/*.js` OK; Browser-Durchlauf (Playwright/Chromium) Detailfenster → Offline herunterladen → Auftrag sichtbar, ohne JavaScript-Fehler.
- QNAP-Dienstlebenszyklus-Test (`test_qdk_project_and_service_lifecycle`) wieder grün; war im 0.5.31.11-Integrationsstand rot (Dateirechte 0600).
- **Nicht geprüft:** echter Netzkino-Abruf (netzkino.de aus der Build-Umgebung nicht erreichbar), Wiedergabe auf macOS, Installation auf Synology/QNAP-Hardware.

## 0.5.25.1 – Release-Kandidatenprüfung (10. November 2026)

- `tests/test_meshpeer.py`: Konfiguration der Verbundpartner sowie bewusst rotierte Schlüssel, Ablehnung alter Schlüssel, bestehende Partnerschaften und Reconnect.
- `tests/test_imdb_archive.py`: Wiederaufnahme ab vorhandenem Byte-Offset, Zeitüberschreitung/Wiederholung, lokale Archiv-Downloads nach Neustart.
- Vollständige CI-Matrix mit Python 3.9/3.13/3.14 und macOS; NAS-Pakete in Actions. Nur grüne Hauptbranch-Builds für Installation verwenden.
- Praxistest: Synology und QNAP teilen ihre Codes, Mac fügt je einen hinzu; bei HTTP 403 die gespeicherte NAS-Adresse gegen den tatsächlichen Dienstport und die aktuelle Freigabe prüfen.
- IMDb: prüfe DNS/TLS und ausreichend freien Speicher auf dem Gerät; ein fehlgeschlagener Download belegt keine fiktiven Archivdatensätze.



## 0.5.25 – Worker-Pool und geplante Download-Abos (9. November 2026)

- `tests/test_v0525.py`: eindeutige SQLite-Auftragsreservierung, parallele Claims, Laufzeitende und Wiederaufnahme nach Absturz, Nutzerzustimmung, nur bestätigte Serienepisoden, Film-Abo bei Verfügbarkeit, wöchentlicher Check einschließlich 48-Stunden-Nachprüffenster, abgelaufene Angebote, Mehrfachdownloads und Persistenz über Neustarts.
- Der Worker-Pool zeigt die tatsächliche Parallelität; externe Anbieterabfragen dürfen gleichzeitig höchstens zweimal laufen.
- Ein Abo aktualisiert keine Quellen außerhalb des offiziellen Katalogimports und kann keine HLS/DASH- oder DRM-Streams herunterladen. Nur reguläre, rechtmäßig zugängliche Direktdateien.
- Alle Downloadjobs nutzen die bestehende Warteschlange; Benutzeraktionen (Pause/Fortsetzen/Löschen) wirken ausschließlich auf den Aboplan, nicht auf bereits erstellte Jobs.
- Vor stabiler Freigabe den Netto-Durchsatz und die 429-/SQLite-Fehlerraten mit dem vorherigen Diagnoseexport messen.



## 0.5.24 – Nachrichtenformat-Schnellpfad und Filmpriorität (9. November 2026)

- `tests/test_v0524.py` deckt eindeutige Nachrichtenformate, frühzeitige API-Umgehung, Film-/Serien-Titelkonflikte, ausdrücklich angeforderte Werkprüfungen, manuelle und verifizierte Episoden, bestehende Serie-mit-Nachrichtenbeiträgen, Filmhinweise und wiederaufnehmbaren Index-Backfill ab.
- Der Status „Sendungsbeitrag“ zählt nicht als abgeschlossene Metadatenanfrage oder als Erstprüfungsdurchsatz.
- Der Filmhinweis-Index dient ausschließlich der Sortierung, nicht der automatischen Bestätigung. Varianten ohne eindeutige Filmbelege bleiben unverändert.
- Katalogzählungen nach gruppiertem SQL werden gegen kleine deterministische Datensätze geprüft; für ~700.000 Angebote muss der nächste reale Diagnoseexport einen Vorher-/Nachher-Vergleich liefern.
- Regressionen: Python 3.9, 3.13, 3.14 und macOS; SPK/QPKG-Builds und Payload-Integrität über CI. Keine GitHub-Zusammenführung nach `main` ohne Freigabe.



## 0.5.23 · Status-Dashboard und resiliente lokale Downloadverwaltung (8. November 2026)

- Build 47: `tests/test_v0523_imdb_manifest.py` prüft persistierte Zeilenzahlen und Übernahmezeitpunkte aller sieben IMDb-Datensätze, Neustart, fehlgeschlagenes Update ohne Datenverlust und alte Snapshot-Datenbanken ohne erweitertes Metadatenfeld.
- IMDb-Status unterscheidet den letzten erfolgreichen Archivaufbau vom letzten Updateversuch und zeigt keine erfundenen historischen Einzelzeitstempel.
- Die Datenübersicht bleibt in der Katalogansicht zunächst eingeklappt, damit das verdichtete Dashboard nicht unnötig Höhe belegt.

- Build 46: Responsives CSS mit Container-Queries, acht Kennzahlen-Spalten bei Inhaltsbreiten ab 1320px, vier im mittleren und zwei im schmalen Fenster; keine festen Mindesthöhen. Anbieter-Status passt sich an den Platz an.

- `tests/test_v0523.py`: Datei umbenannt/verschoben, Ordner vorübergehend getrennt, Dateipfad wieder verknüpfen und Downloadhistorie beibehalten.
- Sicherheitsprüfungen: kein Datei-Zugriff außerhalb explizit erlaubter Bibliotheksordner; Symlink-Ausbruch verweigert; unerwartete Dateigröße blockiert; mehrdeutige Suchtreffer werden nicht automatisch verknüpft.
- Serverseitiger Dateistatus wird separat von dem dauerhaft gespeicherten Downloadauftrag geführt; fehlende Datei löscht keine Werkzuordnung.
- Statische JS-Syntaxprüfung und responsive HTML/CSS-Einbindung; alle Plattformtests und macOS/SPK/QPKG-Paketinhalt über GitHub CI.
- Feldtest: Benutzer verschiebt einen fertigen Film in einen anderen Bibliotheksordner und verknüpft ihn über die Downloads-Karte erneut. Der Status darf zu keinem Zeitpunkt den Katalog- oder Downloadbereich blockieren.



## 0.5.22 · Intelligenter Scheduler, Serienfokus und sichere Angebotsgruppen (8. November 2026)

- `tests/test_v0522.py` verifiziert Filme-zuerst/Serien-zuerst, Vorrang manueller Prüfaufträge, Erstprüfungen vor Wiederholungen, begrenzten Serienfokus und Netto-Erstprüfungsrate.
- Verifizierte Nichttreffer bleiben über einen Neustart erhalten. Ein anderer API-Schlüssel, ein anderes Produktionsjahr und ein manueller Refresh dürfen einen Nichttreffer nicht blind wiederverwenden. Fehler/Timeouts werden nicht negativ zwischengespeichert.
- Zwei Angebote mit exakt denselben Medien-URLs und Fassungsdaten erscheinen gemeinsam, ohne Angebote aus der Datenbank zu entfernen. Unterschiede bei Audiodeskription und signierten URL-Parametern verhindern Gruppierung.
- Die Serien-Detailansicht löst keine Massen-Neuabfrage beim Öffnen aus. Der Benutzerknopf bleibt erhalten.
- Ältere Tests zu Nichttreffern/Retry-Zeiten aktualisiert. Kompatibilitätsprüfungen für Python 3.9/3.13 und NAS-/macOS-Build via CI.
- Die tatsächliche Durchsatzsteigerung und Prognosegenauigkeit müssen mit einem vergleichbaren Nutzerdiagnoseexport geprüft werden.



## 0.5.21 · Sicheres Zusammenführen doppelter Filme (7. November 2026)

- `tests/test_v0521.py`: „Der Rausch“ wird bei unabhängigen verifizierten Quellen, identischem Jahr und passender Laufzeit zu einem Film mit beiden Genres. Sämtliche Senderangebote bleiben erhalten.
- Negativfälle: verschiedene Produktionsjahre, unterschiedliche IDs vom selben Anbieter, unvereinbare Laufzeiten oder nur vorläufig erkannte Titel werden nicht automatisch zusammengeführt.
- Manuell gepflegte Genres und gespeicherte Downloadverweise bleiben erhalten; beide manuell gepflegten Datensätze werden nicht ohne ausdrückliche Auswahl verschmolzen.
- Legacy-Dubletten werden transaktionsweise und mit persistiertem Cursor geprüft; der Nachlauf ist idempotent.
- GitHub CI führt Linux/macOS-Regressionen und NAS-Paketvalidierung aus. Performance auf dem vollständigen Nutzerkatalog muss im nächsten Diagnoseexport verglichen werden.



## 0.5.20 · Inkrementelles Archiv, Serienvorlage, Verfügbarkeit (7. November 2026)

- `tests/test_v0520.py`: Unveränderte Angebote werden nicht neu geschrieben; Neu-/Änderungs-/Reaktivierungs-/Entfallzähler sind korrekt; alte Angebote bleiben nach unvollständigem Import aktiv.
- Klassifizierung wird nur für neue/geänderte Werke wieder geöffnet; eine abgeschlossene vollständige Erstklassifizierung bleibt abgeschlossen.
- Serienidentität wird nur von einer eindeutigen und zum Sendungsthema passenden Vorlage übernommen; Staffel-/Folgenachweise werden nicht von einer anderen Episode kopiert.
- ARD-/ZDF-Daten werden ausschließlich bei ausdrücklichen Ablaufdatumsfeldern verwendet; Sendedatum und API-Token-Lebenszeit dürfen nicht als Ablaufdatum erscheinen.
- Verfügbarkeit ist angebotsbezogen und wird im Download-Dialog erst bei Bedarf abgefragt; bei unbekanntem Ablaufdatum klare Kennzeichnung.
- CI: Python 3.9/3.13 Linux, macOS 3.13 und SPK/QPKG-Build; echte Performance-Benchmarks folgen.



## 0.5.19 · Offline-Suche und früher Abschluss sicherer Zuordnungen (7. November 2026)

- `tests/test_v0519.py`: Hohe Konfidenz trotz fehlender Genres nur bei bestätigter IMDb-Laufzeit bzw. IMDb-Episode; negative Fälle und Konflikte bleiben unbestätigt.
- Staffel-/Folgenummer als Episodenbeleg: nur vollständig gescannte Anbieterlisten, eindeutige Staffel+Folge, keine automatische Bestätigung bei doppelten oder unvollständigen Ergebnissen. IMDb Offline kann eine eindeutig nummerierte Episode auch ohne passenden Episodentitel nachweisen.
- Der Diagnoseexport zeigt SQLite-Verbindungsöffnungen sowie Query-/Credits-Cache-Hits und -Misses, damit sich die Optimierung im Feld messen lässt.
- IMDb-Verbindungen bleiben pro Worker schreibgeschützt und werden nach atomarem Austausch automatisch geschlossen und neu geöffnet. Zwischengespeicherte SQL-Zeilen dürfen keine Laufzeit-/Episodenentscheidungen anderer Werke übernehmen.
- Test für frühzeitigen Abbruch eines Downloads bei zu wenig freiem Speicher. Vorhandene Teildateien und das bisherige Archiv sollen unangetastet bleiben.
- Warteschlangenregression: Vor dem Neustart `queued` bleibt `queued`, in Arbeit befindliche `downloading`/`tagging` werden `interrupted`; terminale Zustände bleiben bestehen.
- Gesamttest, Paketbuild und Tests auf realer Hardware: noch durch CI bzw. Installation zu prüfen.


## 0.5.18 · Wiedergabe im Browser (6. November 2026, Linux-Testumgebung)

- Neuer Test `test_streaming`: Quellenwahl (lokaler Download vor Online-Stream, MP4 vor HLS, höchstens 1080p, DASH und Nicht-HTTP-Adressen abgelehnt, unfertige Jobs abgelehnt, Suchergebnisse aus `records`), Abspielart je Video-/Audiocodec, ffmpeg-Aufruf (Suchen vor `-i`, Reconnect, ADTS→ASC). Endpunkt-Test mit echtem Server und ffmpeg: H.264/MP2-MKV wird ab Sekunde 2 als fragmentiertes MP4 mit H.264/AAC geliefert, falsches Token → 403.
- Manuell mit lokalem HLS-Server (ffmpeg 6.1): Stream ab 8 s liefert 12 s Restlaufzeit. Ohne `aac_adtstoasc` brach ffmpeg 6.1 nach 0,3 s ab, ohne Ausgabe-Start 0 lief die Uhr eine HLS-Segmentlänge vor; beides behoben.
- Chromium (Playwright): Katalog „▶ Serie abspielen“ startet S01E01 mit „Nächste Folge ▸ S01E02“; Download-Karte spielt die MKV-Datei; mit abgeschaltetem nativem HLS läuft der umgewandelte Stream, Springen auf 0:12 zeigt im Bild Sekunde 14 bei Anzeige 0:14, am Ende startet automatisch S01E02. Danach keine ffmpeg-Prozesse übrig, keine JavaScript-Fehler.
- Nicht getestet: Safari/iOS, Firefox, echte Sender-CDNs (Geosperren), Wiedergabe auf NAS-Hardware.

## 0.5.17 · Titelseiten für Serien und Filme (6. November 2026, Linux-Testumgebung)

- Feldbefund: Beim Öffnen einer Serie fehlten Titelbild und Beschreibung; es erschien nur das Folgenraster. Ursache: Die Serienbeschreibung wurde beim Folgenabgleich durch die Folgenhandlung ersetzt, und „Serie öffnen“ filterte lediglich den Katalog.
- Neue Tests `tests/test_title_view.py`: Staffeln und Reihenfolge, Seriendaten aus der besten Folge statt Folgenhandlung, Sendereihen-Text als Rückfall, unbekannte und archivierte Serien, Weitergabe der Serienbeschreibung, Bildabgleich überschreibt vorhandene Beschreibung nicht. Gesamtlauf bestanden.
- Chromium mit befülltem Testkatalog (Serie mit 2 Staffeln/12 Folgen, Folge mit 3 Fassungen inkl. Audiodeskription; Film mit 4 Fassungen; Serie ohne Metadaten), 1440 px und 420 px Breite, jeweils ohne und mit simuliertem Player (`playMedia`): Staffel-Reiter, Fassungsauswahl, Abspielaufrufe mit der gewählten Fassung, Zurück per Knopf und Browser. Keine JavaScript-Fehler. Bilder im Test lokal ersetzt, kein Abruf echter TMDB-Bilder.

## 0.5.16 · Diagnose vom 6. November (6. November 2026, Linux-Testumgebung)

- Feldbefund (Mac, 0.5.15, 06:07–08:20 UTC): 4.844 Prüfungen, davon 3.215 Ausgaben „Schleswig-Holstein Magazin“ (je eine ARD-Abfrage, Ergebnis unverändert). Von den übrigen 1.629 Prüfungen 82 % „Wiederholung“ (OMDb pausiert), 18 % „zu prüfen“, 0,4 % erkannt. Wikidata 5× „Antwort zu groß“, IMDb-Aktualisierung 2× abgebrochen (unter 512 MiB frei, Zeitüberschreitung bei 334/521 MB). Direktverbindung: einzige Gegenstelle lehnt ab, beide NAS seit rund 7 Tagen ohne Lebenszeichen.
- Neue Tests `test_v0516.py`: Magazin-Ausgaben mit Mediathek-Daten → Sendungsbeitrag, Serie ohne Formatwort bleibt erkannt, Nachsortierung läuft genau einmal; Titelzusätze entfernt; arte-Rubrik nicht als Serie, Reihentitel abgefragt; OMDb-Pause ohne Wiederholung nach IMDb-Offline-Prüfung; zu große Wikidata-Antwort ist kein Fehler; IMDb-Download setzt per Range fort, Rückzug 1 h → 2 h.

## 0.5.15 · Mehrere Direktverbindungen (29. Oktober 2026, Linux-Testumgebung)

- Feldbefund: Codes auf allen Systemen eingefügt, jede Eingabe ersetzte Verbindung und eigenen Schlüssel.
- Neuer Test `SeveralConnectionsTests`: zwei NAS-Server (Synology, QNAP) geben frei und verbinden sich gegenseitig, eigener Code wird abgelehnt, eigener Freigabeschlüssel bleibt gültig, Mac-Journal gleicht mit beiden ab und erreicht beide, Entfernen und Freigabe beenden wirken getrennt; alte Einzelverbindung (0.5.5–0.5.14) wird weiter gelesen.
- Chromium NAS-Modus mit zwei Servern: eigener Code → Fehlermeldung, fremder Code → Statuszeile „Verbunden mit …“ samt „Entfernen“, Entfernen leert die Liste; keine JavaScript-Fehler. Alle Tests bestanden.

## 0.5.14 · Direktverbindung Desktop (29. Oktober 2026, Linux-Testumgebung)

- Chromium Desktop-Modus: „Dieses System freigeben“ ausgeblendet, Hinweis sichtbar; Verbinden auf geschlossenen Port zeigt die neue Erklärung; keine JavaScript-Fehler. Server lehnt Freigabe im Desktop-Modus ab. Alle Tests bestanden.

## 0.5.13 · QNAP ohne nohup (29. Oktober 2026, Linux-Testumgebung)

- Feldbefund aus `MediathekAtlas-Startproblem.txt` (QTS 5.2.11, TS-932X, ARM Cortex-A57, Python 3.11.4 unter `/opt/QPython311`): `nohup: command not found`.
- Neuer Test `MinimalShellTests`: Dienst startet mit einem PATH ohne `nohup` und antwortet; schlägt mit dem alten Skript fehl. Alle Tests bestanden.

## 0.5.12 · Startproblem-Hinweis (29. Oktober 2026, Linux-Testumgebung)

- Feldbefund QNAP 0.5.10: Installation erfolgreich, Port 8730 „Verbindung abgelehnt“, Dienst also nicht gestartet; Ursache noch unbekannt (Protokoll liegt im versteckten `.qpkg`-Ordner).
- Neuer Test `StartProblemNoteTests`: belegter Port → Start schlägt fehl, Hinweisdatei mit Grund im Download-Ordner; nächster Start erfolgreich und Datei entfernt. Alle Tests bestanden.

## 0.5.11 · Große Bestände im Verbund (29. Oktober 2026, Linux-Testumgebung)

- Feldbefund (Mac 0.5.9 ↔ Synology 0.5.9 über Tailscale): Bestandsabgleich lief (6.059 geteilt, 82.605 offen, 225 übernommen), danach „Gegenstelle nicht erreichbar (timed out)“, Lebenszeichen der NAS 8 Minuten alt. Vermutete Ursache: unbegrenzte Übernahmerunden (5.000 Ereignisse je Transaktion, Schleife bis leer) auf der NAS. Nicht abschließend bestätigt (Diagnose der NAS ausstehend).
- Neuer Test `test_large_backlog_is_imported_in_bounded_rounds`: Übernahme in Teilmengen, Status „importing“, nach mehreren Runden identische Zustände. Alle Tests bestanden.

## 0.5.10 · QPKG-Prüffeld (29. Oktober 2026, Linux-Testumgebung)

- Feldfehler QTS: „Failed to install MediathekAtlas_0.5.9.qpkg due to a file format error“. Ursache: `qpkg_encrypt` fehlte beim Build (`qbuild: qpkg_encrypt: command not found`), das Größen-Prüffeld 60 Byte vor Dateiende blieb leer. Betraf auch alle CI-Builds.
- Neue Funktion `build_nas.qpkg_checksum`; Ergebnis byte-gleich mit dem aus QDK `src/qpkg_encrypt.c` kompilierten Werkzeug. Neuer Test `QpkgChecksumTests`, CI prüft das Feld. Paketinhalt (46 Dateien) kontrolliert. Alle Tests bestanden.
- Nicht geprüft: Installation auf echter QNAP.

## 0.5.9 · Bestand im Verbund teilen (29. Oktober 2026, Linux-Testumgebung)

- Neuer Test `test_results_from_before_joining_are_shared`: System A erkennt 30 Werke ohne Verbund (eins davon manuell), tritt danach bei; System B übernimmt alle 30 ohne eigene Anbieterabfrage, Zustände identisch, die manuelle Zuordnung bleibt manuell; zweiter Durchlauf teilt nichts doppelt, übernommene Ergebnisse werden nicht zurückgespiegelt. Alle automatisierten Tests bestanden.
- Werk-IDs vor der Zusammenführung werden aus den Angeboten neu berechnet (`catalog.origin_ids`, gleiche Logik wie beim Import, jetzt gemeinsame Funktion `origin_meta`).

## 0.5.8 · Katalogkarten mit mehreren Fassungen (29. Oktober 2026, Linux-Testumgebung)

- Ursache: In 0.5.3 landete die Zeile für den Aufklappzustand der Download-Karten in der Katalogkarte („Weitere Fassungen“), dort gibt es kein `j`. Die vorherigen Browserprüfungen liefen mit leerem Katalog bzw. ohne Mehrfachangebote.
- Chromium mit echtem Server und Katalog (ein Film in drei Fassungen, ein Film in einer): 4 Karten mit „Weitere Fassungen“, Serienansicht leer, keine JavaScript-Fehler. Alle automatisierten Tests bestanden.

## 0.5.7 · Fehlermeldungen Direktverbindung (29. Oktober 2026, Linux-Testumgebung)

- Ursache des Feldfehlers: `PeerError` ist ein `ValueError` und wurde beim Lesen des Index als „kein MediathekAtlas“ umetikettiert; jeder Netzwerk- oder Serverfehler sah deshalb gleich aus.
- Neuer Test `ErrorMessageTests`: 503 mit Grund, 403, fremde HTML-Antwort und nicht erreichbarer Port liefern je eine eigene Meldung. Alle Tests bestanden.

## 0.5.6 · Hinweise und Katalog-Wiederholung (29. Oktober 2026, Linux-Testumgebung)

- Alle automatisierten Tests bestanden.
- Chromium mit echtem Server und simulierten Katalogfehlern: zwei Fehler werden still wiederholt und der Katalog erscheint; „Einstellungen gespeichert“ verschwindet nach 7 s; dauerhafter Fehler bleibt mit Ursache und Schließen-Knopf stehen; keine JavaScript-Fehler.
- Ursache der gemeldeten Ladefehler auf dem NAS noch nicht bestätigt (Fehlertext bzw. Diagnose-ZIP ausstehend).

## 0.5.5 · Direktverbindung (29. Oktober 2026, Linux-Testumgebung)

- Alle automatisierten Tests bestanden, neu `tests/test_meshpeer.py`: Verbindungscode, Schreibregeln (eigenes Verzeichnis gesperrt, Segmente unveränderlich, ältere `node.json` ignoriert, Pfadangriffe abgelehnt), Abgleich gegen einen echten Server im NAS-Modus in beide Richtungen, zweiter Abgleich ohne Übertragung, falscher Schlüssel abgelehnt.
- Chromium mit zwei echten Serverprozessen (NAS-Modus mit Anmeldung und Desktop-Modus): auf dem NAS freigegeben, Code am „Mac“ eingefügt, beide sehen sich, Bereiche 128/128 verteilt, keine JavaScript-Fehler.
- Nicht geprüft: echte Verbindung Mac ↔ Synology über Tailscale.

## 0.5.4 · Python-Erkennung Synology (29. Oktober 2026, Linux-Testumgebung)

- SPK-INFO ohne `install_dep_packages`; `preinst` bricht ohne Python ≥ 3.9 mit Hinweis ab und akzeptiert ein Python aus einem beliebigen Paketordner (Test mit nachgebautem `python311`). Dienstskript sucht zusätzlich alle `/var/packages/*/target/...`-Pythons.
- Nicht geprüft: Installation im echten DSM-Paket-Zentrum.

## 0.5.3 · Genres, Download-Karten, Dateizugriff (29. Oktober 2026, Linux-Testumgebung)

- Alle automatisierten Tests bestanden (`python3 -m unittest discover -s tests`), neu `tests/test_v053.py`: Schreibvarianten aus dem Bildschirmfoto (Dokumentarfilm, Filmdrama, Filmkomödie, Kriminalfilm, Mysteryfilm, Liebesfilm, Biography, Familie) ergeben je ein Genre; einmalige Umstellung gespeicherter Genres, Werk-Metadaten und Serienvorlagen.
- Dateizugriff im NAS-Modus mit echtem Serverprozess: ohne Anmeldung 401, falscher Seiten-Token 403, nicht fertiger Download 404, vollständige Datei 200 mit UTF-8-Dateiname, Teilbereiche 206, ungültiger Bereich 416, verschobene Datei 404.
- Chromium (Desktop-Modus, 1500 px und 390 px): Downloads als Kartenraster, Details klappen auf und bleiben beim Aktualisieren offen, „Herunterladen“ liefert die Datei.
- Nicht geprüft: Download über den Browser von einer echten Synology/QNAP.

## 0.5.2 · Downloads im Verbund (29. Oktober 2026, Linux-Testumgebung)

- Alle automatisierten Tests bestanden (`python3 -m unittest discover -s tests`), darunter 6 neue Downloadtests in `tests/test_mesh.py`: Anspruch blockiert das andere System bis zur Freigabe, abgelaufener Anspruch blockiert nicht, geteilter Download wird erst bei vollständiger Datei als vorhanden gezählt, ungeteilter Download zählt ohne zu blockieren, `done` bleibt gegen späteren Anspruch und fremde Freigabe bestehen, Pfade mit `..` oder absolut werden abgelehnt.
- Durchgang mit zwei echten Serverprozessen (getrennte Datenordner, gemeinsamer Verbundordner, je ein Medienordner mit MeshSync-Marker): System A lädt per FFmpeg und meldet `download.done` mit Pfad, Größe und SHA-256; System B lehnt den gleichen Download ab („MeshSync überträgt“), nach Kopie der Datei zeigt B „hier vorhanden“.
- Nicht geprüft: echter MeshSync-Abgleich zwischen zwei NAS.

## Verbund mehrerer Systeme (Branch, 28. Oktober 2026, Linux-Testumgebung)

- Alle automatisierten Tests bestanden (`python3 -m unittest discover -s tests`), darunter 11 neue Verbundtests in `tests/test_mesh.py` und ein neuer Downloadtest.
- Zwei simulierte Instanzen mit getrennten Datenbanken und gemeinsamem Ordner: 60 Titel aufgeteilt, beide Instanzen am Ende identisch zugeordnet; höchstens die beim Zusammentreffen laufenden Titel werden doppelt geprüft (Test lässt maximal 2 zu, in 8 wiederholten Läufen bestanden).
- Geprüft: Markerprüfung ohne Anlegen fehlender Laufwerke, unveröffentlichte Segmente bleiben unsichtbar, abgerissene Zeile nach Absturz, gefälschte/fremde Zeilen, Gewichtung und Ausfall von Knoten, Übernahme ohne erneute Anbieterabfrage, Vorrang manueller Zuordnungen, Einzelbetrieb bei fehlendem Ordner.
- Download-Zwischendateien: Test schlägt mit dem alten Stand fehl (`original.bin` sichtbar) und besteht mit dem neuen.
- Chromium: Verbund-Einstellungen gespeichert, Fehlermeldung bei fehlendem Ordner, Statusanzeige mit eigenem System, keine JavaScript-Fehler.
- Nicht geprüft: echter MeshSync-Abgleich zwischen zwei NAS, Synology/QNAP-Laufzeit.

27. Oktober 2026, Linux-Testumgebung.

- 97 automatisierte Tests bestanden. Bestehende Katalog-, Serienpaket-, FFmpeg-, Diagnose-, OMDb- und Runtime-Prüfungen bleiben enthalten.
- TVDB mit kontrollierten API-Antworten: Login mit/ohne PIN, Bearer-Token und Cache, einmalige Neuanmeldung bei abgelaufenem Token, HTTP 401/429 mit Zugriffspause und erfolgreichem explizitem Wiederholungstest, fehlender Schlüssel, deutsche Episodentitel, Genre-Normalisierung, mehrdeutige bzw. abgeschnittene Episodenlisten, Serienidentität und TVDB-ID im NFO.
- Zuordnungsfilter berücksichtigt unbekannte Werke; expliziter Filmfilter schließt diese weiterhin aus.
- Chromium: bisherige Serienpaket-/Editor-/Protokoll-/OMDb-Prüfungen bestanden; fehlender TVDB-Schlüssel wird verständlich angezeigt. Verzögerte Filmantwort nach Wechsel auf Serien überschreibt die Auswahl nicht. Zuordnungsfilter, Zurücksetzen und Genre-Auswahl geprüft. Bei fehlerhaften Status-/Baumantworten bleibt die Mediennavigation bedienbar; Kategorie-Wiederholung lädt Genres nach. Keine JavaScript-Fehler.
- Screenshot der Genre-Auswahl visuell geprüft. Python-/JavaScript-/Shell-Syntax und Git-Diff geprüft. App-Bundle 0.4.0, Build 13.

Nicht verifiziert: TVDB-Liveabgleich mit echten Zugangsdaten, persönliche OMDb-Zugangsberechtigung und native Ausführung unter macOS/Finder. Kein TVDB-Projektschlüssel wird mitgeliefert. TVDB ist als Serienquelle angebunden; Filme nutzen die bisherigen Quellen.

Zusätzlich: Cache-Invalidierung während des Statuslesens und leerer Cache mit aktuellem Zeitstempel getestet. Chromium erhält gezielt Statusdaten ohne Angebotszahl und ohne Neuordnungszähler; die Anzeige bleibt ohne JavaScript-Abbruch bedienbar.

0.3.4: Zusätzlich Sperre gegen doppelte Instanzen, Freigabe nach Beenden, Ablehnung externer Wiederöffnungs-URLs und eine blockierte Genre-Berechnung geprüft: API-Aufruf bleibt unmittelbar verfügbar, keine zweite Berechnung, Ergebnis wird später ausgeliefert. Separater Test mit echten Serverprozessen: zweiter Start beendet sich ohne zweiten Server; authentifiziertes Shutdown beendet den ersten Prozess; Sperre anschließend wieder verfügbar. Chromium-Regression ohne JavaScript-Fehler bestanden.

Diagnosebasis: MediathekAtlas_Diagnose_2026-10-27T09-57-24-279Z.zip und image(20261027-095739).png. Version 0.3.2, 719.759 Angebote laut Screenshot, fehlgeschlagene Genre-Anzeige, zeitlich überlappende Protokolle dreier App-Kopien. Kein Beleg für einen vollständigen Erfolg auf diesem Originalkatalog; kein nativer macOS-Test.

0.3.5: 89 Tests erneut bestanden. Chromium prüft zusätzlich den Serientitel als Kartenüberschrift innerhalb einer Serie und direkt sichtbare Dateilinks. Keine automatische Netzwerkprüfung der Pixelauflösung hinzugefügt; vorhandene Dateinamenhinweise sind ausdrücklich als solche beschriftet.

0.3.6: 92 Tests bestanden. Zehn aufeinanderfolgende Titel während OMDb-Pause: kein OMDb-Anbieteraufruf oder OMDb-Log je Titel, TMDB arbeitet weiter. Kostenlose Wikidata-Rückfallquelle separat geprüft. Pause auf Datenträger, Wiederherstellung, anderer Schlüssel, Zeitablauf und nächste erfolgreiche Anfrage geprüft. Chromium zeigt den zentralen OMDb-Countdown nach simuliertem Kontingentfehler. Kein Live-Test mit persönlichem OMDb-Kontingent.

0.3.7: 93 Tests bestanden. Erster Kontingentfehler ergibt eine zentrale Pause statt Titelwarnung; Wikidata bleibt erreichbar. Chromium prüft das Ausblenden historischer OMDb-Warnungen während aktiver Pause sowie die Anzeige konkreter Anbieter-Trefferzahlen. Keine JavaScript-Fehler.

0.4.0: 97 Tests bestanden. Zusätzliche Prüfungen für ungegruppte offene Serienfolgen, Ausschluss bestätigter/inaktiver Werke, Statusfilter, gebundene Suchparameter und getrennte Anbieterzähler. Chromium prüft fünf einzeln sichtbare offene Folgen, Seitenauswahl, Sammelpriorisierung, Öffnen des Korrekturdialogs und vier Anbieterzeilen. Bestehende Katalog-/Serienpaket-/OMDb-Pausenprüfungen bestanden; keine JavaScript-Fehler. Zuordnungsansicht visuell bei 1512 × 1100 geprüft. Keine Live-Validierung mit persönlichen API-Zugängen oder nativ unter macOS.

0.4.1: 99 Tests bestanden. Freier Speicher auf dem Ziellaufwerk und fehlende Sprachangaben geprüft. Echter FFmpeg-Downloadtest prüft gemessene 64×64-Auflösung, Dateigröße und Metadaten. Browserprüfung der gemessenen Video-/Audiodetails sowie bisheriger Katalog-, Zuordnungs-, Serienpaket- und Anbieterfunktionen. Keine native macOS-Validierung. Vorabprüfung entfernter Medien und Pause/Fortsetzen bleiben offen.

0.4.2: 102 Tests bestanden. Teilmengen im Serien-Sammeldownload, ungültige/leere Auswahl und veraltete Vorschau geprüft. Echter FFmpeg-Serienexport prüft Episoden-NFO und tvshow.nfo mit korrekter Serien-ID; keine Serien-ID als Episoden-ID. Browserprüfungen: Serien als Startansicht, kompakte Folgenliste, Auswahlzähler, Sammelvorschau, Katalogfilter, Anbieterpause und Downloads bestanden. Folgenansicht bei 1512×1100 visuell geprüft. Keine native macOS- oder Kodi/Jellyfin-Importprüfung; bestehende Exporte bleiben unverändert.

0.4.3: 116 Tests bestanden. IMDb-Fixtures decken GZIP/TSV-Streaming, NULL, deutsche Aliasse, Bewertungen, Serien-/Episoden-ID, Nummerierungskonflikte, lokale Treffer ohne Netzaufruf, OMDb-identische Dublettenschlüssel, Sieben-Tage-Fälligkeit, manuellen Start, beschädigte Header/GZIP, Download-/Importfehler und Abbruch mit Erhalt des Altbestands ab. Browserprüfung: fünf Anbieterzeilen, IMDb-Status und manueller Aktualisierungsendpunkt sowie bestehende Abläufe bestanden. Kein vollständiger Live-Import der großen IMDb-Datensätze, kein nativer macOS-Test. IMDb-Archiv wird beim ersten Start lokal aufgebaut.

0.4.4: 127 Tests bestanden. Sieben Datensatz-Fixtures, internationale Aliasse, Personen/Besetzung/Regie, NFO-Export und Archiv-Schemawechsel geprüft. Anbieterreihenfolge TVDB→TMDB→OMDb nach lokaler Prüfung, Abbruch bei ausreichendem Treffer, Quellen ohne Schlüssel, ergänzte Genres mit Herkunft, Mehrdeutigkeit und Jahr-/Art-/Staffel-/Folgen-/Laufzeitkonflikte geprüft. Browserregression ohne JavaScript-Fehler bestanden. Kein vollständiger Live-Import, keine nativen macOS- oder Kodi/Jellyfin-Tests.

0.4.5: 132 Tests bestanden. Artwork-Abgleich über externe ID, Ablehnung mehrdeutiger Titel/falscher Jahre, unveränderte Werkidentität, Hintergrundergänzung bestätigter Werke, HTML-Abweisung, erlaubte Bildhosts und überschreibungsfreier Bildexport geprüft. Browserregression inklusive neuer Detailansicht bestanden; Detailansicht bei 1512×1100 visuell geprüft. Tests verwenden simulierte Bildanbieter. Kein nativer macOS-Test oder Live-Test mit persönlichen TVDB-/TMDB-Zugängen.

0.4.6: 134 Tests bestanden. Downloadflag blendet ein Werk aus mehreren Genreansichten aus, bleibt bei erneutem Import erhalten und erlaubt Anzeige ohne Datenlöschung. Stabile Laufzeitkopie überlebt Entfernen des ursprünglichen App-Verzeichnisses; benutzerdefinierter Python-Launcher funktioniert weiterhin. Browserregression mit Detail-Dateilinks, Bewertung/Stimmen und alternativen Angeboten bestanden; Detailansicht visuell geprüft. Syntax- und Diffprüfungen bestanden. Native macOS-AppTranslocation sowie Start des Standard-Videoplayers nicht direkt getestet.

## 0.4.7
138 Python-Tests: erfolgreich. Neue Tests prüfen zulässige Bewertungsskalen, Ablehnung abweichender IMDb-ID/Medienart, null OMDb-Aufrufe während Pause, Empfehlungen nach Stimmen und Bewertung sowie Downloadstatus. Bestehende Browser-Suite erfolgreich, keine JS-Fehler. Zusätzliche Browserprüfung: 2048px Hauptbreite, drei Karten füllen die komplette Zeile, 390px ohne horizontalen Überlauf, Rotten-Tomatoes-/Metacritic-Werte mit Quelle in Details. Screenshots intern visuell geprüft. Python-/JS-/Shell-Syntax geprüft. Anbieterantworten in Tests simuliert; kein Live-Test mit persönlichen Zugangsdaten. Native macOS-Ausführung weiterhin nicht testbar.

0.4.8 (28.10.2026, Linux-Testumgebung): 149 Tests bestanden (Python 3.13). Neu: Passwort-Hash, Sitzungen, Fehlversuchssperre, Einrichtungscode und Übernahme des Assistentenpassworts. SPK wird gebaut, entpackt und mit den echten DSM-Skripten (postinst, start-stop-status start/status/stop) gestartet: Anmeldung, beliebiger Host-Header nur mit Sitzung, Ablehnung von „App beenden“, Downloadpfad aus der Paketkonfiguration, Status 3 nach Stopp. QNAP-Dienstskript mit Ersteinrichtung über die Code-Datei und Rechteabgabe an einen unprivilegierten Benutzer (UID geprüft). Desktop-Modus behält Host-Prüfung ohne Anmeldung. Chromium: Anmelde- und Ersteinrichtungsseite, NAS-Zugangsbereich, ausgeblendetes „App beenden“ visuell geprüft. Das QPKG wird ausschließlich in der GitHub-Action mit dem offiziellen QDK gebaut und dort strukturell geprüft. Nicht verifiziert: Installation auf echter Synology/QNAP-Hardware.

Diagnose 0.4.7 vom 29.10.2026 (macOS arm64, Python 3.13, 2 h 47 min Protokoll, keine ERROR-Ereignisse): 148 Tests bestanden (Linux, Python 3.13), davon 9 neu. Geprüft: Rückstellung unaufgelöster Werke bei pausiertem OMDb mit wachsendem Abstand (1 h bis 24 h) statt stündlich, echte Anbieterfehler weiterhin stündlich; ein Protokollereignis je Anbieterprüfung mit Dauer (auch Wikidata); OMDb-Zugriffsfehler als WARNING; unveränderte Serienfolgen werden bei der Serienübernahme nicht neu geschrieben; ein Artwork-Abgleich gilt für alle Folgen derselben Serie, Fehler werden nicht übertragen; Genre-Baum wird bei langsamer Berechnung seltener neu ermittelt, Suche und Bearbeitung verwerfen den Cache sofort. Lokaler Serverstart mit authentifiziertem Genre-Baum-Abruf geprüft. Nicht verifiziert: Verhalten mit dem Originalkatalog (720.844 Angebote) und echten API-Schlüsseln, native Ausführung unter macOS.

## 0.5.0

29.10.2026, Linux-Testumgebung (Python 3.13): 186 Tests bestanden, 1 übersprungen. Enthält die Stände von 0.4.8 (NAS-Pakete, Anmeldung), Verbund mehrerer Systeme und die Diagnose-Fixes. Neu: 16 Tests für ARD-/ZDF-Senderdaten (Adresserkennung, Auswertung der Antworten, Sendereihe gegen Sammelrubrik, bestätigte Folgennummern, Zwischenspeicher, ZDF-Token als geschütztes Geheimnis, Pause bei HTTP 429, Rückstellung statt Warnung bei Ausfall, Überspringen der Filmdatenbanken für bekannte Sendereihen, erlaubte Bildadressen). Die Testdaten sind aus den Feldpfaden von yt-dlp (ard.py, zdf.py) nachgebildet, nicht live aufgezeichnet. SPK 0.5.0 gebaut und Paketinhalt geprüft (broadcaster.py, meshjournal.py, access.py, version.py enthalten); macOS-App gebaut. QPKG wird nur in CI mit dem QNAP QDK gebaut.

Nicht verifiziert: Live-Abfragen der ARD- und ZDF-Schnittstellen (aus der Testumgebung gesperrt), Verhalten mit dem Originalkatalog, native Ausführung unter macOS, Installation auf echter NAS-Hardware, Verbund mit echtem MeshSync.

## 0.5.1

29.10.2026, Linux-Testumgebung (Python 3.13): siehe Abschnitt unten für die Testzahl. Neu: 7 Tests für Sendungsbeiträge (Formatbegriffe nur im Thema, kurze Beiträge häufiger Themen, Filme/Serien/Trailer/Sammelrubriken ausgenommen, Einordnung unter eine gemeinsame Sendung, Abgleich-Warteschlange überspringt Beiträge, ausdrückliche Anforderung wird einmal abgeglichen und nicht erneut eingeordnet, Erkennungsquote je Sender, Neustart der Einordnung nach Import). Lasttest mit 60.000 synthetischen Werken: Einordnung 5,1 s für den vollständigen Durchlauf (im Hintergrund, in Blöcken zu 500), Erkennungsquote 0,3 s. Kartenansicht im Headless-Chromium bei 1600 px und 390 px Breite geprüft (feste Kartenbreite 240 px, gleiche Kartenhöhe je Reihe, einspaltig auf dem Telefon).

Nicht verifiziert: Einordnung und Laufzeit mit dem Originalkatalog (rund 720.000 Werke), native Ausführung unter macOS, Installation auf echter NAS-Hardware.

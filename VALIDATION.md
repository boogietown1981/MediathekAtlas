# Validierung · MediathekAtlas 0.4.0 Preview

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

# MediathekAtlas · 0.5.10 Preview

Lokaler Film- und Serienkatalog mit automatischem Import der MediathekView-Filmliste, Metadatenabgleich und geordneten Downloads. Wiederverwendete ArchiveMedia-Module bilden die Grundlage für Titelerkennung, Anbieterabgleich, Dateinamen und Export.

## Neu in 0.5.10: QNAP-Paket installierbar

Das QPKG 0.5.9 wurde vom App Center mit „file format error“ abgelehnt: Dem Paket fehlte das Prüffeld im Fußbereich, das QNAPs Hilfsprogramm `qpkg_encrypt` schreibt; der Build hatte dessen Fehlen nur als Warnung gemeldet. `build_nas.py` schreibt das Feld jetzt selbst (byte-gleich mit dem QNAP-Werkzeug geprüft), die CI kontrolliert es. Sonst keine Programmänderung gegenüber 0.5.9.

## Neu in 0.5.9: Bisherige Erkennungen werden im Verbund geteilt

Bisher teilte ein System nur Ergebnisse, die nach dem Einschalten des Verbunds entstanden. Jetzt veröffentlicht jedes System beim ersten Verbinden einmalig auch alle schon vorhandenen Zuordnungen (manuell, zugeordnet, Werk erkannt), in Paketen zu 1000 Werken je 30 Sekunden. Die Verbundanzeige zeigt den Fortschritt („Bisherige Ergebnisse werden geteilt: … übertragen, noch … Werke“). Die anderen Systeme übernehmen sie ohne eigene Anbieterabfrage; eigene manuelle Zuordnungen bleiben unangetastet.


Neu als Paket: `MediathekAtlas_0.5.10.qpkg` für QNAP QTS (architekturunabhängig, über App Center → Manuell installieren). Python ab 3.9 („Python3“ aus dem App Center oder Entware) muss installiert sein; der Einrichtungscode für das erste Passwort liegt danach im Download-Ordner.
## Neu in 0.5.8: Katalog-Fehler „j is not defined“ behoben

Seit 0.5.3 brach die Kartenansicht ab, sobald ein Titel mehrere Fassungen hatte („Katalog konnte nicht geladen werden: j is not defined“). Ursache war ein falsch platzierter Code-Teil der neuen Download-Karten in der Katalogkarte.

## Neu in 0.5.7: Klare Fehlermeldungen der Direktverbindung

Die Statuszeile der Direktverbindung nennt jetzt die tatsächliche Ursache (Gegenstelle nicht erreichbar, Schlüssel abgelehnt, Verbund dort nicht aktiv samt Grund, zu alte Version) statt pauschal „Gegenstelle ist kein MediathekAtlas“. Zeitlimit je Anfrage 30 s für ausgelastete NAS.

## Neu in 0.5.6: Hinweise und Katalog-Ladefehler

- Bestätigungen wie „Einstellungen gespeichert“ verschwinden nach sieben Sekunden von selbst. Fehlermeldungen bleiben rot sichtbar, bis man sie mit × schließt oder die Ursache behoben ist.
- Lädt der Katalog einmal nicht (z. B. NAS kurz ausgelastet, Verbindung über Tailscale unterbrochen), versucht die Oberfläche es zweimal automatisch erneut. Erst danach erscheint „Katalog konnte nicht geladen werden“ mit der Ursache; beim nächsten erfolgreichen Laden verschwindet die Meldung.

## Neu in 0.5.5: Direktverbindung zwischen Systemen (z. B. über Tailscale)

Mac und NAS teilen sich die Erkennung jetzt auch ohne gemeinsamen Sync-Ordner. Auf dem NAS unter Einstellungen → Verbund „Dieses System freigeben“ wählen, den angezeigten Verbindungscode am Mac einfügen, fertig. Der Mac verbindet sich selbst mit dem NAS und gleicht alle 30 Sekunden ab, er muss also nicht erreichbar sein. Geschützt durch einen gemeinsamen 256-Bit-Schlüssel; über Tailscale zusätzlich verschlüsselt. Videos werden dabei nicht kopiert, dafür gibt es „Herunterladen“. Details: `docs/VERBUND.md`.

## Neu in 0.5.4: Synology ohne feste Python-3.9-Abhängigkeit

Das Synology-Paket verlangt nicht mehr das Paket „Python 3.9“. Jedes installierte Python ab 3.9 wird gefunden, auch SynoCommunity 3.10 bis 3.13 oder andere Python-Pakete; das neueste wird verwendet. Fehlt ein passendes Python, bricht die Installation mit einem verständlichen Hinweis ab.

## Neu in 0.5.3: Einheitliche Genres, Downloads als Karten, Dateien vom NAS laden

- **Genres ohne Doppelungen:** Schreibweisen der Anbieter werden zu einem deutschen Genre zusammengeführt, z. B. „Dokumentarfilm“, „Documentary“ → „Dokumentation“, „Kriminalfilm“, „Krimiserie“ → „Krimi“, „Filmdrama“ → „Drama“, „Liebesfilm“ → „Romantik“, „Biography“ → „Biografie“, „Familie“ → „Kinder & Familie“, „Mysteryfilm“ → „Mystery“. Groß-/Kleinschreibung, Bindestriche und „&“/„und“ spielen keine Rolle; „Action & Adventure“ wird zu „Action“ und „Abenteuer“, reine Medienangaben wie „Fernsehserie“ entfallen. Bestehende Kataloge werden beim ersten Start einmalig umgestellt.
- **Download-Ansicht als Kartenraster** wie die Suche: Cover, Titel, Status und Fortschritt kompakt, Speicherort, Tonspuren und Originalquelle unter „Datei & Speicherort“ einklappbar.
- **Fertige Downloads über den Browser laden:** Jede fertige Datei hat die Schaltfläche „Herunterladen“. Das funktioniert auch, wenn MediathekAtlas auf dem NAS läuft und der Browser auf einem anderen Gerät; die Anmeldung gilt dafür genauso. Fortsetzen abgebrochener Übertragungen (HTTP-Range) wird unterstützt. MP4/WebM lassen sich auf dem NAS direkt im Browser abspielen. „Filmdatei öffnen“ bleibt in der Desktop-App erhalten.

## Neu in 0.5.2: Downloads im Verbund abgestimmt

Mit eingerichtetem Verbund lädt jedes NAS einen Titel nur noch einmal für alle. Startet ein System einen Download, meldet es das den anderen. Dort erscheint am Titel „Wird auf ‚NAS X‘ geladen“, und ein zweiter Download wird abgelehnt. Bereits eingereihte Folgen eines Serienpakets bekommen den Status „Auf anderem System“ und lassen sich später erneut starten.

Liegt der Downloadordner in einem MeshSync-Ordner, verteilt MeshSync das fertige Video an die anderen NAS. Die Karte zeigt „MeshSync überträgt“, bis die Datei vollständig angekommen ist (Größe stimmt), danach „hier vorhanden“. Liegt der Downloadordner nicht in einem MeshSync-Ordner, gilt der Titel trotzdem überall als geladen, blockiert aber keinen eigenen Download. Die Verbundeinstellungen zeigen, ob der Downloadordner geteilt wird.

Ein Anspruch läuft nach zwei Stunden ohne Lebenszeichen ab, ein abgestürztes System blockiert also nichts dauerhaft. Abgebrochene oder fehlgeschlagene Downloads geben den Titel sofort frei. Für fertige Downloads wird zusätzlich eine SHA-256-Prüfsumme veröffentlicht (für HomeTube). Format und Grenzen: `docs/VERBUND.md`.

## Neu in 0.5.1

### Sendungsbeiträge unter ihrer Sendung

Einzelbeiträge wiederkehrender Formate (z. B. „aktuell (16 Uhr)“, Lokalzeit, Tagesschau, Servicemagazine) stehen in keiner Filmdatenbank. Sie werden jetzt als Folgen ihrer Sendung einsortiert und erscheinen unter „Serien“ mit dem Beitragstitel als Folgentitel. Diese Beiträge werden nicht mehr bei TMDB, TVDB, OMDb, IMDb oder den Sendern abgefragt; der Abgleich bleibt für Filme und Serien frei. Erkennung: Thema der Filmliste mit Formatbegriff (Nachrichten, aktuell, Journal, Magazin, Lokalzeit, …) und mindestens zwei Beiträgen, oder kurze Beiträge (unter 10 Minuten) eines Themas mit mindestens drei Beiträgen. Filme, erkannte Serien, Trailer und Sammelrubriken wie „Filme im Ersten“ bleiben unberührt. Die Einordnung läuft im Hintergrund nach jedem Import. Wer einen Beitrag trotzdem abgleichen möchte, wählt ihn in der Zuordnungszentrale aus und startet „Auswahl erneut abgleichen“; er wird danach nicht wieder als Beitrag eingeordnet. Filter: „Zuordnung › Sendungsbeiträge“.

### Erkennungsquote je Sender

Die Zuordnungszentrale zeigt unter „Erkennungsquote je Sender“ für jeden Sender: Werke, vollständig zugeordnet, Werk erkannt, Sendungsbeiträge, zu prüfen, offen und die Quote erkannter Werke ohne Sendungsbeiträge. Die Auswertung wird im Hintergrund berechnet und höchstens alle 10 Minuten erneuert. Die Statuszeile im Katalog nennt zusätzlich die Zahl der Sendungsbeiträge.

### Schnellerer Abgleich

Nach jedem Werk wartete der Abgleich fest 2 Sekunden; das begrenzte ihn auf etwa 28.000 Werke am Tag. Die Pause gilt jetzt nur noch, wenn nichts fällig ist. Die Anbieter drosseln sich weiterhin selbst (Zwischenspeicher, Pausen, HTTP 429).

### Ruhigere Kartenansicht

Werkkarten haben eine feste Breite und werden bei wenigen Treffern nicht mehr über die ganze Seite gestreckt. Titel belegen immer drei Zeilen (längere werden gekürzt, voller Titel als Tooltip), Statuszeilen eine Zeile; die Schaltflächen stehen in jeder Reihe auf gleicher Höhe.

## Neu in 0.5.0

### Senderdaten für Eigenproduktionen von ARD und ZDF

Magazine, Nachrichten, Talkformate und Dokumentationen der Sender stehen meist weder bei TMDB noch bei TVDB oder IMDb. Findet keine Filmdatenbank einen Treffer, liest MediathekAtlas jetzt die Mediathek-Seite des jeweiligen Angebots (ARD Mediathek, ZDF Mediathek): Sendereihe, Beschreibung, Bild und, wo vorhanden, Staffel und Folge. Stimmt die Sendereihe mit dem Thema der Filmliste überein, wird das Werk als Serie dieser Reihe erkannt; nummerierte Folgen gelten als bestätigt. Sammelrubriken wie „Filme im MDR“ werden nicht als Reihe behandelt. Genres wie „Magazin“, „Nachrichten“ oder „Dokumentation“ werden aus Reihentitel und Beschreibung abgeleitet und als „Sender (abgeleitet)“ gekennzeichnet.

Bereits als Sendereihe erkannte Folgen fragen die Filmdatenbanken nicht erneut und werden nur alle 30 Tage aufgefrischt. Abfragen an die Sender sind gedrosselt (höchstens zwei pro Sekunde), werden 24 Stunden zwischengespeichert und bei Fehlern 15 Minuten pausiert. Es ist kein Schlüssel nötig. Die Schnittstellen sind nicht offiziell dokumentiert und können sich ändern; ein Ausfall betrifft nur diese Zusatzdaten. 3sat, arte und KiKA sind noch nicht angebunden.

### Weniger Last im Dauerbetrieb (Auswertung der Diagnose 0.4.7)

- Ist OMDb wegen des Tageskontingents pausiert, werden unaufgelöste Werke nicht mehr stündlich neu geprüft, sondern mit wachsendem Abstand (1 h bis 24 h). Vorher war das Kontingent nach jeder Pause sofort wieder aufgebraucht.
- Cover und Fanart werden einmal je Serie statt für jede Folge abgeglichen.
- Die Genre-Übersicht wird bei großen Katalogen seltener neu berechnet.
- Das Diagnoseprotokoll ist kompakter und reicht dadurch etwa doppelt so weit zurück.

### Pakete für Synology und QNAP


MediathekAtlas lässt sich als Dienst auf einem NAS betreiben: `MediathekAtlas-0.5.10-noarch.spk` für Synology DSM 7 und `MediathekAtlas_0.5.10.qpkg` für QNAP QTS, jeweils architekturunabhängig (x86_64, ARM64, ARMv7). Downloads landen direkt in einer NAS-Freigabe; Katalog und Einstellungen bleiben im lokalen Paketdatenordner. Die Weboberfläche ist im Heimnetz unter Port 8730 erreichbar und durch ein Passwort geschützt (Synology: Installationsassistent, QNAP: Einrichtungscode im Download-Ordner). Der Dienst läuft ohne Root-Rechte. Details, Pfade und Grenzen: `packaging/README.md`.

Nicht auf echter NAS-Hardware getestet: Installation im Paket-Zentrum/App Center, Freigabeanlage durch DSM, Rechte unter QTS-ACLs. Die Startskripte, die Anmeldung und die Rechteabgabe sind automatisiert in einer Linux-Umgebung geprüft.

### Verbund mehrerer Systeme (Vorschau)


Mehrere MediathekAtlas-Installationen, etwa auf verschiedenen NAS, teilen sich die Metadatenerkennung. Unter Einstellungen → „Verbund mehrerer Systeme“ wird ein gemeinsamer Ordner eingetragen, bevorzugt ein MeshSync-Ordner. Jede Installation bearbeitet einen Teil der 256 Werkbereiche und übernimmt die Ergebnisse der anderen. Dadurch wird kein Titel doppelt bei TMDB, OMDb oder TVDB abgefragt. Manuelle Zuordnungen gelten überall. Jede Installation behält ihre eigene Datenbank und arbeitet ohne Verbindung allein weiter. Format, Regeln und Grenzen: `docs/VERBUND.md`.

Downloads schreiben alle Zwischendateien jetzt mit der Endung `.partial`. Liegt das Downloadziel in einem MeshSync-Ordner, verteilt MeshSync nur fertige Videos und keine halbfertigen Dateien mehr.

Noch offen: Abstimmung der Downloads zwischen den Systemen, Signaturen, ein eigener Verbund-Reiter. Mit echtem MeshSync auf zwei NAS ist der Verbund noch nicht getestet.

## Start und Aktualisierung

1. Bisherige MediathekAtlas-App beenden und durch `MediathekAtlas.app` aus diesem Paket ersetzen.
2. App öffnen. Voraussetzung bleibt Python 3.9+ sowie FFmpeg/ffprobe für Downloads. Python.org, Homebrew (auch `ffmpeg-full`) und MacPorts werden berücksichtigt. Unter Einstellungen stehen die tatsächlich gefundenen Pfade und Versionen.
3. Der Katalogimport beginnt automatisch. Beim ersten Start wird die komprimierte MediathekView-Filmliste geladen (aktuell ungefähr 75 MiB); anschließend werden Einträge in SQLite einsortiert. Die Oberfläche zeigt den Fortschritt. Es werden dabei keine Videos heruntergeladen.
4. TMDB/OMDb- sowie TVDB-Zugangsdaten bei Bedarf unter Einstellungen hinterlegen. Vorhandene MediathekAtlas-Einstellungen und der alte Katalog werden übernommen; ArchiveMedia-Schlüssel werden nicht ausgelesen.
5. Film auswählen oder Serie zu ihren Folgen öffnen. Die bevorzugte Fassung prüfen und herunterladen. Andere Sender/Fassungen sind ausklappbar.

Die App ist eine unsignierte Preview mit lokaler Browseroberfläche. Ein echter macOS-Finderstart ist hier weiterhin nicht validiert. Der Source-Ordner enthält zusätzlich `Start.command` und `Start.bat`. Linux: `python3 server.py`.

## Neu in 0.4.0: Zuordnungszentrale und Anbieterstatistik

Der neue Reiter „Zuordnung“ zeigt Quelltitel und Katalogtitel nebeneinander, einschließlich Quelle, Jahr, Status und vorhandener Zuordnungsbelege. Offene Serienfolgen bleiben einzeln sichtbar. Filter trennen vorgemerkte Titel, Wiederholungen, Prüffälle, erkannte Werke mit offener Folge sowie automatische/manuelle Zuordnungen. Die Ansicht ist auf 48 Einträge pro Seite begrenzt.

„Vergleichen & korrigieren“ öffnet den vorhandenen Metadateneditor mit Vorschlägen und Belegen. Nach dem Speichern aktualisiert sich die Liste. Einzelne Einträge oder eine ganze Seite können für einen erneuten Abgleich priorisiert werden. Das bestätigt keine Zuordnung automatisch. Die Auswahl gilt nur für die sichtbare Seite und wird beim Wechsel der Suche/Seite gelöscht.

Die einklappbare Anbieterübersicht zeigt seit App-Start Prüfungen, Prüfungen mit Treffern, Kandidaten, Fehler, pausiert übersprungene Abgleiche und den letzten erfolgreichen Prüfzeitpunkt. Die Tabelle aktualisiert sich alle fünf Sekunden, solange die Ansicht geöffnet ist. Diese Zähler messen Anbieter-Titelprüfungen, nicht HTTP-Aufrufe; interne Anbieter-Caches können beteiligt sein. Vollständig aus dem übergeordneten Ergebnis-Cache gelesene Abgleiche erhöhen die Zähler nicht. Ein Kandidat ist noch keine bestätigte Zuordnung. Die Sitzungsstatistik ist auch im Diagnoseexport enthalten.

Vorhandene Titelähnlichkeit wird als Vergleichswert angezeigt, nicht als Trefferwahrscheinlichkeit. Fehlende Belege werden nicht ergänzt oder erfunden. Die Zähler starten bei jedem App-Start neu; Katalog, Zuordnungen, Zugangsdaten und OMDb-Pausen bleiben erhalten.

Dies ist der erste Umsetzungsschritt der priorisierten Erweiterungen. Technische Qualitätsprüfung, ausgebaute Transferzentrale und Serien-Abos sind noch nicht Bestandteil dieser Version.

## Neu in 0.3.7: hilfreiche Anbieteranzeige statt wiederholter OMDb-Fehler

Ein erkannter OMDb-Zugriffsfehler, der eine zentrale Pause auslöst, wird nicht mehr zusätzlich als Fehler jedes einzelnen Titels gespeichert. Bereits gespeicherte OMDb-Warnungen werden während der Pause in der Titelanzeige und im Metadateneditor ausgeblendet. Der zentrale Countdown bleibt sichtbar; der erste Zugriffsfehler und explizite Verbindungstests bleiben im Protokoll nachvollziehbar.

Die Oberfläche zeigt beim letzten Abgleich die tatsächlich versuchten Quellen mit Trefferzahlen bzw. einem Abfragefehler. Ergebnisse aus dem Antwortcache werden als Cache gekennzeichnet. TMDB und OMDb benötigen Zugangsdaten; TVDB wird nur für Serien verwendet. Wikidata wird ohne Schlüssel abgefragt, wenn keine Kandidaten aus den zuvor abgefragten Quellen vorliegen. Es werden nicht pauschal alle Anbieter als erfolgreich genutzt dargestellt.

## Neu in 0.3.6: zentrale OMDb-Pause und weitere Quellen

Nach einem OMDb-Kontingentfehler wird OMDb für eine Stunde zentral übersprungen, bereits vor dem Aufruf des Titelabgleichs. Währenddessen entstehen keine weiteren OMDb-Anfragen oder Fehlerprotokolle je Titel. TMDB, TVDB (Serien) und Wikidata als kostenlose Rückfallquelle arbeiten weiter. Die Anbieteranzeige zeigt die Restzeit in Minuten und die lokale Uhrzeit des nächsten zulässigen Versuchs. Die Pause wird pro gehashtem Schlüssel lokal gespeichert und überlebt App-Neustarts.

Nach Ablauf darf die nächste anstehende OMDb-Abfrage wieder starten. Meldet der Anbieter weiterhin ein Limit, beginnt erneut eine Stunde Pause. Dies ist ein lokales Wiederholungsintervall, keine Zusage, dass das Anbieter-Kontingent nach einer Stunde zurückgesetzt ist. Der ausdrücklich angeklickte Verbindungstest darf die Pause weiterhin umgehen; ein erfolgreicher Test hebt sie auf. Neue Schlüssel haben eine eigene Zugriffspause.

Während einer Pause unvollständige Ergebnisse werden nicht als vollständige Anbieterantwort für 24 Stunden gecacht. Nicht erkannte Titel bleiben zur Wiederholung vorgemerkt; erkannte Werke behalten ihre Metadaten. Gleichzeitige OMDb-Abfragen werden serialisiert, damit nach Ablauf kein Anfragesturm entsteht.

## Neu in 0.3.5: Werktitel und sichtbare Dateilinks

Film- und Serientitel aus den gespeicherten Metadaten stehen als Kartenüberschrift im Vordergrund. In einer geöffneten Serie steht darunter der Episodentitel mit vorhandener Staffel-/Folgennummer. Noch nicht erkannte Werke behalten vorläufig ihren Quelltitel; die Kennzeichnung „Metadaten vorgemerkt“ bleibt sichtbar.

Die Links der bevorzugten Fassung erscheinen direkt auf der Karte unter „Verfügbare Dateien“. HD/Standard/Klein sind Angaben aus der Mediathek, keine bestätigte Pixelauflösung. Enthält der Dateiname beispielsweise 1080p, wird dies ausdrücklich als Dateinamenhinweis gekennzeichnet. Sonst steht „Pixelauflösung nicht angegeben“. Andere Sender/Fassungen bleiben ausklappbar und zeigen dieselben Qualitätsinformationen. Quelllinks öffnen die Originaldatei; für den geordneten Download mit Metadaten weiter „Beste Fassung prüfen & laden“ verwenden. Serienübersichten führen zuerst zu den einzelnen Folgen.

## Neu in 0.3.4: Genre-Abfrage und parallele App-Versionen

Der Diagnoseexport vom 27.10.2026, 10:57 Uhr (Berlin), stammt von Version 0.3.2. Im selben Zeitraum protokollieren drei unterschiedliche App-Kopien weiter Metadatenabfragen. Das Schließen eines Browserfensters hatte deren lokale Server nicht beendet. Der Screenshot zeigt geladene Filme, aber eine fehlgeschlagene Genre-Abfrage. Deren genaue Laufzeit ist im alten Export nicht enthalten.

**Einmaliger Umstieg:** Mac neu starten, damit die alten Hintergrundprozesse beendet sind. Anschließend nur die App aus diesem Paket verwenden; alte Browser-Tabs schließen. Vor dem Neustart andere Arbeiten speichern. Katalog und API-Schlüssel bleiben im bisherigen Datenordner erhalten.

Ab 0.3.4 verhindert eine Betriebssystem-Sperre einen zweiten Server für denselben Datenordner. Ein erneuter Start öffnet die vorhandene Instanz. Zum Aktualisieren oder Beenden künftig die Schaltfläche „App beenden“ unten links verwenden. Ältere Versionen kennen die Sperre nicht und dürfen nicht parallel gestartet werden.

Genres werden separat im Hintergrund ermittelt. Die Oberfläche erhält sofort vorhandene Kategorien und einen Ladezustand; während der Berechnung fragt sie den Fortschritt ab. Es läuft höchstens eine Genre-Berechnung pro Instanz gleichzeitig. Ergebnisse werden 60 Sekunden zwischengespeichert; Fehler und Laufzeit erscheinen im Live-Protokoll. Bei unveränderten Kategorien wird der Baum nicht ständig neu aufgebaut.

Die übrigen Korrekturen aus 0.3.3 sind enthalten. Der persönliche Katalog wurde nicht mitgeliefert; der Erfolg auf dem betroffenen Mac ist deshalb noch nicht bestätigt.

## Neu in 0.3.3: Statusanzeige ohne Abbruch

Behebt „Cannot read properties of undefined (reading 'toLocaleString')“. Der Server liefert einen vollständigen lokalen Snapshot auch bei gleichzeitiger Cache-Invalidierung durch Metadatenänderungen. Fehlende Statuszahlen erscheinen als „–“; Katalog, Kategorien und weitere Statusanzeigen bleiben bedienbar.

## Neu in 0.3.2: Zuordnung, Kategorien und TVDB

Filterwechsel gehen bei einer laufenden Kataloganfrage nicht mehr verloren; veraltete Antworten überschreiben die neue Auswahl nicht. Filme, Serien, noch nicht zugeordnete Werke und weitere Sendungen erscheinen bereits vor der ersten Serverantwort. Genre-Ladefehler behalten die vorhandene Navigation und bieten eine Wiederholung an. „Filter zurücksetzen“ löscht Suche, Medienart, Genre, Serie und Zuordnungsfilter. Ohne gewählte Medienart berücksichtigt der Zuordnungsfilter auch bisher unbekannte Sendungen.

TVDB v4 ergänzt Serien, Genres, Beschreibungen und deutsche Episodentitel. Unter Einstellungen den eigenen **TVDB-Projektschlüssel** sowie bei nutzerfinanziertem Zugang die **Abonnenten-PIN** speichern, anschließend „Gespeicherten TVDB-Zugang testen“ wählen. Ein OMDb-/TMDB-Schlüssel funktioniert dafür nicht; ein TVDB-Projektschlüssel ist nicht mitgeliefert. Zugangsvoraussetzungen: https://github.com/thetvdb/v4-api und https://support.thetvdb.com/kb/faq.php?id=81

Der Abgleich nutzt die offizielle ausgestrahlte Episodenreihenfolge und verlangt einen eindeutigen Titelvergleich ohne Widerspruch zu vorhandenen Nummern. Doppelte Episodentitel und unvollständige Scans werden nicht automatisch zum Download freigegeben. Die Episodenliste wird auf 20 Seiten begrenzt; Antworten werden sechs Stunden im Speicher zwischengespeichert. Bei HTTP 401, 403 oder 429 pausiert der TVDB-Zugang eine Stunde; der explizite Verbindungstest kann erneut prüfen. Ein abgelaufener Token wird einmal erneuert. Andere Anbieter bleiben unabhängig nutzbar. TVDB ist in dieser Version eine Serienquelle; Filmabgleiche bleiben bei den bisherigen Anbietern.

TVDB-Zugangsdaten bleiben lokal, werden in Diagnosen geschwärzt und nicht in Download-Metadaten exportiert. Die TVDB-Werk-ID wird dagegen in der NFO gespeichert. Neue Zugangsdaten aktivieren die erneute Prüfung bislang offener Zuordnungen. Bereits manuell bestätigte Einträge werden dadurch nicht zurückgesetzt.

## Neu in 0.3.1: OMDb-Zugriff gezielt prüfen

Unter Einstellungen gibt es „Gespeicherten OMDb-Schlüssel testen“. Neue Schlüssel zuerst speichern. Der Test umgeht den Antwortcache und eine bestehende Zugriffspause, fragt einen festen Testtitel ab und zeigt Erfolg oder eine verständliche Fehlerklasse: Anfragelimit, nicht aktivierter Schlüssel, abgelehnter Schlüssel, unspezifische Zugriffsablehnung, Netzwerkfehler oder ungültige Antwort. Der Schlüssel wird nicht ausgegeben.

Bei HTTP-Fehlern wird nun auch der begrenzte JSON-Antworttext ausgewertet; bisher blieb nur „Dienst antwortet mit HTTP 401“. Beliebige Antworttexte werden nicht in der Oberfläche ausgegeben. Nach einer OMDb-API-Fehlermeldung pausieren weitere automatische Zugriffe mit demselben Schlüssel eine Stunde. Ein erfolgreicher direkter Test hebt die Pause auf; andere Anbieter bleiben nutzbar. Die Pause gilt innerhalb der laufenden App und beginnt nach einem Neustart gegebenenfalls erneut.

Die Nutzerdiagnose vom 27.10.2026 enthält 50 abgeschlossene Metadatenabgleiche, darunter erfolgreiche TMDB-Zuordnungen, und 49 OMDb-Fehler mit HTTP 401. Der genaue OMDb-Ablehnungsgrund ist in dieser alten Diagnose nicht enthalten. Das Update behebt die fehlende Fehlerdifferenzierung, verspricht jedoch keine serverseitige Freischaltung des Schlüssels.

Zusätzlich startet der abgeschlossene Katalog-Neuordnungsarbeiter nicht mehr alle fünf Sekunden erneut. Die Diagnose hatte 57 wiederholte Abschlussmeldungen gezeigt.

## Neu in 0.3.0: Werke, Metadaten und Serienpakete

- Der Abgleich bearbeitet Filme, Serien und noch unbekannte Titel abwechselnd. Serien müssen nicht mehr hinter sämtlichen Filmen warten. Neue Indizes vermeiden die bisherige globale Sortierung der Warteschlange.
- Ein eigener Statusbereich zeigt aktuellen Titel, eingerichtete Anbieter, das letzte Ergebnis und die Anzahl der Abgleiche seit Start. Live-Log und Diagnoseexport enthalten Anbieterstart, Trefferzahl, Laufzeit und Fehler. „Diese Ansicht jetzt abgleichen“ priorisiert die sichtbaren maximal 48 Werke; in einer geöffneten Serie ihre Folgen (maximal 1.000).
- TMDB und OMDb sind seit 0.3.0 angebunden; TVDB ergänzt sie seit 0.3.2. Für TMDB/OMDb ist ein eigener Schlüssel nötig. Ohne Schlüssel verwendet die App Wikidata. Fehlende Genres oder Episodendaten werden nicht erfunden.
- OMDb übernimmt jetzt Genre, Beschreibung, Jahr und Laufzeitbelege. Genres werden vereinheitlicht und können im Metadateneditor geändert werden. Genre und Anbieter-ID werden zusätzlich in MKV-Tags eingebettet.
- Serien werden über Werkmetadaten gruppiert. TMDB/OMDb-Episodenlisten können fehlende Nummern über einen eindeutigen Episodentitel ergänzen. Bereits vorhandene Nummern dürfen nicht widersprechen. Die Suche ist auf 24 Staffeln begrenzt; bei größeren Serien ohne bekannte Staffel bleibt die Episode ungeprüft. Titelvarianten oder doppelte Episodennamen benötigen gegebenenfalls manuelle Zuordnung.
- „Werk erkannt“ unterscheidet sich bewusst von „vollständig zugeordnet“: Titel und Werkmetadaten können sichtbar sein, während eine konkrete Datei bzw. Episode noch geprüft werden muss. Mehrdeutige Werke bleiben zur Prüfung offen. Das bestätigt nicht den tatsächlichen Inhalt einer bereits heruntergeladenen Datei.
- Ein erkannter Serienname samt Jahr/Genres kann auf die übrigen Angebote derselben Serie übertragen werden; Episodennummern werden niemals von einer Folge auf andere kopiert. Wiederkehrende, kurze Angebote eines eindeutig bekannten Serienthemas erhalten diese Werkmetadaten als vorläufige Zuordnung. Unterschiedliche Serienzuordnungen verhindern diese automatische Wiederverwendung.
- Lokale Suche berücksichtigt nun auch das Quellthema, damit beispielsweise „Bibi und Tina“ schon vor dem vollständigen Abgleich gefunden werden kann. Hauptansicht und Baum ordnen nach Werktitel, Medienart, Genre und Zuordnungsstatus. Sortierung: Titel, Jahr oder bestätigte Werke zuerst. Sender erscheinen weiterhin unter den verfügbaren Fassungen.
- Bestehende, nicht bestätigte Einträge werden beim ersten Start einmalig aus den lokalen Quelldaten neu eingeordnet. Manuell bestätigte und bereits zugeordnete Metadaten bleiben bestehen. Dies ist kein erneuter Videodownload; der Fortschritt ist sichtbar.

**Serien gesammelt laden:** Auf der Serienkarte „Serie gesammelt laden“ öffnen. Die Vorschau zeigt ladbare Folgen und Auslassungsgründe. Erst nach Bestätigung werden die vollständig zugeordneten Folgen eingereiht, jeweils mit ihrer besten verfügbaren Fassung. Ungeprüfte Episoden, fehlende Nummern, nicht unterstützte Streams und bereits vorhandene/eingereihte Ziele werden ausgelassen. Die Vorschau wird serverseitig erneut geprüft; Änderungen erfordern eine neue Bestätigung. Maximal 1.000 Folgen pro Serie. Es werden nur aktuell im Katalog vorhandene Folgen berücksichtigt, keine Vollständigkeit einer Staffel versprochen.

**Zum gemeldeten Fehler:** Die bereitgestellte Diagnose von 0.2.1 belegt einen abgeschlossenen Import mit 719.568 Datensätzen und einen vorhandenen Metadaten-Thread, aber keine erfolgreichen oder fehlgeschlagenen Anbieterabfragen. Ein gestoppter Abgleich war damit nicht nachgewiesen. Im Code waren feste Filmpriorität, fehlende OMDb-Felder, zu grobe Quellklassifikation und fehlende Metadaten-Telemetrie erkennbar. Diese Punkte adressiert 0.3.0.

## Neu in 0.2.1: Diagnose und Wiederherstellung

- Seitenleiste **Live-Protokoll**: letzte 400 Logzeilen, automatische Aktualisierung alle 2,5 Sekunden, pausierbare Ansicht und **Diagnose-ZIP herunterladen**.
- Export enthält rotierende Ereignisprotokolle (maximal ungefähr 8 MiB), technischen Status und einen begrenzten, bereinigten Ausschnitt des Startprotokolls. API-Schlüssel, URLs und Heimverzeichnis werden maskiert; Einstellungen und Katalogdatenbank werden nicht exportiert. Vor Weitergabe kann der Export eingesehen werden.
- Wenn die Oberfläche nicht erreichbar ist: **Diagnose.command** neben der App im entpackten Paket doppelklicken. Das ZIP wird auf dem Schreibtisch abgelegt und im Finder ausgewählt. Dafür wird kein Webserver gestartet. Python muss weiterhin verfügbar sein.
- Filmlisten-Download mit kleineren Leseblöcken, Socket-Timeout und bis zu drei Versuchen pro Durchlauf. Nach endgültigem Fehler folgt automatisch nach fünf Minuten ein neuer Durchlauf, solange automatischer Import aktiviert ist. Wiederholungen starten den Dateidownload neu; kein Byte-Resume.
- „Filmliste aktualisieren“ fordert auch bei laufendem Import einen Neustart an. Ein blockierter Netzwerk-Lesezugriff muss zuvor seinen Timeout erreichen.
- Hintergrundarbeiter werden nach Ausnahmen protokolliert und neu gestartet. SQLite-Verbindungen werden nach jeder Nutzung explizit geschlossen. GET-Fehler liefern eine JSON-Fehlermeldung statt eines kommentarlosen Verbindungsabbruchs.
- Die Oberfläche zeigt Verbindungsprobleme mit Uhrzeit, versucht Statusabfragen erneut und kennzeichnet fehlenden Importfortschritt nach 50 Sekunden. Die Fortschrittsanzeige verwendet den aktuellen Arbeitsschritt.

Die konkrete Ursache des beim Nutzer beobachteten Stillstands bei 16,3 MiB ist noch nicht belegt. Dieses Update behebt gefundene Fehlerpfade und liefert die Diagnose für eine weitere Eingrenzung. Browserfenster schließen beendet den alten Dienst nicht: vor dem Austausch den bisherigen MediathekAtlas-Python-Prozess beenden oder den Mac neu starten. Keine Katalogdaten löschen.

## Automatischer Katalog

- Vollständiger verfügbarer Filmlisten-Snapshot statt eines begrenzten Suchausschnitts. Die Filmliste ist die Datenbasis des MediathekView-Projekts; ergänzende Online-Suche läuft weiterhin über MediathekViewWeb.
- Automatische Aktualisierung beim Start, sobald der letzte erfolgreiche Import mindestens 12 Stunden alt ist. Im laufenden Programm ebenfalls alle 12 Stunden. Einstellungen können Import und Metadatenabgleich getrennt pausieren; „Filmliste aktualisieren“ startet einen manuellen Durchlauf.
- Streaming-Dekomprimierung und blockweises Einlesen: Die komplette JSON-Datei muss nicht in den RAM passen. Größen- und Formatgrenzen schützen vor beschädigten Listen.
- Alte Angebote werden nur nach vollständig abgeschlossenem Import als „nicht mehr gelistet“ markiert. Katalogeinträge, Zuordnungen und Metadaten werden nicht gelöscht. Fehler und Abbrüche behalten den bisherigen Verfügbarkeitsstand.
- Der Baum enthält Filme und Serien mit Genres, außerdem „Noch zuordnen“ und „Weitere Sendungen“. Die Hauptansicht zeigt zunächst als Filme/Serien eingeordnete Einträge, darunter noch ungeprüfte Quellenangaben. Der Filter „Erkannte Werke“ begrenzt auf zugeordnete Werke. Ein Genre kann aus einem Senderhinweis oder aus TMDB stammen; bei fehlendem Beleg bleibt es unbekannt.
- Eine Serie erscheint einmal in der Übersicht. Beim Öffnen werden ihre Folgen angezeigt. Es wird keine unbekannte Staffel oder Folge erfunden.
- Katalogsuche arbeitet lokal. „Online ergänzen“ übernimmt zusätzlich die ersten 30 MediathekViewWeb-Suchergebnisse; der Vollimport läuft unabhängig davon.

## Mehrfachangebote und bevorzugte Fassung

Ein Film bzw. eine konkrete Episode besitzt mehrere Angebote. Die bevorzugte Fassung wird nach diesen Regeln ermittelt:

1. Reguläre Fassung vor ausdrücklich gekennzeichneter Audiodeskription/Hörfassung oder Gebärdensprache.
2. Direkt ladbare Videodatei vor derzeit nicht unterstütztem HLS/DASH-Stream.
3. Höchster erkennbarer Auflösungshinweis; ansonsten Qualitätsstufe HD, Standard, Klein.

Das ist eine Rangfolge nach Quellenangaben, **keine technische Qualitätsgarantie**. Jede angebotene URL wird nicht vorab komplett heruntergeladen oder mit ffprobe geprüft. Geoblocking und abgelaufene CDN-Links können einen Download weiterhin verhindern. Ist ausschließlich eine Sonderfassung vorhanden, bleibt sie ausdrücklich gekennzeichnet verfügbar.

Gleiche Titel werden nur mit zusätzlichen Identitätsangaben zusammengeführt: bei Filmen Titel plus Jahr oder, ohne Jahr, übereinstimmende Beschreibungsanfänge; bei Serien Serienname plus konkrete Episodenkennung/-titel. Unterschiedliche Erscheinungsjahre bleiben getrennt. Bestätigte Anbieter-IDs erlauben späteres Zusammenführen. Mehrdeutige Angebote können zunächst doppelt erscheinen, damit keine verschiedenen Filme fälschlich verschmelzen.

## Metadaten

Der Hintergrundarbeiter prüft fehlende Zuordnungen seriell mit Abstand zwischen Abfragen. TMDB-Such- und Detailantworten werden im Prozess gecacht; vollständige Abgleichresultate ohne Fehler bis zu 24 Stunden lokal. Ohne Schlüssel wird Wikidata als Ausweichquelle genutzt.

Die vollständige automatische Zuordnung erfordert einen sehr guten Titelvergleich und einen zusätzlichen Jahr-, Laufzeit- oder Episodenbeleg. Eine getrennte vorläufige Werkzuordnung kann eindeutige Werkmetadaten bereits sichtbar machen, ohne eine konkrete Episode zu bestätigen. Mehrdeutige Treffer und fehlende Belege landen bei „Zuordnung prüfen“; Kandidaten bleiben im Dialog sichtbar. Bei Netzfehlern wird später erneut versucht. Serien- und Anbieterantworten werden zwischengespeichert, damit Folgen derselben Serie nicht jedes Mal sämtliche Werkdaten neu laden. Nach Änderung eines API-Schlüssels werden ungeklärte Abgleiche neu vorgemerkt.

„Im Katalog speichern“ bewahrt eine manuelle Korrektur dauerhaft. Import und Hintergrundabgleich überschreiben manuell bestätigte Metadaten nicht. Genres aus der Zuordnung werden auch in NFO exportiert.

Ein vollständiger Katalogimport ist nicht gleichbedeutend mit einem vollständig abgeglichenen Metadatenbestand. Große Bestände werden schrittweise verarbeitet; die Zähler unterscheiden Angebote, vorgemerkte, abgeglichene und zu prüfende Einträge.

## Downloads und Dateien

Die bisherige Downloadwarteschlange bleibt erhalten. MKV wird ohne Neukodierung erstellt und mit eingebetteten Metadaten, NFO und Herkunfts-/Spur-JSON ergänzt. ffprobe prüft die vollständige lokale Datei. Vorhandene Dateien werden nicht überschrieben. Unterbrechungen lassen sich erneut starten; ein Byte-Resume ist noch nicht enthalten.

```text
Filme/Titel (2020)/Titel (2020).mkv
Filme/Titel (2020)/Titel (2020).nfo
Filme/Titel (2020)/Titel (2020).metadata.json
Serien/Serie (2019)/Season 02/Serie (2019) - S02E03.mkv
Serien/Serie (2019)/tvshow.nfo
```

Der Videodownload wird weiterhin bewusst ausgewählt. Die automatische Katalogisierung lädt keine komplette Videosammlung herunter. Externe Untertitel, HLS/DASH und Serien-Abos sind noch offen. Das MKV-Verhalten ist playerabhängig; NFO ist für Jellyfin/Kodi die zusätzliche verlässliche Metadatenquelle.

## Daten, Diagnose und Quellcode

Datenordner macOS: `~/Library/Application Support/MediathekAtlas`, sonst `~/.mediathekatlas`. Startprotokoll: `startup.log`. Katalog, Einstellungen und Schlüssel bleiben lokal. API-Schlüssel werden nicht in Exportdateien oder im Quellcodepaket gespeichert. Das Schließen des Browserfensters beendet den Hintergrunddienst nicht; zum vollständigen Beenden die Prozessverwaltung bzw. bei Terminalstart Ctrl+C verwenden.

Tests: `python3 -m unittest discover -s tests -v`. Details der tatsächlich durchgeführten Prüfung stehen in `VALIDATION.md`.

ArchiveMedia-Basis: fünf unveränderte Module aus `ArchiveMedia_v0.10.12_Source.zip` samt MIT-Lizenz unter `vendor/archivemedia`. Herkunft und Hashes: `PROVENANCE.json`. Der Archive.org-Crawler wird nicht gestartet.

Das Paket enthält den vollständigen Quellcode und ein Git-Bundle. Ein GitHub-Remote wurde nicht angelegt; der verfügbare Connector bot keine Repository-Erstellung. Der vorbereitete Projektname bleibt MediathekAtlas.

Quellen: https://mediathekviewweb.de/ · https://liste.mediathekview.de/Filmliste-akt.xz · https://github.com/mediathekview/mediathekviewweb · https://developer.themoviedb.org/reference/search-movie · https://developer.themoviedb.org/reference/search-tv

Dieses Produkt verwendet die TMDB API, ist aber nicht von TMDB unterstützt oder zertifiziert. Lizenz: MIT.

## Neu in 0.4.1: Downloadkontrolle

Downloads zeigen Durchschnittsgeschwindigkeit und bei bekannter Dateigröße die geschätzte Restzeit. Vor und während der Übertragung wird der freie Speicher am tatsächlichen Ziel geprüft, einschließlich Platz für Original und MKV sowie Reserve. Nach Abschluss erscheinen gemessene Auflösung, Codecs, Tonkanäle, vorhandene Sprachangaben und Dateigröße. Diese Messung erfolgt nach dem Download; die Katalogangaben bleiben Quellenhinweise. Pause/Fortsetzen und eine Prüfung entfernter Dateien vor dem Download sind noch nicht enthalten.

## Neu in 0.4.2: Serien finden und gezielt herunterladen

Die Startansicht zeigt Serien. Filme bleiben über einen eigenen Schalter erreichbar. Katalogstatus, Metadatenabgleich, Genreäste und Dateilinks sind eingeklappt; Folgen erscheinen als kompakte Liste. Die Sammelvorschau erlaubt die Auswahl einzelner bestätigter Folgen und zeigt die endgültigen Zielpfade. Ungeklärte Folgen werden mit Grund ausgelassen und können über „Prüfen & laden“ zugeordnet werden.

Export für Kodi/Jellyfin: Serienordner, Season-Ordner, SxxEyy im Dateinamen, gleichnamige Episoden-NFO, tvshow.nfo und MKV-Metadaten. Serien-IDs stehen ausschließlich in der tvshow.nfo, nicht als falsche Episoden-ID in Episoden-NFOs. Serienposter werden im Serienordner abgelegt. Bereits exportierte Dateien werden nicht rückwirkend geändert. Die Ordner „Serien“ und „Filme“ als getrennte Bibliotheken im Medienserver einbinden; lokale NFO-Metadaten berücksichtigen. Integration anhand der offiziellen Dokumentation geprüft, kein praktischer Importtest in Kodi/Jellyfin.

Referenzen: https://kodi.wiki/view/NFO_files/Episodes · https://kodi.wiki/view/NFO_files/TV_shows · https://jellyfin.org/docs/general/server/metadata/nfo/

## Neu in 0.4.3: Persönliches IMDb-Offline-Archiv

Beim ersten App-Start werden die offiziellen IMDb-Datensätze title.basics, title.ratings, title.episode und title.akas geladen. Der Import speichert alle Basistitel, Bewertungen und Episodenzuordnungen sowie deutsche/DE/AT/CH-Alternativtitel in SQLite. Fehlwerte werden als NULL gespeichert. Die App liest GZIP/TSV zeilenweise und schreibt Blöcke von 5.000 Zeilen; keine komplette Datei im RAM und keine entpackten TSV-Zwischendateien.

Speicherort auf macOS: ~/Library/Application Support/MediathekAtlas/imdb/imdb_archive.db. Der Import benötigt mehrere GB freien Speicher für Downloads, Datenbank und Suchindizes; bei Aktualisierungen kommt die bisherige Datenbank hinzu. Datenmengen und Laufzeit sind nicht fest vorhersagbar. Unter Einstellungen → IMDb ist der Fortschritt sichtbar, dort kann die Aktualisierung auch manuell angefordert werden.

Ein vollständiger Neuaufbau erfolgt sieben Tage nach dem letzten erfolgreichen Import, solange die App läuft. Verpasste Termine werden beim Start nachgeholt. Bei Fehlern wird frühestens nach einer Stunde erneut versucht; die bisherige Datenbank bleibt nutzbar. Das neue Archiv wird erst nach vollständigem Import und SQLite-Prüfung atomar veröffentlicht. Nach dem Update werden ungeklärte Werke erneut vorgemerkt; bestätigte/manuelle Zuordnungen bleiben erhalten.

Der Metadatenabgleich sucht zuerst lokal nach normalisierten exakten Primär-, Original- und deutschen Alternativtiteln. Eindeutige Filme benötigen einen Jahr- oder Laufzeitbeleg, Serien zusätzlich eine eindeutige Episodentitel-Zuordnung ohne Nummerierungskonflikt, um Online-Abfragen zu überspringen. Andernfalls bleiben die vorhandenen Anbieter ergänzend aktiv. Es gibt keine unscharfe Volltextsuche im IMDb-Archiv. IMDb-Serien- und Episoden-IDs werden getrennt exportiert; OMDb und IMDb Offline verwenden dieselbe IMDb-Identität zur Dublettenerkennung.

Die kostenlosen Datensätze enthalten keine Poster oder Inhaltsbeschreibungen. Die App enthält keine vorab heruntergeladene IMDb-Datenbank. Tests verwenden kleine lokale Datensatz-Fixtures; ein vollständiger Live-Import und native macOS-Tests wurden hier nicht ausgeführt.

Information courtesy of IMDb (https://www.imdb.com). Used with permission.
Für persönliche, nichtkommerzielle Nutzung. Bedingungen und Datensätze: https://developer.imdb.com/non-commercial-datasets/ und https://help.imdb.com/article/imdb/general-information/can-i-use-imdb-data-in-my-software/G5JTRESSHJBBHTGX

## Neu in 0.4.4: Vollständige freie IMDb-Datensätze und geordneter Abgleich

Alle sieben offiziellen freien Datensätze werden vollständig eingelesen: title.basics, title.ratings, title.episode, title.akas, title.crew, title.principals und name.basics. Internationale Alternativtitel werden nicht mehr nach Sprache gefiltert. Personen, Berufe, bekannte Werke, Hauptbesetzung, Rollen, Regie und Drehbuch werden gespeichert. Das sind die von IMDb veröffentlichten freien Datensätze, nicht sämtliche Inhalte der IMDb-Website. Poster und Inhaltsbeschreibungen sind weiterhin nicht enthalten.

Ein bestehendes Archiv aus 0.4.3 bleibt lesbar und wird beim Start einmalig durch einen vollständigen Neuaufbau erweitert. Dieser benötigt deutlich mehr Speicher und Zeit. Zeitplan und atomarer Austausch bleiben erhalten. Besetzung, Regie und Drehbuch werden bei lokalen Treffern übernommen und in NFOs exportiert; Serien- und Episodenbesetzung bleiben getrennt.

Der Abgleich verwendet vorhandene Ergebnis-Caches und anschließend IMDb offline → TVDB (Serien) → TMDB → OMDb. Quellen ohne Zugang werden übersprungen, OMDb-Pausen respektiert. Nach jeder Quelle wird geprüft: eindeutige Identität, hoher Titelvergleich, passende Medienart, keine Jahr-/Laufzeitwidersprüche, bei Serien bestätigte konsistente Staffel/Folge und vollständige Episodenprüfung. Jahr und Genre müssen vorhanden sein, damit die weitere Anbietersuche endet. Poster und Beschreibung lösen allein keine zusätzliche Suche aus. Wikidata bleibt als letzte Rückfallquelle erhalten, falls überhaupt keine Kandidaten gefunden wurden.

Mehrdeutige Treffer und widersprüchliche Anbieter bleiben zur Prüfung offen; TMDB erhält keinen pauschalen Vorrang mehr. Fehlende beschreibende Felder werden nur zwischen kompatiblen Treffern mit nahezu identischem Titel ergänzt; Herkunft der Ergänzung wird gespeichert. IDs, Staffel/Folge und Identitätsbelege werden nicht vermischt. Laufzeiten werden geprüft, soweit Anbieter entsprechende Werte liefern; fehlende Werte sind kein positiver Laufzeitbeleg.

Validierung mit kleinen synthetischen Datensätzen und simulierten Anbietern. Kein vollständiger Live-Import aller großen Datensätze und kein nativer macOS-Test in dieser Umgebung.

## Neu in 0.4.5: Cover, Fanart und Detailansicht

Coverorientierte Karten und „Details & Bilder“ mit Fanart, Cover, Jahr, Genres, Bewertung, Beschreibung, Regie und Besetzung, soweit vorhanden. Folgen bleiben in einer kompakten Liste. Fehlende oder nicht abrufbare Bilder werden ausdrücklich als fehlend dargestellt.

Ein separater Hintergrundlauf ergänzt Bilder für identifizierte, bestätigte und manuell zugeordnete Werke. Voraussetzung: automatischer Metadatenabgleich und mindestens ein eingerichteter TMDB-/TVDB-Zugang. Zuerst TVDB bei Serien, danach TMDB für fehlende Cover/Fanart. Es werden bevorzugt bestehende Anbieter-IDs oder eindeutige ID-Verknüpfungen verwendet; reine Titelsuche verlangt zusätzlich identisches Jahr und eindeutigen Treffer. Die Bildsuche ändert keine Titel-, Anbieter- oder Episodenidentität. Einmal sichtbare Werke werden für den Hintergrundlauf vorgezogen. Ergebnisse werden pro Werkidentität 24 Stunden zwischengespeichert; erneute Versuche frühestens am nächsten Tag. Die Anzeige lädt Bilder über HTTPS von den Bildanbietern, sie ist noch kein vollständig offline gespeichertes Bilderarchiv.

Vor einem Download werden fehlende Bilder noch einmal gesucht. Vorhandene Cover/Fanart werden als poster.jpg/png und fanart.jpg/png im Film- bzw. Serienordner gespeichert. NFOs enthalten Fanart-Verweise. Bildexport unterstützt nun auch TVDB und IMDb-Cover; Bildantworten sind größenbegrenzt und werden auf JPEG-/PNG-Signatur geprüft. Bestehende Bilder werden nicht überschrieben. Bereits abgeschlossene Downloads werden nicht rückwirkend geändert. Ohne Anbieterzugang, verfügbares Motiv oder eindeutige Zuordnung kann kein passendes Bild garantiert werden. Staffelposter, Logos und Episoden-Stills sind noch nicht Teil dieses Updates.

API-Grundlagen: https://developer.themoviedb.org/docs/image-basics und https://thetvdb.github.io/v4-api/

## Neu in 0.4.6: Vollständige Details, Downloadstatus und stabiler Start

Die Detailansicht zeigt Dateilinks samt Qualitätsangaben, alternative Angebote, Bewertung mit Quelle/Stimmen, Laufzeit des Angebots, Zuordnung, Anbieter-ID, Sender, Fassung, Episodendaten sowie vorhandene Credits. Direkte Quelllinks öffnen die Originaldatei; für MKV/NFO und saubere Namen weiterhin über die App herunterladen. TMDB-/OMDb-Bewertungen werden bei neuen Abgleichen gespeichert. Fehlende Bewertungen werden bei passender TMDB-Bildzuordnung nachgetragen. Fehlende Werte werden nicht erfunden.

Nach erfolgreichem Abschluss erhält das Werk einen dauerhaften Downloadstatus. Die normale Katalogliste blendet solche Werke aus; „Alle anzeigen“ und „Heruntergeladen“ machen sie wieder sichtbar. Daten und Angebote bleiben erhalten, auch nach erneutem Katalogimport. Vorhandene abgeschlossene Aufträge werden beim Start übernommen. Ein Werk kann weiterhin mehreren Genres angehören; das ist keine zweite Kopie, und die Ausblendung gilt für alle Genreansichten dieses Werkes. Genrebaum-Zähler beschreiben den gesamten Katalogbestand. Verschiedene, noch nicht eindeutig zusammengeführte Anbieteridentitäten werden weiterhin nicht allein aufgrund eines gleichen Titels verschmolzen.

Downloadkarten zeigen Cover, Jahr, Genre, Episodendaten, Anbieter und den Originalquelllink. Fertige Dateien lassen sich über „Filmdatei öffnen“ mit dem Standardprogramm auf dem Rechner öffnen. Verschobene oder gelöschte Dateien ergeben eine verständliche Fehlermeldung. Der Status wird dadurch nicht automatisch gelöscht.

Der macOS-Launcher kopiert Programmressourcen vor dem Start in ein inhaltsversioniertes, dauerhaftes Laufzeitverzeichnis unter Application Support/MediathekAtlas/runtime. So bleibt die Weboberfläche verfügbar, wenn macOS ein AppTranslocation-Verzeichnis entfernt oder die ursprüngliche App ersetzt wird. Katalog und IMDb-Archiv werden nicht kopiert oder zurückgesetzt. Beim Umstieg von einer bereits defekten laufenden Altversion diese vollständig beenden; falls ihre Oberfläche nicht mehr funktioniert, einmal den Mac neu starten und anschließend die neue App aus Programme öffnen. Alte Browser-Tabs schließen, da sich die lokale Portnummer ändern kann.

Validiert mit automatisierten Tests einschließlich entfernter ursprünglicher App-Ressourcen. Native macOS-AppTranslocation und Start des macOS-Videoplayers sind in dieser Umgebung nicht direkt testbar.


## Neu in 0.4.7: Flexible Kategorien und Empfehlungen

Die Hauptansicht nutzt die gesamte Fensterbreite. Karten verteilen sich automatisch auf die verfügbaren Spalten; auch eine kurze Trefferliste füllt die Zeile. Lange Filmtitel werden umgebrochen statt abgeschnitten. Die Ansicht wurde bei 2048 und 390 Pixeln Breite geprüft.

Unter „Entdecken“ stehen „Großes Kino“ und „Serienfavoriten“. Die Auswahl gilt für den ganzen gefilterten Katalog, nicht nur die aktuelle Seite. Kriterien: erkannte/bestätigte Werke mit mindestens 7,5 von 10 Punkten und mindestens 10.000 IMDb-Stimmen oder 1.000 TMDB-Stimmen. Karten kennzeichnen diese Auswahl; die Details nennen Kriterien und tatsächliche Werte. Das ist eine nachvollziehbare Bewertungsauswahl, kein Beleg für Hollywood-Herkunft, Einspielergebnis oder Exklusivrechte. Fehlende Bewertungen qualifizieren nicht. Originalnetzwerke und Produktionsfirmen aus TMDB werden separat angezeigt, soweit verfügbar.

Rotten Tomatoes, Metacritic und IMDb-Zusatzwertungen werden in der Detailansicht mit Originalskala und Herkunft „via OMDb“ angezeigt. Bestehende Werke werden im separaten Hintergrundlauf ergänzt, ohne die bevorzugte Identitätsprüfung IMDb Offline → TVDB → TMDB → OMDb zu verändern. Dafür muss automatischer Metadatenabgleich eingeschaltet sein. OMDb wird nur mit vorhandener/verknüpfter IMDb-ID aufgerufen; Antwort-ID und Medienart müssen passen. Der globale OMDb-Pausentimer wird respektiert, Ergebnisse werden 24 Stunden zwischengespeichert. Zusätzliche Wertungen verbrauchen OMDb-Kontingent und sind nicht für jeden Titel verfügbar. TVDB-Zuordnungen brauchen derzeit eine eindeutige TMDB-Verknüpfung, um deren IMDb-ID für Zusatzwertungen zu erhalten. Keine direkte Rotten-Tomatoes-Webseitenauslese; kein neuer API-Schlüssel erforderlich, sofern OMDb schon eingerichtet ist.

Beim ersten Start dieser Version wird die ergänzende Bild-/Bewertungsprüfung neu vorgemerkt. Der Katalog und das IMDb-Archiv bleiben erhalten. Außerdem wird der Downloadstatus-Filter jetzt korrekt vom Web-Endpunkt an die Katalogabfrage weitergereicht.

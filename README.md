# MediathekAtlas · 0.5.87

## Neu in 0.5.87: TOGGO nach dem echten Angebot von toggo.de

- Grundlage ist Björns Mitschnitt von toggo.de (13.11.2026). TOGGO lädt den Katalog jetzt so, wie die Website selbst: **alle Serien und zusätzlich alle Filme**, mit Titelbild, Beschreibung, Altersempfehlung, Staffeln und Folgen. Die bisherige Ableitung aus der Seitenübersicht (0.5.79 bis 0.5.85) entfällt; der alte TOGGO-Bestand wird beim ersten Start ersetzt, danach bitte einmal „Katalog jetzt laden“.
- **Kostenlos oder Abo:** Jede Kachel und jede Folge zeigt „kostenlos“ (bei Folgen aus dem Fernsehprogramm mit Enddatum, z. B. „kostenlos bis 20.11.“) oder „Nur mit Abo“. Im Reiter „TOGGO“ gibt es die Auswahl „Angebot“: Alles, nur Kostenloses, nur mit Abo, TOGGOLINO (Vorschule), TOGGO (Schulkinder). Die Serienseite nennt, wie viele Folgen kostenlos sind.
- **Wiedergabe:** Der Mitschnitt zeigt, dass TOGGO alle Folgen und Filme, auch die kostenlosen, nur mit Kopierschutz (Widevine/PlayReady/FairPlay) ausliefert. MediathekAtlas umgeht ihn nicht. Deshalb gibt es bei TOGGO keinen eigenen Player und kein Offline-Speichern; „Bei TOGGO ansehen“ öffnet genau die Folge oder den Film auf toggo.de. Sollte TOGGO einen Titel einmal ohne Kopierschutz anbieten, erscheint dort „▶ Ansehen“.
- TOGGO-Filme stehen auch im gemeinsamen Katalog unter „Filme“.
- **Nicht geprüft:** ein Abruf gegen toggo.de selbst (aus der Bauumgebung gesperrt). Die Anfragen entsprechen dem Mitschnitt; ob das Blättern bei mehr als 500 Titeln je Liste so funktioniert, war im Mitschnitt nicht enthalten (aktuell 182 Serien und 104 Filme, also eine Antwort je Liste).
- Diese Version baut auf 0.5.85 auf und enthält alles daraus.

## Neu in 0.5.85: Joyn lädt den Katalog wieder vollständig

- Bisher reichte eine einzige langsame Antwort von Joyn, und der Katalog galt als „nur teilweise geladen“ (in der Diagnose vom 13.11.2026 fehlten dadurch 70 Filme, ohne Angabe eines Grundes). Jetzt wird eine fehlgeschlagene Seite nach kurzer Pause noch einmal abgefragt, und ein Genre, das trotzdem abbricht, läuft am Ende des Abrufs ein zweites Mal.
- Bleibt danach etwas offen, nennt die Meldung das Genre und den Grund, und der nächste Versuch startet nach einer Stunde statt nach einem Tag (bei eingeschaltetem täglichen Abruf).

## Neu in 0.5.84: TOGGO-Katalog repariert, Code aufgeräumt

- **TOGGO lädt wieder Serien.** In 0.5.79 bis 0.5.82 blieb der TOGGO-Katalog leer („nennt in seiner Seitenübersicht keine Folgen“). Die Diagnose vom 13.11.2026 zeigte, dass toggo.de die Folgen unter `/…/serien/<Serie>/folge/<Folge>` führt und nicht unter der erwarteten kürzeren Adresse. Beide Formen werden jetzt gelesen. Nach dem Update unter Plattformen → TOGGO „Katalog laden“ drücken oder den nächsten stündlichen Versuch abwarten.

- Der Programmcode, der für Pluto TV, JustWatch TV, Rakuten TV, Joyn, TOGGO und YouTube jeweils fast gleich kopiert war (Katalogseite, Details, Offline-Liste, Katalogabruf, täglicher Abruf, Werkzuordnung, Offline-Download, Hintergrundaufgaben), steht jetzt einmal in `platform_registry.py`. Alle Adressen und Antworten sind gleich geblieben; ein Fehler wird künftig an einer Stelle behoben und gilt für alle Plattformen.
- Die 44 alten Installationspakete (625 MB) liegen nicht mehr im Git. Sie bleiben in den Projektdateien unter `releases/` und in der Git-Historie.
- 0.5.84 enthält auch 0.5.83 (einheitliche Kategorien für Filme und Serien, siehe unten).

## Neu in 0.5.83: einheitliche Kategorien für Filme und Serien

- **Eine feste deutsche Kategorieliste für alle Quellen** (ARD/ZDF, Netzkino, Pluto TV, JustWatch, Rakuten, YouTube, Joyn, TOGGO): Action, Abenteuer, Animation, Biografie, Drama, Erotik, Fantasy, Historie, Horror, Kinder & Familie, Komödie, Krieg, Krimi, Musical, Mystery, Romantik, Science-Fiction, Thriller, Western, Dokumentation, Natur & Tiere, Wissen & Technik, Politik & Gesellschaft, Nachrichten & Magazine, Kultur, Musik, Sport, Reise, Ratgeber & Lifestyle, Talk, Show & Unterhaltung, Reality-TV.
- **Kategorie erst nach dem Abgleich:** Solange ein Titel nicht mit IMDb/TMDB/TVDB abgeglichen ist, steht er unter „Unklassifiziert“. Danach entscheiden die Genres der Referenz, die des Anbieters ergänzen. Passt nichts, steht er unter „Sonstige“.
- Dubletten wie „Fantasie“/„Fantasy“ oder „Krimi“/„Kriminalfilms“ und englische Bezeichnungen landen in derselben Kategorie. „Joyn (kostenlos)“, „Joyn+“ und „TOGGOLINO“ sind keine Kategorien mehr, bleiben aber filterbar.
- Die Original-Genres der Anbieter bleiben gespeichert: auf der Titelseite unter den Anbieterangaben und im klassischen Genre-Baum (Verwaltung → Werkkatalog).


## 0.5.82: Sammelstand, Archive.org erkennt Werke

0.5.82 enthält alles aus 0.5.78 (YouTube), 0.5.79 (TOGGO), 0.5.80 (Besetzung mit Fotos, Clips, Windows und Linux) und 0.5.81 (Merkliste, Weiterschauen, Speicher). Neu dazu:

- **Archive.org-Uploads werden Werken zugeordnet** (aus Archive Media). Bisher stand jeder Upload für sich. Jetzt zeigt jeder gespeicherte Upload, welcher Film oder welche Serie er ist, mit Kennung bei IMDb, TVDB oder TMDB und Bewertung.
- **Suchtitel:** Zusätze wie `[DVD]`, `1080p`, Upload-Zähler und Folgenangaben werden für die Abfrage entfernt. Der gespeicherte Upload bleibt unverändert.
- **Jahr berichtigt:** Archive.org nennt oft das Upload-Datum statt des Erscheinungsjahrs. Findet die Abfrage mit dem Jahr nichts, läuft sie einmal ohne; nur ein eindeutiger Treffer liefert dann das Jahr („Jahr aus der Datenbank“).
- **Serien aus mehreren Uploads** gehören zusammen: gleicher Serienname oder nach der Prüfung dieselbe Kennung. Staffel und Folge aus dem Upload-Titel stehen dabei.
- **Anime** ohne Treffer in den Filmdatenbanken werden bei AniList gesucht (nur ein eindeutiger, fast wörtlicher Titeltreffer zählt).
- Plattformen → Internet Archive → Liste: Umschalter „Einzelne Uploads / Werke (Archive.org)“, je Werk „Alle Uploads zeigen“ und „Neu prüfen“. Die Prüfung läuft im Hintergrund wie bei den anderen Plattformen (Verwaltung → Aufgaben: „Internet Archive · Werkzuordnung“).
- TOGGO-Serien lassen sich merken und erscheinen in „Weiterschauen“.

## Neu in 0.5.81: Merkliste, „Weiterschauen“ auf jedem Gerät und Speicherübersicht

- Jede Film- und Serienkachel hat den Schalter „☆ Merken“. Gemerkte Titel stehen im Dashboard unter „Merkliste“.
- „Weiterschauen“ im Dashboard zeigt angefangene Titel mit Fortschritt. Der Abspielstand liegt jetzt in MediathekAtlas statt nur im Browser; ein anderer Browser oder ein anderes Gerät setzt an derselben Stelle fort.
- Verwaltung → Speicher: belegter Platz je Quelle, freier Platz auf dem Laufwerk, ein Platzbudget und ein Vorschlag, was gehen kann. MediathekAtlas löscht dort nichts von selbst. Gemerkte, angeheftete, kürzlich gesehene und neu geladene Titel werden nie vorgeschlagen.
- Ältere Browser ohne Container-Abfragen (Safari vor 16, Firefox vor 110) zeigen die Statusübersicht wieder passend zur Fensterbreite; die Unschärfe hinter Dialogen wirkt auch in Safari vor 18.
- Merkliste und Speicherregeln stammen aus HomeTube. Der vollständige Review und die Lückenanalyse gegen HomeTube und Archive Media stehen in `docs/REVIEW_0577.md`.

## Neu in 0.5.80: Besetzung mit Fotos, Clips bei ihrer Sendung, Pakete für Windows und Linux

Baut auf 0.5.78 (YouTube) auf.

- **Besetzung mit Fotos:** Titelseiten zeigen die Darsteller mit Foto und Rolle (TMDB, nur mit hinterlegtem TMDB-Schlüssel). Fotos kommen nur aus den Angaben des Titels selbst oder über die IMDb-Personenkennung, nie aus einer bloßen Namenssuche; ohne Treffer bleiben die Initialen. Antworten werden gemerkt (`people.sqlite`).
- **Nachrichten- und Magazinclips bei ihrer Sendung:** Clips, die bisher unter „Weitere Sendungen“ lagen, und Ausgaben, die genau wie ihre Sendung heißen („Hessenschau“), werden der Sendung zugeordnet (Ausgaben mit Sendedatum) und nicht mit Filmdatenbanken abgeglichen. Der Durchlauf läuft einmal über den ganzen Katalog.
- **Erkennungsrate je Sender und Medienart:** Die Tabelle „Erkennungsquote je Sender“ zeigt zusätzlich die Quote für Filme und Serien sowie die Zahl der Clips und Extras, darunter eine Tabelle „Nach Medienart“.
- **Live-TV:** Der Fehlalarm „0 Sender bei aktivem Filter“ in der Diagnose ist weg. Er kam von der Live-Leiste der Joyn-Plattform, solange Joyn noch keine Sender hatte; die Sender selbst waren nie betroffen.
- **Windows und Linux:** `MediathekAtlas_v0.5.80-Windows-Setup.exe` (Installation ohne Administratorrechte, Startmenü, Desktop, optional Autostart), portable ZIP, `mediathekatlas_0.5.80_all.deb` (Debian, Ubuntu, Mint, Raspberry Pi OS) und `MediathekAtlas_v0.5.80-Linux.tar.gz` mit `install.sh` für alle anderen. Voraussetzung ist Python ab 3.9; unter Windows bietet der Start die Installation über winget an. Gebaut mit `python3 build_desktop.py`.

## Neu in 0.5.79: TOGGO (Kinderserien von toggo.de, mit TOGGOLINO)

- Neue Quelle **TOGGO**: Reiter „TOGGO“ unter „Plattformen“ und im Katalog (Dashboard, „Serien“). Alle Serien von TOGGO und TOGGOLINO mit Serienseite, Staffeln, Folgen und Clips; Genre „Kinder & Familie“, dazu die Kategorien „TOGGO“ und „TOGGOLINO“ (Vorschule) zum Filtern nach Altersgruppe.
- Der Katalog entsteht aus der Seitenübersicht (Sitemap) von toggo.de. Titel, Nummer und Bild der Folgen einer Serie werden beim ersten Öffnen der Serie nachgeladen.
- **Wiedergabe:** Eine Folge läuft im MediathekAtlas-Player, wenn TOGGO sie ohne Kopierschutz ausliefert. Liefert TOGGO nur mit Kopierschutz (Widevine/FairPlay), umgeht MediathekAtlas ihn nicht; die Folge öffnet dann toggo.de („Bei TOGGO ansehen“). Nach dem Katalogabruf prüft MediathekAtlas an je einer Folge von bis zu drei Serien, welcher Fall vorliegt, und zeigt danach den passenden Knopf.
- Kein Offline-Speichern für TOGGO in dieser Version, kein Live-TV.
- **Wichtig:** toggo.de war aus der Bauumgebung nicht erreichbar. Die Anbindung beruht auf öffentlich dokumentierten Formaten und ist nicht live geprüft. Lädt der Katalog nicht, bitte die Diagnose schicken (Einträge `toggo_sitemap`, `toggo_sync_failed`) oder einen HAR-Mitschnitt von toggo.de.

## Neu in 0.5.78: Musikvideos laufen auch, wenn YouTube das Einbetten ablehnt

- Lehnt YouTube ein Video im eingebetteten Player ab, schaltet MediathekAtlas automatisch auf den eigenen Player um. Das geht nur mit eingeschaltetem YouTube-Offline-Schalter, weil der Stream dabei wie beim Speichern über yt-dlp geholt wird.
- Unter dem YouTube-Player stehen immer die Auswege: „Auf YouTube ansehen“, „▶ Im eigenen Player abspielen“ und „⬇ Kurz laden und hier abspielen“.
- Im Katalog gibt es neben „Filme“ und „Serien“ jetzt „Musikvideos“.

## Neu in 0.5.77: Die Seite bringt alle ihre Teile selbst mit, Streams sammeln erst Puffer

Sammelstand: enthält 0.5.75 (YouTube-Quellen sofort eingelesen) und 0.5.76 (JustWatch-Download).

- **Nichts geht mehr verloren:** Die Seite lädt ihre rund zwanzig Skripte nicht mehr einzeln nach, sie stecken in der Seite selbst. Bisher konnte ein einzelnes Skript ausbleiben, dann fehlte der Player, die Netzkino-Wiedergabe („Cannot read properties of undefined (reading 'play')“) oder ein Plattform-Reiter. Das ist unabhängig vom Browser.
- **Flüssigere Wiedergabe:** Online-Streams sammeln erst einen Vorrat, bevor sie laufen: 8 Sekunden beim Start, 4 nach dem Spulen, 5 nach jedem Stocken. Der Player zeigt dabei „Puffer wird gefüllt … 3 von 8 s“. Länger als 15 Sekunden wartet er nie, ein Klick auf Wiedergabe startet sofort.


## Neu in 0.5.76: JustWatch – Download startet, sobald der Titel abspielbar ist

Enthält alles bis 0.5.73.

- Titel mit Jugendschutz-Zeitfenster: Beim Klick auf „Offline speichern“ fragt MediathekAtlas JustWatch direkt, ob der Stream gerade freigegeben ist. Ist er es, startet der Download sofort (JustWatch gibt ab 16 schon ab 22 Uhr und ab 18 ab 23 Uhr frei). Ist er es nicht, wird er für die Nacht vorgemerkt – auch wenn der Katalog zuletzt nachts gelesen wurde.
- Die Stream-Adresse wird bei jedem Start und jedem neuen Versuch frisch geholt, nie aus dem Zwischenspeicher.

## Neu in 0.5.75: YouTube-Quellen sofort eingelesen, mit Fortschritt

- Eine neu eingetragene Playlist, ein Kanal oder ein Video wird sofort eingelesen. Läuft gerade ein Abruf, kommt sie direkt danach dran.
- Während des Abrufs steht im YouTube-Bereich und auf der Plattformkarte, welche Quelle gerade dran ist und wie viele Videos geprüft werden.
- Die Plattformkarte zeigt Musik-Playlists und Musikvideos in einer eigenen Kachel.
- Behoben: Ein Protokollfehler konnte Wiedergabe-Statistik und Stream-Ende abbrechen.
## Neu in 0.5.73: Alle Teile der Seite kommen an

Enthält alles bis 0.5.72.

- **Player lädt:** Die Seite lädt rund zwanzig Skripte gleichzeitig. Der Server nahm bisher nur wenige Verbindungen auf einmal an, einzelne Skripte wie der Player konnten dabei verloren gehen. Er nimmt jetzt deutlich mehr an.
- **Automatisch nachladen:** Kommt ein Skript trotzdem nicht an, lädt die Seite es bis zu dreimal selbst nach, auch über eine zweite Adresse, falls eine Browser-Erweiterung oder ein Schutzprogramm den Dateinamen sperrt. Das gilt in Chrome, Safari und Firefox gleich.
- **Ursache sichtbar:** Scheitert auch das, nennt die Meldung, ob der Server nicht antwortet oder der Browser die Anfrage ablehnt.


## Neu in 0.5.72: Player startet zuverlässig, der letzte Klick gewinnt

Enthält alles bis 0.5.71 (YouTube-Musikvideos).

- **Player:** Die Wiedergabe-Bibliothek hls.js wird erst geladen, wenn ein Stream sie braucht. Fehlt sie oder lädt sie nicht, läuft der Stream über ffmpeg weiter. Der Player startet auch dann, wenn ein Teil der Seite fehlt.
- **Richtiger Sender:** Wer kurz nacheinander zwei Sender oder Titel anklickt, bekommt den zuletzt gewählten. Vorher konnte der zuerst gewählte unter dem Namen des zweiten starten.
- **Schnellerer Start:** MediathekAtlas fragt den Anbieter vor dem Start nicht mehr zusätzlich nach den Qualitätsstufen, wenn der Browser sie selbst liest.
- **Klare Meldung:** Lädt der Player trotzdem nicht, nennt die Meldung die Ursache, und sie steht in der Diagnose. „▶ Ansehen“ im Katalog zeigt die Meldung jetzt auch, statt nichts zu tun.


## Neu in 0.5.71: YouTube-Musikvideos

Enthält alles bis 0.5.70.

- **Musikvideos:** Im YouTube-Bereich unter „YouTube-Kanäle & API-Schlüssel“ eine Playlist, einen Kanal oder ein einzelnes Video mit der Art „Musikvideos“ eintragen. Hier gibt es keine Mindestlänge und keinen Werbefilter.
- **Abspielen:** Der Reiter „Musikvideos“ zeigt Playlists und einzelne Videos. „▶ Playlist abspielen“ spielt ein Video nach dem anderen im offiziellen YouTube-Player oder aus der Offline-Kopie.
- **Offline:** „⬇ Ganze Playlist offline speichern“ reiht mit einem Klick alle Videos ein. Mit den Kästchen lässt sich auch nur eine Auswahl speichern. Die Dateien liegen unter `Musikvideos/<Playlist>/`. Das geht wie bei Filmen nur, wenn der YouTube-Offline-Schalter an ist.


## Neu in 0.5.70: Streams wie auf den Anbieterseiten, einheitliche Kacheln, Fassungen

Enthält alles bis 0.5.69 (Joyn).

- **Wiedergabe wie auf den Anbieterseiten:** Live-Sender und Streams von Pluto TV, Rakuten TV, JustWatch TV und den Sendern lädt jetzt der Browser selbst (mit der freien Bibliothek hls.js, Apache-2.0, in der App enthalten). Er hält einen Puffer vor, passt die Qualität laufend an die Verbindung an und hält Bild und Ton zusammen. Bisher lief jeder Stream ohne Puffer durch ffmpeg, daher das Anfangspuffern und das Ruckeln. „Qualität“ im Player schaltet jetzt ohne Neustart um.
- **Rückfall:** Erlaubt ein Anbieter das direkte Laden nicht, läuft der Stream wie bisher über ffmpeg. In der Kopfzeile des Players steht dann „über MediathekAtlas umgewandelt“.
- **Chrome:** Der neue eingebaute HLS-Player von Chrome wird nicht mehr benutzt. Safari spielt weiter selbst ab.
- **Einheitliche Kacheln:** Jede Kachel hat dieselben Knöpfe: Details, Ansehen (oder „↗ Bei … ansehen“ als gleich geformter Knopf) und einen Download-Knopf, wenn ein Download möglich ist. Das gilt jetzt auch für ARD, ZDF & Co. („⬇ Herunterladen“). Ist kein Download möglich, steht dort nichts mehr; der Kopierschutz-Hinweis steht nur noch auf der Titelseite.
- **Fassungen auf der Titelseite:** Film- und Folgenseiten der Plattformen zeigen „Fassungen zum Herunterladen“ mit einem Knopf je Auflösung des Anbieters; ein Klick speichert genau diese Fassung. Bei ARD, ZDF & Co. stehen die Dateien (HD, Standard, Klein) als Knöpfe über der Fassungsliste.

## Neu in 0.5.69: Joyn füllt sich schon beim ersten Laden

- Die Joyn-Sender stehen sofort nach dem Start des Abrufs im Reiter Live-TV und unter Plattformen → Joyn. Filme und Serien kommen Genre für Genre dazu, die Statuszeile zeigt „Genre-Seite n von m“. Vorher erschien alles erst am Ende des mehrminütigen ersten Abrufs.

## Neu in 0.5.67: Live-TV-Reiter bleibt nicht mehr hängen

- Der Reiter Live-TV fragt die Anbieter jetzt nebeneinander und mit einer Zeitgrenze von vier Sekunden ab. Antwortet ein Anbieter nicht rechtzeitig (zum Beispiel, während sein Katalog geladen wird), erscheinen die übrigen Sender sofort und für den langsamen Anbieter der letzte bekannte Stand. Die Statuszeile nennt den Anbieter.
- Schlägt das Laden fehl, bleiben die schon gezeigten Sender stehen; daneben steht der Grund und „Erneut versuchen“.
- Ob das die Ursache des leeren Reiters in 0.5.61 war, ist nicht bestätigt: Der Fehler ließ sich mit Testdaten nicht nachstellen.

## Neu in 0.5.66: Wiedergabe, Download-Auswahl, Dubletten, Live-TV

Enthält alles aus 0.5.61 (Archive.org-Downloads) und 0.5.65 (Joyn).

- **Bild und Ton laufen zusammen:** Bei Streams, die MediathekAtlas für den Browser umwandelt (Chrome, Firefox, Edge; Live-TV und Filme von Pluto TV, Rakuten TV, JustWatch TV, Sender-Livestreams), ging bisher der Versatz zwischen Bild- und Tonspur verloren. Im Test lief der Ton dadurch 0,8 Sekunden zu früh, nach dem Spulen das Bild bis zu eine Sekunde. Der Versatz bleibt jetzt erhalten.
- **Qualität im Player wählbar:** Oben im Player steht „Qualität“. „Automatisch“ lädt höchstens 720p und geht von selbst eine Stufe herunter, wenn der Stream innerhalb einer Minute länger als sechs Sekunden stockt. Feste Stufen (z. B. 480p) und „Beste“ sind wählbar; die Wahl wird auf diesem Gerät gemerkt. Bisher wurde immer die höchste Stufe geladen, egal wie schnell die Verbindung war, und vor dem Start jede Stufe einzeln geprüft.
- **Safari und die macOS-App** spielen solche Streams selbst ab und passen die Qualität selbst an („Automatisch“). Wer dort eine feste Stufe wählt, bekommt den Stream über MediathekAtlas in genau dieser Stufe.
- **Offline speichern mit Auswahl:** Vor jedem Offline-Speichern fragt ein kleiner Dialog nach der **Auflösung** (Beste verfügbare, höchstens 2160p, 1080p, 720p, 480p, 360p) und zeigt, welche Stufen der Anbieter für diesen Titel hat. Gibt es denselben Titel bei mehreren Anbietern, lässt sich dort auch der **Anbieter** wählen. Die Auflösung wird für das nächste Mal gemerkt.
- **Dubletten:** „Ab ins Meer“ (YouTube) und „Ab ins Meer: Auf der Suche nach der verlorenen Perle“ (Netzkino) werden jetzt zusammengeführt, wenn Erscheinungsjahr (höchstens ein Jahr Abstand), Titel der Referenz, Laufzeit oder Beschreibung zusammenpassen. Ein fehlendes Jahr ist kein Widerspruch. Die gespeicherten Plattform-Ansichten werden nach dem Update einmal neu aufgebaut.
- **Live-TV:** Ein fehlerhafter Sendereintrag leert nicht mehr den ganzen Reiter; der Grund wird angezeigt. Blendet eine Suche oder ein Filter alle Sender aus, steht das dabei, mit „Alle Sender zeigen“. Leere oder langsame Antworten landen im Protokoll.
- **Nicht änderbar:** Live-Streams über das Internet laufen grundsätzlich 20 bis 40 Sekunden hinter Kabel und Satellit her; das liegt an der Technik der Anbieter.

## Neu in 0.5.65: Joyn

- **Joyn als Plattform:** Neuer Reiter „Joyn“ unter Plattformen und Quelle „Joyn“ im Dashboard. Geladen werden alle Filme und Serien der Joyn-Genreseiten – kostenlos (mit Werbung) und, getrennt gekennzeichnet, Joyn+. Die Kategorien „Joyn (kostenlos)“ und „Joyn+“ filtern danach. Bewertungen, Kategorien und Titelseite wie bei den anderen Plattformen.
- **Live-TV:** Die rund 125 Joyn-Sender stehen im Reiter Live-TV; Sender, die es auch bei ARD, ZDF & Co. gibt, erscheinen einmal mit beiden Anbietern.
- **Ansehen:** Joyn spielt nur im eigenen Player ab, in der Regel mit Kopierschutz. MediathekAtlas umgeht ihn nicht und meldet sich nicht bei Joyn an: „Bei Joyn ansehen“ öffnet joyn.de, wo du angemeldet bist. Kein Abspielen im MediathekAtlas-Player, kein Offline-Speichern. Folgenlisten einzelner Serien folgen, sobald ein Mitschnitt die Abfrage zeigt.

## Neu in 0.5.61: Archive.org-Filme und -Folgen herunterladen (wie in ArchiveMedia)

- Unter Plattformen → Internet Archive → „Fassungen, Folgen und Sprachen prüfen“ hat jede angezeigte Videodatei jetzt einen Knopf **„⬇ Herunterladen“**. Die Datei läuft durch die normale Download-Warteschlange: gleiche Ordner und Namen wie bei ARD/ZDF (`Filme/<Titel> (<Jahr>)/…`, `Serien/<Serie>/Season NN/…`), MKV mit Metadaten, NFO.
- **Dauerhaft:** Anders als bei Netzkino, Pluto & Co. gibt es keine 30-Tage-Frist. Die Lizenzangabe des Uploaders (z. B. „Public Domain“, Creative-Commons-Link) wird mit dem Auftrag gespeichert und angezeigt, aber nicht geprüft (Björns Entscheidung vom 12.11.2026: „alles wie in ArchiveMedia“).
- **Untertitel:** Im Upload mitgelieferte .srt/.vtt/.ass-Dateien werden nach dem Download neben das Video gelegt (z. B. `….de.srt`), vorhandene Dateien werden nie überschrieben.
- **Folgen ohne Nummer:** Ist bei einer Serienfolge Staffel oder Folge unbekannt, fragt die App beim Herunterladen danach (oder lädt die Datei als Film). Es wird keine Staffel 1 erfunden.
- Archive.org-Downloads bleiben auf diesem System (kein Verbund-Austausch) und markieren keine Mediathek-Sendung als geladen.


## Neu in 0.5.60: Plattform-Kataloge sofort, aufgeräumte Titelseiten, weniger Dubletten

Enthält 0.5.57 (Dashboard-Fix), 0.5.59 (Rakuten-Livesender) und die YouTube-Korrekturen (Werbevideos aussortieren, Einrichtung öffnet sich von selbst).

- **Plattform-Kataloge sofort:** Jede Plattform hält ihre fertig aufbereitete Liste gespeichert (Ordner `snapshots` im Datenordner), bis ein neuer Katalogabruf fertig ist. Reiter und Dashboard zeigen sie sofort, auch direkt nach dem Start und während Abruf oder Werkzuordnung in die Datenbank schreiben. Neue Bewertungen und Kategorien fließen im Hintergrund ein.
- **„Alle 24 Stunden aktualisieren“:** Über jedem Plattform-Katalog steht jetzt, ob die tägliche Aktualisierung an ist und von wann der Bestand stammt; „Verwalten“ öffnet den Bereich mit dem Schalter. Der Schalter bestätigt das Speichern und springt nicht mehr zurück, wenn gleichzeitig eine ältere Statusantwort eintrifft.
- **Titelseiten:** Kandidatenlisten mit tt-Nummern, „IMDb Offline“, „Erscheinungsjahr widersprüchlich“, die Zeile „Zuordnung“ und die Anbieterhinweise stehen nicht mehr auf der Seite, sondern im zugeklappten Bereich „Technische Angaben“ am Ende. „IMDb Offline“ heißt überall „IMDb“. Es gibt nur noch einen Offline-Knopf (oben, er speichert direkt); der Abschnitt „Offline ansehen“ erscheint erst, wenn eine Kopie existiert.
- **Dubletten:** „Ab ins Meer“ (YouTube) und „Ab ins Meer: Auf der Suche nach der verlorenen Perle“ (Netzkino) werden eine Kachel, wenn der Originaltitel des Uploads den Untertitel enthält oder dieselbe Kennung bzw. dieselbe Laufzeit (höchstens zwei Minuten Abstand, Spielfilmlänge) das belegt. Ohne Beleg bleibt es bei zwei Kacheln („Alien“ ist nicht „Alien: Covenant“).

## Neu in 0.5.59: Rakuten-TV-Livesender

- **Livesender:** Die Stream-Anfrage an Rakuten TV enthält jetzt dieselben technischen Felder wie die Website (Sitzungskennung, Player- und Qualitätsangaben). Werbekennungen, IP-Adresse, Browserkennung und eine Werbe-Einwilligung werden weiterhin nicht gesendet; die Einwilligung wird als abgelehnt übermittelt, die Werbung bleibt im Stream.
- **Stream-Adressen:** Live-Adressen von Werbe-CDNs werden nicht mehr wegen ihres Hosts oder ihrer Länge verworfen; die Kopierschutzprüfung (`hls_guard`) prüft jede Wiedergabeliste weiter.
- **Fehlermeldung:** Liefert Rakuten trotzdem keinen Stream, nennt die Meldung den Grund (Rakutens Fehlertext oder was in der Antwort fehlt), und die Diagnose enthält den Eintrag `rakuten_live_no_stream`.
## Neu in 0.5.57: Dashboard ohne Statusblöcke, Katalog sofort nach dem Start

- **Dashboard:** Die Kennzahlen („Katalog & Metadatenabgleich“, „Aktuelle Erkennung“) und der klassische Katalog mit zweiter Suchleiste stehen jetzt fest unter Verwaltung → „Status & Abgleich“ bzw. „Klassischer Katalog“. Bisher verschob sie erst ein Skript nach dem Laden dorthin; startete die App langsam, standen sie so lange doppelt im Dashboard.
- **Start:** Das Dashboard zeigt sofort die Plattformen (Netzkino, Pluto TV, JustWatch TV, Rakuten TV, YouTube). Der große Bestand von ARD, ZDF & Co. wird im Hintergrund eingelesen und ergänzt die Ansicht von selbst; die Statuszeile sagt das an. Ab dem zweiten Start kommt auch er sofort, weil die zuletzt berechnete Liste gespeichert wird (`listing-cache.json` im Datenordner) und im Hintergrund erneuert wird.
- **Blättern:** Die zusammengeführte Liste wird nicht mehr alle 45 Sekunden beim nächsten Klick neu aufgebaut, sondern im Hintergrund erneuert.
- **Diagnose:** Skriptfehler der Oberfläche und langsame Aufbauten der Gesamtliste (mit Sekunden je Quelle) stehen jetzt im Protokoll.

## Neu in 0.5.56: Archive Media Stufe 1 – Fanart.tv und Datenbanksicherungen

- **Fanart.tv:** Zusätzliche Poster, Hintergrundbilder und Titel-Logos für bereits erkannte Filme und Serien (über IMDb-, TVDB- oder TMDB-Kennung). Widerspricht die Kennung bei Fanart.tv, werden die Bilder verworfen. Vorhandene TMDB-/TVDB-Bilder bleiben, Fanart.tv füllt Lücken. Das Logo ersetzt auf der Titelseite den Schriftzug und wird bei Downloads als `clearlogo` für Jellyfin/Kodi abgelegt. Schlüssel unter Verwaltung → Einstellungen → Metadatenanbieter (Projektschlüssel und/oder persönlicher Schlüssel).
- **Datenbanksicherungen:** Die Katalogdatenbank wird wöchentlich geprüft gesichert (Ordner „Backups“ im Datenordner, SQLite-Online-Sicherung, die App bleibt nutzbar). Vier automatische Sicherungen bleiben erhalten, eigene nie automatisch gelöscht. Unter Verwaltung → Einstellungen → Datenbanksicherungen: Liste, „Jetzt sichern“, Mehrfachauswahl löschen mit Bestätigung. Unter Verwaltung → Aufgaben als „Datenbanksicherung“ pausier- und startbar.
- **ArchiveMedia v0.10.53:** `fanart_client` und `backup_manager` übernommen, die alten v0.10.12-Kopien angeglichen (Herkunft und Prüfsummen in `PROVENANCE.json`).


## Neu in 0.5.55: Dashboard nur mit Filmen und Serien, Bereich „Verwaltung“, schnellere Oberfläche

- **Dashboard:** Die Startseite zeigt nur noch Filme und Serien, standardmäßig aller Plattformen (ARD, ZDF & Co., Netzkino, Pluto TV, JustWatch TV, Rakuten TV, YouTube) in einer gemeinsamen, durchgehend sortierten Liste. Die Statuskarten oben sind in die Verwaltung umgezogen.
- **Ein Titel, eine Kachel:** Bietet mehr als ein Anbieter denselben Film an, steht er einmal da, mit den Anbietern in der Kopfzeile und unter „Auch bei …“ einem Satz Knöpfe je Anbieter. Zusammengefasst wird vorsichtig (gleicher Titel, passendes Jahr, nie zwei Einträge desselben Anbieters) und nur in der Anzeige; abschaltbar unter Verwaltung → Darstellung.
- **Verwaltung** (ein Menüpunkt mit Reitern): *Aufgaben* (jede Hintergrundaufgabe pausieren, fortsetzen, von Hand starten; Priorität für die Werkzuordnung je Plattform), *Status & Abgleich* (alle bisherigen Statuskarten), *Darstellung* (was Kacheln und Titelseite zeigen, Kachelgröße, Startansicht), *Zuordnung*, *Download-Abos*, *Werkkatalog* (die klassische Ansicht mit Genre-Baum), *Protokoll*, *Einstellungen*. Nichts wurde entfernt, nur verschoben.
- **Downloads:** Wartende Aufträge lassen sich vorziehen („Als Nächstes laden“) oder zurückstellen; die ganze Warteschlange lässt sich unter Aufgaben anhalten. Nacht-Vormerkungen zeigen ihre Startzeit und lassen sich sofort versuchen.
- **Plattform-Reiter:** Der Katalog steht jetzt oben, mit denselben Kacheln und Knöpfen wie im Dashboard. Katalogabruf, Bestand und Werkzuordnung der Plattform stehen eingeklappt darunter.
- **Tempo:** Laut Diagnose vom 12.11.2026 brauchte jede Katalogabfrage 7 bis 31 Sekunden und lief praktisch ununterbrochen (239-mal in sechs Stunden), weil die alte Katalogansicht bei jeder Zähleränderung neu lud. Dadurch warteten auch Plattform-Reiter, Live-TV und der Start von Streams. Jetzt kommen Katalogseiten aus dem Speicher (mit neuem Datenbankindex), die alte Ansicht lädt nur noch, wenn sie geöffnet ist.
- **Streams:** Online-Streams (HLS, z. B. Pluto TV und Live-Sender) werden gleichmäßiger an den Browser ausgeliefert (ein Abschnitt je Sekunde statt je Schlüsselbild-Intervall).

## Neu in 0.5.53: YouTube – kostenlose Filme und Serien offizieller Kanäle

- Neue Quelle YouTube: Katalog-Reiter „YouTube“ und Plattform-Reiter mit denselben Kacheln, Kategorien, Bewertungen, Titel- und Serienseiten und derselben Übersichtskarte wie die anderen Anbieter. Der IMDb/TVDB/TMDB-Abgleich läuft über die gemeinsame Werkzuordnung; ein Film, der schon bei einer anderen Plattform geprüft wurde, wird nicht erneut abgefragt.
- Kuratiert statt Suche: Gelesen werden nur die Kanäle und Playlists aus deiner Liste (Plattformen → YouTube → „YouTube-Kanäle & API-Schlüssel“). Aus Kanälen kommen nur ganze Filme (Mindestlänge, Standard 60 Minuten; ohne Trailer, Clips, Making-of, Livestreams). Eine Playlist kann als Serie eingetragen werden. In Deutschland gesperrte, private und Live-Videos werden ausgelassen. Vorschläge zum Start: FilmRise Movies, Paramount Vault, Popcornflix (englisch, ungeprüft; entfernbar).
- Benötigt einen kostenlosen API-Schlüssel für die offizielle „YouTube Data API v3“ (Google Cloud Console). Kein Auslesen von youtube.com.
- Abspielen im offiziellen YouTube-Player im MediathekAtlas-Fenster (mit der Werbung von YouTube), „Weiterschauen“ inklusive. Videos, deren Kanal das Einbetten verbietet oder die altersbeschränkt sind, öffnen „Bei YouTube ansehen“.
- Offline speichern (30 Tage) ist ein Schalter, **standardmäßig aus**. Die YouTube-Nutzungsbedingungen erlauben das Herunterladen nur über YouTube-eigene Funktionen oder mit Erlaubnis von YouTube und Rechteinhaber; Einschalten nur nach Bestätigung, auf eigene Verantwortung. Geladen wird mit yt-dlp (vorhandene Installation oder „yt-dlp einrichten“), ohne Anmeldung und ohne Umgehen von Alters- oder Regionssperren.

## Neu in 0.5.52: JustWatch – Nacht-Vormerkung nur bei echtem Zeitfenster, Hinweis bei Kopierschutz

- „🌙 Heute Nacht offline speichern“ erscheint nur noch bei Titeln, für die JustWatch selbst ein Jugendschutz-Zeitfenster meldet (FSK 16/18).
- Titel, die JustWatch nur im eigenen, kopiergeschützten Player (DRM) abspielt – z. B. die Folgen von „Andromeda“ –, zeigen „🔒 Kopiergeschützt (DRM): nur im JustWatch-Player“ und den Knopf „Bei JustWatch ansehen“. Wiedergabe und Offline-Kopie in MediathekAtlas sind dafür nicht möglich; der Kopierschutz wird nicht umgangen.
- 0.5.52 enthält außerdem alles aus 0.5.50 (Live-TV nach Sendern) und 0.5.51 (Rakuten TV).

## Neu in 0.5.51: Rakuten TV (kostenlose Filme, Serien und Live-Sender)

- Neue Quelle Rakuten TV: Katalog-Reiter „Rakuten TV“ und Plattform-Reiter mit allen kostenlosen Filmen (ca. 1.900) und Serien (ca. 120), gleiche Kacheln, Kategorien, Bewertung, Titel- und Serienseite (alle Staffeln) wie Netzkino, Pluto TV und JustWatch TV.
- **Wichtig:** Rakuten liefert kostenlose Filme und Folgen nur mit Kopierschutz (Widevine/PlayReady) aus – das zeigt der Mitschnitt von rakuten.tv eindeutig. MediathekAtlas umgeht das nicht. Diese Titel öffnen deshalb „Bei Rakuten TV ansehen“; Abspielen im MediathekAtlas-Player und „Offline speichern (30 Tage)“ gibt es für sie nicht.
- Die rund 160 kostenlosen **Live-Sender** von Rakuten TV laufen ohne Kopierschutz im MediathekAtlas-Player: im Plattform-Reiter unter „Live-TV“ und im Reiter „Live-TV“ zusammen mit ARD/ZDF und Pluto TV (nur live, nicht speicherbar).
- Der IMDb/TVDB/TMDB-Abgleich nutzt den gemeinsamen Abgleich: Filme, die schon auf einer anderen Plattform abgeglichen wurden, werden nicht erneut abgefragt.

## Neu in 0.5.50: Live-TV nach Sendern

- Neuer Reiter **„Live-TV“**: alle Live-Sender deiner Quellen an einem Ort, nach Sendern sortiert und gruppiert (Öffentlich-rechtlich, Regional (ARD), Pluto-Kategorien). Läuft ein Sender bei mehreren Anbietern, steht er einmal mit einem Knopf je Anbieter. Suche, Filter nach Anbieter und Gruppe, Favoriten (★) oben.
- **ARD, ZDF & Co. live:** die offiziellen Livestreams der Sender kommen aus der Filmliste (Thema „Livestream“). Sie werden nicht mehr als Werke abgeglichen.
- **Beim Anbieter:** Im Katalog unter „ARD, ZDF & Co.“ und „Pluto TV“ gibt es eine aufklappbare Live-Leiste; unter Plattformen → Pluto TV → Live-TV führt „Alle Sender im Reiter Live-TV →“ in die Senderübersicht.
- Der Player setzt Live-Sender nicht an einer gespeicherten Position fort. Live-Sender lassen sich nicht offline speichern.

## Neu in 0.5.49: Plattform-Ansicht wie der Katalog, JustWatch-Folgen, geteilter Abgleich

- Die Reiter Netzkino, Pluto TV und JustWatch TV unter „Plattformen“ zeigen oben dieselbe Übersicht wie der Katalog: Bestand, Stand, eindeutig zugeordnet, zu prüfen, ohne Treffer, noch offen, Offline-Kopien.
- Der Katalog-Reiter „Mediatheken“ heißt jetzt „ARD, ZDF & Co.“.
- JustWatch-Serien: Liefert die Sammelabfrage keine Folgen (z. B. „Andromeda“), werden die Staffeln einzeln geladen, so wie es die JustWatch-Seite tut.
- Ein Film, der schon für eine Plattform mit IMDb/TVDB/TMDB abgeglichen wurde, wird für eine andere Plattform nicht erneut abgefragt.

## Neu in 0.5.48: Geplanter Nacht-Download für JustWatch-Titel mit Jugendschutz-Zeitfenster

- Manche kostenlosen JustWatch-Titel (ab 16/18) gibt JustWatch nur von 0 bis 6 Uhr frei. Solche Kacheln haben jetzt „🌙 Heute Nacht offline speichern (30 Tage)“: Der Auftrag wird vorgemerkt („Vorgemerkt für 00:10 Uhr“) und startet im Zeitfenster von selbst, wenn MediathekAtlas dann läuft. Andere Downloads laufen in der Zwischenzeit normal weiter.

## Neu in 0.5.47: „30 Tage offline speichern“ in jeder Kachel

- Netzkino, Pluto TV und JustWatch TV haben in jeder Film-Kachel (Katalog und Plattform-Reiter) und in jeder Folgenzeile denselben Knopf „⬇ Offline speichern (30 Tage)“ mit Status: Vorgemerkt, Lädt mit Fortschritt und „Abbrechen“, „✓ Offline verfügbar bis …“, bei einem Fehler der Grund und „↻ Erneut offline speichern“.

## Neu in 0.5.46: Katalogfehler nennen die Ursache

- Scheitert der Abruf von Netzkino, Pluto TV oder JustWatch TV, steht jetzt dabei, woran es liegt (Name nicht auflösbar/Filter, Zertifikat, Zeitüberschreitung, Proxy, abgelehnt). Der Diagnose-Export prüft zusätzlich jeden Katalogserver (DNS, Verbindung, TLS).

## Neu in 0.5.45: Serienseiten mit allen Folgen – für jeden Anbieter gleich

- Serien von Pluto TV, JustWatch TV und Netzkino öffnen dieselbe Serienseite wie ARD/ZDF: Staffeln als Reiter („Alle · n“, „Staffel 1 · n“), darunter jede Folge mit ▶ Abspielen, ⬇ Offline speichern (mit Status) und Details. Eine Folge führt über „Zur Serie“ zurück, auch bei Netzkino.

## Neu in 0.5.44: Bessere IMDb-Zuordnung bei gleichnamigen Filmen

- Netzkino, Pluto TV und JustWatch TV liefern meist das Erscheinungsjahr mit. Gibt es mehrere Filme gleichen Namens (z. B. sechs IMDb-Treffer für „#Roxy“), gewinnt jetzt der Treffer mit genau diesem Jahr; ein Jahr Abweichung gilt nicht mehr als Widerspruch. Bisher „widersprüchliche“ Titel werden im Hintergrund automatisch neu geprüft.

## Neu in 0.5.43: Dateinamen mit Auflösung und Codecs

- Jeder Download (ARD/ZDF, Netzkino, Pluto TV, JustWatch TV) landet in einem eigenen Ordner und heißt nach dem Muster `Spellbound - (2024) - 1080p - H264 E-AC-3.mkv`. Auflösung und Codecs werden nach dem Download gemessen. Daneben liegen `….nfo`, `….metadata.json`, `…-poster.jpg` und `…-backdrop.jpg`; Serien: `Serien/<Serie> (<Jahr>)/Season 01/<Serie> - (<Jahr>) - S01E02 - 720p - H264 AAC.mkv` mit tvshow.nfo, poster und fanart im Serienordner.

- Download-Warteschlange: fehlgeschlagene Aufträge lassen sich entfernen, „Erneut versuchen“ erzeugt keine Doppelungen mehr, Pluto-Downloads mit Werbepausen gelten nicht mehr fälschlich als unvollständig.

## Neu in 0.5.42: Eine Detailansicht für alle Plattformen

- Netzkino, Pluto TV und JustWatch TV öffnen dieselbe Titelseite wie die ARD/ZDF-Werke (Cover, Jahr, Laufzeit, ★ Bewertung, Kategorien, Inhalt, Besetzung), egal ob aus dem Katalog oder unter Plattformen. Darunter für jede Plattform gleich: Folgen (Serien), Offline ansehen (30 Tage), Werkzuordnung (IMDb/TVDB/TMDB/OMDb/Wikidata) und „Angaben von <Anbieter>“ mit allem, was nur dieser Anbieter liefert.
- Netzkino-Offline-Download: Dateiadressen mit Leerzeichen („…Teil 1.mp4“) funktionieren wieder; fehlgeschlagene Aufträge mit „Erneut versuchen“ neu starten.

## Neu in 0.5.41: Kataloge bleiben gespeichert

- Netzkino-, Pluto- und JustWatch-Kataloge bleiben nach einem Neustart erhalten und werden als „Gespeicherter Bestand“ angezeigt; ein unterbrochener Abruf wird als solcher gemeldet. Beim allerersten Start werden sie einmal automatisch geladen.

## Neu in 0.5.40: JustWatch TV

- Plattformen → JustWatch TV: die kostenlosen eigenen Filme und Serien von JustWatch TV (ohne Plus, Leihtitel oder andere Dienste), mit Kategorien, Bewertung, Details, im Katalog unter „JustWatch TV“ und „Gesamt“.
- Titel, die JustWatch für externe Player freigibt, laufen im MediathekAtlas-Player und lassen sich 30 Tage offline speichern. Alle anderen öffnen die offizielle JustWatch-Seite. Kopiergeschützte (DRM-)Streams werden weder abgespielt noch gespeichert.

## Neu in 0.5.39: Genres und „Großes Kino“ wieder im Katalog

- Über den Katalogkarten stehen wieder die Mediathek-Genres mit Anzahl (Filme bzw. Serien), für Netzkino und Pluto TV deren Kategorien in derselben Leiste.
- „Entdecken“ mit „Großes Kino“ und „Serienfavoriten“ direkt im Katalog, für alle Quellen. Die klassische Ansicht mit Genre-Baum bleibt unter „Klassische Katalogansicht …“ erhalten.

## Neu in 0.5.38: Kategorien, Bewertungen und Details für Netzkino und Pluto TV

- Netzkino und Pluto TV zeigen Kategorien wie der Mediathek-Katalog (Genres aus IMDb, TVDB, TMDB; sonst die Angabe des Anbieters) mit Anzahl, dazu die IMDb-/TMDB-Bewertung und eine Sortierung nach Bewertung.
- Pluto TV hat eine Detailansicht (Cover, Inhalt, Kategorien, Referenzen, Ansehen, Offline speichern) und steht im Katalog unter „Pluto TV“ sowie im „Gesamt“-Katalog. Die Plattformübersicht zeigt Netzkino und Pluto mit Katalog, Abgleich und Offline-Kopien.
- Downloads von Netzkino und Pluto werden vor dem Einreihen mit IMDb/TVDB/TMDB abgeglichen und erhalten Genres, Besetzung, Cover/Hintergrund, IMDb-/TVDB-ID und Bewertung wie ARD-/ZDF-Downloads.
- Pluto TV: Offline-Frist 30 Tage (statt 20).

## Neu in 0.5.37: Pluto TV offline

- Pluto-Filme und -Folgen lassen sich mit „⬇ Offline speichern“ herunterladen. Sie laufen durch dieselbe Download-Warteschlange wie Mediathek- und Netzkino-Videos (gleiche Ordner und Namen, MKV mit NFO und metadata.json) und werden nach Ablauf der Frist automatisch entfernt. Die Datei enthält die Werbung, die Pluto ausliefert. Live-Sender sind nicht speicherbar.

## Neu in 0.5.36: Pluto TV

- Plattformen → Pluto TV: Filme, Serien und Live-Sender von Pluto TV laden („↻ Katalog jetzt laden“) und direkt im MediathekAtlas-Player ansehen, mit Werbung wie beim Anbieter. Keine Anmeldung.


## Neu in 0.5.34: Netzkino direkt abspielen

- „▶ Ansehen“ spielt Netzkino-Filme im eingebauten MediathekAtlas-Player ab, genau wie Mediathek-Videos (auch auf Synology/QNAP). Eine Offlinekopie hat Vorrang, sonst ermittelt ytdl-nightly die MP4-Datei.
- Netzkino bietet keine vollständige Titelliste an. Ab 0.5.35 liest der Katalogabgleich den Netzkino-Kategoriebaum (Genres, Themenkino, Partnerkataloge) mit vollständigen Kategorielisten statt nur der Startseiten-Auszüge. Zusätzlich lernt er Kategorien aus Filmdetails und optional aus einem Netzwerk-Mitschnitt (HAR): Plattformen → Netzkino → „Weitere Titel aus einem Netzkino-Mitschnitt übernehmen“.

## 0.5.32: Netzkino offline ansehen

- Netzkino-Titel lassen sich im Detailfenster mit **„Offline herunterladen (30 Tage)“** laden. Gespeichert wird genau wie bei Mediathek-Videos (gleiche Ordner, Dateinamen, MKV, NFO, Cover).
- Nach 30 Tagen entfernt MediathekAtlas die Datei automatisch; die Restlaufzeit steht im Detailfenster und in der Downloadliste.
- Die Dateiadresse ermittelt das mitgelieferte ytdl-nightly. Aktualisieren: `python3 tools/update_ytdl_nightly.py` (Entwickler) oder testweise `MEDIATHEKATLAS_YTDL_DIR=/pfad/zu/ytdl-nightly`.
- DRM-geschützte Titel werden nicht geladen. Netzkino liefert nur innerhalb Deutschlands aus.

## 0.5.25.1 – Verbund wiederherstellen und IMDb-Offline-Download absichern

- **Verbund:** Unter Einstellungen → Verbund kann ein NAS seinen bestehenden Verbindungscode anzeigen oder ausdrücklich einen neuen Schlüssel erzeugen. Die Schlüsselrotation benötigt eine eigene Bestätigung und macht bisherige eingehende Codes ungültig. Ausgehende Gegenstellen, Journal und Katalog bleiben dabei erhalten.
- **Code-Adresse:** Der Code nutzt den tatsächlichen MediathekAtlas-HTTP-Dienstport statt eventuell den DSM-/QNAP-Webinterface-Proxyport. Die NAS-Adresse lässt sich für Tailscale (100.x.x.x), LAN oder eigene Reverse-Proxy-Adressen anpassen; die Vorschau aktualisiert sich automatisch.
- **IMDb:** Ein kurzfristiger Netzwerkausfall beim ersten Download startet nicht den ganzen umfangreichen Import von vorn. Bereits vollständig heruntergeladene Datensätze bleiben bis zum erfolgreichen Erstimport zwischengespeichert (bis sieben Tage), begonnene Dateien werden mit HTTP Range fortgesetzt, sofern der Server dies unterstützt.
- **Diagnose:** Die IMDb-Statusabfrage enthält jetzt die vollständigen und teilweise heruntergeladenen Datei-Mengen. Es werden bis zu drei kurze Wiederholungsversuche pro betroffenem Datensatz unternommen; danach greift der bestehende gestaffelte Rückzug.
- **Geltungsbereich:** Die offiziellen IMDb-Datensätze dienen ausschließlich der zulässigen persönlichen, nichtkommerziellen Nutzung. Keine Umgehung von Authentifizierung, DRM oder Lizenzbedingungen.



## 0.5.25 · Parallele Metadatenerkennung und automatische Download-Abos

- **Erkennung:** Einstellbar mit 1, 2 (Standard) oder 4 parallelen Erkennungsworkern. Ein SQLite-basierter, eindeutiger Werk-Lease verhindert doppelte Prüfungen; abgelaufene Reservierungen werden nach Absturz wieder freigegeben. Externe Metadatenanbieter werden gleichzeitig von höchstens zwei Workerketten abgefragt. Status-Karten zeigen die aktiven und konfigurierten Worker.
- **Download-Abos:** Eigener Menüpunkt. Der Nutzer kann Filme oder Serien abonnieren – entweder „sobald verfügbar“ (Katalogabgleich in 15-Minuten-Abständen) oder mit einem wöchentlichen Prüfungstermin nach Gerätezeit. Nach dem wöchentlichen Start wird für 48 Stunden alle 15 Minuten nachgeprüft, damit leicht verspätete Veröffentlichungen nicht verloren gehen. Bei mindestens einem aktiven Abo wird die offizielle Filmliste inkrementell spätestens etwa alle zwei Stunden statt nur alle zwölf Stunden abgeglichen (sofern der automatische Katalogimport eingeschaltet ist). Titel- und Serienkennungen müssen eindeutig passen. Abos können pausiert, fortgesetzt, gelöscht und manuell geprüft werden.
- **Sicherheit und Rechte:** Automatischer Download ist ausdrücklich zustimmungspflichtig und wird nur für rechtmäßig zugängliche, direkt unterstützte Senderdateien mit bestätigter Werk- und bei Serien belegter Episodenidentität zugelassen. Keine HLS/DASH- oder DRM-Umgehung. Doppelte Aufträge werden nach Werk-/Episodenkennung, Zielpfad und bestehender Historie verhindert.
- **Persistenz:** Abos, nächste Prüfung, bereits eingereihte Episoden und die Zuordnung zwischen Abo und Downloadauftrag bleiben bei Neustarts erhalten. Bestehende Folgen können optional einbezogen werden; Serienabos nehmen standardmäßig nur spätere Folgen auf. Bereits eingereihte Aufträge bleiben beim Löschen eines Abos erhalten.
- **Verhalten:** Die Aboprüfung erstellt ausschließlich reguläre Downloadjobs. Der normale Download-Worker führt Übertragung, Umwandlung, Fehlerdiagnose und Wiederaufnahme aus. Fehlende oder nicht eindeutig verifizierte Folgen werden nicht automatisch als heruntergeladen betrachtet.
- **Validierung:** Regressionstests für Worker-Leases, Absturz-Wiederaufnahme, Titel- und Episodenabgleich, deduplizierte Aufträge, Wochenplan, abgelaufene Angebote und das Weiterbestehen von Abos nach DB-Neustart.



## Neu in 0.5.24: Nachrichtensendungen, Filmhinweise und effiziente Statistiken

- Bekannte, eindeutig benannte Nachrichten- und Magazinformate (beispielsweise „heute journal“, „heute in Europa“ oder „hallo deutschland“) werden vor unnötigen Film-/Serien-API-Anfragen als Sendungsbeiträge einsortiert. Die Zuordnung lässt sich bewusst über einen manuellen Prüfauftrag übergehen; bestätigte und manuell zugeordnete Werke sowie extern verifizierte Episoden bleiben geschützt.
- Bereits als Serie erkannte, aber nicht vollständig belegte tägliche Nachrichten-Ausgaben werden beim Formatabgleich ebenfalls berücksichtigt. Sendungsdaten und bisherige Anbieterkennungen bleiben erhalten; eine unbewiesene Staffel-/Folgenverifikation wird nicht übernommen.
- Bei „Filme zuerst“ werden bislang unbekannte Werke mit **ausdrücklichen Filmrubriken** oder klaren Filmhinweisen im Sendertext vor generischen Serien geprüft. Diese Hinweise bestimmen ausschließlich die Warteschlangenreihenfolge – sie bestätigen keine Filmidentität.
- Ein separater, kleiner Hintergrundlauf berechnet Filmhinweise für den bestehenden Katalog einmalig und resumierbar, ohne zusätzliche externe API-Anfragen. Neue Werke werden beim Import entsprechend vorgemerkt.
- Katalogstatus: Werktypen und Erkennungszustände werden in einer gruppierten SQL-Abfrage gezählt; die bisher vielen gleichartigen Tabellenzählungen werden eingespart.
- Neue Diagnosedaten: wie viele Nachrichteneinträge ohne externe Film-API abgefangen wurden. Diese zählen ausdrücklich **nicht** als erledigte Metadatenprüfungen oder als Erhöhung des Erstprüfungsdurchsatzes.
- Serienvervollständigung, verfügbare Downloads, die IMDb-Offline-Archivdetails und die kompakte UI aus 0.5.23 bleiben erhalten.
- Separate Performance-Arbeit (atomare parallele Erkennungsworker) folgt erst nach Vergleich der geänderten Katalogarbeit und SQLite-Latenzen.



## Neu in 0.5.23: Status-Dashboard und verschobene Downloads

**Build 47 – IMDb-Archiv transparent:** Im aufklappbaren Bereich „Katalog & Metadatenabgleich“ zeigt der Providerstreifen nun auch IMDb Offline und den letzten erfolgreichen Archivaufbau. Über „IMDb-Archiv“ sind alle sieben importierten Datensätze (Titel, Bewertungen, Episoden, Alternativtitel, Regie/Drehbuch, Mitwirkende, Personen), ihre Dateinamen, Zeilenzahlen und Übernahmezeitpunkte einsehbar. Dieselben Details stehen unter Einstellungen → IMDb-Offline-Archiv. Zeitstempel sind lokale Dateiabhol- bzw. Importzeitpunkte – keine Garantie für den Veröffentlichungszeitpunkt bei IMDb. Diese Detaildaten werden im SQLite-Snapshot dauerhaft gespeichert; ältere bereits erstellte Archive zeigen korrekterweise „nicht gespeichert“, bis der nächste erfolgreiche Import die Zahlen erfasst. Ein abgebrochener Update-Versuch darf den Datenstand des nutzbaren Archivs nicht verändern.

**Build 46 – Layoutverdichtung:** Auf breiten Bildschirmen erscheinen alle acht Statuswerte in einer Zeile; kleinere Fenster verwenden vier bzw. zwei Spalten. Karten, Anbieterstatus und Importdetails beanspruchen weniger Höhe, bleiben aber vollständig lesbar.

- Der Bereich „Katalog & Metadatenabgleich“ zeigt acht responsive Kennzahlen-Karten nebeneinander statt einer unübersichtlichen Statuszeile: aktiver Angebotsbestand, bestätigte Werke, erkannte Werke, vorgemerkte/ungeklärte Werke, Sendungsbeiträge, offene Erstprüfungen und echte Erstprüfungen pro Minute.
- Die letzte Filmlistenänderung erhält eigenständige, gut lesbare Markierungen für neue, geänderte, reaktivierte, weggefallene und unveränderte Angebote. Fortschritt und Fehler werden separat dargestellt.
- TMDB, TVDB, OMDb und Wikidata werden in eigenen Statusfeldern gezeigt. Der laufende Werkabgleich bleibt unabhängig davon sichtbar.
- Heruntergeladene Filme/Folgen bleiben in der Historie, auch wenn der Dateipfad veraltet ist oder ein Laufwerk derzeit fehlt. Die Oberfläche zeigt dann „Datei verschoben / derzeit nicht erreichbar“ statt ungültiger Wiedergabe- und Herunterladen-Schaltflächen.
- Unter „Downloads“ kann man eine fehlende Datei innerhalb freigegebener Bibliotheksordner suchen oder einen neuen absoluten Dateipfad manuell verknüpfen. Für verschobene Dateien außerhalb des ursprünglichen Downloadordners können unter „Einstellungen“ weitere Bibliotheksordner angegeben werden.
- Die Wiederverknüpfung ändert ausschließlich die Referenzen in der Datenbank. Der Originaldatei wird **nichts** angetan; vor dem Verknüpfen werden zugelassener Speicherort, unterstützter Medientyp und, soweit bekannt, Dateigröße geprüft. Mehrdeutige Ergebnisse werden nicht automatisch ausgewählt.
- Neue lokale Dateistatus-Prüfungen werden für 15 Sekunden zwischengespeichert, damit das regelmäßige UI-Polling nicht ständig alle Speicherorte neu abfragt. Die Suche ist auf 25.000 Dateien bzw. drei Sekunden je Benutzeraktion begrenzt.
- Die laufende Erstprüfung aus 0.5.22 bleibt im Hintergrund unverändert aktiv. Parallele Metadaten-Worker und ein Ablaufdatum-Radar gehören ausdrücklich zu einem separaten Folgeschritt.



## Neu in 0.5.22: Intelligente Warteschlange, Serienvervollständigung, Angebotsprüfung

- Die Erkennung kann in den Einstellungen zwischen **Ausgewogen**, **Filme zuerst** und **Serien zuerst** umgestellt werden. Manuelle Prüfungen behalten Vorrang; die Auswahl betrifft ausdrücklich nicht Downloadaufträge.
- Neue, noch nicht geprüfte Werke gehen automatisch vor fälligen Wiederholungen. Bereits gespeicherte Prüfversuche bleiben auch bei späterer Werk-Zusammenführung erhalten.
- Nach eindeutiger Serienerkennung können **bis zu 24** weitere fällige Folgen derselben Serie bevorzugt werden. Der Fokus ist zeitlich und mengenmäßig begrenzt, um Endlosschleifen und die erneute Überprüfung langer Nachrichtenformate zu verhindern.
- Das Öffnen der Serien-Detailseite löst keinen automatischen Massenabgleich mehr aus. Der manuelle Knopf „Metadaten abgleichen“ bleibt erhalten.
- **Dauerhafter anbieterbezogener Nichttreffer-Cache:** Erfolgreiche Anfragen ohne Treffer werden befristet gespeichert, um wiederholte API-Last zu verhindern. Netzwerkfehler und gesperrte Anbieter werden niemals als Nichttreffer vermerkt. Ausdrückliche manuelle Suche erzwingt eine neue Anfrage.
- Echte Erstprüfungen und Wiederholungen werden getrennt gezählt. Die Statusleiste zeigt die verbleibenden Erstprüfungen sowie eine Prognose auf Basis der beobachteten Netto-Erstprüfungen pro Minute.
- Zwei Senderangebote werden nur dann in der **Ansicht** zusammengefasst, wenn die tatsächlichen Video-/Untertitel-URLs, Sender, Laufzeit und Fassungsart exakt übereinstimmen. Unterliegende Datensätze und alle unterschiedlichen oder barrierefreien Fassungen bleiben erhalten.
- Geänderte Retry-Strategie: kurz gestörte Anbieter nach gestaffeltem Backoff erneut prüfen; bestätigte Nichttreffer frühestens nach mehreren Tagen wieder aufgreifen.



## Neu in 0.5.21: Doppelte Filme zuverlässig zusammenführen

- Ein Filmtitel kann aufgrund verschiedener Quellen zunächst mehrfach erkannt worden sein (z. B. „Der Rausch“ als „Komödie, Drama“ und „Drama“). Die Genre-Liste selbst ist keine Identität und erzeugt keine neue Werk-ID.
- Automatisches Zusammenführen erfolgt nur mit hinreichenden Belegen: exakt normierter Titel, gleiches bestätigtes Produktionsjahr, entweder übereinstimmende IMDb-/Anbieteridentität oder zwei unabhängig bestätigte Anbieter mit nahezu gleicher Laufzeit.
- Widersprüche bei Produktionsjahr, Anbieter-ID oder Laufzeit sowie zwei separat manuell gepflegte Werke verhindern automatisches Zusammenführen. Ähnliche Titel allein reichen nie aus.
- Beim Zusammenführen automatisch bestätigter Filme bleiben die vollständigen Genres aus beiden geprüften Zuordnungen, alternative Senderangebote, Download-Historie und manuell gepflegte Metadaten erhalten.
- Bereits vorhandene Dubletten werden nebenbei in kleinen, fortsetzbaren SQLite-Teilstapeln geprüft, statt beim Programmstart den gesamten Katalog zu blockieren.
- Das Diagnoseprotokoll meldet die Anzahl sicher zusammengeführter Filme, ohne unbestätigte Treffer zu verändern.



## Neu in 0.5.20: Inkrementeller Filmlistenabgleich, Serienwissen, Verfügbarkeit

- Die offizielle vollständige Filmliste wird weiterhin komplett geladen und kontrolliert, aber identische Angebote aktualisieren nicht mehr ihre Metadaten, Werkgruppen oder Nutzereinstellungen. Stattdessen notiert eine separate Tabelle nur ihre Identität.
- Erst nach **vollständigem** Import werden verschwundene Angebote als inaktiv markiert; abgebrochene Importe entfernen keine bisher aktiven Angebote.
- Diagnose und Status enthalten eine Änderungsstatistik mit neu, verändert, unverändert, reaktiviert und aus der Filmliste entfernt. Ein entfallener Eintrag wird archiviert, nicht gelöscht.
- Nur neue oder geänderte Werke landen in der Format-Nachprüfung. Eine bereits abgeschlossene Klassifikation wird nicht bei jedem Import über Hunderttausende Werke zurückgesetzt.
- Für bestehende, noch unbestätigte Serienfolgen werden eindeutig gelernte Serienidentitäten lokal wiederverwendet. Wenn IMDb Offline die genaue Episode bestätigen kann, wird sie zugeordnet; sonst bleibt die Episode ausdrücklich offen und nur das Werk wird erkannt. Manuell priorisierte Werke behalten die vollständige Provider-Suche.
- Beim Öffnen des Download-Dialogs wird, soweit möglich, bei ARD/ZDF nach einem ausdrücklich ausgewiesenen Ablaufdatum gefragt. Die Antwort wird angebotsbezogen zwischengespeichert. Bekannte Daten erscheinen in Detailansicht und vor dem Download, baldige oder abgelaufene Termine als Hinweis.
- Die Standard-MediathekView-Filmliste enthält normalerweise **kein** allgemeines Ablaufdatum. Wenn ein Sender keine explizite Information liefert, wird „Ablaufdatum nicht angegeben“ gezeigt. Das Sendedatum oder die Ablaufzeit eines API-Tokens wird nie als Verfügbarkeitsende verwendet.



## Neu in 0.5.19: Offline-Erkennung beschleunigt

- IMDb: Datenbankverbindung je Hintergrund-Worker wiederverwenden, statt für jede Werkprüfung eine neue Verbindung zu öffnen. Nach atomarer Aktualisierung des IMDb-Archivs wird die Verbindung automatisch neu geöffnet.
- IMDb: Der Diagnoseexport enthält ab jetzt unter `imdb.performance` Zähler für geöffnete Datenbankverbindungen und Cache-Treffer/-Fehlversuche.
- IMDb: Exakte Titel-, Episoden- und Besetzungsabfragen werden begrenzt zwischengespeichert. Werkabhängige Entscheidungen (etwa Laufzeit, Jahr oder Staffel/Folge) werden **immer pro Werk neu** berechnet. Dadurch entstehen keine übernommenen Fremdzuordnungen.
- Wenn IMDb Offline einen Film durch Laufzeit oder eine Episode durch exakte Episodenprüfung sicher bestätigt hat, werden unnötige Online-Anfragen übersprungen, selbst wenn das Archiv noch keine Genres liefert.
- Staffel-/Folgenummern aus dem Senderangebot können gegen IMDb Offline oder eine **vollständig gelesene** Anbieter-Episodenliste geprüft werden, auch wenn der Episodentitel anders lautet. Nur eindeutige Ergebnisse werden automatisch bestätigt; bei unvollständigen oder widersprüchlichen Daten bleibt die Zuordnung offen. Fehlende Zusatzdaten bleiben für die spätere Anreicherung offen.
- IMDb-Download: Die verfügbare Speichermenge wird vor der Übertragung anhand der gemeldeten Restgröße geprüft. Ein Speichermangel wird früh erkannt; das bisherige Archiv bleibt nutzbar.
- Regressionstests prüfen die Wiederverwendung der SQLite-Verbindung, das sichere Umschalten auf neue Datenbank-Snapshots sowie die Grenzen der automatischen Erkennung.
- Download-Warteschlange: Noch nicht gestartete Aufträge bleiben nach einem Neustart als `queued` erhalten und werden vom Worker automatisch übernommen. Nur tatsächlich laufende Aufträge werden zunächst als `interrupted` markiert (sichere Wiederaufnahme folgt gesondert).



Lokaler Film- und Serienkatalog mit automatischem Import der MediathekView-Filmliste, Metadatenabgleich und geordneten Downloads. Wiederverwendete ArchiveMedia-Module bilden die Grundlage für Titelerkennung, Anbieterabgleich, Dateinamen und Export.

## Neu in 0.5.18: Filme und Serien direkt abspielen

- „▶ Abspielen“ auf jeder Katalogkarte, auf den neuen Titelseiten (Film, Serie, jede Folge), in der Detailansicht und bei fertigen Downloads. Bei Serien heißt der Knopf „▶ Serie abspielen“ und startet die nächste ungesehene bzw. angefangene Folge; „Nächste Folge“ und automatisches Weiterspielen am Folgenende.
- Quelle: Ist der Titel schon heruntergeladen, läuft die lokale Datei (auch vom NAS auf jedem Gerät im Heimnetz), sonst der Online-Stream des Senders.
- Direkte MP4-Dateien der Sender spielt der Browser selbst, ohne Last auf NAS oder Mac. HLS-Streams (Safari, neuere Chrome-Versionen) ebenfalls direkt, sonst und für MKV-Downloads wandelt ffmpeg ohne Neukodierung des Bildes in einen MP4-Stream um (Ton nur bei Bedarf nach AAC). Das läuft auch auf älteren NAS.
- Eigene Zeitleiste mit Springen, ±10/30 Sekunden, Tastatur (Leertaste, Pfeile, f), Vollbild. Die Position wird je Titel auf dem Gerät gemerkt und beim nächsten Öffnen fortgesetzt („Von vorn“ startet neu).
- Sicherheit: Abgespielt wird nur, was in der eigenen Datenbank steht (Angebot oder Download), keine frei übergebenen Adressen oder Pfade. Höchstens drei gleichzeitige Umwandlungen; Spulen ersetzt den laufenden Stream.

## Neu in 0.5.17: Titelseiten für Serien und Filme

- „Serie öffnen“ zeigt jetzt eine eigene Serienseite statt nur eines Folgenrasters: Hintergrundbild, Poster, Serienbeschreibung, Jahr, Bewertung, Staffelzahl, Genres, Sender, Netzwerk, Studios, Regie, Drehbuch und Besetzung, darunter Staffel-Reiter und die Folgenliste mit Laufzeit, Qualität, Status, Folgenbeschreibung und weiteren Fassungen.
- Filme öffnen eine gleich aufgebaute Filmseite mit Fassungsauswahl (Sender, Audiodeskription, Gebärdensprache, Qualität) und allen Fassungen samt Dateien.
- Die Serienbeschreibung wird getrennt von der Folgenbeschreibung gespeichert (TMDB, TVDB, ARD-Sendereihe). Bisher hat die Folgenhandlung sie überschrieben. Bestehende Serien erhalten sie beim nächsten Bildabgleich nach; das Öffnen einer Serienseite stößt ihn bevorzugt an.
- Zurück über den Knopf, die Browser-Zurück-Taste oder Esc; die Katalogposition bleibt erhalten.
- Platz für den Abspielknopf ist vorgesehen. Er erscheint, sobald der Browser-Player verfügbar ist.

## Neu in 0.5.16: Erkennung entlastet (Diagnose vom 6. November)

- Ausgaben von Nachrichten- und Magazinsendungen, die nur die ARD- bzw. ZDF-Mediathek erkannt hat (z. B. 3.215 Ausgaben „Schleswig-Holstein Magazin“), werden unter ihrer Sendung geführt und nicht mehr einzeln abgefragt. Bild, Beschreibung und Genres der Mediathek bleiben erhalten. Bestehende Kataloge werden beim Start einmal nachsortiert.
- Ist das OMDb-Tageskontingent aufgebraucht, bleibt ein Werk nicht mehr nur deswegen in der Wiederholung, wenn das Offline-IMDb-Archiv es bereits geprüft hat (OMDb liefert dieselben IMDb-Daten).
- Titelzusätze wie „(Originalversion mit Untertitel)“, „(mit Untertitel)“ oder „(OmU)“ werden vor dem Abgleich entfernt. arte-Rubriken („Politics and society - Insights“, „Culture - Pop culture“) gelten nicht mehr als Sendungsname; stattdessen wird der Reihentitel vor „ - “ gesucht.
- Wikidata: Sehr allgemeine Titel mit zu großer Antwort zählen als „nicht gefunden“ statt als Fehler mit stündlicher Wiederholung.
- IMDb-Archiv: Ein abgebrochener Download wird fortgesetzt statt neu begonnen, fertige Dateien bleiben bis zu zwei Tage erhalten, Wiederholungen warten 1, 2, 4 … bis 24 Stunden. Fehlt Speicher, sagt die Meldung, dass das bisherige Archiv nutzbar bleibt.
- Eine Neuprüfung, deren Mediathek gerade pausiert war, wird nicht mehr als Ergebnis an den Verbund verteilt.
- Die Diagnose-ZIP enthält jetzt Katalogzahlen und die Erkennungsquote je Sender.

## Neu in 0.5.15: Mehrere Direktverbindungen je System

- Jedes System kann beliebig viele Verbindungscodes aufnehmen („Verbindung hinzufügen“). Bisher hat jeder neue Code die vorherige Verbindung und den eigenen Freigabeschlüssel überschrieben.
- Freigabe und Verbindungen sind getrennt: „Freigabe beenden“ betrifft nur den eigenen Code, jede Verbindung hat ihren eigenen „Entfernen“-Knopf und eine eigene Statuszeile.
- Der eigene Code wird beim Hinzufügen erkannt und abgelehnt.
- Empfehlung: Synology und QNAP freigeben, auf jedem System die Codes der jeweils anderen NAS hinzufügen. Systeme reichen Ergebnisse weiter, ein Stern um ein NAS reicht ebenfalls.

## Neu in 0.5.14: Klarere Direktverbindung

- In der Mac-/Desktop-App gibt es „Dieses System freigeben“ nicht mehr: Sie ist nur auf dem eigenen Rechner erreichbar, ihr Code konnte nie funktionieren („Connection refused“). Freigeben lässt sich nur ein NAS; Mac und weitere NAS verbinden sich mit dessen Code. Mehrere Systeme hängen sternförmig am freigegebenen NAS, das die Ergebnisse weiterreicht.
- „Verbindung abgelehnt“ wird erklärt (kein MediathekAtlas unter der Adresse, Dienst gestartet?, Code der Mac-App).

## Neu in 0.5.13: Start auf QNAP QTS 5.2

Auf QNAP (QTS 5.2, TS-932X) beendete sich der Dienst sofort: QTS hat den Befehl `nohup` nicht. Der Start kommt jetzt ohne ihn aus; Python ignoriert das Auflegesignal selbst. QPython-Pakete (`/opt/QPython3*`) werden gezielt gesucht.

## Neu in 0.5.12: Startprobleme auf dem NAS ohne SSH sichtbar

Startet der Dienst auf Synology oder QNAP nicht (kein passendes Python, Port belegt, fehlende Rechte), liegt jetzt `MediathekAtlas-Startproblem.txt` mit Grund und den letzten Protokollzeilen im Download-Ordner (z. B. `Download/MediathekAtlas`), lesbar in File Station. Nach dem nächsten erfolgreichen Start verschwindet die Datei. Auf QNAP wird Python zusätzlich in allen bekannten Ordnern des App-Center-Pakets „Python3“ und von Entware gesucht. Enthält außerdem die Verbund-Verbesserungen aus 0.5.11.

## Neu in 0.5.11: Große Bestände im Verbund ohne Aussetzer

Bei sehr großen Beständen (getestet wurde im Feld mit rund 88.000 erkannten Werken) konnte die Übernahme auf dem NAS so lange am Stück laufen, dass Lebenszeichen und Direktverbindung ins Stocken kamen („Gegenstelle nicht erreichbar (timed out)“). Jetzt:

- Fremde Ergebnisse werden in kleinen Paketen (250) mit höchstens 20 Sekunden je Runde übernommen; danach kommen Lebenszeichen und Abgleich wieder dran. Die Statuszeile zeigt „Übernahme läuft, weitere Ergebnisse folgen“.
- Der eigene Bestand wird gebremst geteilt (500 Werke alle 20 Sekunden) und pausiert, solange die Gegenstelle nicht erreichbar ist.
- Zeitlimit je Anfrage der Direktverbindung 60 Sekunden.

## Neu in 0.5.10: QNAP-Paket installierbar

Das QPKG 0.5.9 wurde vom App Center mit „file format error“ abgelehnt: Dem Paket fehlte das Prüffeld im Fußbereich, das QNAPs Hilfsprogramm `qpkg_encrypt` schreibt; der Build hatte dessen Fehlen nur als Warnung gemeldet. `build_nas.py` schreibt das Feld jetzt selbst (byte-gleich mit dem QNAP-Werkzeug geprüft), die CI kontrolliert es. Sonst keine Programmänderung gegenüber 0.5.9.

## Neu in 0.5.9: Bisherige Erkennungen werden im Verbund geteilt

Bisher teilte ein System nur Ergebnisse, die nach dem Einschalten des Verbunds entstanden. Jetzt veröffentlicht jedes System beim ersten Verbinden einmalig auch alle schon vorhandenen Zuordnungen (manuell, zugeordnet, Werk erkannt), in Paketen zu 1000 Werken je 30 Sekunden. Die Verbundanzeige zeigt den Fortschritt („Bisherige Ergebnisse werden geteilt: … übertragen, noch … Werke“). Die anderen Systeme übernehmen sie ohne eigene Anbieterabfrage; eigene manuelle Zuordnungen bleiben unangetastet.

Neu als Paket: `MediathekAtlas_0.5.14.qpkg` für QNAP QTS (architekturunabhängig, über App Center → Manuell installieren). Python ab 3.9 („Python3“ aus dem App Center oder Entware) muss installiert sein; der Einrichtungscode für das erste Passwort liegt danach im Download-Ordner.
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

MediathekAtlas lässt sich als Dienst auf einem NAS betreiben: `MediathekAtlas-0.5.14-noarch.spk` für Synology DSM 7 und `MediathekAtlas_0.5.14.qpkg` für QNAP QTS, jeweils architekturunabhängig (x86_64, ARM64, ARMv7). Downloads landen direkt in einer NAS-Freigabe; Katalog und Einstellungen bleiben im lokalen Paketdatenordner. Die Weboberfläche ist im Heimnetz unter Port 8730 erreichbar und durch ein Passwort geschützt (Synology: Installationsassistent, QNAP: Einrichtungscode im Download-Ordner). Der Dienst läuft ohne Root-Rechte. Details, Pfade und Grenzen: `packaging/README.md`.

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

Die App ist eine unsignierte Preview mit lokaler Browseroberfläche. Ein echter macOS-Finderstart ist hier weiterhin nicht validiert. Der Source-Ordner enthält zusätzlich `Start.command` und `Start.bat`. Seit 0.5.80 gibt es eigene Pakete für Windows (Setup.exe, ZIP) und Linux (.deb, tar.gz), siehe oben; aus dem Quellordner startet Linux weiter mit `python3 server.py`.

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

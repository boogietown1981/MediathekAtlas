# MediathekAtlas · 0.6.167

## Neu in 0.6.167: gesperrte Reihen kommen nach „Zurücknehmen“ sofort wieder, Kinderecke schneller
- Wird eine Sperre in der Elternansicht zurückgenommen, steht die Reihe beim nächsten Aufbau wieder in der Kinderecke (vorher teils erst nach 10 Minuten oder einem Neustart).
- Die Kinderecke baut sich schneller auf (Reihenprüfung liest Themen und Folgen nur noch einmal je Aufbau).

## Neu in 0.6.166: Netzkino-Beschreibungen, weniger Doppel in der Kinderecke
- Netzkino-Filme bekommen ihre Beschreibung (und fehlendes Jahr/FSK) aus den schon geladenen Filmdetails; das hilft auch der Erkennung.
- Kinderecke: dieselbe Folge erscheint auch innerhalb einer Reihe nur einmal (z. B. zwei Einträge gleicher Länge bei Pluto).

## Neu in 0.6.165: Kinderecke – verschoben nummerierte Folgen und „Zurücknehmen“
- Zählen zwei Sender dieselbe Folge unterschiedlich (z. B. „Conni“ bei ZDF-tivi Folge 5, bei KiKA Folge 6), erscheint sie bei gleichem Titel und gleicher Länge nur einmal.
- „Zurücknehmen“ einer Sperre stellt eine vorher erteilte Freigabe wieder her, statt sie mitzulöschen; die Reihe kommt zurück.
- YouTube: Bleibt ein Download stehen, weil yt-dlp YouTubes Player nicht entschlüsseln kann, wird yt-dlp jetzt auch dann sofort erneuert.

## Neu in 0.6.164: Kinderecke – zusammengeführte Reihen vollständig und ohne Doppel
- Eine Kachel aus gleichnamigen Reihen zeigt jetzt alle Folgen beider Teile (vorher endete die Liste bei 400, z. B. „Schloss Einstein“).
- Dieselbe Folge von zwei Sendern erscheint nur einmal, auch wenn ein Sender keine Folgennummern angibt.
- Sperren oder Freigeben einer solchen Kachel gilt für alle ihre Teile; Zurücknehmen ebenso.
- Das Platzhalterbild von TheTVDB („kein Bild“) wird nicht mehr als Bild der Reihe gezeigt.

## Neu in 0.6.163: weniger YouTube-Anfragen, keine falschen „Bot“-Meldungen
- Ein Abo, bei dem noch Videos ausstehen, fragt YouTube nicht mehr alle 20 Minuten nach der Kanalliste. Es lädt die schon bekannten Videos nach und liest die Liste erst nach dem eingestellten Abstand (Standard 3 Stunden) neu. „Jetzt prüfen“ und geänderte Einstellungen lesen sie sofort.
- „This video is not available“ wird nicht mehr als „Bot-Sperre“ bezeichnet. Eine echte Bot-Prüfung von YouTube („confirm you're not a bot“) bleibt eine eigene Meldung mit Pause.
- Scheitern zwei verschiedene Videos nacheinander mit derselben Meldung, pausieren die YouTube-Downloads einmal gemeinsam, statt jedes Video einzeln zu versuchen und zu melden. „YouTube-Zugang prüfen“ hebt die Pause bei Erfolg sofort auf.

## Neu in 0.6.162: Kinderecke ohne doppelte Reihen
- Reihen mit gleichem Namen (z. B. „Animanimals“), die von verschiedenen Sendern oder Anbietern kommen, stehen in der Kinderecke nur noch einmal. Beim Öffnen erscheinen die Folgen aller Teile zusammen, doppelte Folgen nur einmal. Reihen mit verschiedenen Namen bleiben getrennt.

## Neu in 0.6.161: „YouTube-Zugang prüfen“
- Im YouTube-Bereich (Offline-Speichern) prüft ein Knopf ein Video, ohne es herunterzuladen: das zuletzt gescheiterte oder eine eingegebene Video-ID/-Adresse. Kann yt-dlp YouTubes Player nicht mehr entschlüsseln, wird es sofort aktualisiert und noch einmal geprüft; klappt es, werden die gescheiterten Videos erneut versucht.

## Neu in 0.6.160: YouTube-Kindervideos laden wieder (yt-dlp hält sich selbst aktuell)
- YouTube hat seinen Player geändert; das mitgelieferte yt-dlp konnte ihn nicht mehr entschlüsseln. Normale Videos liefen über einen Umweg weiter, Kindervideos scheiterten mit „This video is not available“. MediathekAtlas erkennt das jetzt, holt selbst eine neuere yt-dlp-Version (offizielle Ausgabe, Prüfsumme geprüft, höchstens zweimal am Tag) und versucht die betroffenen Downloads erneut.

## Neu in 0.6.159: YouTube-Fehler ehrlich erklärt
- Scheitert ein YouTube-Download mit „This video is not available“, obwohl Deno eingerichtet ist, rät MediathekAtlas nicht mehr zu „Deno einrichten“, sondern nennt die wahrscheinlichen Gründe (Sperre der Adresse, Kindervideo, regional gesperrt) und versucht es später erneut. Der Deno-Rat erscheint nur noch, wenn Deno wirklich fehlt; ist yt-dlp zu alt, heißt es „yt-dlp einrichten“.
- Die Diagnose hält zu jedem gescheiterten YouTube-Download fest, welche YouTube-Zugänge yt-dlp probiert hat, ob Deno benutzt wurde und was yt-dlp gemeldet hat (ohne Adressen).

## Neu in 0.6.158: Fortsetzungen bleiben einzeln
- Filmfortsetzungen wie „Zärtliche Chaoten“ (Pluto TV), „Freitag der 13“ (Rakuten, Joyn) oder „The Lies We Tell …“ (Plex) werden nicht mehr zu einem Mehrteiler zusammengefasst; die Genres der Plattformen zählen jetzt mit. Echte Mehrteiler (Traktorgiganten, Elvis, Kolbenfresser, Vera Brühne …) bleiben eine Kachel.
- Kinderecke: „Die wilde Natur“ bekommt sein passendes Vorschaubild zurück.

## Neu in 0.6.157: Bilder und Mehrteiler genauer
- Kinderecke: Ein YouTube-Vorschaubild wird nur genommen, wenn ein ganzer Teil des Videotitels zur Reihe passt; zu allgemeine Reihennamen („Die Serie“) bekommen keines. Ganze Filme aus dem YouTube-Katalog („Die drei Musketiere der Neuzeit“) werden nicht mehr verwechselt.
- Mehrteiler wie „Kolbenfresser“ stehen wieder in einer Kachel; nur Spielfilme mit eigenem Jahr je Teil gelten als Fortsetzungen.
- Filme einer Filmreihe erscheinen in der Suche als „Film“ (nicht „Serie · 1 Folgen“), der Player zeigt „Tatort – Filmtitel (Jahr)“.

## Neu in 0.6.156: Filmreihen öffnen sich richtig
- Der Knopf einer Filmreihen-Kachel heißt „Alle Filme“ und zeigt alle Filme der Reihe (vorher Fehlermeldung „Serie nicht gefunden“). Die Kachel nennt das Jahr des neuesten Films.
- Mehrteiler: Teile mit Zusatz im Titel („Kolbenfresser Teil 1 Maisernte hautnah“) gehören dazu; Fortsetzungen wie „Zärtliche Chaoten“ bleiben einzeln, auch ohne IMDb-Nummer.
- Kinderecke: Die Bildersuche liest den YouTube-Bestand nur noch einmal je Lauf und endet spätestens nach 2 Minuten.

## Neu in 0.6.155: Feinschliff nach den Prüfungen 0.6.152–0.6.154
- Mehrteiler mit Teilen aus verschiedenen Jahren (z. B. „Traktorgiganten Teil 1–4“) stehen wieder in einer Kachel; Fortsetzungen, die eigene Filme sind (z. B. „Zärtliche Chaoten“), bleiben einzeln.
- Kinderecke: Ist das Stundenlimit der Senderabfragen erreicht, bekommen Reihen trotzdem ein passendes Vorschaubild aus dem eigenen YouTube-Bestand.
- Die Zeitanzeige des Players geht am Ende der Leiste nicht mehr über die Gesamtdauer hinaus.

## Neu in 0.6.154: Filmreihen und Mehrteiler wieder zusammengefasst, korrigiert
- Unter „Filme“ stehen Filmreihen (Tatort, Polizeiruf 110, Nord bei Nordwest …) und Mehrteiler (Teil 1–n) wieder als je eine Kachel. Die Kachel öffnet alle Filme der Reihe bzw. alle Teile einzeln, Reihen mit den neuesten zuerst.
- Korrigiert nach der Prüfung von 0.6.150: eine Reihe erscheint nur noch einmal (Praxis mit Meerblick), Filme wie „Tatort: Azra“ gehören mit in die Tatort-Reihe, auch Titel mit einem zweiten Anbieter (Maria Wern). Fortsetzungen aus verschiedenen Jahren (Zärtliche Chaoten Teil 1 und 2) gelten nicht als Mehrteiler, Fassungen (Audiodeskription) zählen nicht als eigene Teile, „Teil 1/ 2“ wird richtig gelesen.
- Eine Suche zeigt weiter jeden Film einzeln.

## Neu in 0.6.153: Filmreihen-Kacheln vorerst aus
- Die Sammelkacheln „Filmreihe“ und „Mehrteiler“ aus 0.6.150 sind ab Werk ausgeschaltet, bis ihre Korrektur geprüft ist (Prüfung 0.6.150: eine Reihe doppelt, einzelne Tatort-Filme nicht erfasst, Fortsetzungen als Mehrteiler). Unter „Filme“ steht wieder jeder Film einzeln wie in 0.6.149. Alles andere aus 0.6.150–0.6.152 bleibt.
- Lokale Filmarchive (Prüfung 0.6.151): „sample.mkv“ im Filmordner erscheint nicht mehr als zweiter Film; übergangene kleine Videos (unter 20 MB) werden je Ordner genannt; Tippfehler beim Ordner erscheinen nur als Hinweis, nicht als Fehler im Protokoll.
- MKV-Dateien (lokales Archiv und eigene Downloads) brechen im eingebauten Player nicht mehr kurz nach dem Start ab bzw. springen nicht mehr zurück.

## Neu in 0.6.152: Korrekturen aus der Prüfung von 0.6.147
- Kinderecke: Mit der Maus über „Mehr davon“ fahren hält den Countdown zur nächsten Folge an. „Mehr davon“ zeigt die laufende Reihe nicht mehr selbst an.
- Kinderecke-Bilder: Die Bildsuche bei ARD/ZDF behält einen Teil des Stundenlimits (20 von 120) und versucht es nach 10 statt 60 Minuten erneut, wenn das Limit erreicht war. Reihen ohne Senderseite (viele KiKA-Reihen) bekommen das Vorschaubild eines passenden YouTube-Videos aus dem eigenen Bestand.
- „⬇ Geladen“ nur noch, wenn die Datei wirklich da ist (verschobene oder gelöschte Downloads zählen nicht mehr).
- Diagnose-Export enthält die Senderstatistik auch beim ersten Abruf mit altem Stand. Film- und Serienliste kommen nach 10 Minuten sofort aus dem Speicher und werden im Hintergrund erneuert.

## Neu in 0.6.151: Lokale Filmarchive auf Ordnern und Freigaben
- Einstellungen → „Lokale Filmarchive“: eigene Film- und Serienordner eintragen, z. B. eine eingebundene NAS-Freigabe (/Volumes/Filme). MediathekAtlas liest dort nur, verändert und löscht nichts.
- Liegen NFO-Dateien (Kodi, Jellyfin, Emby) daneben, werden Titel, Jahr, Beschreibung, Genres, Bild und IMDb-/TMDB-Nummer direkt übernommen; die IMDb-Nummer entscheidet dann den Abgleich. Ohne NFO werden Datei- und Ordnernamen gedeutet (Titel, Jahr, S01E02, Staffelordner) und wie die Plattform-Titel über IMDb, TVDB und TMDB zugeordnet.
- Neue Quelle „Lokales Archiv“ im Katalog; gleiche Titel anderer Anbieter landen in derselben Kachel. Archivtitel gelten als „⬇ Geladen“ und laufen im eingebauten Player (MKV & Co. über ffmpeg).
- Neu eingelesen wird alle 6 Stunden und auf Knopfdruck, nur Neues und Geändertes. Ist eine Freigabe nicht eingebunden, bleiben die Titel erhalten und sind als offline markiert.

## Neu in 0.6.150: Filmreihen und Mehrteiler unter Filme zusammengefasst
- Unter „Filme“ stehen Reihenfilme einer Mediatheken-Reihe (Tatort, Polizeiruf 110, Der Usedom-Krimi …) ab drei Filmen als EINE Kachel „Filmreihe · n Filme“; sie öffnet die Filme der Reihe. Sendeplätze wie „FilmMittwoch im Ersten“ oder „Herzkino“ sind keine Reihe und bleiben einzeln.
- Mehrteiler („… Teil 1“, „… (2/3)“) stehen als eine Kachel „Mehrteiler · n Teile“; sie zeigt die Teile in Reihenfolge.
- Eine Suche zeigt weiterhin jeden Film einzeln; Kinderecke und Ansehen-Modus bleiben unverändert.

## Neu in 0.6.149: Kinderecke-Kanäle repariert, Fortschritt überall sichtbar
- Kinderecke: Ein neu abonnierter Kanal zeigt beim Antippen oben seine Videos (vorher blieb die Ansicht leer). In „Alle“ stehen die Kanalreihen jetzt direkt nach „Neu“ und „Weiterschauen“, vor den Film- und Seriengruppen.
- Fortschritt wie bei YouTube: Katalogkarten zeigen einen roten Balken für Angefangenes und „✓ Gesehen“ für Fertiges; Starten setzt an der gemerkten Stelle fort (wie bisher im Player). Die Kinderecke übernimmt auch Stände, die im großen Player entstanden sind.

## Neu in 0.6.148: Nummerierte Folgen als eine Serie, geladene Titel zuerst
- Anbieter führen Folgen einer Reihe oft als einzelne Filme mit vorangestellter Nummer („10. Die verwegenen Vier auf heißer Spur“, „2. Die verwegenen Vier reißen aus“). Ab drei solchen Filmen desselben Anbieters mit gemeinsamem Titelanfang zeigt die Kinderecke EINE Serienkachel („Die verwegenen Vier“), die Folgen darin nach Nummer sortiert. Abspielen, Weiterschauen und Sperren funktionieren wie vorher.
- Geladene Filme und Serien zuerst: Titel mit lokaler Kopie (ARD/ZDF-Downloads; Plattform-Kopien von Netzkino, Pluto, Plex, ServusTV, Red Bull TV …) stehen in der Kinderecke in jeder Reihe vorn, tragen „⬇ Geladen“ und werden unter „Mehr davon“ bevorzugt. Im normalen Katalog (Filme/Serien, Ansehen-Modus) stehen sie ebenfalls vorn und sind markiert; eine Serie gilt als geladen, sobald eine Folge geladen ist.

## Neu in 0.6.147: Kinderecke schlägt nach dem Video Passendes vor
- Am Ende eines Videos, Films oder einer Folge zeigt die Kinderecke wie YouTube eine Reihe „Mehr davon“: weitere Videos desselben Kanals, Titel aus demselben Thema (Tiere, Wissen, Märchen …) und Titel mit gemeinsamen Wörtern, Ungesehenes und Neues zuerst. Vorgeschlagen wird nur, was die Kinderecke ohnehin zeigt (Freigaben, Sperren und Altersgrenze gelten weiter). Feste Regeln, keine KI.
- Die Suche findet neue Reihenfilme sofort nach dem Markierlauf (in 0.6.144–0.6.146 blieb eine vorher gestellte Suche bis zum Neustart veraltet).
- Die nächste Folge startet weiterhin nach 6 Sekunden; wer in den Vorschlägen blättert oder tippt, hält den Countdown an. Nach einem Film bleiben die Vorschläge stehen, bis ein Kind wählt oder „Zurück“ drückt (nach einer Minute automatisch zurück).

## Neu in 0.6.146: Kinderecke kompakter und mit mehr Bildern
- Die Reihen der YouTube-Kanäle sind nur noch so hoch wie ihre Kacheln (die „Alle …“-Kachel am Ende hat jetzt die Form der Reihe).
- Reihen aus den Mediatheken, für die es nirgends ein Bild gab, bekommen das Bild der Sendung von der ARD- bzw. ZDF-Mediathek (im Hintergrund, stündlich, mit derselben Drosselung wie die Erkennung). Gleichnamige Filme und Serien teilen sich ein Bild.

## Neu in 0.6.145: filmfriend vollständig
- Liefert filmfriend eine Seite des Katalogs nicht, fragt MediathekAtlas sie nach kurzer Pause noch einmal ab und liest danach die übrigen Seiten weiter. Fehlt eine Seite trotzdem oder kommen deutlich weniger Titel als beim letzten vollständigen Abgleich, gilt der Abgleich als teilweise und die bisherigen Titel bleiben sichtbar (vorher fehlte nach einem einzigen Fehler gut ein Drittel des Katalogs für einen Tag).
- Die Diagnose wartet auf eine aktuelle Senderstatistik, wenn nur ein alter Stand vorliegt, und nennt dessen Alter.

## Neu in 0.6.144: Filmliste ohne Wartezeit nach Katalogänderungen
- Ändert sich der Katalog im Hintergrund (zum Beispiel neue Reihenfilme), zeigt die Filmliste sofort den bisherigen Stand und aktualisiert sich im Hintergrund, statt hinter dem Aufbau der Kinderecke zu warten. Suchen warten ebenfalls nicht mehr darauf.

## Neu in 0.6.143: unterwegs und auf kleinen Macs
- Das IMDb-Update startet nur, wenn neben dem Archiv genug Platz ist. Sonst steht „Wartet auf Speicherplatz“ da, nichts wird geladen, und alle 15 Minuten wird neu geprüft. Bereits geladene Dateien bleiben erhalten.
- Bricht der Download der Filmliste ab (Mobilfunk, Hotspot), setzt der nächste Versuch an derselben Stelle fort. Ohne Netz wartet MediathekAtlas länger zwischen den Versuchen (10, 30, dann 60 Minuten); „Jetzt starten“ geht immer sofort. Eine Anmeldeseite eines WLANs wird als solche gemeldet.
- filmfriend hält nach drei Verbindungsfehlern an und versucht es später erneut, statt Hunderte Fehler zu sammeln.
- Auf Macs mit Apple-Chip startet MediathekAtlas ein natives Python (arm64) bevorzugt; läuft nur ein Intel-Python unter Rosetta, steht ein Hinweis im Startprotokoll und in der Diagnose.
- Die Diagnose enthält Arbeitsspeicher, Auslagerung, Speicherdruck, Rosetta und die Größe der Datenbanken.

## Neu in 0.6.142: Reihenfilme auch unter Filme
- Filme einer Reihe (Der Usedom-Krimi, Die Füchsin, Die drei von der Müllabfuhr, Tatort, Polizeiruf 110 …) bleiben in ihrer Reihe und stehen zusätzlich einzeln unter Filme, mit eigenem Filmtitel und Filmjahr („Die drei von der Müllabfuhr – Altlasten“, 2023). Die Suche findet sie auch über den Filmtitel.
- Als Reihenfilm gilt eine erkannte Folge ab 80 Minuten, die der Sender als deutschsprachigen Spielfilm oder Fernsehfilm ankündigt (Produktionsland Deutschland, Österreich oder Schweiz; ohne Landangabe zählt der Film als deutschsprachig). Folgen von Serien mit gezählten Teilen (Rebecka Martinsson „Del 1“, Brokenwood, Mord auf Shetland), Fassungen desselben Films und Filme, die es schon als eigenen Film gibt, erscheinen nicht zusätzlich.

## Neu in 0.6.139 (enthält 0.6.138): More than Honey, regionale Nachrichtensendungen
- Filme, deren Jahr in der IMDb zwei Jahre abweicht, werden mit passender IMDb-Laufzeit jetzt tatsächlich verknüpft („More than Honey“ 2010/2012); „Black Box“ 2022 bleibt getrennt vom US-Film.
- Regionale Nachrichtensendungen ohne Nachrichtenwort im Namen (hessenschau, DER TAG in Berlin & Brandenburg, Abendschau, Lokalzeit …) tragen das Genre Nachrichten statt Kultur oder keinem Genre.

## Neu in 0.6.136: 3sat-Filme, Sport-Genres, Kinderecke ohne Kopierschutz-Kacheln
- 3sat-Filme werden auch erkannt, wenn die Datenbank eine Reihennummer im Titel führt („Mankells Wallander 01 – …“) oder das Jahr zwei Jahre abweicht – nur mit exaktem Titel und einer Laufzeit, die zur IMDb-Angabe passt („More than Honey“ 2010/2012; „Black Box“ 2022 wird nicht mit dem US-Film von 2020 verwechselt).
- Sport-Sendungen („Sport-Clip“, „Sport-Arena“, „Paris 2024“, „Sportschau Wintersport“) tragen das Genre Sport statt Nachrichten oder Talk; Nachrichtensendungen (tagesschau24, hessenschau) bleiben Nachrichten.
- Kinderecke: ein Netzkino-/Plex-Film, der wegen Kopierschutz oder fehlender Verfügbarkeit nicht spielt, verschwindet für 7 Tage aus der Liste.

## Neu in 0.6.134: Märchen in der Kinderecke spielen wieder
- Filme mit mehreren KiKA-Angeboten (Das Märchen von der Regentrude, Der Schweinehirt, Die sechs Schwäne …) ließen sich in der Kinderecke nicht abspielen („Dieses Video gibt es in der Kinderecke nicht“). Jedes Angebot vom Kindersender ist jetzt zulässig.
- Filme der Mediatheken erscheinen in der Kinderecke nur noch, wenn ihr Angebot aktiv ist (oder lokal gespeichert) und sie nach aktuellem Stand zugelassen sind.

## Neu in 0.6.132: Krimireihen bleiben Serien, 3sat-Filme, Genres, freier Speicher am Mac
- Nummerierte Folgen einer Reihe („Brokenwood (7/20)“, „Rebecka Martinsson (02/08)“) werden nicht mehr als Filme zurückgeholt; Zweiteiler und einzelne Spielfilme bleiben Filme.
- 3sat-Filme: ein Autorenname vor dem Titel („Mankells Wallander – …“) stört die Suche nicht mehr; bei Filmen auf „prüfen“ steht im Protokoll, warum der Kandidat nicht genommen wurde.
- Genres aus der Reihe nur noch, wenn mindestens drei Folgen ein eigenes Genre tragen und zwei Drittel davon dasselbe; bisher so nachgetragene Genres werden einmal neu bewertet.
- Am Mac zeigt die App den freien Speicher wie der Finder (einschließlich löschbarem Platz).

## Neu in 0.6.131: verschiedene Sendungen gleichen Namens bleiben getrennt
- Reihen werden nur noch bei echten Leerzeichen-Unterschieden zusammengeführt („#BR24 Zeitreise“/„#BR24Zeitreise“); Sendungen, die sich nur in Groß-/Kleinschreibung oder Satzzeichen unterscheiden (KiKA „ECHT“, WDR „Echt?“, MDR „Echt“), bleiben getrennt und behalten ihren Namen.

## Neu in 0.6.130: Reihennamen ohne Großschreibung, Trailer als Trailer, sauberer Programmführer
- Zusammengeführte Reihen behalten ihre normale Schreibweise („Nachtcafé“ statt „NACHTCAFÉ“).
- 3sat-Filmtitel, zu denen nur ein kurzer Trailer vorliegt („Kurzer Prozess – Righteous Kill“), stehen als Trailer da statt auf „prüfen“; kommt der ganze Film, wird er wieder als Film geprüft.
- Programmführer: keine Unterzeile „Deutschland 2015“ mehr bei täglichen Serien, keine doppelten 3sat-Einträge und keine überlappenden Blöcke bei phoenix.

## Neu in 0.6.129: Programmführer im Live-TV nachgebessert
- phoenix, KiKA und 3sat zeigen das Programm nur noch aus einer Quelle; „Jetzt“ ist die tatsächlich laufende Sendung statt eines langen Sendeblocks, und was mitten im Block beginnt, steht als „Ab 13:00“ da.
- Tägliche ARD-Serien zeigen ihre Folgennummer („Rote Rosen · Folge 2019“) statt einer scheinbaren Jahreszahl.
- „ARD Tagesschau“ gehört zu tagesschau24 (Programm und Mediathek-Knopf in einer Kachel); arte zeigt seine zwei Livestreams als „ARTE.DE“ und „ARTE.FR“.

## Neu in 0.6.128: aussortierte Filme zurück, bessere Reihennamen
- Filme mit einem kurzen Ausschnitt als erstem Angebot („Kurzer Prozess – Righteous Kill“) bleiben Filme; maßgeblich ist das längste Angebot. Von 0.6.123/0.6.125 aussortierte Filme kommen zurück.
- Fortsetzungen werden in allen üblichen Schreibweisen gesucht („Der Pate II“ = „Der Pate – Teil II“); bei mehreren gleichnamigen Filmen entscheiden Jahr und Laufzeit.
- Zusammengeführte Reihen tragen die lesbare Schreibweise („Eishockey aktuell“ statt „eishockeyaktuell“), unsichtbare Trennzeichen fallen weg.

## Neu in 0.6.127: weniger „Unbekannt“, keine doppelten Reihen durch Leerzeichen
- Werke ohne Genre (im Werkkatalog „Unbekannt“) bekommen es nachgetragen: aus dem IMDb-Archiv, wenn sie mit IMDb verknüpft sind, sonst von den anderen Folgen ihrer Reihe.
- Reihen desselben Senders, die sich nur in Leerzeichen unterscheiden („#BR24 Zeitreise“/„#BR24Zeitreise“), werden eine Reihe.

## Neu in 0.6.126: Programmführer im Live-TV
- Die Sender von ARD (Das Erste, Dritte, ONE, ARD alpha, tagesschau24), ZDF (mit ZDFneo, ZDFinfo, 3sat, KiKA, phoenix) und SRF zeigen im Live-TV, was gerade läuft (mit Fortschritt) und was danach kommt – direkt aus den Programmdaten der Sender, ohne Konto und ohne Schlüssel, alle 6 Stunden aktualisiert (Live-TV → „Programmführer · ARD, ZDF, SRF“, abschaltbar).
- In der Detailansicht eines Werks führt „Sendetermine bei Wunschliste“ zur Suche bei TV Wunschliste (nur als Link; MediathekAtlas liest die Seite nicht aus).

## Neu in 0.6.125: Filme bleiben Filme, Einstellungen sofort gespeichert
- Filme in Spielfilmlänge (ab 60 Minuten) bleiben Filme, auch mit Nummer im Titel („Der Amsterdam-Krimi (2)“, „Wo ist Anne Frank – Teil 1“); nur datierte Sendungsausgaben und kurze nummerierte Teile gelten nicht als Film. Die Neu-Einordnung aus 0.6.123 nimmt nur noch solche Werke.
- Einstellungen werden auch direkt nach dem Start sofort übernommen: ist die Datenbank belegt, gilt die Änderung gleich und wird im Hintergrund gespeichert.

## Neu in 0.6.124: 3sat-Filme besser erkannt, Kinderecke schneller nach dem Start
- 3sat-Filme, deren Titel zwei Namen verbindet („The Pledge - Das Versprechen“, „Jussi Adler-Olsen: Erlösung“), werden auch über den einzelnen Titelteil im IMDb-Archiv gefunden – nur mit passendem Jahr; automatisch verknüpft nur, wenn auch die Laufzeit passt.
- Nach einer Änderung der Suche werden erneut geprüfte Titel wirklich neu gesucht statt mit dem gespeicherten alten Ergebnis beantwortet.
- Die Kinderecke wird nach dem Start erst vorbereitet, wenn die einmaligen Aufräumarbeiten fertig sind – der erste Aufruf muss sie dann nicht neu bauen.

## Neu in 0.6.123: keine Sendungsausgaben mehr unter „Filme“
- Datierte Sendungsausgaben („10 vor 10 vom 21.11.2026“), nummerierte Teile („Teil 3“, „Folge 12“) und Videos unter 20 Minuten werden nicht mehr als Film eingeordnet, nur weil die Beschreibung „Film“ enthält; Kurz-, Animations- und Trickfilme bleiben Filme. Bereits so eingeordnete offene Werke werden einmal neu eingeordnet.
- Einstellungen (z. B. Serien automatisch laden) speichern während der Start-Heilungen: bei belegter Datenbank wird gewartet und wiederholt statt „database is locked“ zu melden.

## Neu in 0.6.122: Bilder in der Kinderecke, abgeschnittene Titel, längere Diagnosen
- Kinderecke: Reihen und Filme ohne eigenes Bild nehmen das Bild eines anderen Angebots, einer anderen Folge oder der erkannten Reihe statt nur des Anfangsbuchstabens; Dokus stehen nicht mehr unter „Zeichentrick“; die Kopfleiste ist deckend.
- Titel, die der Sender nach 80 Zeichen abschneidet („… (Originalversion“), werden ohne den Rest des Hinweises gesucht und einmal neu geprüft.
- Der Bilder-Abgleich schreibt Fehler je Titel nur noch einmal am Tag und Erfolge als Stichprobe ins Protokoll – eine Diagnose reicht dadurch deutlich länger.


## Neu in 0.6.120: Schreibweise je Sender
- Markenschreibweisen (KiKANiNCHEN) gelten nur für den Sender, der sie selbst so schreibt: ARD und MDR behalten „Mittagsmagazin“, SRF „MittagsMagazin“. Auch Ausschnitte und Extras einer Reihe werden angeglichen.


## Neu in 0.6.119: 3sat-Filme, Jahrgänge, Schreibweisen
- 3sat-Filme mit Titelzusatz („… - Spielfilm, USA 1993“) werden verknüpft, wenn Titel und Jahr stimmen – vorher blieben sie auf „prüfen“, sobald die Laufzeit nicht passte.
- Jahrgänge („Dein Song 2022“ … „2026“) kommen auch aus „prüfen“ unter die bekannte Reihe.
- Schreibweisen werden nur noch zu einer belegten Markenschreibweise angeglichen (KiKANiNCHEN); sonst bleibt alles, wie der Sender es schreibt.
- Altersrunde der Kinderecke wartet auf die Start-Heilungen; eine belegte Datenbank ist kein Fehler mehr.


## Neu in 0.6.118: Korrektur der Erkennung aus 0.6.117
- Sportarten und Themenwörter („Schwimmen“, „Sport“) werden nie mehr zur Serie – unter jedem Thema. Echte Sendungen (Tell-Star, Cinema Strikes Back, Sonntagsmärchen) und Reihen, die IMDb oder TVDB kennen (Formel 1), bleiben unangetastet.
- Jahrgänge einer Sendung („Dein Song 2022“ bis „2026“) werden eine Reihe, auch mit nur einer Folge je Jahr und bei ZDF/KiKA gemischt.
- Eine Reihe hat eine Schreibweise (KiKANiNCHEN), nie die ganz großgeschriebene, wenn es eine andere gibt.
- Filmlisten-Import übersteht eine belegte Datenbank (kein „database is locked“ mehr nach den Start-Heilungen).
- Kinderecke: „Gevatter Tod“ & Co. warten mit eigenem Grund.


## Neu in 0.6.117: Erkennung sauberer, Kataloge täglich aktuell, Kinderecke genauer
- Sportarten wie „Schwimmen“ gelten nie mehr als Serie; eine nur bei Wikidata bekannte Serie wird nicht mehr auf alle Beiträge eines Themas übertragen. Bereits falsch zugeordnete Beiträge werden neu erkannt.
- Jahrgänge einer Sendung („Dein Song 2023“, „Dein Song 2024“) erscheinen als eine Reihe; das Jahr steht im Folgentitel.
- filmfriend, DMAX/TLC, Red Bull TV und dailyme aktualisieren sich jetzt täglich (in den Einstellungen der Plattform abschaltbar).
- Bilder: Einträge, die TVDB nicht kennt, werden erst nach einer Woche wieder abgefragt statt stündlich.
- Kinderecke: dunkle Märchen wie „Gevatter Tod“ warten auf Freigabe, „Aschenputtel“ ist sichtbar.

## Neu in 0.6.116: Märchen zurück in der Kinderecke, ganze Sendungen werden erkannt, Vorschläge schneller
- Märchen- und Kinderbuchverfilmungen mit belegter Altersfreigabe (z. B. Aschenputtel, Der kleine Lord, Heidi und Peter) stehen wieder in der Kinderecke; die Liste ist direkt nach dem Start vollständig.
- Ganze Sendungen, die nur wegen Wörtern wie „Pressekonferenz“ als Clip galten (z. B. eine nummerierte Serienfolge), werden jetzt normal erkannt. Podcasts und Trailer bleiben Clips.
- Kanal-Vorschläge werden schneller aufgelöst.

## Neu in 0.6.115: Kinderecke – Familienfilme nur mit eigenem Kindersignal
- Ein Familienfilm mit Altersfreigabe kommt nur noch automatisch in die Kinderecke, wenn er erkennbar für Kinder ist (Zeichentrick, Märchen, bekannte Kinderbuch-Vorlage oder Kinderreihe). Alle anderen warten im Elternbereich auf deine Freigabe.
- Die Diagnose nennt, welche Titel bei einem Neuaufbau der Kinderecke hinzukommen oder wegfallen.

## Neu in 0.6.114: Nachbesserungen an Erkennung, Kanal-Vorschlägen und Kinderecke
- Sendungen, die IMDb ohne Einzelfolgen kennt, werden jetzt wirklich als Beiträge abgelegt (in 0.6.113 blieb das aus).
- Interviews und Ausschnitte zu einem erkannten Film oder einer Serie erscheinen als Extra dazu, nicht als eigene Sendung.
- Kanal-Vorschläge suchen zuerst für das Kinderprofil und sind schneller.
- Die Kinderecke lässt Erwachsenen-Fernsehfilme draußen, blendet leere Plattform-Reihen aus und lädt wieder schnell.

## Neu in 0.6.113: Erkennung räumt auf, YouTube-Vorschläge mit API-Schlüssel, Kinderecke spielt das KiKA-Angebot
- Trailer, Vorschauen, Podcasts und Pressekonferenzen bleiben nicht mehr dauerhaft „offen“: Trailer gehören als Extra zu ihrer Reihe, die übrigen Clips werden als Clip abgelegt, nie als Folge einer echten Serie.
- Sendungen, die IMDb ohne Einzelfolgen kennt (z. B. Sportpanorama, Euromaxx), führen ihre Ausgaben jetzt sofort als Beiträge, statt 30 Tage auf die Folgensuche zu warten.
- Läuft der Abgleich leer, steht im Protokoll, warum die übrigen offenen Werke warten (z. B. Angebot abgelaufen).
- Kanal-Vorschläge funktionieren auch mit eigenem YouTube-API-Schlüssel.
- Hat eine Folge ein KiKA-Angebot, zeigt und spielt die Kinderecke genau dieses.
- Eltern können sichtbare Titel der Kinderecke direkt sperren (Einstellungen → Kinderecke · Eltern → „In der Kinderecke“).

## Neu in 0.6.112: Kinderecke genauer
- Jugend- und Reportageformate wie „Young Crime“ oder „POV“ zeigen in der Kinderecke nur Folgen von KiKA; andere Folgen warten auf Ihre Freigabe.
- Reihen ohne abspielbare Folge erscheinen nicht mehr. TOGGO-Serien fehlen deshalb, solange TOGGO sie nur mit Kopierschutz anbietet.
- Eine geänderte Altersgrenze wirkt in beide Richtungen sofort auch für Netzkino, Plex und Pluto TV.

## Neu in 0.6.111: Angefangene Serien genauer nachladen
- Gibt es eine Folge in deutscher Fassung und als Originalfassung mit Untertiteln, wird nur eine davon geladen, bevorzugt die deutsche. Ist nur eine Sonderfassung ladbar, steht das am Auftrag in der Downloads-Liste.
- Wurde die Folge in der Kinderecke zu Ende gesehen, lädt MediathekAtlas nur Folgen und Filme nach, die die Kinderecke auch zeigen würde.
- Sehr lange Serien (über 1.000 Folgen) laden die Folgen rund um die zuletzt gesehene, statt gar nichts.

## Neu in 0.6.110: Kanal-Vorschläge mit Namen und Kanalbild
- Vorschläge unter YouTube → Kanal-Abos → „Neue Kanäle entdecken“ zeigen jetzt Namen und Kanalbild. Für die Kinderecke stehen deutschsprachige Kanäle mit erkennbarem Kinderbezug vorn; englischsprachige und solche ohne Kinderbezug rutschen nach hinten.
- Die Suche liefert schon beim ersten Mal Vorschläge, auch wenn noch nichts zu Ende geschaut wurde.

## Neu in 0.6.109: Kinderecke zeigt nur, was selbst für Kinder ist
- Reihen, in denen nur einzelne Folgen von KiKA, TOGGO oder ZDFtivi stammen (z. B. „WUMMS“, „Young Crime“), zeigen nur noch diese Folgen. Sportschau, Nachrichten und Livestreams erscheinen nicht mehr unter Filme und Serien.
- Live-Fernsehen gibt es in der Kinderecke nur unter „Fernsehen“ und nur mit echten Kindersendern; „Familie“ im Sendernamen reicht dafür nicht.
- Die Altersgrenze im Elternbereich gilt jetzt auch für Netzkino, Plex und Pluto TV. Familienserien für Erwachsene kommen nicht mehr über die Altersfreigabe hinein.
- „Wartet auf Freigabe“ zeigt alle wartenden Titel, nicht mehr höchstens 300.

- Reihentitel werden nur noch behutsam an die Schreibweise des Senders angepasst (aus „kulturzeit“ wird „Kulturzeit“, aus „KIKA LIVE“ „KiKA LIVE“), nie mehr in Großbuchstaben („MDR Sachsenspiegel“ bleibt).
## Neu in 0.6.108: Filme von 3sat werden wirklich gesucht
- Filme mit dem 3sat-Zusatz im Titel („8 Mile - Spielfilm, USA 2002“) werden jetzt als Erstes neu gesucht. In 0.6.97 standen sie auf „prüfen“ und kamen nie an die Reihe.
- Ein Film mit um ein Jahr abweichendem Jahr gilt nur noch ab 40 Minuten Laufzeit; zwei Kurzclips von SRF („Sport“, „Moda“), die so fälschlich Filme wurden, werden neu erkannt.
- Sendungen, für die IMDb keine Einzelfolgen kennt, stehen jetzt im Protokoll, und die Regeln für Werke ohne Art laufen einmal neu über den Bestand.

## Neu in 0.6.106: Kinderecke strenger, Reihen unter ihrem bekannten Namen
- Eine Reihe heißt so, wie der Sender sie schreibt: „KiKA LIVE“ statt „KIKA LIVE“ aus TMDB.
- Ableger einer KiKA-Reihe („KiKA LIVE fordert heraus“, „KiKA LIVE #ZuHauseUmDieWelt“, „KiKA LIVE - Fragen an die Astronautinnen“ …) stehen unter der Hauptreihe statt als eigene Mini-Reihen; der Ableger steht im Folgentitel.
- „Anna, Nina, Pia und die wilden Tiere“, „Paula, Anna und die wilden Tiere“ und „Checker Can, Checker Tobi und Checker Julian“ (BR/ARD) zählen als Kinderprogramm und erscheinen in der Kinderecke.
- „Kinder“ im Namen allein macht nichts mehr zum Kinderprogramm („Die Kinder von Lügde“, „Ein Herz für Kinder“, „Kinderärzte im Einsatz“); solche Zuordnungen werden einmalig entfernt.
- Kinderecke: automatisch nur noch Angebote von KiKA, TOGGO und ZDFtivi, bekannte Kinderreihen (Maus, Sandmännchen, Löwenzahn, Checker …), Filme mit Kinder- oder Familienkennung aus einer Filmdatenbank und Ihre Freigaben. Alles andere steht unter „Wartet auf Freigabe“. Titel mit heiklen Wörtern (Porno, Missbrauch, Krieg, Mord, Krimi …) erscheinen nur, wenn sie von einem Kindersender kommen oder Sie sie freigegeben haben.

## Neu in 0.6.105: Altersregel der Kinderecke strenger
- Über die Altersfreigabe kommt ein Film nur noch in die Kinderecke, wenn er zusätzlich als Familienfilm eingeordnet ist; nie neben Science-Fiction, Action, Mystery oder Romantik. „Fantasy“ oder „Abenteuer“ allein reichen nicht mehr (Monster-, Hai- und Actionfilme ab 12 aus Netzkino und Plex), solche Titel stehen unter „Wartet auf Freigabe“.
- Die Altersfreigaben aus Wikidata werden jetzt auch für Filme gesucht, die über TMDB erkannt wurden.


## Neu in 0.6.104: Sammelstand
- Enthält 0.6.103 (Kinderecke wieder gefüllt, Live-Sender spielen; mit 0.6.99 Altersfreigabe und Elternbereich), 0.6.100 (Kanal-Vorschläge, Abo-Einstellungen bleiben offen) und 0.6.101 (Serien-Nachladen mit deutscher Fassung).

## Neu in 0.6.103: Kinderecke wieder gefüllt, Live-Sender spielen
- 0.6.98 und 0.6.99 zeigten in der Kinderecke keine Filme und Serien, und jeder Live-Sender meldete „'str' object has no attribute 'get'“. Ursache: Ein einziger Titel eines anderen Portals mit anderer Datenform brach den ganzen Listenaufbau ab. Jetzt wird jedes Feld nur in der erwarteten Form gelesen, und ein unlesbarer Titel wird übersprungen und protokolliert statt die Liste zu leeren.
- Reihen vom Kinderkanal KiKA (z. B. „Wissen macht Ah!“, „Der Krieg und ich“, „KiKA LIVE“) stehen immer in der Kinderecke. Solange die Liste nach dem Start noch entsteht, steht dort „wird noch zusammengestellt“.
- Eine weitergeblätterte Reihe springt beim automatischen Aktualisieren nicht mehr an den Anfang zurück.

## Neu in 0.6.101: Serien-Nachladen lädt die deutsche Fassung
- Angefangene Serien und gesehene Filme werden in der deutschen Fassung geladen, nicht als Originalversion mit Untertitel, Hörfassung oder Gebärdensprache, wenn es die deutsche gibt.
- Fehlen Folgen zwischen der gesehenen und der nächsten ladbaren, nennt der Kasten unter Downloads die Lücke. Das Fenster (Standard 20 Folgen) füllt sich sofort, nicht in Zehnerschritten.

## Neu in 0.6.100: Kanal-Vorschläge mit echten Treffern
- Unter YouTube → Kanal-Abos → „Neue Kanäle entdecken“ kommen Vorschläge jetzt aus den Playlists deiner Abos, aus @Kanal-Erwähnungen in Beschreibungen und Titeln und aus einer YouTube-Suche nach den Schlagwörtern gesehener Videos. Für die Kinderecke werden kindgerechte Kanäle bevorzugt und Prank-, Horror- oder Gaming-Kanäle nach hinten gestellt.
- Freigeben geht weiterhin erst nach dem Probeschauen; eine Freigabe lädt zum Start die 3 neuesten Videos.
- Abo-Einstellungen und die Vorschau in „Neue Kanäle entdecken“ bleiben bei der Aktualisierung offen (Korrektur aus der Prüfung).

## Neu in 0.6.99: Kinderecke nach Altersfreigabe, Elternbereich, Kindersender live
- Automatisch in die Kinderecke kommt: alles von KiKA und TOGGO; sonst nur Erkanntes, das eindeutig Kinderprogramm ist oder als Familien-, Animations-, Fantasy- oder Abenteuerfilm eine belegte Altersfreigabe bis zur eingestellten Grenze hat (z. B. Bibi & Tina, Märchen unter „Fantasy“); nie neben Horror, Thriller, Krimi, Erotik, Krieg oder Romantik. Ein Drama ab 12 kommt nicht allein über die Altersfreigabe hinein.
- Altersgrenze FSK 0, 6 oder 12 (Standard 12) unter Verwaltung → „Kinderecke · Eltern“. Dort stehen auch die Titel, die auf deine Freigabe warten (nicht erkannt, ohne oder mit zu hoher Altersfreigabe), mit „Freigeben“/„Sperren“; jede Entscheidung lässt sich zurücknehmen.
- Altersfreigaben (FSK) holt die App im Hintergrund aus Wikidata über die IMDb-Kennung; Anbieter mit eigener FSK-Angabe zählen ebenfalls. Das IMDb-Archiv enthält keine Altersfreigaben.
- Neuer Knopf „Fernsehen“ in der Kinderecke: nur Kinder- und Familiensender live (z. B. KiKA), im Elternbereich abschaltbar.

## Neu in 0.6.98: Kinderecke ohne Nachrichten- und Talkreihen
- Eine Serie von ARD, ZDF & Co. steht nur noch in der Kinderecke, wenn sie selbst eindeutig Kinderprogramm ist (mindestens 80 % der eingeordneten Folgen, KiKA/TOGGO oder Kinderreihe). Nachrichten-, Talk-, Politik- und Magazinreihen („heute“, „Politik“, „NACHTCAFÉ“, „Abendschau“ …) erscheinen nie, auch wenn einzelne Beiträge „Kinder“ heißen.
- In einer Kinderserie fehlen Folgen, die als Nachrichten, Talk, Drama o. Ä. eingeordnet und nicht selbst Kinderprogramm sind.
- Das Genre „Kinder“ wurde bisher auch aus Beschreibungen übernommen („Wenn Kinder pflegen“); das passiert nicht mehr und wird nach dem Start einmalig bereinigt.

## Neu in 0.6.97: Erkennung – falsche Sendungs-Zuordnungen zurück, Filme bei 3sat/ARD, Lernreihen
- Werke, die 0.6.88–0.6.96 über einen unsicheren Vorschlag (Wikidata, Namensvetter ohne Jahr, nur Sendername als Thema) einer fremden Serie zugeordnet hatten, sind wieder offen. Solche Vorschläge entscheiden nicht mehr allein.
- Kennt IMDb eine Sendung, aber keine Einzelfolgen (Sportpanorama, Euromaxx …), werden ihre Werke Beiträge der Sendung statt „Folge ungeklärt“.
- 3sat-Filme mit „- Spielfilm, USA 1993“ im Titel werden ohne diesen Zusatz gesucht; ein Jahr Abstand (Produktion/Erscheinen) gilt bei passender Laufzeit als derselbe Film. Beides wird einmal auf vorhandene Filme angewendet.
- Lernreihen warten gemeinsam auf das Stundenkontingent der ARD Mediathek; die gelernte Reihe gilt für alle Folgen. Reine Wikidata-Fehler halten Werke ohne Art nicht mehr fest. Das Thema eines Werks bleibt beim Zusammenführen erhalten. „Europa“ ist ein Themenwort.
- Enthält 0.6.89–0.6.95 (0.6.92 nicht vergeben).

## Neu in 0.6.93: Gruppen in der Kinderecke
- Filme und Serien stehen in wenigen Gruppen mit Bild-Symbol: 🏰 Märchen, 🎨 Zeichentrick, 🐾 Tiere & Natur, 🔬 Wissen, 🗺️ Abenteuer, 😂 Lustiges, ⭐ Noch mehr. Oben gibt es für jede Gruppe einen runden Knopf, so findet auch ein Kind etwas, das noch nicht liest.
- Leere Gruppen erscheinen nicht, sehr kleine (unter 3 Titeln) stehen unter „Noch mehr“. Die Einordnung folgt den Kategorien und Reihen des Katalogs, ohne KI.
## Neu in 0.6.94: Angefangene Serien automatisch offline, gesehene Filme behalten
- Ist eine Folge einer Serie zu Ende gesehen (Player oder Kinderecke), lädt MediathekAtlas die übrigen Folgen dieser Serie von selbst herunter: erst die folgenden, dann frühere, die noch nicht gesehen sind.
- Kurze Serien werden komplett geladen. Lange oder tägliche Sendungen nur bis zur Grenze (Standard: 20 ungesehene Folgen und 20 GB je Serie); jede gesehene Folge macht Platz für die nächste. Bei wenig freiem Platz (Reserve aus YouTube → Abos, Platz fürs IMDb-Update) wird nichts nachgeladen.
- Ein zu Ende gesehener Film wird dauerhaft offline gespeichert (Downloadordner, ohne 30-Tage-Frist), damit er sich jederzeit nochmal ansehen lässt; seine Sendereihe wird nicht mitgeladen.
- Nur ARD, ZDF & Co. mit direkter Videodatei, bei Serien mit bestätigter Staffel/Folge. Anbieter mit Kopierschutz oder nur Link werden nie geladen.
- Downloads → „Angefangene Serien automatisch laden“: Schalter, Grenzen, je Serie „Automatik beenden“; die Folgen stehen darunter unter „Angefangene Serie · …“ mit Fortschritt und Abbrechen. Schalter auch unter Einstellungen.
## Neu in 0.6.95: Hochformat-Videos ganz im Bild
- Kinderecke: Videos im Hochformat (YouTube-Shorts, Handy-Clips wie „Checker Tobi“) werden vollständig eingepasst statt nur das obere Drittel zu zeigen; ihre Vorschaubilder werden nicht mehr beschnitten.

## Neu in 0.6.91: Kinderecke zeigt Märchen, Serienfolgen und lässt sich blättern
- Erkannte Märchenfilme (z. B. „Sechs auf einen Streich“, „Märchenperlen“) und Filme von KiKA stehen jetzt bei den Filmen der Kinderecke. Ausschluss bleibt: nie neben Horror, Thriller, Krimi, Erotik, Krieg.
- Kinderserien von ARD, ZDF & Co. zeigen ihre Folgen, auch wenn eine Folge selbst noch nicht abgeglichen ist.
- Reihen haben große Pfeilknöpfe zum Blättern (auch ohne Seitwärtsrad); am Ende einer Reihe führt „Alle … Filme“ zur ganzen Liste. Die Liste endet nicht mehr nach 240 Titeln.

## Neu in 0.6.90: Neue YouTube-Kanäle entdecken, prüfen, freigeben
- YouTube → Kanal-Abos → „Neue Kanäle entdecken“: Vorschläge aus den Kanälen, die eure Abos selbst empfehlen, und aus Links in den Beschreibungen geladener Videos; was zu Ende geschaut wurde, zählt mehr. Ohne Konto, ohne KI.
- „Videos ansehen“ zeigt die neuesten Videos (abspielbar im offiziellen YouTube-Player). Erst danach lässt sich der Kanal „Für die Kinderecke freigeben“ (neues Kinder-Abo) oder „Für mich abonnieren“. „Nicht vorschlagen“ blendet ihn dauerhaft aus. Die Kinderecke zeigt nie Vorschläge.

## Neu in 0.6.89: Gesehene YouTube-Abo-Videos ins Archiv
- Läuft ein Abo-Video im MediathekAtlas-Player bis zum Ende, wandert es nach 5 Minuten in `YouTube-Abos/_Archiv/<Kanal>/`. Dort gilt keine 30-Tage-Frist, und es zählt nicht mehr zu Anzahl und Speicherbudget der Abos.
- YouTube → Abos zeigt Archivgröße und Ordner; der Schalter „ins Archiv verschieben“ ist an und lässt sich ausschalten. Das Archiv zieht mit dem Zwischenspeicher um (Einstellungen → Speicherorte).

## Neu in 0.6.88: Folgensuche nach IMDb-Update, Sendungsvorschläge als Folge, tägliche Kataloge
- Ruht die Folgensuche (alles geprüft), zeigt die Übersicht bis wann. Nach jedem neuen IMDb-Archiv wird alles „ohne Treffer“ verteilt über drei Tage erneut gesucht.
- Werke ohne Art, deren Sendung genau so in IMDb/TVDB/TMDB steht, werden Folgen dieser Serie und kommen in die Folgensuche.
- Pluto TV, Joyn, Rakuten TV, RTL+, TOGGO und JustWatch aktualisieren ihren Katalog wieder täglich (einmalig eingeschaltet, abschaltbar).

## Neu in 0.6.87: Themenwörter werden keine Serie

- Themen wie „Doku“, „Sport“ oder „Masterclass“ werden weder als Serie gesucht noch als Serie übernommen (vorher fand IMDb eine Serie „Doku“ für 93 ZDF-Werke).

## Neu in 0.6.86 (nicht ausgegeben, in 0.6.87 enthalten): Umzug vom USB-Laufwerk, Heilungen vor der Erkennung

- Ein Umzug des Speicherorts von einem exFAT-/USB-Laufwerk scheitert nicht mehr an den macOS-Hilfsdateien „._Name“. Sie werden weder kopiert noch geprüft und beim Aufräumen mit ihrer Datei entfernt.
- Der Rückweg-Knopf heißt „Standardordner verwenden“, wenn der bisherige Datenstand im Standardordner liegt.
- Einmalige Korrekturen der Erkennung (Planet Schule, Kurzserien, Themen-Vorlagen) laufen jetzt fertig, bevor Erkennung und Folgensuche starten (höchstens 10 Minuten Wartezeit).
- Themen wie „Sport“ oder „Masterclass“ werden nicht mehr als Serienvorlage gelernt; Werke, die so eine Identität bekommen haben, werden neu erkannt.

## Neu in 0.6.85: Kurzserien bleiben Serien, letzte Planet-Schule-Werke

- Kurze Clips gelten nur dann als Beitrag einer Sendung, wenn die Sendung auch ganze Ausgaben (ab 20 Minuten) zeigt; Kurzserien wie „JoNaLu-Minis“ oder ARTE „Kurz und witzig“ bleiben Serien. Schon so abgelegte Werke werden zurückgenommen.
- Werke, die unter einem anderen oder leeren Thema noch „Planet Schule“ heißen, bekommen ihre Reihe aus dem Titel.

## Neu in 0.6.84 (nicht ausgegeben, in 0.6.85 enthalten): Planet Schule bleibt wirklich bei seiner Reihe

- Die gelernte Serienvorlage für das Thema „planet schule“ gab neu erkannten Werken sofort wieder den Portalnamen; sie wird vergessen, für Portale und Rubriken nicht mehr gelernt, und ein Treffer, der nur das Portal ist („Planet Schule“ bei TVDB), wird nie automatisch übernommen. Betroffene Werke werden einmal neu erkannt.

## Neu in 0.6.83 (nicht ausgegeben, in 0.6.84 enthalten): mehr Sendungsbeiträge erkannt, Abo-Schalter für ungesehene Videos

- Beiträge von Sendungen, die fast nur Kurzclips veröffentlichen und keine Folgenliste haben (z. B. „Hallo Niedersachsen“), werden als Beitrag der Sendung abgelegt statt „ohne Treffer“. Kinderprogramme sind ausgenommen.
- Einträge der Folgensuche, die eine ältere Version bis zu 30 Tage als „ohne Treffer“ geparkt hat, werden einmal mit den heutigen Regeln neu geprüft, wenn sie danach Ausgabe oder Beitrag wären.
- Abo-Verwaltung: neuer Schalter je Abo „Wenn voll: auch ungesehene Videos löschen (älteste zuerst)“. Standard aus. Angeheftete, als Favorit markierte und angefangene Videos bleiben immer; gelöscht wird nur, wenn das Abo sein Speicherlimit erreicht, nie beim Update selbst.

## Neu in 0.6.82 (nicht ausgegeben, in 0.6.83 enthalten): Planet Schule bleibt bei seiner Reihe

- Die Reihe aus dem Titel („Wasserinsekten · Natur nah“ → „Natur nah“) wird von der ARD Mediathek nicht mehr durch den Portalnamen „planet schule“ ersetzt; betroffene Werke werden einmal neu erkannt.

## Neu in 0.6.81 (nicht ausgegeben, in 0.6.82 enthalten): schnellere Werkliste und Kinderecke

- Die Startansicht der Werkliste und die Kinderecke werden nach dem Start im Hintergrund vorbereitet; die Kinderecke zeigt danach immer sofort ihre Liste und erneuert sie im Hintergrund.
- Langsame Seiten nennen in der Diagnose, woran es lag (Filter, Neuaufbau, Teilzeiten).
- Planet Schule: Auch Werke, die automatisch nur dem Portal „Planet Schule“ zugeordnet waren, bekommen ihre Reihe.

## Neu in 0.6.80 (= 0.6.79 mit Gesamtgrenze „ohne Grenze“ als Standard): Speicher für Abos und das IMDb-Update

- Gesamtbudget für alle YouTube-Abos zusammen (Standard: ohne Grenze, damit nach dem Update nichts gelöscht wird; einstellbar unter YouTube → Abos), zusätzlich zum Budget je Abo. Gesehene Videos machen zuerst Platz.
- Liegen Abos und IMDb-Archiv auf demselben Laufwerk, bleibt immer Platz für das wöchentliche IMDb-Update frei; Abos und IMDb-Einstellungen warnen, wenn es knapp wird.
- Folgen mit Nummer werden nicht mehr als Kurzclip-Beitrag eingeordnet; schon so eingeordnete kommen zurück.

## Neu in 0.6.78: Korrektur nach der Mac-Prüfung von 0.6.77

- Schon zuvor falsch als Beitrag eingeordnete ganze Ausgaben (etwa „Gesichter & Geschichten“) werden einmalig nach der aktuellen Regel geprüft und, wenn sie keine Beiträge sind, wieder zur Folgensuche freigegeben.
- Die Art-Einordnung läuft nach dem Update sofort neu, damit alte Wikidata-Vorschläge nicht erst nach sechs Stunden wirken.
- „Planet Schule“: Die Reihe steht im Titel nach dem Punkt („Das schnelle Pendel · Achtung! Experiment“) und wird jetzt als Serie erkannt.

## Neu in 0.6.77: Befunde der Nachtdiagnose

- Ganze Ausgaben wie bei „Gesichter & Geschichten“ bleiben unangetastet, auch wenn die Sendung einzelne lange Sondersendungen hat.
- Kurze, vollständige Archivclips (z. B. „BR Retro“, „Wir in Bayern“) stehen nicht mehr als „vielleicht nur Kurzformat“ unter „zu prüfen“, sondern werden als Beitrag der Sendung eingeordnet – auch die schon markierten.
- Alte Wikidata-Vorschläge (Personen, Bands, Begriffe aus der Zeit vor 0.6.58) halten die Art-Einordnung nicht mehr auf.
- Eine gleichnamige, längst beendete IMDb-Miniserie (etwa „Stark“ von 1993 für KiKA „stark!“) wird nicht mehr allein über den Titel übernommen; betroffene Werke werden neu erkannt.

## Neu in 0.6.76: Korrektur nach der Mac-Prüfung von 0.6.75

- Ganze Ausgaben, die nach ihrem Aufmacher benannt sind (z. B. „Gesichter & Geschichten“), werden nicht mehr als Beitrag eingeordnet: Die längere Beitragsgrenze gilt nur, wenn die Länge einer ganzen Ausgabe bekannt ist.
- „Eisenbahn-Romantik“: auch Folgen ohne IMDb-Untertitel („Wolken, Wolle, Wales“) und mit „Teil 1“ statt „1“.

## Neu in 0.6.75: Beiträge von Tagesmagazinen, Eisenbahn-Romantik

- Kurze Beiträge von Sendungen, die IMDb nur als tägliche Ausgaben führt („Kaffee oder Tee?“, „Landesschau Baden-Württemberg“, „DER TAG in Berlin & Brandenburg“), werden als Beitrag der Sendung eingeordnet statt wochenlang als offene Folge zu warten. Die Sendung bleibt erkannt, eine Folge wird nicht behauptet.
- „Eisenbahn-Romantik“: Folgen werden auch erkannt, wenn IMDb eine laufende Nummer vor den Titel setzt („1092. Mit dem Schienenbus an den Bodensee“).

## Neu in 0.6.74: ein gemeinsamer Stand

- Fasst die Erkennungs-Kette bis 0.6.73 (Folgensuche, Daily Soaps, Abo-Speicherbudget) und die zweite Kette bis 0.6.72 (Besetzung, Folgen-Kacheln, Verbund und Datenbanksicherung, Samsung TV Plus, dailyme TV) in einer Version zusammen. Keine neuen Funktionen.

## Neu in 0.6.72

- Ein Doppelklick auf „Starten“ der Datenbanksicherung legt keine zweite volle Kopie mehr an.
- Samsung TV Plus zeigt nach dem Wiedereinschalten der Automatik die Zeit des nächsten Abrufs. Österreichische und Schweizer Sender lassen sich aus Deutschland oft nicht abspielen (Sperre des Anbieters).

## Neu in 0.6.69: Datenbanksicherung zuverlässig

- „Starten“ der Datenbanksicherung unter Verwaltung → Aufgaben funktioniert.
- Eine Sicherung wird auch fertig, während die Erkennung läuft (vorher begann sie immer wieder von vorn).
- Ein zweiter Start während einer laufenden Sicherung wird als „läuft bereits“ angezeigt, nicht als Fehler.

## Neu in 0.6.64: Samsung TV Plus einstellbar

- Live-TV → „Samsung TV Plus · Region und Automatik“: Land der Senderliste (Deutschland, Österreich, Schweiz), automatische Aktualisierung alle 12 Stunden an oder aus und „Senderliste jetzt laden“, dazu Stand und nächste Aktualisierung.
- Nach einem Wechsel der Region lädt MediathekAtlas die Senderliste sofort neu.

## Neu in 0.6.62: dailyme TV

- Neue Plattform „dailyme TV“: Filme, Serien, Anime und Dokus, die dailyme.de kostenlos mit Werbung und ohne Anmeldung zeigt, mit allen Folgen, FSK, Laufzeit und Beschreibung, im Werkkatalog, als eigener Reiter unter Plattformen und mit Folgen-Kacheln.
- Abgespielt wird nur bei dailyme: „Bei dailyme ansehen“ öffnet den Titel auf dailyme.de. Der Player von dailyme braucht eine eigene Sitzung und einen Schlüssel je Video; das baut MediathekAtlas nicht nach.
- Offline-Kopien gibt es dafür nicht; offline ansehen geht mit dem Offline-Modus der dailyme-App. Der Katalog wird schonend gelesen (robots.txt, eine Anfrage pro Sekunde, Sitemap zuerst; ein unterbrochener Lauf setzt fort).

## Neu in 0.6.61: Verbund robuster mit iCloud

- Ausgelagerte iCloud-Dateien (Finder → „Download entfernen“, macOS 14 und neuer) werden erkannt und mit Frist nachgeladen; solange zeigt der Verbund „wartet auf …“, statt hängen zu bleiben.
- Die Meldung der automatischen Datenbanksicherung im Protokoll und unter Aufgaben funktioniert wieder (die Sicherungen selbst waren nicht betroffen).
- Eine kurz gesperrte Datenbank verwirft kein Erkennungsergebnis mehr.

## Neu in 0.6.59: Folgen als Kacheln

- Beim Öffnen einer Serie stehen die Folgen als Kacheln neben- und untereinander, mit einem Abspielknopf direkt auf dem Bild.
- Der Knopf nimmt den besten Weg: liegt die Folge lokal (Download oder Offline-Kopie), wird sie lokal abgespielt; sonst im eingebauten Player; geht sie nur beim Anbieter, öffnet er die Folge dort (mit Autostart über die Chrome-Erweiterung). Ein Schild auf dem Bild zeigt den Weg: Lokal, Player oder Anbieter.
- Gesehene Folgen tragen „✓ Gesehen“, angefangene einen Fortschrittsbalken. Über „☰ Liste“ gibt es die bisherige Liste weiterhin.

## Neu in 0.6.57: vollständige Besetzung

- Serien, für die keine Besetzung der ganzen Serie vorliegt (z. B. „Der Pass“), zeigen jetzt die Darsteller und die Regie aus ihren Folgen; wer in den meisten Folgen mitspielt, steht vorn.
- „Weitere … anzeigen“ blendet die übrige Besetzung laut TMDB ein (bis zu 40 Personen mit Rolle und Foto), sonst bleibt die Seite kurz.
- Titel ohne eigene Besetzungsangaben, etwa bei Plex, bekommen die Besetzung über ihre IMDb-Kennung von TMDB: die ersten 14 sofort, der Rest mit „Alle … anzeigen“.

## Neu in 0.6.73: Sturm der Liebe auch mit dreistelligen Folgennummern

- „Episode 500“ oder „Folge 610“ wurden bisher als Folge ohne Staffel gelesen und deshalb nicht über die fortlaufende IMDb-Nummer gesucht. Jetzt werden auch die Folgen 1–999 zugeordnet, mit denselben Sicherheitsregeln wie in 0.6.70. Schon geprüfte Folgen kommen sofort wieder dran.

## Neu in 0.6.71: Wiederholungen von Sturm der Liebe

- Folgen, die in der Mediathek „Episode 1140“ statt „Folge 1140“ heißen (Wiederholungen auf ONE), werden jetzt ebenfalls ihrer IMDb-Folge zugeordnet – mit denselben Sicherheitsregeln wie in 0.6.70.
- YouTube-Abos: Das Protokoll nennt beim Zurücknehmen von Aufträgen auch die geplante Größe.

## Neu in 0.6.70: Folgen von Daily Soaps werden erkannt

- „Sturm der Liebe“, „Dahoam is Dahoam“ und andere Serien, die IMDb fortlaufend durchzählt, bekommen ihre Folge über die Nummer im Sendertitel („Folge 4556“, „… · 17.08.15 | Folge 1562“). Bisher blieben dort über 90 % „ohne Treffer“.
- Sicherheitsregeln: Nur bei Serien, deren Folgen in IMDb in einer einzigen Staffel stehen; Laufzeit, ein Erstsendedatum im Titel und ein eigener Folgentitel müssen zu IMDb passen, sonst bleibt die Folge offen.
- Schon geprüfte Folgen solcher Serien kommen sofort wieder dran.
- (0.6.69 ist an einen anderen Versionsstand vergeben.)

## Neu in 0.6.68: Folgensuche ordnet mehr Sendungsausgaben ein

- Regionalmagazine, die nur Tag und Monat nennen („buten un binnen vom 23. Oktober“), werden als Ausgabe der Sendung abgelegt, wenn der Tag der Sendetag ist.
- Gesprächssendungen, deren Folgen nach dem Gast heißen („THADEUSZ lang & breit – Gast: …“), werden als Ausgabe abgelegt statt wochenlang „ohne Treffer“ zu warten. Schon geprüfte solche Werke kommen sofort wieder dran.
- Die letzten zurückgesetzten Beiträge (BR24) werden wieder abgelegt.
- Fehlt das IMDb-Offline-Archiv, steht das auch dann im Protokoll, wenn gerade keine Folge geprüft wird.
- YouTube-Abos: „Speicherbudget verplant“ (laufende Downloads) und „erreicht“ (wirklich belegt) werden getrennt angezeigt, mit der Zahl wartender Videos; Aufträge über dem Budget werden alle 10 Minuten zurückgenommen, nicht erst bei der nächsten Kanalprüfung.

## Neu in 0.6.67: Episoden-Einordnung abgesichert

- Zähler und Protokoll der Episodensuche zählen nur noch, was wirklich gespeichert wurde. Eine kurz gesperrte Datenbank wird wiederholt, ohne doppelt zu zählen.
- Eine Sendung wird gleichzeitig nur von einem Worker eingeordnet.
- Die Übersicht zeigt, wo Datenbank-Sperren auftraten und wie oft eine Sendung später drankam.

## Neu in 0.6.66: Speicherbudget für YouTube-Abos gilt hart

- Das Budget je Abo („Speicher höchstens“) gilt jetzt auch für Videos, die schon in der Warteschlange stehen, und wird beim Start jedes Downloads geprüft. Liegt ein Abo darüber, gehen noch nicht gestartete Videos zurück auf „gewünscht“ und warten, bis gesehene Videos Platz machen; ungesehene werden nie gelöscht.
- Die Größe wartender Videos schätzt MediathekAtlas aus den schon geladenen Dateien des Abos statt mit einem festen Wert.
- Die Abo-Verwaltung zeigt deutlich „Über dem Speicherbudget: … von … GB belegt“.
## Neu in 0.6.65: Episodensuche läuft sichtbar weiter

- „Davon bereit“ zählt nur noch Folgen, die die Episodensuche auch prüfen kann; Werke ohne aktuelles Angebot standen bisher als „bereit“ in der Liste, wurden aber nie geprüft.
- Früher zurückgesetzte Sendungsausgaben und Beiträge werden einmalig im Hintergrund wieder abgelegt, auch wenn ihr Angebot schon abgelaufen ist.
- Fehlt das IMDb-Offline-Archiv, zeigt die Übersicht „Folgensuche wartet auf das IMDb-Offline-Archiv“ statt scheinbar stillzustehen.
- Wikidata: Filme und Serien mit Regie, Besetzung, Folgenzahl oder IMDb-Titelkennung bleiben Vorschläge, auch wenn ihre Klasse unbekannt ist („Der Baum“, „100% Wolf“).
- 0.6.58 wurde nicht ausgegeben; 0.6.65 enthält dessen Korrekturen.

## Neu in 0.6.58: Erkennung und Episodensuche

- Schon abgelegte Sendungsausgaben und Beiträge bleiben abgelegt. Bisher setzte jede weitere Erkennung in derselben Serie sie zurück, und die Episodensuche ordnete sie immer wieder neu ein („BR retro“ 399-mal in 4,5 Minuten). Die Episodensuche hat dadurch wieder Zeit für echte Folgen; zurückgesetzte Werke werden beim nächsten Durchgang ohne Abfrage wieder abgelegt.
- Ist das Stundenkontingent für den Senderabruf (ARD/ZDF) aufgebraucht, kommen zuerst Werke dran, die ohne Senderseite entschieden werden können.
- Wikidata schlägt keine Personen, Tiere, Orte oder Begriffe mehr als Film oder Serie vor.
- Meldet ein Anbieter „zu viele Anfragen“, pausiert MediathekAtlas ihn so lange, wie er verlangt (1 bis 15 Minuten), statt weiter zu fragen; die Werke warten und werden danach geprüft.
## Neu in 0.6.56: Erkennung zwischen Geräten teilen

- Mehrere Macs (oder ein Mac und ein PC) teilen sich die Erkennung jetzt mit einem Klick: Einstellungen → Verbund & andere Systeme → „Über iCloud Drive verbinden“ (auch Dropbox, OneDrive, Google Drive, Synology Drive), auf jedem Gerät einmal. Ein NAS oder offener Port ist nicht nötig, die Geräte müssen nicht gleichzeitig laufen.
- Jedes Gerät erkennt nur noch seinen Teil des Katalogs und übernimmt den Rest von den anderen. Neu geteilt werden auch bestätigte Episoden und „keine Episode gefunden“ der Episodensuche.
- Eigene manuelle Zuordnungen werden nie von einem anderen Gerät überschrieben. Weicht ein anderes Gerät ab, erscheint das unter „Abweichende manuelle Zuordnungen“ mit „Eigene behalten“ oder „Übernehmen“.
- Der Verbund zeigt, wie viele Erkennungen und Episodensuchen von anderen Geräten übernommen statt selbst berechnet wurden.

## Neu in 0.6.55: Besetzung mit Fotos

- Titelseiten von Filmen und Serien (auch auf den Plattformen) zeigen „Besetzung & Regie“ in einer Reihe: zuerst die Regie, dann die Darsteller mit ihrer Rolle, jeweils mit Foto von TMDB.
- Die Fotos werden beim ersten Anzeigen einmal geladen und im Datenordner (`people-photos/`) gespeichert; danach kommen sie von MediathekAtlas selbst, auch ohne Internet. Der Speicher ist auf 48 MB begrenzt (rund 3000 Gesichter), die am längsten nicht gezeigten Fotos werden zuerst entfernt.
- Ohne Foto bleibt der Name mit Initialen stehen. Es wird nie nach einem bloßen Namen gesucht: ein Foto erscheint nur, wenn die Person sicher zum Titel gehört (Besetzung des Titels bei TMDB oder IMDb-Personenkennung).
- Ohne TMDB-Zugang sagt die Titelseite, wo er einzutragen ist („Einstellungen öffnen“ → Metadatenanbieter & Schlüssel).

## Neu in 0.6.54: Offline-Kopien für ServusTV und Red Bull TV

- Filme und Folgen von ServusTV und Red Bull TV lassen sich jetzt wie bei Pluto TV, Netzkino und Plex mit „⬇ Offline speichern (30 Tage)“ sichern: in der Kachel, auf der Titelseite, bei jeder Folge einer Sendung. Gespeichert wird wie bei Mediathek-Videos (gleicher Ordner, gleiche Benennung, MKV mit NFO), zu sehen in der Downloads-Liste, unter „Offline-Kopien von …“ und in der Speicherverwaltung.
- Beide Sender bieten selbst keine Downloads an; die Kopie ist eine private Kopie nur für dich. Sie bleibt 30 Tage und nie länger, als der Sender den Titel anbietet (nennt der Player ein Verfügbarkeitsende, wird die Datei spätestens dann entfernt; Anzeige „Offline bis …“).
- Gespeichert wird nur, was der Sender gerade ohne Kopierschutz freigibt: Live-Sender nie, Jugendschutz-Sperrzeiten und Geosperren gelten auch für das Speichern, nichts wird umgangen.
- „Beste verfügbare“ lädt bis 1080p in H.264 (läuft auch auf älteren Macs und NAS-Playern); 4K (HEVC) nur, wenn 2160p gewählt wird.
- Katalogabrufe aller Plattformen enden jetzt auch dann nach spätestens 150 Sekunden, wenn der Anbieter die Verbindung annimmt, aber nie antwortet (auf dem Mac hing so ein DMAX-Lauf). Ein DMAX-Lauf hört nach drei Verbindungsfehlern auf, gilt als teilweise geladen und versucht es nach zwei Stunden erneut. Beim ServusTV-Katalog macht eine einzelne Zeitüberschreitung den Lauf nicht mehr „teilweise“: die Seite wird einmal erneut versucht, sonst übersprungen und als Hinweis genannt.
- filmfriend: pro Lauf werden jetzt bis zu 1200 statt 400 Titel im Detail gelesen (nur dort steht die FSK). Bis dahin zeigt die Titelseite „FSK noch unbekannt“; die Kinderecke nimmt filmfriend-Titel weiterhin nicht auf.

## Neu in 0.6.52: filmfriend, die Filme und Serien der öffentlichen Bibliotheken

- filmfriend ist eine neue Plattform: Spielfilme, Serien, Dokumentationen und Kinderfilme, die viele Bibliotheken ihren Mitgliedern kostenlos anbieten, mit Genre, Jahr, Laufzeit, FSK und IMDb-Verweis. Ansehen geht auf filmfriend.de nach Anmeldung mit dem Bibliotheksausweis; „Bei filmfriend ansehen“ öffnet den Titel dort.
- Abrufe bei den Anbietern können nicht mehr minutenlang hängen: Jede Antwort hat eine Gesamtfrist von zwei Minuten.

## Neu in 0.6.50: DMAX & TLC wieder abrufbar, ServusTV-Listen „nur in Österreich“, Joyn-Titel lesbar

- DMAX und TLC laden ihre Sendungen und Folgen wieder (die Sender haben ihre Schnittstelle umgestellt). Die Folgen öffnen vorerst auf der Website des Senders, bis die Wiedergabe geprüft ist. HGTV fällt vorerst weg (Schnittstelle für HGTV nicht gefunden).
- ServusTV: Die Listen, die bei jedem Abruf mit „verweigert“ endeten, gibt es nur in Österreich. Sie werden sofort als solche erkannt, nicht mehr wiederholt und als Hinweis gezeigt; der Abruf gilt als vollständig.
- Joyn: Folgentitel wie „Mensch, der Bulle is 'ne Frau“ erscheinen ohne HTML-Zeichencodes.

## Neu in 0.6.49: Mehr Werke mit erkannter Art, „Art offen – warum?“

- Beiträge von Sendungen werden auch dann ihrer Sendung zugeordnet, wenn die Filmdatenbanken nur unpassende Vorschläge lieferten (anderer Film gleichen Namens mit falscher Laufzeit, ungenauer Titel, die Sendung selbst mehrfach). Passende Vorschläge halten das Werk weiter offen.
- ARTE-Rubriken in allen Sprachen gelten nicht mehr als Sendung; falsch abgelegte Werke werden neu geprüft.
- „Auswahl erneut abgleichen“ hebt eine automatische Einordnung auf und bringt die Vorschläge zurück.
- Verwaltung → Zuordnung → Erkennungsquote je Sender: Spalte „Art offen“ und die Gründe je Sender und Sendung, auch in der Diagnose.

## Neu in 0.6.48: DMAX, TLC & HGTV, Joyn-Folgenlisten, Red Bull TV repariert

- DMAX, TLC und HGTV sind eine neue Plattform: alle Sendungen der drei Sender mit ihren Folgen. Freie Folgen laufen im eigenen Player, Folgen nur mit discovery+ und kopiergeschützte Folgen sind gekennzeichnet und öffnen beim Sender.
- Joyn-Serien zeigen jetzt alle Folgen mit Staffel, Laufzeit und „Kostenlos“ oder „Joyn+“ je Folge (gelesen von der Serienseite, 12 Stunden gemerkt). Abgespielt wird weiterhin bei Joyn (Kopierschutz).
- Red Bull TV liefert wieder Videos: die neuen Kennungen der Website (rrn:content:…) werden erkannt, Links führen zu redbull.tv.
- Mac: Wird eine hängende Instanz durch einen neuen Start ersetzt, erscheint kein Fehlerdialog „Anwendung konnte nicht gestartet werden“ mehr.

## Neu in 0.6.47: Red Bull TV, WELT und n-tv im Live-TV, Mac-App startet nach dem Beenden wieder

- Red Bull TV ist eine neue Plattform: Sport- und Abenteuerdokus, Serien mit allen Folgen, Filme und die Red-Bull-TV-Sender, kostenlos und ohne Konto im eigenen Player (gleiche Technik wie ServusTV).
- Im Live-TV gibt es die Gruppe „Nachrichten (privat)“: WELT läuft direkt mit dem offiziellen Stream des Senders, n-tv öffnet n-tv.de (dafür ist kein frei abspielbarer Stream bekannt). WELT von Samsung TV Plus steht im selben Eintrag.
- Mac: Ein Doppelklick auf die App wirkt jetzt auch dann, wenn eine alte Instanz hängt; die App gilt nicht mehr dauerhaft als „läuft noch“.

## Neu in 0.6.46: Kinderfilme und -serien in der Kinderecke, Vollbild beim Anbieter, sicherer Neustart

- Die Kinderecke zeigt neben den YouTube-Abos auch Filme und Serien aus dem Katalog, aber nur, was eindeutig als „Kinder“ eingeordnet ist und im eigenen Player läuft.
- Mit der Chrome-Erweiterung „Videostart“ starten Videos bei Joyn, TOGGO, Crunchyroll, RTL+, Rakuten TV und JustWatch im Vollbild-Fenster; der erste Klick blendet auch die Chrome-Leisten aus, Esc beendet.
- Nach „App beenden“ startet MediathekAtlas wieder zuverlässig. Hängt eine alte Instanz, räumt der Start sie selbst weg. „App beenden“ fragt vorher nach.

## Neu in 0.6.45: Speicherbudget für YouTube-Abos, weniger Wiedergabe-Störungen

- Je Abo lässt sich festlegen, wie viel Speicher die Videos höchstens belegen (Standard 10 GB). Ist es voll, machen gesehene Videos Platz; ungesehene und gemerkte bleiben.
- Abo-Downloads pausieren, wenn am Speicherort weniger als 5 GB frei sind (einstellbar).
- Titel von Joyn, RTL+ und Crunchyroll öffnen beim Anbieter statt „Der Player ist nicht geladen“ zu melden. Tritt die Meldung doch auf, steht der Befund in der Diagnose.
- ServusTV: Seiten, die dauerhaft gesperrt sind, werden nicht mehr bei jedem Lauf dreimal abgefragt.

## Neu in 0.6.44: Episodensuche ohne Leerlauf, saubere Dateinamen, Verwaltung oben

- Ist das Stundenkontingent für den direkten Senderabruf aufgebraucht, entscheidet die Episodensuche mit dem IMDb-Archiv weiter, statt Werke immer wieder zurückzustellen.
- Ausgaben mit „vom Montag, 16. Februar 2026“, „Jänner“ oder „Teil 1 vom 15.04.2026“ werden erkannt.
- YouTube-Abos werden zeitlich versetzt geprüft (mindestens 5 Minuten Abstand).
- Dateinamen von Downloads ohne Emojis, Hashtags und Sonderzeichen; Umlaute bleiben. Alte Dateien werden weiter gefunden.
- Auf jeder Plattformseite steht „… verwalten“ jetzt oben.
- Das Diagnoseprotokoll reicht wieder deutlich länger.

## Neu in 0.6.43: Werke ohne erkannte Art werden eingeordnet

- Rund 40.000 Werke standen unter „Noch zuordnen“, meist Magazinbeiträge und Reportagen von SRF, ARTE, ORF und 3Sat, die keine Filmdatenbank kennt. Nach dem Abgleich ordnet MediathekAtlas sie jetzt ihrer Sendung zu (Ausgabe, Beitrag, Teil oder Folge), als Einzelsendung unter „Weitere Sendungen“ oder bei klarem Filmhinweis als Film.
- Das läuft im Hintergrund und berührt keine eigenen Zuordnungen; „Erneut prüfen“ hebt die Einordnung auf.

## Neu in 0.6.42: stabiler mit Datenbank auf USB-Laufwerk

- Das IMDb-Update scheitert auf exFAT-Laufwerken nicht mehr mit „attempt to write a readonly database“.
- Weniger „database is locked“: weniger Synchronisierungen je Schreibvorgang, Einstellungen werden zwischengespeichert, der Verbund schreibt nur noch bei Änderungen.
- Das Diagnoseprotokoll reicht jetzt für eine ganze Nacht.

## Neu in 0.6.41: Episodensuche räumt Sendungsausgaben auf

- Ausgaben von Nachrichten- und Regionalmagazinen („SWR Aktuell“, „buten un binnen“, „Sachsenspiegel vom 19.11.2026“) und ihre kurzen Beiträge haben keine eigene Folge in IMDb. Die Episodensuche legt sie jetzt als Ausgabe bzw. Beitrag ihrer Sendung ab, statt sie als „ohne Treffer“ oder „unsicher“ immer wieder zu prüfen. Echte Serienfolgen kommen dadurch schneller an die Reihe.
- Talkshows und Magazine mit Datum im Titel werden über IMDbs Ausgabe zum Datum gefunden, Folgentitel auch ohne Zähler und „Audiodeskription“.

## Neu in 0.6.40: Sammelstand

- Enthält 0.6.36 bis 0.6.39 in einem Paket (Abschnitte unten).

## Neu in 0.6.39: Weniger „ohne Treffer“ bei ARD, ZDF & Co.

- Sendungsausgaben mit Datum im Titel („ttt vom 2. Februar 2025“, „Studio 2 vom 16.11.2026“) und die französischen, spanischen, italienischen, polnischen und englischen ARTE-Fassungen wiederkehrender Sendungen werden ihrer Sendung zugeordnet, statt als Film gesucht zu werden – auch wenn sie schon ohne Treffer geprüft wurden.
- Suchtitel ohne Folgenzähler und Zusätze („Donna Leon (12) – …“, „(2/6)“, „Season 1“, „- Audiodeskription“, „NEU“); nummerierte Teile („Die Rosenheim-Cops (13/20): …“) werden zuerst als Serie gesucht.

## Neu in 0.6.38: Chrome-Erweiterung einfacher installieren

- Kein ZIP mehr herunterladen und entpacken: MediathekAtlas legt die Erweiterung „Videostart“ selbst in einen festen Ordner und hält ihn aktuell.
- Einstellungen → „Videostart bei Anbietern“ führt in drei Schritten durch die Installation: Adresse `chrome://extensions` kopieren, Entwicklermodus einschalten, „Ordner im Finder zeigen“ und den Ordner auf die Chrome-Seite ziehen.
- Die Seite erkennt die installierte Erweiterung von selbst (auch ohne Neuladen) und zeigt „installiert und aktuell“.
- Updates kommen ohne Handarbeit: nach einer neuen MediathekAtlas-Version lädt sich die Erweiterung aus ihrem Ordner neu.
- Einmalig nötig: eine vor 0.6.38 installierte Fassung auf `chrome://extensions` entfernen und über den Assistenten neu laden.

## Neu in 0.6.37: Downloads als Liste, Abos unter YouTube

- Downloads stehen je Zustand in übersichtlichen Tabellen. Videos, deren Datei verschwunden ist, sucht MediathekAtlas automatisch an allen bekannten Speicherorten (auch früheren) und verknüpft eindeutige Funde neu; der Rest lässt sich einzeln oder gesammelt entfernen.
- Umzug mit „Vorhandene übernehmen“ passt die Pfade der Downloads jetzt an.
- YouTube-Abos: Dashboard → YouTube → Abos. Werkkatalog ARD, ZDF & Co.: Plattformen → ARD, ZDF & Co.

## Neu in 0.6.36: Kindervideos von YouTube

- Videos, die YouTube als „Made for Kids“ führt (z. B. „Anna und die wilden Tiere“), scheiterten mit „This video is not available“: yt-dlp kann sie nur mit einer JavaScript-Laufzeit laden. Der Knopf im YouTube-Bereich richtet jetzt neben yt-dlp auch Deno ein (offizielle Version, Prüfsumme geprüft); danach werden die gescheiterten Videos einmal neu versucht.

## Neu in 0.6.35: Start ohne Hänger

- Der neue Datenbank-Index aus 0.6.34 wird nicht mehr vor dem Start angelegt, sondern danach im Hintergrund. Die Oberfläche ist sofort erreichbar und zeigt „Datenbank wird einmalig vorbereitet“, bis der Index fertig ist; die Erkennung beginnt danach.

## Neu in 0.6.34: Sammelstand

- Enthält 0.6.32 (IMDb-Archiv an eigenem Ort) und 0.6.33 (schnelle Werkauswahl auch mit älteren SQLite-Versionen) in einem Paket.

## Neu in 0.6.32: IMDb-Archiv an einem eigenen Ort

- In Einstellungen → Speicherorte lässt sich das IMDb-Archiv (rund 20 GB) getrennt von der Hauptdatenbank ablegen, zum Beispiel auf einem externen Laufwerk. Ein dort schon vorhandenes Archiv kann ohne Kopieren übernommen werden.
- Fehlt das Laufwerk, läuft MediathekAtlas ohne IMDb-Abgleich weiter und nimmt das Archiv wieder dazu, sobald das Laufwerk verbunden ist.

## Neu in 0.6.33: Werkerkennung auch mit älteren SQLite-Versionen schnell

- Die Korrektur aus 0.6.31 griff mit älteren SQLite-Versionen (z. B. 3.45) noch nicht vollständig: Die Abfrage für Serien „im Fokus“ las weiterhin alle wartenden Folgen. Jetzt unabhängig von der SQLite-Version behoben.

## Neu in 0.6.31: Werkerkennung läuft auch mit der Datenbank auf einem USB-Laufwerk

- Die Auswahl der nächsten Prüfung las bei jedem Durchgang alle rund 220.000 Serien der Folgen-Warteschlange. Mit der Datenbank auf einem externen Laufwerk dauerte das Minuten; die Hauptworker standen bei „0 / 4 aktiv“. Jetzt hilft ein eigener Index, die Auswahl braucht nur noch Millisekunden.
- Beim ersten Start legt MediathekAtlas den Index einmalig an (auf einem USB-Laufwerk einige Minuten).
- Solange noch kein Ergebnis da ist, steht in „Letzte Erkennung“ jetzt „Sucht die nächste fällige Prüfung …“ statt „Wird gestartet“.

## Neu in 0.6.29: Sammelstand

- Fasst 0.6.24 (Episodensuche), 0.6.27 (YouTube-Abos im Dashboard, einheitliche Katalogübersicht, gegliederte Downloads) und 0.6.28 (exFAT-Downloads, YouTube-Abruf, Zähler der Werkzuordnung) in einem Paket zusammen.

## Neu in 0.6.28: Downloads auf exFAT-Laufwerken, stabiler YouTube-Abruf, ehrliche Zähler

- Downloads und YouTube-Abos lassen sich auf Laufwerke ohne Hardlinks speichern (exFAT, FAT32, viele Netzlaufwerke). Bisher scheiterte dort jeder fertige Download mit „[Errno 45] Operation not supported“; diese Aufträge laufen nach dem Update einmal neu.
- YouTube-Katalog: eine kurz abgebrochene Verbindung wird wiederholt, statt die Quelle für 24 Stunden ausfallen zu lassen. Nach einem Teilfehler folgt der nächste Versuch nach 2 Stunden, und die Titelzahl bleibt bei dem, was der Katalog tatsächlich zeigt.
- Verwaltung: „Werkzuordnung … von … geprüft“ zählt nur Titel, die heute im Katalog stehen (vorher z. B. „3.894 von 3.075“ bei Joyn).
- Enthält die Episodensuche aus 0.6.24.

## Neu in 0.6.27: YouTube-Abos im Dashboard, aufgeräumte Downloads

- Dashboard → Quelle „YouTube-Abos“: alle abonnierten Videos je Kanal; unter „Alle“ steht oben „Neu aus deinen YouTube-Abos“.
- Downloads nach Zustand gegliedert (läuft, wartet, geplant, fehlgeschlagen, fertig) und darin je Kanal bzw. Anbieter.
- Verwaltung → Status: alle Kataloge in einer einheitlichen Tabelle; bei der Werkzuordnung steht, wann zuletzt geprüft wurde.

## Neu in 0.6.26: bedienbar auch während eines Umzugs

- „Protokoll herunterladen“ klappt auch, wenn das Laufwerk ausgelastet ist: Was nicht rechtzeitig fertig wird, steht als Zeitüberschreitung im Export.
- Ein Umzug im laufenden Betrieb bremst sich zugunsten der Datenbank. Die Seite „Speicherorte“ wartet nicht mehr auf schlafende Laufwerke oder hängende Freigaben.

## Neu in 0.6.25: sicherer Weg zurück, wenn das Laufwerk mit der Datenbank wegfällt

- „Bisherigen Ort verwenden“ (beim Start, wenn das Laufwerk fehlt, und in Einstellungen → Speicherorte): MediathekAtlas arbeitet wieder mit dem Datenstand am bisherigen Ort. Es wird nichts kopiert und nichts gelöscht; die Kopie auf dem Laufwerk bleibt unverändert liegen.
- Verschwindet das Laufwerk im Betrieb, hält MediathekAtlas sauber an und meldet es, statt mit Datenbankfehlern weiterzulaufen.
- „Zurück an den Standardort“ überschreibt nie mehr einen dort noch liegenden früheren Datenstand.

## Neu in 0.6.24: Episodensuche findet Folgen erkannter Serien

- Die Folgensuche verwarf IMDb-Folgen, sobald TMDB/TVDB das Startjahr der Serie ein Jahr anders angab als IMDb, und fand Titel wie „Folge 12: Titel“ oder „Titel (S01/E12)“ nicht, weil IMDb nur „Titel“ führt. Beides ist behoben; die erkannte Serie (Titel, Jahr, Anbieter) bleibt dabei unverändert, IMDb ergänzt nur Staffel, Folge und Besetzung.
- Ausgaben von Magazinen und Nachrichten, zu denen IMDb keine Folgen kennt, werden je Serie in einem Schritt um 30 Tage verschoben, statt jede Ausgabe einzeln zu prüfen. Echte Serienfolgen kommen dadurch schnell an die Reihe.
- Die Auswahl der nächsten Folge dauerte bei 200.000 Einträgen etwa eine Sekunde je Prüfung, jetzt etwa eine Millisekunde.
- Zurückgestellte Prüfungen (z. B. Senderabruf im Stundenlimit) zählen nicht mehr als Episodenprüfung; die Übersicht zeigt sie getrennt.
- Bisher ungelöste Folgen werden nach dem Update einmal neu geprüft.

## Neu in 0.6.23: Umzug scheitert nicht mehr an Dateien, die die App gerade schreibt

- Beim Umzug von „System und Datenbank“ meldete die Prüfung Protokolle und Verbund-Ereignisse, die die laufende App seit der Kopie geschrieben hatte, als Fehler. Jetzt prüft sie nur die kopierten, seitdem unveränderten Dateien; der Rest wird beim Neustart nachgezogen und dann vollständig geprüft.
- Downloads und Zwischenspeicher: seit der Kopie geänderte Dateien werden sofort noch einmal kopiert.
- Bereits kopierte Dateien werden bei einem neuen Versuch übernommen.

## Neu in 0.6.22: Umzug großer Datenbanken mit Fortschritt

- Beim Umzug von „System und Datenbank“ zeigt die Anzeige jetzt auch bei großen Datenbanken (catalog.db, IMDb-Archiv) laufend, was passiert: kopiert X von Y GB, wird geprüft, wird auf das Laufwerk geschrieben, seit wie vielen Minuten.
- Die lange Prüfung der ganzen Kopie (bisher bei 5,5 GB auf einem USB-Laufwerk viele Minuten ohne Anzeige) ist bei großen Datenbanken durch eine schnelle Strukturprüfung ersetzt.
- „Umzug abbrechen“ wirkt jetzt auch mitten in einer großen Datei.

## Neu in 0.6.21: Sammelstand

- Enthält 0.6.19 (Crunchyroll-Filmliste immer laden, abgebrochene Katalogabrufe sofort neu starten, Abo-Downloads nach Sperre oder bei vollem Speicher wiederholen) und 0.6.20 (Einstellungen → Speicherorte mit geprüftem Umzug). Keine neue Funktion.

## Neu in 0.6.20: Speicherorte einstellbar, mit Umzug der Daten

- Einstellungen → **Speicherorte**: Downloads, Zwischenspeicher (YouTube-Abo-Videos) sowie System und Datenbank lassen sich einzeln festlegen, z. B. auf einem externen Laufwerk oder einer Netzwerkfreigabe.
- Beim Umzug wird zuerst alles kopiert und geprüft, erst dann umgestellt. Fortschritt und Abbruch in der Oberfläche; ein abgebrochener Umzug setzt beim nächsten Versuch fort.
- System und Datenbank: Abschluss beim Neustart (Knopf „Jetzt neu starten“), geänderte Dateien werden dabei nachkopiert.
- Der alte Ort bleibt erhalten, bis du ihn ausdrücklich löschst; gelöscht wird nur, was am neuen Ort gleich vorliegt.
- Fehlt ein Laufwerk (abgezogen), meldet MediathekAtlas das verständlich: Downloads warten, und ohne Datenordner startet die App nicht an einem leeren Ort neu.
- 0.6.19 ist für die Auswertung der Diagnose von 0.6.18 vorgesehen.

## Neu in 0.6.19: Korrekturen aus der Diagnose von 0.6.18

- **Crunchyroll zeigt seine Filme:** Crunchyroll führt rund 170 Filme nur in seiner Filmliste. 0.6.17 hatte diese Liste übersprungen, sobald ein einzelner Film in der Serienliste erkannt war. Jetzt wird sie immer geladen, der Katalog nach dem Update einmal neu.
- **Abgebrochene Katalogabrufe laufen nach einem Neustart sofort weiter** statt erst am nächsten Tag (ServusTV braucht über eine halbe Stunde und wurde durch Updates mehrfach unterbrochen).
- **YouTube-Abos:** „This video is not available“ direkt nach der Bot-Sperre und „Zu wenig freier Speicher“ beenden einen Auftrag nicht mehr endgültig. Die Downloads warten und versuchen es später selbst; bei vollem Speicher pausieren alle Downloads, bis wieder Platz sein könnte. Bereits so gescheiterte Abo-Videos werden einmal neu eingereiht.

## Neu in 0.6.18: Sammelstand

- Enthält 0.6.14 bis 0.6.17 in einem Paket: Abo-Videos gleichmäßig über die Stunde verteilt, ServusTV mit deutlich mehr Titeln, Crunchyroll-Filme werden erkannt. Keine neue Funktion.

## Neu in 0.6.17: Crunchyroll-Filme werden erkannt

- **Crunchyroll führt Filme als Serie** (Björns Beispiel: „One Piece Film Red“ unter `/de/series/…`). MediathekAtlas erkennt sie jetzt daran: eine Staffel mit genau einer Folge (außer laufenden Simulcasts, die anfangs auch nur eine Folge haben), oder „Film“/„Movie“ im Titel bei höchstens drei Folgen. Solche Titel stehen unter **Filme**, nicht mehr unter Serien.
- „Bei Crunchyroll ansehen“ öffnet zuerst die Filmseite; nach dem Öffnen der Titelseite kennt MediathekAtlas die Wiedergabeseite und die Laufzeit.
- Der Crunchyroll-Katalog wird nach dem Update einmal neu geladen (bei eingeschalteter Automatik innerhalb einer Minute).

## Neu in 0.6.16: ServusTV mit deutlich mehr Titeln

- **Lange „Clips“ zählen jetzt mit:** ServusTV kennzeichnet viele vollständige Sendungen als „Clip“ (ganze Diskussionen wie „Links. Rechts. Mitte“, Vodcasts, Doku-Reihen, Rennen in voller Länge). Bisher wurden alle Clips verworfen; jetzt gelten Videos ab 20 Minuten als Folge ihrer Sendung bzw. als Film. Kurze Ausschnitte bleiben weiter draußen. Im Mitschnitt vom 13.11. waren das 185 von 787 Clips aus 23 Formaten.
- **Sport- und Ereignisseiten** (MotoGP, Superbike, DTM, Wintersport …) werden mitgelesen, ebenso Hinweiskacheln wie „Alle Folgen: Jetzt streamen!“ und Filme, die ServusTV als eigene Seite verlinkt.
- **Einzelne gesperrte Seiten** (HTTP 403, in Björns Diagnose immer dieselben 10 von 2.361 Abrufen) machen den Katalog nicht mehr „teilweise geladen“; sie werden übersprungen und gezählt. Erst wenn mehr als 3 % der Abrufe abgewiesen werden, gilt der Abruf als unvollständig.
- Die ServusTV-Übersicht zeigt zusätzlich die Zahl der Folgen.

## Neu in 0.6.15: Crunchyroll-Filme, zweiter Versuch und genaue Diagnose

- In 0.6.13 lieferte die Crunchyroll-Filmliste ohne Fehler keinen einzigen Film (1.690 Serien, 0 Filme). Bringt die Filmliste nichts, fragt MediathekAtlas jetzt zusätzlich eine zweite Filmliste ab (einzelne Filme statt Film-Einträge); solche Filme öffnen direkt ihre Wiedergabeseite bei Crunchyroll.
- Die Diagnose zeigt je Liste, was Crunchyroll geliefert hat: Gesamtzahl, empfangene und neue Einträge, Typen, verworfene Einträge und die Feldnamen eines Eintrags (keine Titel). Damit lässt sich die Ursache genau eingrenzen, falls weiter keine Filme kommen.
- Basis 0.6.13; 0.6.14 (YouTube-Abos) entsteht parallel.

## Neu in 0.6.14: Abo-Videos gleichmäßig über die Stunde verteilt

- **Höchstens 4 Abo-Videos pro Stunde** (einstellbar 1, 2, 3, 4, 6, 10 oder 20, Plattformen → YouTube → Kanal-Abos). Die Abo-Downloads starten gleichmäßig verteilt, bei 4 also etwa alle 15 Minuten, statt im Schub. Die Download-Karte zeigt „nächstes startet um … Uhr“. „Offline speichern“ von Hand und „Jetzt versuchen“ starten weiter sofort.
- Vorher (0.6.13) lagen zwischen zwei Abo-Videos nur 5–20 Sekunden. In der Diagnose vom 16.11. luden so 21 Videos in rund 40 Minuten, danach sperrte YouTube.
- **Nach einer Bot-Sperre** beginnen die neuen Versuche jetzt bei 1 Stunde (dann 3, 6, 12, 24 Std.) statt bei 15 Minuten; die Sperre hielt in der Diagnose mindestens 80 Minuten.

## Neu in 0.6.13: Abo-Downloads laufen von selbst weiter

- **Bot-Prüfung von YouTube:** Meldet YouTube „Anmeldung erforderlich („kein Bot“)“ oder „zu viele Anfragen“, bleibt das Video nicht mehr dauerhaft im Fehler. MediathekAtlas versucht es automatisch mit wachsendem Abstand erneut (15 Min., 1 Std., 3, 6, 12, 24, 24 Std.) und lässt bis dahin auch alle anderen YouTube-Downloads und Abo-Prüfungen ruhen, damit YouTube die Sperre nicht verlängert. Die Download-Karte zeigt „Geplant für … Uhr“ mit dem Grund; „Jetzt versuchen“ startet trotzdem sofort.
- **Hängende Downloads:** Statt dauerhaft „0.0 MiB · Geschwindigkeit wird ermittelt“ steht da, was gerade passiert (Videoseite wird abgerufen, Videodaten werden abgefragt, kurze Pause …). Kommen nach 10 Minuten keine Daten (oder 5 Minuten lang keine weiteren), bricht MediathekAtlas ab und versucht es später automatisch erneut.
- **Schonender laden:** Abo-Downloads machen zwischen den Anfragen kurze Pausen (1 s, vor jedem Video 5–20 s). Ein einzelner Klick auf „Offline speichern“ startet weiter sofort.
- **Nach dem Update:** Abo- und YouTube-Videos, die vorher an der Bot-Prüfung gescheitert oder durch einen Neustart unterbrochen sind, werden gestaffelt wieder eingereiht.
- **Abo-Verwaltung:** Chip „neuer Versuch geplant“ je Abo, Grund unter „Warum ausgelassen oder verzögert?“, Hinweis oben, solange YouTube bremst.
- Keine Anmeldung bei YouTube: MediathekAtlas meldet sich weiterhin nicht mit einem Konto an und nutzt keine Cookies.

## Neu in 0.6.12: Sammelstand

- Enthält alles aus 0.6.6 bis 0.6.11 in einem Paket: Untertitel und Tonspur im Player, YouTube-Kanal-Abos mit Kinderecke, Ansehen-Modus, Korrekturen aus der Diagnose, Crunchyroll mit Filmen und Abos getrennt nach Profil. Keine neue Funktion.

## Neu in 0.6.11: YouTube-Abos getrennt für Kinder und Erwachsene

- **Profile:** Jedes Kanal-Abo gehört jetzt einem Profil: **Kinderecke** (erscheint nur unter `/kinder`) oder **Für mich** (erscheint nur im Ansehen-Modus `/ansehen`). Nichts wird mehr vermischt. Derselbe Kanal darf in beiden Profilen stehen; ein Video, das in beiden vorkommt, wird nur einmal geladen.
- **Bestehende Abos:** „In der Kinderecke zeigen“ an → Profil Kinderecke, aus → Für mich. Bis 0.6.10 erschienen Kinder-Abos zusätzlich im Ansehen-Modus; das entfällt.
- **Verwaltung aufgeräumt** (Plattformen → YouTube → Kanal-Abos): Reiter je Profil mit Zahl der Abos und Offline-Videos, kompakte Karten mit Kanalbild, Regeln in einer Zeile, Zahlen als farbige Chips und kleine Knöpfe (↻ prüfen, ⚙ Einstellungen, ⏸ pausieren, ✕ beenden, ↗ YouTube). „＋ Kanal abonnieren“ öffnet ein kurzes Formular (Für wen? · Kanal · Was laden? · Reihe); Seltenes steckt unter „Weitere Einstellungen“. Ein Abo lässt sich über ⚙ in das andere Profil verschieben.

## Neu in 0.6.10: Crunchyroll mit Filmen

- **Crunchyroll zeigt jetzt auch Filme.** Bisher kamen nur Serien an (laut Diagnose 1.690 Serien, 0 Filme): Crunchyroll liefert in seiner Katalogliste ohne Angabe nur Serien, Filme stehen in einer eigenen Liste. MediathekAtlas lädt jetzt beide.
- Ein bereits geladener Crunchyroll-Katalog wird nach dem Update einmal neu geladen (bei eingeschalteter Automatik innerhalb einer Minute, sonst „Katalog jetzt laden“).
- Scheitert nur die Filmliste, bleiben die Serien sichtbar und die Katalog-Karte nennt den Grund.
- Manche Anime-Filme führt Crunchyroll selbst als Staffel einer Serie (z. B. Kinofilme zu einer Serie); die stehen weiter auf der Serienseite.

## Neu in 0.6.9: Korrekturen aus der Diagnose vom 16.11.2026

- **Erkennung prüft Sendungen nicht mehr täglich neu:** Ausgaben einer Sendereihe (z. B. „Schleswig-Holstein Magazin“, „NDR Info“, „Nordtour“), deren Sendung schon erkannt ist, werden erst nach 30 bis 37 Tagen wieder bei den Anbietern abgefragt, egal ob TMDB, TVDB, IMDb oder die Mediathek sie erkannt hat. Bisher lag die Frist nur bei ARD/ZDF-Ergebnissen bei 30 Tagen, sonst bei einem Tag; das waren 82 % aller Prüfungen in der Nacht.
- **Übersicht reagiert schneller:** Die Katalogzahlen und die Prüfung von ffmpeg/ffprobe laufen im Hintergrund; die Seite bekommt sofort den letzten Stand, statt 5 bis 16 Sekunden zu warten.
- **Diagnose aussagekräftiger:** Langsame Abfragen der Übersicht nennen ihre langsamsten Teile, die Tabelle „Erkennung je Sender“ und die Werkzeugprüfung sind enthalten, Netzkino-Kategoriefehler ohne Fehlercode bringen einen kurzen Hinweistext mit.
- Die Python-3.14-Warnung aus dem mitgelieferten Downloader erscheint nicht mehr im Startprotokoll.

## Neu in 0.6.8: Ansehen-Modus für Erwachsene

- **Ansehen-Modus** (`/ansehen`, Link „▶ Ansehen-Modus“ links im Menü): dieselbe App ohne Seitenleiste und Verwaltung, aufgebaut wie ein Streamingdienst. Oben die Bereiche *Startseite*, *Filme*, *Serien*, *Live-TV*, *Offline* und *Merkliste*, eine Suche, ein Vollbild-Knopf sowie Links zur Kinderecke und zur Verwaltung.
- **Startseite:** großes Titelbild mit „Fortsetzen“ (zuletzt angefangener Titel), sonst das neueste Abo-Video oder der neueste Film. Darunter waagerecht wischbare Reihen: *Weiterschauen*, *Neu aus deinen Abos*, *Meine Merkliste*, *Offline gespeichert*, *Live-TV* (Favoriten zuerst), *Neue Filme*, *Neue Serien*, *Filme bei <Anbieter>* für jeden geladenen Dienst und je YouTube-Abo eine Reihe.
- **Filme/Serien:** alle freien Dienste zusammen, neueste zuerst, mit Genre-Knöpfen und „Mehr laden“. Ein Tipp öffnet die gewohnte Titelseite mit „Abspielen“, „Offline speichern“ und „Merken“.
- **Abspielen:** Offline-Kopien, Abo-Videos, Weiterschauen und Live-Sender starten direkt. Beim ersten Start geht die ganze Seite ins Vollbild, der Player füllt den Bildschirm.
- Für Handy, Tablet und Fernseher-Browser ausgelegt; die Bedienung per Tastatur (Tab/Enter) funktioniert.

## Neu in 0.6.7: YouTube-Kanäle abonnieren, automatisch offline, Kinderecke

- **Kanal-Abos** (Plattformen → YouTube → „Kanal-Abos: automatisch offline“): Kanal (`youtube.com/@Kanal`) oder Playlist eintragen. Je Abo einstellbar:
  - *Was laden?* „Nur neue Videos“ (ab dem Abo, dazu die neuesten *N* zum Start) oder „Alle Videos“ (neueste zuerst).
  - *Nur eine Reihe:* Wörter, von denen eines im Titel stehen muss (z. B. „Bluey, Folge“); *Ausschließen* entsprechend. Eine Reihe kann auch direkt als Playlist abonniert werden.
  - *Höchstens offline:* so viele Videos je Abo; für ein neues wird das älteste **schon gesehene** entfernt, ungesehene bleiben immer.
  - *Qualität* 480p/720p/1080p (Standard 720p), *Prüfen alle* 1–24 Stunden (Standard 3), *Shorts auslassen*, *In der Kinderecke zeigen*.
  - Knöpfe „Jetzt prüfen“, „Einstellungen“, „Pausieren“, „Abo beenden“ (geladene Videos bleiben bis zum Ablauf ihrer Frist).
- **Ohne API-Schlüssel:** Die Videoliste kommt über yt-dlp; mit Schlüssel über die YouTube Data API (spart Zeit). Geladen wird nur mit eingeschaltetem YouTube-Offline-Schalter, wie bisher auf eigene Verantwortung und mit derselben Frist (30 Tage); abgelaufene Videos werden nicht erneut geladen.
- **Ablage:** `<Downloadordner>/YouTube-Abos/<Kanal>/<Datum> - <Titel> [<ID>] - 720p - H264 AAC.mp4` mit Vorschaubild und NFO. MP4 statt MKV, damit Safari, iPad und schwache NAS ohne Umwandlung abspielen.
- **Kinderecke** (`/kinder`, Link „★ Kinderecke“ links im Menü): große, bunte Kacheln, oben runde Kanal-Knöpfe mit Zahl der neuen Videos, Reihen „Neu für dich“, „Weiterschauen“ und je Kanal. Neue Videos tragen „NEU“, gesehene einen Haken. Ein Tipp startet das Video **im Vollbild**; am Ende folgt nach 6 Sekunden das nächste ungesehene Video desselben Kanals („Zurück“ hält an). Bilder liegen auf dem Server, die Seite läuft ohne Internet. Zurück in die Verwaltung: „Eltern“ unten rechts 2 Sekunden gedrückt halten.
- **Hintergrund:** ein Eintrag im gemeinsamen Planer (kein eigener Dauer-Thread), je Prüfung höchstens 8 neue Aufträge je Abo; die Downloads laufen in der gewohnten Warteschlange.
## Neu in 0.6.6: Untertitel und Tonspur im Player wählen

- **Auswahl „Untertitel“ und „Ton“** oben im Player, sobald der Titel mehr als eine Tonspur bzw. Untertitel hat. „Aus“ schaltet Untertitel ab. Die Wahl (Sprache) merkt sich das Gerät und gilt beim nächsten Titel wieder.
- **Woher die Untertitel kommen:** aus der HLS-Wiedergabeliste (im Browser über hls.js), aus der DASH-Beschreibung (z. B. Plex), als Untertiteldatei des Anbieters (Plex, Untertiteldatei der Mediathek-Sender), aus lokalen Dateien (eingebettete Text-Untertitel, `.srt`/`.vtt` daneben). TTML/EBU-TT der Sender und SRT werden in WebVTT umgewandelt. Bild-Untertitel (PGS, DVB) werden nicht angeboten.
- **Tonspur:** bei hls.js direkt im Browser; bei Strömen über MediathekAtlas (ffmpeg, z. B. Plex-DASH, lokale MKV) startet der Stream an derselben Stelle mit der gewählten Spur neu.
- **OmU-Korrektur:** Nennt der Titel „OmU“, der Stream hat aber nur deutschen Ton, zeigt MediathekAtlas nach dem ersten Abspielen kein „OmU“ mehr, sondern z. B. „DE · UT DE“ und vermerkt den Widerspruch in den Sprachangaben.

## Neu in 0.6.5: Sprachen je Film und Serie (Sammelstand: enthält auch 0.6.2, 0.6.3 und 0.6.4)

- **Titelseite:** Neue Zeilen *Tonspuren*, *Untertitel*, *Barrierefreiheit* (Audiodeskription, Gebärdensprache, Klare/Leichte Sprache) und *Sprachangaben*. Die letzte Zeile sagt immer, woher die Angabe stammt: „im Stream geprüft am …“, „laut Anbieter“, „laut Titel bzw. Sender“ oder „vermutet: deutschsprachiges Angebot, nicht geprüft“. Ohne Beleg steht „unbekannt“.
- **Kacheln:** Ein kleines Feld wie „🗣 OmU“, „🗣 DE · EN · UT DE“ oder „🗣 FR“ erscheint, sobald die Sprache mehr sagt als „deutsch“. Der Tooltip nennt die Quelle.
- **Filter „Sprache“** im gemeinsamen Katalog: Deutsch, Englisch, Französisch, Originalfassung (OV/OmU), Mit Untertiteln. Wirkt für alle Quellen, auch wenn nur eine Plattform gewählt ist.
- **Woher die Sprachen kommen:**
  - *Beim Abspielen:* Nennt die HLS-Wiedergabeliste des Anbieters Ton- oder Untertitelspuren, merkt sich MediathekAtlas sie (Server bei ffmpeg, Browser bei hls.js). Das gilt für jede Quelle mit HLS-Stream, z. B. Pluto TV, Plex, ServusTV, Samsung TV Plus und viele Mediatheken.
  - *Mediatheken:* Fassungen eines Werks werden zusammengefasst (regulär, OmU, Audiodeskription). ARTE.FR/EN/ES/IT/PL gelten als Sprachfassung des Senders, eine Untertiteldatei des Senders als Untertitel.
  - *Anbieterangaben:* Crunchyroll (deutsche Synchronfassung/Untertitel), YouTube (Tonsprache des Videos). Pluto TV, Rakuten TV, Joyn, TOGGO, Plex und RTL+ werden beim Katalogabruf nach Sprachfeldern durchsucht.
  - *Titelzusätze:* OmU, OV, Originalfassung, „mit Untertiteln“, „(Englisch)“, „English version“ usw.
- Nicht geraten wird: Ohne Anbieterangabe, Titelzusatz oder geprüften Stream bleibt die Sprache „unbekannt“. Nur bei deutschsprachigen Angeboten (ARD/ZDF & Co., Netzkino, Joyn, TOGGO, RTL+, ServusTV) steht „Deutsch (vermutlich)“.

## Neu in 0.6.4: YouTube „Filme & TV“ – die kostenlosen Filme mit Werbung

- **Neue Quelle mit einem Klick.** YouTube → Einstellungen → „＋ YouTube „Filme & TV“: kostenlose Filme aufnehmen“. Danach stehen die Filme, die YouTube selbst kostenlos mit Werbung anbietet, als Kacheln bei YouTube und im gemeinsamen Katalog (mit Poster, Jahr, Genre, Inhalt, IMDb-Wertung).
- **Woher die Liste kommt.** Die YouTube Data API gibt den Bereich „Filme & TV“ nicht heraus, und youtube.com selbst liest MediathekAtlas nicht aus. Die Liste kommt deshalb über JustWatch (dieselbe öffentliche Schnittstelle wie bei JustWatch TV): alle YouTube-Angebote für Deutschland mit der Kennzeichnung „kostenlos“ bzw. „mit Werbung“, jeweils mit dem direkten YouTube-Link.
- **Kopierschutz.** YouTube liefert seine eigenen Filme geschützt und nur im eigenen Player aus. Diese Titel sind deshalb Katalogeinträge mit „↗ Bei YouTube ansehen“. Kein eigener Player, kein Offline-Speichern, auch nicht bei eingeschaltetem Offline-Schalter. Meldet YouTube für einen Film, dass er eingebettet werden darf, erscheint wie bei jedem anderen YouTube-Titel „▶ Ansehen“ (offizieller eingebetteter Player).
- **Grenzen.** Die Liste ist so vollständig wie JustWatch. Titel, zu denen JustWatch keinen YouTube-Link nennt, fehlen (die Zahl steht in der Quellenzeile). Der Abruf wurde nicht gegen das echte JustWatch und YouTube geprüft, weil beide von der Entwicklungsumgebung aus gesperrt sind.

## Neu in 0.6.3: Plex-Titel 30 Tage offline speichern

- Filme und Folgen von Plex, die ohne Kopierschutz ausgeliefert werden, lassen sich wie bei Pluto TV, JustWatch TV und Rakuten TV mit „⬇ Offline speichern (30 Tage)“ sichern: in der Kachel, auf der Titelseite und im Bereich „Offline-Kopien von Plex“. Gespeichert wird als MKV mit NFO im gewohnten Ordner; nach 30 Tagen entfernt MediathekAtlas die Datei selbst.
- Kopiergeschützte Titel (Widevine) bleiben ausgenommen und zeigen nur „Bei Plex ansehen“. Ist ein Titel noch nicht geprüft, prüft MediathekAtlas beim Speichern zuerst, ob Plex ihn ohne Kopierschutz liefert. Serien werden folgenweise gespeichert, Live-Sender gar nicht.
- Plex selbst bietet für seine Gratis-Titel keinen Download an. Die Kopie ist für die persönliche Nutzung gedacht und enthält die Werbung, die Plex ausliefert.
- Diagnose: Die Netzprüfung nutzt jetzt denselben Zertifikatsspeicher wie die Katalogabrufe. Unter macOS meldete sie bisher bei allen Servern fälschlich einen Zertifikatsfehler, obwohl die Kataloge luden.

## Neu in 0.6.2: Schnittstelle für Geräte und Apps (API v1)

- **Neu: Verwaltung → System → „Geräte und Apps (API v1)“.** Dort entsteht je Gerät ein Geräteschlüssel, zum Beispiel für einen Abspieler am Fernseher. Der Schlüssel wird einmal angezeigt und lässt sich jederzeit löschen; das Gerät hat dann sofort keinen Zugriff mehr.
- Mit einem Schlüssel erreicht ein Gerät Katalog, Titelseiten, Live-Sender, Wiedergabe, fertige Downloads und die Merkliste mit Abspielpositionen. Einstellungen, Katalogabrufe und die Schlüsselverwaltung bleiben gesperrt.
- **Ohne Schlüssel ist die Schnittstelle geschlossen.** Wer keinen Schlüssel anlegt, öffnet nichts Neues.
- Beschreibung für Entwickler: `docs/API_V1.md`; der Server nennt seine Adressen selbst unter `/api/v1`.
- Noch offen: eigenes HTTPS. Bis dahin Geräteschlüssel nur im Heimnetz oder über VPN verwenden.

## Neu in 0.6.1: Routen-Tabelle im Server (Umbau ohne sichtbare Änderung)

- Für die Bedienung ändert sich nichts. Jede Adresse der Oberfläche antwortet wie in 0.6.0.
- Entwicklung: `server.py` beantwortete bisher rund 130 Adressen in zwei langen if-Ketten. Jetzt ist jede Adresse eine eigene Funktion in einer Routen-Tabelle (`routing.py`). Die Tabelle kennt drei Stufen: offen (vor der Anmeldung), angemeldet und angemeldet mit Sitzungs-Token. Doppelt vergebene Adressen fallen beim Start auf. Die Tabelle ist die Grundlage für die spätere API-Beschreibung (Phase C).

## Neu in 0.6.0: Ein Planer für alle Anbieter, Profil für schwache Hardware

- **Weniger Last im Hintergrund.** Bisher hatte jeder Anbieter zwei eigene Hintergrund-Threads (Katalogabruf und Abgleich mit IMDb/TVDB/TMDB). Jetzt übernimmt ein gemeinsamer Planer beides: ein Thread für die Katalogabrufe, zwei für den Abgleich. Im Leerlauf laufen 31 statt 52 Threads.
- **Katalogabrufe starten nicht mehr alle gleichzeitig.** Höchstens zwei laufen zugleich (auf schwacher Hardware einer), die übrigen folgen eine Minute später. Von Hand gestartete Abrufe laufen wie bisher sofort.
- **Neu: Verwaltung → System → „Hintergrundarbeit“.** *Automatisch* (Standard) wählt „Schwache Hardware“ bei höchstens zwei Prozessorkernen oder weniger als 2 GB Arbeitsspeicher, z. B. auf kleinen NAS. Dort läuft je ein Katalogabruf und ein Abgleich zur Zeit. Die Ansicht zeigt auch, welche Katalogabrufe gerade laufen.
- **Datenbanken der Anbieter im WAL-Modus.** Die Oberfläche wartet nicht mehr, während ein Katalogabruf schreibt. Liegt der Datenordner auf einer Netzwerkfreigabe, schaltet `MEDIATHEKATLAS_NO_WAL=1` das ab.
- Entwicklung: `provider_base.py` hält den gemeinsamen Rahmen (Datenbank, Regel „Katalog fällig“), `planner.py` den Planer.

## Neu in 0.5.108: Aufgeräumt nach dem Review

- **Alle Anbieter laden nach einem Update neu, wenn ihr Katalog vorher unvollständig war.** Bisher taten das nur Plex, ServusTV und RTL+; jetzt auch Joyn, TOGGO, Pluto TV, JustWatch, Rakuten TV, Crunchyroll, YouTube und Netzkino. Das passiert einmal je Version.
- **Ein- und Ausblenden unter Verwaltung → Darstellung funktioniert auch in älteren Browsern.** Safari vor 15.4 und Firefox vor 121 ignorierten bisher alle Ausblende-Haken, weil eine Regel einen dort unbekannten Selektor enthielt.
- Archivnachweise: Die Signaturprüfung nimmt nur noch die eindeutige Schreibweise eines Schlüssels an.
- Entwicklung: Der alte Bausatz `integration/preview` (0.5.31.11) und sein Workflow sind entfernt; seine Tests liefen gegen veraltete Kopien und sind längst in `tests/` übernommen. `main` enthält wieder den vollständigen Stand.

## Neu in 0.5.107: RTL+ nur noch kostenlos, „Meine Abos“

- **RTL+ zeigt nur noch, was ohne Abo läuft.** Der Katalog kommt jetzt aus dem Gastbereich „Kostenlose Inhalte“ von RTL+. Titel, die RTL+ nur mit Abo zeigt („+“), werden gezählt und ausgeblendet; die frühere Liste mit Abo-Titeln verschwindet beim ersten Abruf von selbst. Weitere Seiten werden jetzt über den richtigen Pfad geladen (keine „HTTP 404“ mehr).
- **Neu: Verwaltung → Darstellung → „Meine Abos“.** Je Anbieter ein Haken „Ich habe ein Abo“:
  - RTL+: zeigt zusätzlich die Abo-Titel, markiert mit „In deinem RTL+ Abo“.
  - Crunchyroll: Abo-Titel heißen dann „In deinem Abo“ statt „Nur mit Abo“.
  - MediathekAtlas speichert keine Zugangsdaten. „Bei … ansehen“ öffnet den Anbieter in deinem Browser; dort einmal anmelden, die Chrome-Erweiterung drückt auf Wunsch „Abspielen“. Abgespielt wird beim Anbieter (Kopierschutz).
- Nicht geprüft: echter Gastbereich von RTL+ (aus der Bauumgebung gesperrt). Ordner und Pfade stammen aus einem öffentlichen RTL+-Free-Client.

## Neu in 0.5.106: RTL+-Links führen auf die richtige Seite

- „Bei RTL+ ansehen“ öffnet jetzt die Seite im Schema, das Björn bestätigt hat (`plus.rtl.de/<titel>-p_<nummer>`), statt „Diese Seite existiert nicht“. Bereits gespeicherte Links werden beim ersten Start einmal umgeschrieben, ein neuer Katalogabruf ist nicht nötig.
- **ServusTV** ruft langsamer ab (0,5 s statt 0,25 s zwischen den Anfragen) und versucht es nach „HTTP 403“ zweimal mit Pause erneut; die Plattform hatte zu schnelle Abrufe abgewiesen. Bleibt etwas abgewiesen, nennt der Hinweis die Anzahl.
- **Nach einem Update** lädt MediathekAtlas einen Katalog, der zuletzt nur teilweise oder gar nicht geladen wurde (Plex, ServusTV, RTL+), einmal neu, ohne auf den 24-Stunden-Abruf zu warten.
- Sonst wie 0.5.105.

## Neu in 0.5.105: Sammelstand

- 0.5.105 = 0.5.104 (Korrekturen Plex, RTL+, ServusTV) + 0.5.103 (Kinder und Familie getrennt) und alles davor. Keine weiteren Änderungen.

## Neu in 0.5.104: Korrekturen nach Björns Diagnose vom 13.11.

- **Plex** zeigt wieder Filme und Serien: Plex beantwortet die Bereichsliste für Gäste mit „HTTP 404“. Dann liest MediathekAtlas jetzt die Startseiten-Leisten von Plex (wie die Plex-Web-App) und blättert sie vollständig durch.
- **RTL+**: Kacheln, die direkt auf ein Video zeigen, verlinken jetzt auf die Seite der Sendung bzw. des Films. Weitere Seiten einer Leiste, die RTL+ nicht mehr kennt (HTTP 404), machen den Abruf nicht mehr „teilweise“. Genre-Unterordner werden mitgelesen (mehr Titel). Fehler nennen den Ordner (z. B. „Kids: …“).
- **ServusTV**: Der alte Hinweis „WordPress: … nicht erreichbar“ aus 0.5.101 verschwindet beim nächsten Abruf. Der erste vollständige Abruf dauert einige Minuten; in der Diagnose steht dabei der Fortschritt.
- Nicht geprüft: echte Antworten von Plex und RTL+ (aus der Bauumgebung gesperrt). Ob RTL+-Filmlinks jetzt stimmen, zeigt erst der Test bei Björn.
- 0.5.103 kam aus dem Kategorien-Thread und steckt im Sammelstand 0.5.105.

## Neu in 0.5.103: „Kinder“ und „Familie“ getrennt

- Die frühere Kategorie „Kinder & Familie“ ist geteilt. **Kinder** gibt es nur bei eindeutigen Kinder-Angaben (Kinderfilm, Kinderserie, KiKA, TOGGO, Kids) und nie zusammen mit Horror, Thriller, Krimi, Erotik oder Krieg oder ab FSK 12. **Familie** (z. B. TMDB „Family“, Weihnachtsfilme) steht nie neben Horror oder Erotik und gilt bis FSK 12.
- Bestehende Datenbanken werden beim Start einmal umgestellt.

## 0.5.102: RTL+ als Katalog, ServusTV nach Björns Mitschnitt

- **Neuer Plattform-Reiter „RTL+“** mit dem kostenlosen Teil von RTL+ (RTL+ Free, ohne Konto): Filme, Serien, Shows und Kindersendungen, mit einheitlichen Kategorien, Titel- und Serienseite, Suche, Merkliste und im Dashboard. RTL+ liefert jedes Video nur mit Kopierschutz (Widevine) aus. Deshalb spielt MediathekAtlas RTL+ nie selbst ab: Jeder Titel hat „Bei RTL+ ansehen“, die optionale Chrome-Erweiterung startet dort die Wiedergabe. Titel, die RTL+ Premium brauchen, werden nur gezählt. Kein Offline-Speichern.
- **ServusTV läuft jetzt über die echten Schnittstellen** aus Björns HAR-Mitschnitt von servustv.com: Katalog aus der Red-Bull-Plattform (alle Sendungen und Kategorien, Sendungen mit Staffeln und Folgen, Filme), Wiedergabe über den Red-Bull-Player (klares HLS, bis 1080p). Live-Sender kommen aus dem Katalog (ServusTV, dazu Red Bull TV und Wetterpanorama, soweit ServusTV sie anbietet). Clips und Trailer bleiben draußen.
- Nicht geprüft: RTL+ und ServusTV selbst (aus der Bauumgebung gesperrt). Die ServusTV-Antworten sind im Test genau so aufgebaut wie im Mitschnitt; die RTL+-Schnittstelle stammt aus öffentlichen Open-Source-Clients und ist noch nicht mitgeschnitten.
- Sammelstand: 0.5.102 enthält 0.5.101 und alles davor.

## Neu in 0.5.101: ServusTV On

- **Neuer Plattform-Reiter „ServusTV“** mit der kostenlosen Videothek von ServusTV (ohne Konto): Dokumentationen, Sendungen wie „Bergwelten“ mit allen Folgen, Spielfilme. Dazu **ServusTV Deutschland und Österreich live**, auch im Reiter Live-TV. Wie bei den anderen Plattformen mit einheitlichen Kategorien, Titel- und Sendungsseite, Suche, Merkliste und im Dashboard.
- **Alles läuft im MediathekAtlas-Player**: ServusTV liefert ohne Kopierschutz aus (jeder Stream wird trotzdem vorher geprüft). Gibt ServusTV ein Video gerade nicht frei, nennt der Player den Grund, zum Beispiel „Jugendschutz: nur von 22:00 bis 06:00 Uhr“ oder „Geosperre“.
- **Kein Offline-Speichern**: ServusTV erlaubt Downloads nur in der eigenen App.
- Überholt durch 0.5.102: Katalog und Wiedergabe laufen jetzt über die Schnittstellen aus Björns HAR-Mitschnitt.
- Sammelstand: 0.5.101 enthält 0.5.100 (Plex) und alles davor.

## Neu in 0.5.100: Plex – kostenlose Filme, Serien und Live-Sender

- **Neuer Plattform-Reiter „Plex“** mit dem kostenlosen Angebot von Plex (mit Werbung, ohne Plex-Konto): Filme, Serien mit Staffeln und Folgen, Live-Sender. Wie bei den anderen Plattformen mit einheitlichen Kategorien, Bewertung, Titel- und Serienseite, Suche, Merkliste und im Dashboard unter „Alle“ oder „Plex“. Die Live-Sender stehen zusätzlich im Reiter **Live-TV**.
- **Kopierschutz wird je Titel geprüft.** Viele Plex-Titel kommen ohne Kopierschutz und laufen im MediathekAtlas-Player (über ffmpeg, weil Plex sie als DASH ausliefert). Manche liefert Plex nur mit Widevine aus: Das zeigt sich beim ersten „Ansehen“, danach steht dort „Bei Plex ansehen“. Nichts wird umgangen.
- **Kein Offline-Speichern**: Plex selbst bietet für seine Gratis-Titel keinen Download an.
- Der Katalog lädt sich beim ersten Start von selbst; danach auf Wunsch alle 24 Stunden (Schalter im Reiter). Welche Titel Plex anbietet, hängt vom Land der Internetverbindung ab.
- Nicht geprüft: Plex selbst (aus der Bauumgebung gesperrt). Die Schnittstellen stammen aus öffentlich verfügbaren Plex-Programmen (Kodi-Erweiterungen, python-plexapi) und sind mit nachgebauten Antworten getestet. Falls der Katalog leer bleibt oder ein Titel nicht startet, hilft ein HAR-Mitschnitt von watch.plex.tv.
- Sammelstand: 0.5.100 enthält 0.5.99 (helles Design, Systemmonitor), 0.5.98 (Plex, bisher einzeln), 0.5.97 (Samsung TV Plus), 0.5.96 (Crunchyroll), 0.5.95 (Archivnachweise) und alles davor.

## Neu in 0.5.99: Helles Design, Systemmonitor, Klicktest in echten Browsern

- **Helles Design.** Verwaltung → Darstellung → „Design“: Dunkel (wie bisher, Standard), Hell oder „Wie das System“. Die Auswahl gilt für alle Browser, die diese Installation öffnen. Das helle Design wird aus dem dunklen berechnet: gleiche Aufteilung, gleiche Akzentfarben, nur die Helligkeit gespiegelt. Player, Hintergrundbilder und alles, was auf einem Bild liegt, bleiben dunkel. Erste Fassung: Ansichten mit echten Covern und Titelseiten konnten hier nicht beurteilt werden, Rückmeldungen zu einzelnen Stellen sind willkommen.
- **Systemmonitor.** Verwaltung → „System“ zeigt Prozessorlast, freien Arbeitsspeicher, Speicherbedarf von MediathekAtlas, Temperatur (wo das System sie meldet), freien Platz auf den Laufwerken von Daten und Downloads, die Größe der Datenbanken und was gerade läuft (Downloads, Umwandlungen, Dateiprüfung, Verbund). Dazu Hinweise in Klartext, wenn Prozessor, Speicher, Temperatur oder Platz knapp werden. Gemessen wird nur, solange die Ansicht offen ist.
- **Klicktest in der CI.** Bei jedem Pull Request öffnet ein Test alle Hauptansichten, alle Bereiche der Verwaltung und alle Plattform-Reiter in Chromium, Firefox und WebKit (steht für Safari) und schlägt bei jedem Skriptfehler oder fehlgeschlagenen Aufruf an.
- Die Reiter der Verwaltung sind etwas schmaler, damit der neue Reiter „System“ in die Zeile passt.
- Sammelstand: 0.5.99 enthält 0.5.97 (Samsung TV Plus), 0.5.96 (Crunchyroll), 0.5.95 (Archivnachweise), 0.5.94 (Umwandeln) und alles davor. 0.5.98 (Plex) folgt in 0.5.100.

## Neu in 0.5.97: Samsung TV Plus im Reiter Live-TV

- **Rund 200 kostenlose Live-Sender von Samsung TV Plus** (Filme, Serien, Dokus, Kids, Anime, Sport, News …) stehen im Reiter **Live-TV**, mit Logo, Gruppe, Kanalnummer und dem Programm, das **gerade läuft und danach kommt**. Über den Anbieter-Filter „Samsung TV Plus“ siehst du nur diese Sender.
- Samsung TV Plus hat in Deutschland nur Live-Sender, keine Filme oder Serien zum Abrufen. Deshalb gibt es keinen eigenen Plattform-Reiter und kein Offline-Speichern.
- **Kopierschutz:** 16 der 216 deutschen Sender liefert Samsung nur mit Widevine aus. Die werden nicht aufgeführt, nur gezählt. Alle anderen Streams werden vor dem Abspielen geprüft und laufen im eigenen Player (mit der Werbung des Senders).
- Die Senderliste lädt sich beim ersten Start von selbst und danach alle 12 Stunden. Fehlt sie oder schlug der Abruf fehl, steht im Reiter Live-TV ein Knopf zum Laden. Unter Verwaltung → Aufgaben heißt der Abruf „Samsung TV Plus · Senderliste“.
- Quelle: Samsung hat keine offene Schnittstelle. Die Senderliste kommt aus der öffentlichen Sammlung bei i.mjh.nz, die Wiedergabe-Adresse über deren Weiterleitung jmp2.uk zur offiziellen Samsung-Adresse (wie bei Kodi-Erweiterungen und IPTV-Playern). Fällt eines davon weg, nennt der Reiter den Grund, die anderen Anbieter laufen weiter.
- Nicht geprüft: Wiedergabe echter Samsung-Streams (aus der Bauumgebung gesperrt). Geprüft ist die Senderliste mit dem echten Stand vom 13.11.2026.
- Sammelstand: 0.5.97 enthält 0.5.94 und alles davor (0.5.95 und 0.5.96 sind von anderen Threads reserviert).

## Neu in 0.5.96: Crunchyroll

- **Neuer Plattform-Reiter „Crunchyroll“** und Crunchyroll im gemeinsamen Katalog: Anime-Serien mit Staffeln und Folgen sowie Filme, mit deutschen Texten, Altersfreigabe, einheitlichen deutschen Kategorien, Bewertung (IMDb/TMDB-Abgleich wie bei den anderen Plattformen), Merkliste und Weiterschauen.
- **Wichtig: Crunchyroll hat das kostenlose Angebot mit Werbung zum 31.12.2025 eingestellt.** Seit dem 1.1.2026 braucht man auf crunchyroll.com für jeden Titel ein Abo, und alle Streams sind mit Widevine geschützt. MediathekAtlas umgeht nichts: „Bei Crunchyroll ansehen“ öffnet den Titel auf crunchyroll.com; die optionale Chrome-Erweiterung „Videostart“ klickt dort auf Abspielen. Kein Player, kein Offline-Speichern.
- Die Auswahl „Angebot“ filtert nach **Kostenlos / Nur mit Abo / Deutsche Synchronfassung / Deutsche Untertitel**. Sollte Crunchyroll wieder Folgen ohne Abo freigeben, erscheinen sie automatisch als „Kostenlos“.
- **Gratis-Folgen:** Der offizielle YouTube-Kanal „Crunchyroll auf Deutsch“ (@CrunchyrollDE) ist unter YouTube als Vorschlag eingetragen (ganze Folgen ab 20 Minuten, Trailer und Clips bleiben draußen). Er läuft im MediathekAtlas-Player, braucht aber den YouTube-API-Schlüssel.
- Nicht live geprüft: crunchyroll.com ist aus der Bauumgebung gesperrt. Crunchyroll schützt die Seite mit Cloudflare; blockiert es den Abruf, sagt die Katalog-Karte das im Klartext.
- Sammelstand: 0.5.96 enthält 0.5.95 (Archivnachweis) und alles davor.

## Neu in 0.5.95: Prüfsumme und Archivnachweis für Archive.org-Downloads, Zweitkopie im Verbund

- **Jeder Archive.org-Download wird beim Laden geprüft.** Archive.org nennt zu jeder Datei eine Prüfsumme. Stimmt die geladene Datei nicht damit überein, wird sie verworfen statt gespeichert. Dafür muss der Dateibestand des Uploads mit dieser Version gelesen sein („Dateibestand neu von Archive.org lesen“ in der Detailansicht); bei älteren Einträgen wird nur gemessen.
- **Archivnachweis je Datei.** Nach dem Download entsteht ein signierter Nachweis: welche Datei von welchem Upload, Prüfsumme der geladenen und der gespeicherten Datei, Datum. Jedes System hat dafür einen eigenen Schlüssel, der das Gerät nicht verlässt.
- **Zweitkopie im Verbund.** Im Verbund tauschen die Systeme ihre Nachweise aus. Verwaltung → Speicher → „Archivnachweise“ zeigt je Datei: nur hier, Zweitkopie belegt (mit Name des anderen Systems und Datum) oder nur auf einem anderen System. Nachweise mit ungültiger Signatur werden nicht angenommen. Meldet ein System später unter einem anderen Schlüssel, steht „Schlüssel geändert“ da und die Kopie zählt nicht.
- **„Hier ebenfalls laden“** holt eine Datei, die nur ein anderes System hat, von Archive.org auf dieses System. So entsteht gezielt eine zweite Kopie; sie wird wie jeder Download geprüft.
- **„Erneut prüfen“** liest die Datei vollständig und vergleicht sie mit ihrem Nachweis. Das erkennt beschädigte oder veränderte Dateien. Fehlt die Datei, wird der Nachweis zurückgezogen. Wer eine Datei unter „Speicher“ löscht, zieht ihren Nachweis ebenfalls zurück; die anderen Systeme erfahren das.
- **„Fehlende Nachweise erstellen“** holt den Nachweis für Downloads aus früheren Versionen nach (ohne Prüfung der Quelle, weil die geladenen Daten nicht mehr vorliegen).
- Ein Nachweis ist eine Aussage mit Datum, keine laufende Überwachung. MediathekAtlas löscht deshalb auch bei belegter Zweitkopie nichts von selbst.
- Ohne Verbund bleiben die Nachweise auf dem System und werden veröffentlicht, sobald ein Verbund eingerichtet ist. Systeme mit älterer Version überspringen die Nachweise.
- Nicht geprüft: echte Downloads von Archive.org (aus der Bauumgebung gesperrt), zwei echte Geräte über MeshSync oder Tailscale. Getestet sind zwei Installationen auf einem Rechner mit gemeinsamem Verbundordner.
- Sammelstand: 0.5.95 enthält 0.5.94 (Umwandeln) und alles davor.

## Neu in 0.5.94: Umwandeln auf 1080p, 720p oder 480p (Encoder)

- **Verwaltung → Speicher → „Umwandeln“** rechnet einen fertigen Download mit ffmpeg auf eine kleinere Bildgröße herunter (H.264 in MKV). Ton und Untertitel bleiben unverändert, Kapitel und Titelangaben auch.
- **Das Original bleibt erhalten.** Ohne weiteres Zutun entsteht eine zweite Datei daneben, z. B. „Titel [720p].mkv“. Nur mit dem Haken „Original ersetzen“ und einer Bestätigung tritt das Ergebnis an die Stelle des Originals, und auch dann erst, wenn es geprüft ist (Bildhöhe, Laufzeit, Zahl der Tonspuren). Besteht es die Prüfung nicht, bleibt das Original und das Ergebnis wird verworfen.
- **Schonend für ältere Geräte:** immer nur eine Umwandlung, mit gesenkter Priorität. „Schnell“ braucht weniger Rechenzeit, „Ausgewogen“ ergibt kleinere Dateien. Hochrechnen wird abgelehnt (ein 720p-Video wird nicht zu 1080p).
- Die Warteschlange steht unter der Dateiliste, mit Fortschritt, „Abbrechen“ und „Liste leeren“. Nach einem Neustart wird eine unterbrochene Umwandlung von vorn begonnen; halbfertige Dateien heißen `.partial` und zählen nie als Ergebnis.
- Vor dem Start wird der freie Platz geprüft. Fehlen ffmpeg oder ffprobe, sagt die Seite das, statt einen Auftrag anzunehmen.
- Bewusst ffmpeg statt HandBrake: ffmpeg ist für Downloads ohnehin dabei, auf macOS, Windows, Linux und NAS. Hardware-Beschleunigung (VideoToolbox, Quick Sync) ist noch nicht eingebaut.
- Nicht geprüft: echte NAS-Hardware, macOS und Windows, sehr lange Filme. Getestet ist mit kurzen echten Videos unter Linux.
- Sammelstand: 0.5.94 enthält 0.5.93 und alles davor.

## Neu in 0.5.93: Videostart auch bei TOGGO und JustWatch, SAT.1 als Joyn+

- Nach Björns Test von 0.5.91: Joyn startet direkt. Bei TOGGO war noch der pinke Play-Knopf zu klicken, bei JustWatch der Play-Knopf im Mini-Player.
- Die Chrome-Erweiterung klickt jetzt auch **Play-Knöpfe ohne Beschriftung** über dem Player: bekannte Player-Knöpfe (Video.js, JW Player, Bitmovin, Shaka u. a.), Elemente mit „play“ im Klassennamen, und als Letztes die Mitte des Players. Sie klickt wie eine Maus (Zeiger- und Maus-Ereignisse), weil manche Player nicht auf einen einfachen Klick reagieren. Videos, die erst beim Abspielen laden (Mini-Player), startet sie direkt. Sie wirkt auch in eingebetteten Rahmen derselben Seite.
- **SAT.1 ist als Joyn+ gekennzeichnet** (Live-TV und Reiter Joyn), auch in schon geladenen Katalogen. Joyns eigene Senderliste führt SAT.1 als frei; die Kennzeichnung beruht auf Björns Beobachtung vom 13.11.2026. SAT.1 GOLD, SAT.1 emotions und die Regionalfenster bleiben unverändert.
- **Erweiterung aktualisieren:** neues ZIP unter Einstellungen → „Videostart bei Anbietern“ herunterladen, den alten Ordner damit ersetzen und unter `chrome://extensions` bei „MediathekAtlas Videostart“ auf ↻ (Neu laden) klicken.
- Nicht geprüft: die echten Seiten von TOGGO und JustWatch (aus der Bauumgebung gesperrt); getestet mit nachgebauten Seiten. Liegt der Player in einem Rahmen einer anderen Adresse, kommt die Erweiterung dort nicht hin.
- Sammelstand: 0.5.93 enthält 0.5.92 (Archive-Media-Module) und alles davor.

## Neu in 0.5.92: Archive.org-Scan wird verlässlich, Listen-Austausch, Blu-ray-Abbilder (aus Archive Media)

- **Der Scan zählt nur noch, was Archive.org wirklich geliefert hat.** Sammlungen und Uploader werden sortiert abgefragt, und jede Seite muss nachweislich die angefragte sein. Bisher konnte eine still wiederholte erste Seite als Fortschritt gelten.
- **Große Sammlungen werden vollständig gelesen.** Archive.org beantwortet höchstens 10 000 Treffer je Frage; größere Quellen blieben bisher dort stehen. Jetzt werden sie nach Veröffentlichungsdatum in Zeitfenster geteilt und Fenster für Fenster gelesen.
- **Fehler werden unterschieden.** Netzprobleme werden mit wachsender Pause wiederholt und nach acht Versuchen angehalten statt endlos weiterzulaufen. Liefert Archive.org dreimal nicht die angefragte Seite, stellt der Scan von Seiten auf Zeitfenster um. Eine abgelehnte Anfrage hält die Quelle an. Die Position bleibt immer erhalten; „Start / Fortsetzen“ macht dort weiter.
- **„Neu durchsuchen“** liest eine Quelle von vorn. Bereits Gefundenes bleibt, die Zähler des alten Laufs werden aufbewahrt. Jede Quelle zeigt, wie viel Archive.org nennt und wie viel gelesen wurde (ein Anhaltspunkt, kein Beweis).
- **Liste austauschen** (Plattformen → Internet Archive → Scanquellen → „Gefundene Uploads mit einer anderen Installation austauschen“): „Liste speichern“ schreibt alle bekannten Uploads in eine Datei, „Liste einlesen“ übernimmt auf einer anderen Installation nur die, die dort fehlen. Die Datei hat das Format von ArchiveMedia, Listen gehen also in beide Richtungen. Sie enthält nur Archive.org-Kennungen, Titel und Dateinamen.
- **Blu-ray-Abbilder.** Besteht ein Upload aus nummerierten Blu-ray-Clips, zeigt die Detailansicht die Playlists. „Hauptfilm suchen“ liest sie (je höchstens 256 KiB) und nennt den längsten Titel, dessen Clips alle im Upload liegen, mit Reihenfolge, Laufzeit und Größe. Geladen und zusammengefügt werden die Clips noch nicht.
- **Weitere Inhalte eines Uploads.** Musik, Hörbücher, Bücher, Comics oder Programme, die neben dem Film im Upload liegen, werden mit vorsichtiger Einordnung und Begründung aufgeführt; die Links öffnen die Datei bei Archive.org. Nennt der Uploader eine ISBN oder eine MusicBrainz-Kennung, lässt sie sich auf Klick bei Open Library bzw. MusicBrainz nachschlagen.
- Bei Uploads, deren Dateibestand schon vor dem Update gelesen wurde, zeigt die Detailansicht jetzt „Dateibestand neu von Archive.org lesen“. Erst danach erscheinen dort Bildhöhe (für die Staffel-Auswahl), Blu-ray-Struktur und weitere Inhalte.

## Neu in 0.5.91: Videos bei Rakuten TV, Joyn, TOGGO und JustWatch TV starten schneller

- Titel mit Kopierschutz laufen weiter nur beim Anbieter. Bisher öffnete der Link die Detailseite, dann musste man auf „Ansehen“ klicken und bei Rakuten TV noch den HDCP-Hinweis bestätigen.
- **Direkter Player-Link:** Bei Joyn öffnet „Bei Joyn ansehen“ jetzt gleich den Player (`joyn.de/play/filme/…` bzw. `/play/serien/…/<folge>`), nicht mehr die Detailseite. Gilt für Kacheln, Titel- und Serienseiten, Plattform-Reiter und Live-TV. Bei Rakuten TV, TOGGO und JustWatch TV bleibt die bisherige Seite, weil deren Player-Adresse nicht belegt ist.
- **Optionale Chrome-Erweiterung „MediathekAtlas Videostart“:** Verwaltung → Einstellungen → „Videostart bei Anbietern“ → ZIP herunterladen, entpacken, in Chrome unter `chrome://extensions` mit Entwicklermodus → „Entpackte Erweiterung laden“. Danach klickt sie bei Links aus MediathekAtlas den Abspielknopf und bestätigt den HDCP-Hinweis. Kaufen, Leihen, Abo, Anmelden und Cookie-Zustimmung klickt sie nie. Sie wird nur auf rakuten.tv, joyn.de, toggo.de und justwatch.com aktiv, nur bei Links aus MediathekAtlas und höchstens 90 Sekunden lang. Sie verschickt keine Daten.
- Chrome erlaubt Autoplay mit Ton nur nach einem Klick in die Seite. Lehnt Chrome ab, startet das Video stumm, und der erste Klick schaltet den Ton ein. Dauerhaft mit Ton: beim Anbieter Schloss-Symbol → Website-Einstellungen → Ton: Zulassen.
- Mit dem Schalter im selben Bereich lässt sich alles abschalten. Der Kopierschutz wird nicht umgangen.
- **Nicht geprüft:** die echten Seiten von Rakuten TV, Joyn, TOGGO und JustWatch (aus der Bauumgebung gesperrt). Die Erweiterung erkennt Knöpfe an ihrer Beschriftung. Ändert ein Anbieter sie, öffnet der Link die Seite wie bisher, und man klickt selbst.
- Sammelstand: 0.5.91 enthält 0.5.88, 0.5.89 (YouTube 1080p) und 0.5.90 (Joyn-Sender).

## Neu in 0.5.90: Joyn-Sender öffnen den richtigen Sender

- **Live-TV → Joyn öffnete arte.** Bei 114 von 128 Joyn-Sendern zeigte der Knopf „Joyn“ auf die allgemeine Live-Seite von joyn.de. Joyn spielt dort seinen Standardsender, deshalb landete man z. B. bei Naruto oder SAT.1 auf arte. Jetzt öffnet jeder Knopf die Player-Seite genau dieses Senders, so wie joyn.de selbst verlinkt (`/play/live-tv?channel_id=…`).
- Ein schon geladener Joyn-Katalog wird kurz nach dem Start mit einer einzigen Anfrage repariert, Filme und Serien bleiben unverändert. Bis dahin zeigen Joyn-Sender keinen falschen Link, sondern „Direktlink folgt nach dem nächsten Joyn-Abruf“.
- Geprüft: Pluto TV, Rakuten TV und ARD/ZDF & Co. spielen je Sender über die eigene Kennung ab und haben keinen solchen Sammel-Link. Joyns „Hessischer Rundfunk“ steht jetzt beim hr-fernsehen.
- Sammelstand: 0.5.90 baut auf 0.5.88 auf (enthält 0.5.86 und 0.5.87). 0.5.89 ist für die YouTube-Auflösung reserviert.

## Neu in 0.5.89: YouTube im eigenen Player in 1080p

- Bisher lief YouTube im eigenen Player oft nur in 480p. Ohne Anmeldung bietet YouTube Bild und Ton als getrennte H.264-Dateien häufig nur bis 480p an; die höheren Stufen gibt es als HLS-Stream (Bild und Ton zusammen) oder als VP9. MediathekAtlas nahm die erste passende Variante statt der höchsten.
- Jetzt wählt MediathekAtlas die höchste Auflösung bis zur Grenze: „Automatisch“ bis 1080p, „Beste“ bis 2160p. Bei gleicher Auflösung wird H.264 vor VP9 bevorzugt, weil Safari H.264 sicher abspielt.
- Unter „Qualität“ stehen jetzt die Auflösungen, die YouTube für das jeweilige Video anbietet.

## Neu in 0.5.88: Ganze Staffeln von Archive.org laden, Uploader erkannter Werke vormerken

- **Staffeln und Folgen auswählen.** Bisher musste bei einem Upload mit vielen Dateien jede Folge einzeln angeklickt werden. In der Detailansicht eines Archive.org-Uploads (Plattformen → Internet Archive → „Fassungen, Folgen und Sprachen prüfen“) gibt es jetzt den Bereich „Staffeln und Folgen auswählen“: Tonsprache, Untertitel, Auflösung, Dateiformat und Staffel wählen, „Auswahl anzeigen“ zeigt je Folge die beste passende Datei und bei fehlenden Folgen den Grund. Mit einem Klick werden die angehakten Dateien vorgemerkt (höchstens 300 auf einmal). Eine Sprache aus dem Dateinamen gilt als Hinweis; mit „Sprache muss durch die Tonspur belegt sein“ zählen nur Dateien, deren Spuren geprüft wurden.
- **Uploader erkannter Werke.** Wer einen erkannten Film oder eine erkannte Serie hochgeladen hat, hat oft mehr davon. Das öffentliche Archive.org-Konto solcher Uploads wird als Scanquelle vorgemerkt (Plattformen → Internet Archive → Scanquellen, mit dem Hinweis „Uploader von …“). Vorgemerkte Konten sind pausiert und werden erst durchsucht, wenn du sie startest; ein entferntes Konto kommt nicht wieder. E-Mail-Adressen von Uploadern werden nie gelesen oder gespeichert.
- Sammelstand: 0.5.88 enthält auch 0.5.86 (flüssige Wiedergabe) und 0.5.87 (TOGGO nach dem Mitschnitt).

## Neu in 0.5.87: TOGGO nach dem echten Angebot von toggo.de

- Grundlage ist Björns Mitschnitt von toggo.de (13.11.2026). TOGGO lädt den Katalog jetzt so, wie die Website selbst: **alle Serien und zusätzlich alle Filme**, mit Titelbild, Beschreibung, Altersempfehlung, Staffeln und Folgen. Die bisherige Ableitung aus der Seitenübersicht (0.5.79 bis 0.5.85) entfällt; der alte TOGGO-Bestand wird beim ersten Start ersetzt, danach bitte einmal „Katalog jetzt laden“.
- **Kostenlos oder Abo:** Jede Kachel und jede Folge zeigt „kostenlos“ (bei Folgen aus dem Fernsehprogramm mit Enddatum, z. B. „kostenlos bis 20.11.“) oder „Nur mit Abo“. Im Reiter „TOGGO“ gibt es die Auswahl „Angebot“: Alles, nur Kostenloses, nur mit Abo, TOGGOLINO (Vorschule), TOGGO (Schulkinder). Die Serienseite nennt, wie viele Folgen kostenlos sind.
- **Wiedergabe:** Der Mitschnitt zeigt, dass TOGGO alle Folgen und Filme, auch die kostenlosen, nur mit Kopierschutz (Widevine/PlayReady/FairPlay) ausliefert. MediathekAtlas umgeht ihn nicht. Deshalb gibt es bei TOGGO keinen eigenen Player und kein Offline-Speichern; „Bei TOGGO ansehen“ öffnet genau die Folge oder den Film auf toggo.de. Sollte TOGGO einen Titel einmal ohne Kopierschutz anbieten, erscheint dort „▶ Ansehen“.
- TOGGO-Filme stehen auch im gemeinsamen Katalog unter „Filme“.
- **Nicht geprüft:** ein Abruf gegen toggo.de selbst (aus der Bauumgebung gesperrt). Die Anfragen entsprechen dem Mitschnitt; ob das Blättern bei mehr als 500 Titeln je Liste so funktioniert, war im Mitschnitt nicht enthalten (aktuell 182 Serien und 104 Filme, also eine Antwort je Liste).
- Diese Version baut auf 0.5.85 auf und enthält alles daraus.

## Neu in 0.5.86: Videos laufen im eigenen Player flüssig

- YouTube im eigenen Player: Bild und Ton werden wie auf youtube.com in Stücken von 4 MB geladen, drei gleichzeitig. Bisher kam ein Video nur ungefähr in Abspielgeschwindigkeit an (laut Diagnose 1,8 Mbit/s, erstes Bild nach 8 s, nach dem Spulen 20 s nichts), dadurch stockte es ständig.
- Alle Streams, die MediathekAtlas umwandelt (YouTube, Pluto TV, Rakuten, Sender-Streams ohne direkten Zugriff, MKV-Dateien): Nach dem Spulen oder beim Weiterschauen startet das Bild jetzt genau an der Stelle. Bisher stand es bis zu einige Sekunden still, während der Ton schon lief.
- Der Startpuffer aus 0.5.77 gilt nicht mehr für umgewandelte Streams. Chrome meldet bei ihnen nie genug Vorrat, deshalb hielt der Player das Bild nach jedem kurzen Stocken wieder mindestens 3 s an.
- Während ein Video läuft, lädt die Seite dahinter ihren Stand nicht mehr alle 2,5 s neu. Die Diagnose nennt jetzt auch ausgelassene Bilder je Wiedergabe.

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

# Änderungsverlauf – MediathekAtlas

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

# Änderungsverlauf – MediathekAtlas

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

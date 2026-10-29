# NAS-Pakete: Synology (SPK) und QNAP (QPKG)

MediathekAtlas läuft auf dem NAS als Hintergrunddienst mit Weboberfläche im Heimnetz:
`http://<NAS-Adresse>:8730/`. Der Server ist reines Python (Standardbibliothek), daher gibt es je
Plattform **ein** architekturunabhängiges Paket für x86_64, ARM64, ARMv7 und ältere Modelle.

## Bauen

```sh
python3 -m pip install pillow                 # nur für Paket-Icons
python3 build_nas.py                          # dist/MediathekAtlas-<Version>-noarch.spk + build/qnap (QDK-Projekt)
python3 build_nas.py --qbuild /usr/share/QDK/bin/qbuild   # zusätzlich dist/MediathekAtlas_<Version>.qpkg
```

Die GitHub-Action „NAS-Pakete“ baut beide Pakete bei jedem Push/PR (QPKG mit dem offiziellen
QNAP QDK v2.5.3), prüft sie und stellt sie als Artefakt `MediathekAtlas-NAS-Pakete` bereit.

## Synology DSM 7

| Punkt | Umsetzung |
|---|---|
| Installation | Paket-Zentrum → Manuelle Installation → `.spk`. Unsigniert: Hinweis „unbekannter Herausgeber“ bestätigen. |
| Python | Abhängigkeit `Python3.9` wird vom Paket-Zentrum mitinstalliert. Neuere SynoCommunity-Pythons werden bevorzugt, falls vorhanden. |
| Rechte | Dienst läuft als Paketbenutzer `mediathekatlas`, nie als root (`conf/privilege`). |
| Downloads | Freigegebener Ordner **MediathekAtlas** (wird angelegt, Paketbenutzer erhält Schreibrecht). Andere Freigabe: Systemsteuerung → Freigegebener Ordner → Berechtigungen → Systeminterner Benutzer `mediathekatlas` Lesen/Schreiben geben, danach Zielordner in MediathekAtlas → Einstellungen ändern. |
| Katalog/Einstellungen | `/var/packages/MediathekAtlas/var` (bleibt bei Updates erhalten). |
| Zugang | Passwort im Installationsassistenten; nur als PBKDF2-Hash gespeichert. |
| Öffnen | DSM-Hauptmenü → MediathekAtlas, oder Port 8730. Firewall-Profil `MediathekAtlas` wird mitgeliefert. |
| FFmpeg | Für Downloads z. B. SynoCommunity `ffmpeg7`; wird automatisch gefunden. |

## QNAP QTS

| Punkt | Umsetzung |
|---|---|
| Installation | App Center → Manuell installieren → `.qpkg`. Unsigniert: In App Center-Einstellungen „Installation von Anwendungen ohne gültige digitale Signatur zulassen“ aktivieren. |
| Python | App Center „Python3“ (ab 3.9) oder Entware `/opt/bin/python3`. |
| Rechte | Das App-Center-Skript läuft als root, startet den Server aber als `httpdusr` (Rechteabgabe vor dem ersten Anwendungscode). |
| Downloads | `<Freigabe Download, sonst Multimedia, sonst Public>/MediathekAtlas`, Gruppe `everyone`, `2775`. |
| Katalog/Einstellungen | `<QPKG-Ordner>/data` (bleibt bei Updates erhalten, wird bei Deinstallation entfernt). |
| Zugang | Erster Aufruf zeigt die Ersteinrichtung: Code aus `MediathekAtlas-Einrichtungscode.txt` im Download-Ordner (File Station) eingeben und Passwort festlegen. |

## Konfiguration ohne Terminalpflicht

Alle Standardwerte funktionieren ohne Eingriff. Optional überschreibt eine Datei
`mediathekatlas.conf` im Datenordner (KEY=VALUE, wird nicht als Shell-Code ausgeführt):
`PORT`, `DOWNLOADS`, `PYTHON`, `FFMPEG`, `FFPROBE`, `RUN_AS` (nur QNAP), `LISTEN`.
Der Zielordner lässt sich zusätzlich jederzeit in der Weboberfläche ändern.

## Sicherheit

- Netzwerkmodus erzwingt Anmeldung (Cookie `HttpOnly`, `SameSite=Strict`, 7 Tage), zusätzlich das bisherige Sitzungs-Token für jede API-Anfrage.
- Zehn Fehlversuche je Client in zehn Minuten sperren weitere Versuche.
- Kein HTTPS im Paket: für Zugriff außerhalb des Heimnetzes nur über VPN oder den NAS-Reverse-Proxy mit Zertifikat freigeben, nicht per Portweiterleitung.
- Desktop-Modus (macOS/Linux/Windows) bleibt unverändert: nur `127.0.0.1`, ohne Passwort.

## Anschluss an verteilte Erkennung / MeshSync (geplant)

Die Pakete trennen bewusst: Programmcode (schreibgeschützt), Zustand (`ATLAS_HOME`: SQLite,
Einstellungen, Zugang) und Medien (`DOWNLOADS` auf einer Freigabe). Ein späterer Sync-Dienst kann
dadurch Downloads direkt auf der Freigabe verteilen und Erkennungsergebnisse über die
authentifizierte HTTP-API austauschen, ohne Paketdateien zu verändern. Die eigentliche Sync-Logik
ist nicht Bestandteil dieser Pakete.

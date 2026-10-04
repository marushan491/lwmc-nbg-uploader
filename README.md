# LWMC NBG Audio Uploader

Eine Python-Anwendung mit Dateiauswahl und Terminal-Modus für zwei unabhängige Wege:

| Weg | Verarbeitung | Ziel |
|---|---|---|
| Spreaker | WAV/MP3 → Lautheit messen → normalisieren → MP3 | Episode in ausgewählter Spreaker-Show |
| Worship | WAV/MP3 → optional normalisieren → MP3 | Google-Drive-Ordner |

Separate WAV/MP3-Dateilisten; beide Wege können gleichzeitig laufen. Innerhalb eines Wegs werden Dateien nacheinander verarbeitet. Spreaker wird immer normalisiert, Worship nach Auswahl. Standard: Stereo, 44,1 kHz, 192 kbit/s CBR, Normalisierung auf −16 LUFS, True-Peak-Ziel −1,5 dBTP, LRA-Ziel 11. FFmpeg verwendet zweipassiges `loudnorm` und bei Bedarf dessen dynamischen Modus. MP3-Encoding kann die gemessene Lautheit/Peaks leicht verändern. Original-WAVs und Original-MP3s bleiben erhalten. Stille Dateien werden bei aktivierter Normalisierung mit einer verständlichen Meldung abgewiesen.

## Downloads und Voraussetzungen

Der Quellcode läuft auf Windows, Linux und macOS mit **Python 3.10+**, **Tkinter** und **FFmpeg** (einschließlich `ffprobe`; für Vorschau zusätzlich `ffplay`). Die Oberfläche ist auf allen drei Systemen identisch. Die separat gebauten Release-ZIPs enthalten Python und die Python-Abhängigkeiten. **FFmpeg wird separat installiert und muss im PATH liegen.** Die Anwendung enthält keine persönlichen Zugangsdaten.

Der Workflow `.github/workflows/release.yml` baut Windows x64, Linux x64, macOS Intel und macOS Apple Silicon auf jeweils nativen GitHub-Runnern. Ein Push auf `main` oder ein `v*`-Tag veröffentlicht alle vier ZIPs erst, wenn alle Builds erfolgreich sind. Bei einem Push auf `main` wird ein Release-Tag `v1.1.<Workflow-Nummer>` erzeugt. Manuell ausgelöste Builds erscheinen unter Actions → Artifacts. Die Binärpakete werden nicht als bereits vorhanden dargestellt, bevor ein Build tatsächlich abgeschlossen wurde.

### Windows

1. Für das Skriptpaket Python von https://www.python.org/downloads/windows/ installieren; Python zum PATH hinzufügen. Bei fertigen Release-Binärpaketen entfällt dies. Das Windows-Binärpaket öffnet keine Konsole; auch die FFmpeg-Unterprozesse starten ohne zusätzliche Terminal-Fenster.
2. FFmpeg installieren, beispielsweise im Terminal:

   ```powershell
   winget install --id Gyan.FFmpeg -e
   ```

3. Ein neues Terminal öffnen. Im entpackten Skriptordner:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1
   .\start-windows.bat
   ```

   Im Binärpaket stattdessen `WorshipUploader.exe` starten. Das ganze ZIP entpacken, nicht nur die EXE herauskopieren.

### Linux (Debian/Ubuntu)

```bash
sudo apt update
sudo apt install python3 python3-venv python3-tk ffmpeg
chmod +x setup.sh start.sh
./setup.sh
./start.sh
```

Bei fertigen Binärpaketen reicht FFmpeg plus eine grafische Sitzung. Falls die Ausführungsrechte beim Entpacken verloren gehen: `chmod +x WorshipUploader`. Linux-Releases werden auf Ubuntu 22.04 gebaut und benötigen glibc 2.35 oder neuer; keine Alpine/musl-Binärpakete. Für SSH ohne grafische Sitzung den Terminal-Modus verwenden.

### macOS

Für das Skriptpaket Python mit Tkinter verwenden, zum Beispiel die Python-3.12-Installation von python.org. Mit vorhandenem Homebrew kann FFmpeg über `brew install ffmpeg` installiert werden. Bei Homebrew-Python zusätzlich das zur Python-Version passende `python-tk`-Paket installieren.

```bash
chmod +x setup.sh start.sh Start.command
./setup.sh
./start.sh
```

Alternativ nach der Einrichtung `Start.command` doppelklicken. Im Binärpaket **WorshipUploader.app** doppelklicken; die App öffnet kein Terminal-Fenster. Intel und Apple Silicon haben getrennte ZIPs. Die Builds sind nicht mit einem Apple-Developer-Zertifikat signiert oder notarisiert; macOS kann beim ersten Start eine Freigabe unter Datenschutz & Sicherheit verlangen.

## Einmalige Einrichtung über die Oberfläche

1. **Einrichtungshilfe** öffnen, wenn du noch keine OAuth-Zugangsdaten hast. Danach **Einstellungen** öffnen.
2. Für Spreaker Client-ID, Client-Secret, Show-ID und Redirect-URI eintragen.
3. Für Drive die OAuth-Desktop-JSON auswählen, optional eine Ordner-ID eintragen.
4. Speichern, anschließend **Spreaker anmelden** und/oder **Drive anmelden**.
5. WAV- oder MP3-Dateien direkt auswählen oder im **Audio-Editor** Teile vorbereiten.
6. **MP3 speichern und hochladen** wählen. Optional Worship normalisieren; optional Parallelbetrieb ausschalten.
7. **Speichern und hochladen** drücken und einen Zielordner wählen. Die MP3-Dateien werden dort gespeichert und danach hochgeladen.

Der Episodentitel und der Drive-Dateiname werden aus dem WAV-Dateinamen abgeleitet. Zum Beispiel `Predigt 04.10.2026.wav` → Titel `Predigt 04.10.2026`. Eine Beschreibung für Spreaker lässt sich in `config.json` setzen.

**Spreaker ist standardmäßig privat.** Erst die Option „Spreaker öffentlich veröffentlichen“ bzw. `--public` macht die neue Episode öffentlich. Privat ist kein Entwurf. Die öffentliche Sichtbarkeit des GitHub-Projekts beeinflusst diese Einstellung nicht. Spreaker verarbeitet eine angenommene Episode noch serverseitig; die Uploadbestätigung bedeutet nicht, dass sie sofort abspielbar ist.

## Aufnahme schneiden und teilen

**Aufnahme schneiden / teilen** öffnet den Editor:

1. Eine oder mehrere WAV-/MP3-Dateien öffnen. Per Dateiauswahl oben zwischen den Aufnahmen wechseln.
2. Start und Ende als Sekunden, `MM:SS` oder `HH:MM:SS.mmm` eingeben. Alternativ den passenden Marker wählen und in die Wellenform klicken.
3. Titel und Ziel (**Spreaker**, **Drive (Worship)** oder **Beide**) wählen und **Teil hinzufügen**.
4. Für zwei Spreaker-Teile **Spreaker** wählen, den Teilungsmarker setzen und **Bei Teilung teilen** klicken.
5. Für den Worship-Teil den gewünschten anderen Bereich wählen, Ziel **Drive (Worship)** setzen und hinzufügen.
6. **Auswahl ausschneiden** entfernt einen Bereich aus allen geplanten Teilen dieser Originaldatei. Die übrigen Bereiche werden beim Export verbunden; die Originaldatei wird nicht gelöscht oder überschrieben.
7. Markierte Teile können aus der Planung gelöscht, einem anderen Ziel zugeordnet oder in Listenreihenfolge verbunden werden. So lassen sich auch zwei getrennte Aufnahme-Dateien zusammenführen.
8. **Rückgängig** stellt den letzten Planungsstand wieder her. **Auswahl anhören** spielt die behaltenen Bereiche ab; dafür wird `ffplay` benötigt.
9. **Teile erzeugen und in die Upload-Listen übernehmen** erzeugt verlustfreie PCM-WAVs. Danach im Hauptfenster Normalisierung wählen und Upload starten.

Beispiel: Predigt 1 → Spreaker, Predigt 2 → Spreaker, Worship → Drive. Die Zwischen-WAVs liegen unter `~/.audio-uploader/edits`; sie beanspruchen deutlich mehr Platz als MP3. Normalisierung und abschließende MP3-Konvertierung erfolgen erst beim Upload. MP3-Eingaben werden decodiert; die Schnittfunktion verursacht keinen zusätzlichen MP3-Kodierungsschritt. An Schnittstellen können harte Übergänge auftreten; es werden keine automatischen Crossfades eingefügt.

## MP3 exportieren ohne Anmeldung

**MP3 speichern** ist im Hauptfenster vorausgewählt. Dateien hinzufügen, bei Bedarf schneiden, dann den einzigen Hauptbutton **MP3 speichern** drücken und einen Zielordner wählen. Es erfolgt kein Upload und keine Spreaker-/Google-Anmeldung; auch Show-ID und Google-Zugangsdaten sind dafür nicht nötig. Predigt-/Spreaker-Teile werden normalisiert, bei Worship entscheidet der Schalter **Worship-Lautstärke normalisieren**. Die Dateien liegen getrennt in den Unterordnern `spreaker` und `drive`. FFmpeg muss installiert sein. Das Speichern funktioniert auch offline und bei Browser-403. Erst bei **MP3 speichern und hochladen** erscheinen die Konto- und Veröffentlichungsoptionen.

## GitHub-Update-Meldung

Die App prüft beim Start höchstens einmal täglich den neuesten stabilen Release des öffentlichen Projekts `marushan491/lwmc-nbg-uploader`. **Nach Updates suchen** prüft jederzeit manuell. In den Einstellungen lässt sich die automatische Prüfung ausschalten. Die Prüfung benötigt Internet und sendet keine Aufnahmen oder OAuth-Zugangsdaten an GitHub.

Bei einer neueren Version erscheint eine Meldung mit Release-Link und passendem Download für dein Paket/OS. Es gibt bewusst keinen Austausch laufender Programmdateien: ZIP entpacken, neue Anwendung starten und die alte schließen. Gespeicherte Konfiguration und Anmeldedaten im Benutzerverzeichnis bleiben erhalten. Die Versionsnummer des Binärpakets entspricht dem Release-Tag. Über den Python-Quellcode ist auch `python audio_uploader.py check-update` möglich.

## Anmeldung abbrechen und 403

Wenn die Browserseite geschlossen wird oder 403 anzeigt, kann die App das Schließen des externen Browser-Tabs nicht erkennen. **Anmeldung abbrechen** gibt die Bedienelemente sofort wieder frei. Verspätete Antworten eines abgebrochenen Versuchs sperren einen neueren Vorgang nicht erneut. Ohne Antwort wird der Browser-Login nach 120 Sekunden beendet. Auch das Schließen der Anwendung während der Anmeldung bricht den Wartevorgang ab.

Ein 403 auf der Anbieter-Browserseite lässt sich nicht allein durch den Statuscode eindeutig bestimmen. Bei Spreaker die eigene OAuth-App, Client-ID und exakt registrierte Redirect-URI prüfen. Bei Google die Drive API, die Desktop-Client-JSON und bei einer persönlichen External-Test-App den verwendeten Google-Account in **Google Auth Platform → Audience → Test users** prüfen. Workspace-Administratoren können Apps blockieren. Die **Einrichtungshilfe** erklärt beide Wege direkt in der Anwendung. Ein Browser-403 wird nicht als erfolgreich behoben behauptet; der Anbieter muss die Freigabe tatsächlich zulassen.

## Spreaker-Zugang

Offizielle Anleitung: https://developers.spreaker.com/guides/authentication/

- Developer Tools im Spreaker-Konto aktivieren und eine eigene OAuth-Anwendung registrieren.
- Als Redirect-URI exakt `http://127.0.0.1:8765/callback` registrieren. Falls Spreaker diese URI für deinen App-Typ nicht zulässt, eine akzeptierte URI konfigurieren und den manuellen Terminal-Login nutzen.
- Client-ID und Client-Secret in den Einstellungen eintragen. Show-ID aus der eigenen Show ermitteln; der verwendete Account muss die Show besitzen.
- Im Terminal alternativ:

  ```bash
  ./start.sh login-spreaker
  ```

- Vorhandener Access-Token ist ebenfalls möglich: `SPREAKER_ACCESS_TOKEN` als Umgebungsvariable setzen. Der Token wird nicht in Protokollen ausgegeben. `SPREAKER_CLIENT_SECRET` überschreibt das konfigurierte Secret.
- Access- und Refresh-Token werden lokal gespeichert und bei Bedarf erneuert. Für persönlichen Gebrauch muss jeder Benutzer seine eigene OAuth-App konfigurieren; keine gemeinsamen Secrets in öffentliche Downloads eintragen.

Manueller Login über SSH:

```bash
./start.sh login-spreaker --manual
```

Die ausgegebene URL auf dem eigenen Rechner öffnen. Nach Zustimmung die vollständige Weiterleitungs-URL mit `code` und `state` in das Terminal einfügen. Der Redirect-Server muss für diese Variante nicht erreichbar sein; im Browser kann die lokale Zielseite einen Verbindungsfehler zeigen. Die URL enthält ein kurzlebiges Anmeldegeheimnis und gehört nicht in Screenshots oder Chats.

## Google Drive

Offizielle Einrichtung: https://developers.google.com/workspace/drive/api/quickstart/python

1. Eigenes Google-Cloud-Projekt erstellen und Google Drive API aktivieren.
2. OAuth-Zustimmungsbildschirm konfigurieren, bei Testbetrieb den eigenen Account als Testnutzer hinzufügen.
3. OAuth-Client vom Typ **Desktop-App** erstellen und JSON herunterladen.
4. Die JSON in den Einstellungen auswählen. Alternativ als `google_credentials.json` neben dem Skript speichern und in `config.json` referenzieren.
5. **Drive anmelden** klicken oder `./start.sh login-drive` verwenden.

Standardmäßig wird nur `drive.file` angefragt. Bei leerer Ordner-ID erstellt die Anwendung einen eigenen **Worship**-Ordner und merkt sich dessen ID. Der Zugriff ist auf von der App erstellte oder für sie autorisierte Dateien beschränkt.

Ein beliebiger bereits vorhandener Ordner ist durch Eingabe seiner ID nicht automatisch für `drive.file` freigegeben. Für diesen Fall in den Einstellungen **Drive-Vollzugriff für vorhandenen Ordner** aktivieren (`full_access: true`), erneut anmelden und eine Ordner-ID eintragen. Diese Option gewährt die weitergehende Google-Berechtigung `drive`; die Anwendung verwendet sie zum Prüfen des Zielordners und für Uploads. Für eine öffentliche OAuth-App können zusätzliche Google-Verifikationsanforderungen gelten. Geteilte Ablagen benötigen Schreibberechtigung auf den Zielordner; unterstützt werden dessen IDs, nicht Ordnerlinks.

Bei einem Google-Kontowechsel die gespeicherte Worship-Ordner-ID prüfen. Test-Apps können erneute Autorisierung verlangen. Uploads verwenden 8-MiB-Chunks mit begrenzten Wiederholungsversuchen für vorübergehende Fehler.

SSH-Login mit Port-Weiterleitung:

```bash
# Vom lokalen Rechner mit Browser:
ssh -L 8766:127.0.0.1:8766 USER@HOST
# Auf dem Server in der SSH-Sitzung:
./start.sh login-drive --port 8766 --no-browser
```

Die ausgegebene URL im lokalen Browser öffnen. Die Weiterleitung erreicht den Server über den SSH-Tunnel.

## Terminal-Beispiele

Beide Wege parallel, Worship normalisieren:

```bash
./start.sh upload --spreaker '/pfad/Predigt.wav' --drive '/pfad/Worship.wav' --normalize-drive
```

Spreaker öffentlich veröffentlichen:

```bash
./start.sh upload --spreaker '/pfad/Predigt.wav' --public
```

Worship ohne Normalisierung:

```bash
./start.sh upload --drive '/pfad/Worship 1.wav' '/pfad/Worship 2.wav'
```

Zuerst nur lokal MP3s erzeugen (keine Anmeldung erforderlich):

```bash
./start.sh upload --spreaker '/pfad/Predigt.wav' --drive '/pfad/Worship.wav' --convert-only
```

Auf Windows `start-windows.bat` statt `./start.sh` verwenden. Für Terminal-Aufrufe auf Windows/macOS den Python-Quellcode verwenden; die Desktop-Binärpakete starten ohne Konsole. Unter Linux unterstützt auch die Binärdatei den Terminal-Modus. `--sequential` deaktiviert parallele Verarbeitung. Exit-Codes: 0 erfolgreich, 1 Fehler, 130 Abbruch.

## Dateien, Fehler und Wiederholungen

- MP3s landen standardmäßig unter `~/Music/WorshipUploader`, getrennt nach Ziel. `audio.output_dir` kann den Pfad überschreiben. Die Beispielkonfiguration verwendet einen Unterordner `output` neben dem Skript.
- Konfiguration und Anmeldedaten liegen standardmäßig unter `~/.audio-uploader`. Falls beim Skript eine `config.json` daneben liegt, wird diese verwendet. `AUDIO_UPLOADER_STATE` überschreibt das Anmeldedatenverzeichnis.
- Lokale Token- und Konfigurationsdateien werden atomar geschrieben und auf Unix mit Rechten nur für den Benutzer angelegt. Auf Windows gelten die Rechte des persönlichen Benutzerverzeichnisses. Keine Tokens, OAuth-JSONs oder echten Konfigurationen committen; `.gitignore` schließt die üblichen Dateien aus.
- Das lokale Erfolgsprotokoll `successful_uploads.json` enthält Ziel-IDs und Links. Bei gleicher Quelldatei, gleichem Ziel und gleichen Einstellungen werden bestätigte erfolgreiche Uploads übersprungen. `--force` erzwingt einen neuen Upload. Das ist keine globale Duplikaterkennung auf den Plattformen.
- Jede neue Drive-Datei bleibt unter den Berechtigungen des Zielordners. Die Anwendung schaltet keine öffentliche Freigabe ein und ersetzt keine vorhandenen Dateien.
- Nach einem Spreaker-Netzwerkfehler kann der Server die Datei bereits angenommen haben. Zuerst im Konto prüfen, bevor erneut hochgeladen wird. Upload-POSTs werden deshalb nicht automatisch wiederholt. Das gilt auch nach Abbruch oder wenn das lokale Erfolgsprotokoll nicht geschrieben werden konnte.
- Dateien während der Verarbeitung nicht verändern und keine zwei Instanzen gleichzeitig mit demselben Anmeldedatenverzeichnis starten.
- Ein Fehler während eines Datei-Uploads verhindert nicht den anderen Weg. Zugangsdaten und Ordnerberechtigungen werden vor Beginn gemeinsam geprüft; bei fehlender Anmeldung zuerst den betroffenen Weg anmelden oder aus der Auswahl entfernen.

## Entwicklung und Release

```bash
python3 -m unittest discover -s tests -v
```

Die Audio-Integrationstests benötigen `ffmpeg` und `ffprobe`; ohne diese werden nur die Audiotests übersprungen. Weitere Tests prüfen Parallelbetrieb, getrennte Normalisierung, Fehlerisolation, Schnitt/Verbindung, unveränderte Originale, Update-Versionen, OAuth-State und Anmelde-Abbruch. GUI-Tests prüfen die Zielzuordnung und dass eine verspätete OAuth-Antwort die Oberfläche nicht erneut sperrt. Sie benötigen eine grafische Sitzung; auf Linux führt CI sie mit Xvfb aus. Die Tk-Fenstertests laufen in CI auf Windows und Linux; auf macOS benötigen sie eine lokale Desktop-Sitzung und werden auf den CI-Runnern übersprungen. Die übrigen Tests und der Build-/Versions-Starttest laufen auch auf macOS.

Repository: https://github.com/marushan491/lwmc-nbg-uploader

Ein Push auf `main` startet automatisch die Builds und erstellt anschließend einen Release mit allen Downloads. Alternativ lässt sich eine feste Version über ein Tag veröffentlichen:



```bash
git tag v1.1.0
git push origin v1.1.0
```

GitHub Actions muss aktiviert sein. Der Workflow veröffentlicht Download-ZIPs mit Drittanbieter-Lizenzhinweisen. Keine Spreaker-/Google-Zugangsdaten sind für den Build nötig. Plattform-Builds werden erst durch tatsächliche GitHub-Actions-Läufe geprüft; lokale Tests beweisen keine native Windows-/macOS-Ausführung. Live-Uploads benötigen eigene Konten und wurden nicht durch die automatischen Tests ausgelöst.

## API-Referenzen

- Spreaker Upload: https://developers.spreaker.com/guides/upload-an-episode/
- Spreaker OAuth: https://developers.spreaker.com/guides/authentication/
- Google Drive Upload: https://developers.google.com/workspace/drive/api/guides/manage-uploads
- Google Drive Scopes: https://developers.google.com/workspace/drive/api/guides/api-specific-auth
- FFmpeg loudnorm: https://ffmpeg.org/ffmpeg-filters.html#loudnorm

MIT-Lizenz für diese Anwendung; externe Programme und Python-Bibliotheken haben eigene Lizenzen.

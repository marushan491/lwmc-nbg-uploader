# LWMC NBG Audio Uploader

Eine Python-Anwendung mit Dateiauswahl und Terminal-Modus für zwei unabhängige Wege:

| Weg | Verarbeitung | Ziel |
|---|---|---|
| Spreaker | WAV → Lautheit messen → normalisieren → MP3 | Episode in ausgewählter Spreaker-Show |
| Worship | WAV → optional normalisieren → MP3 | Google-Drive-Ordner |

Separate WAV-Dateilisten; beide Wege können gleichzeitig laufen. Innerhalb eines Wegs werden Dateien nacheinander verarbeitet. Spreaker wird immer normalisiert, Worship nach Auswahl. Standard: Stereo, 44,1 kHz, 192 kbit/s CBR, Normalisierung auf −16 LUFS, True-Peak-Ziel −1,5 dBTP, LRA-Ziel 11. FFmpeg verwendet zweipassiges `loudnorm` und bei Bedarf dessen dynamischen Modus. MP3-Encoding kann die gemessene Lautheit/Peaks leicht verändern. Original-WAVs bleiben erhalten. Stille Dateien werden bei aktivierter Normalisierung mit einer verständlichen Meldung abgewiesen.

## Downloads und Voraussetzungen

Der Quellcode läuft auf Windows, Linux und macOS mit **Python 3.10+**, **Tkinter** und **FFmpeg**. Die Oberfläche ist auf allen drei Systemen identisch. Die separat gebauten Release-ZIPs enthalten Python und die Python-Abhängigkeiten. **FFmpeg wird separat installiert und muss im PATH liegen.** Die Anwendung enthält keine persönlichen Zugangsdaten.

Der Workflow `.github/workflows/release.yml` baut Windows x64, Linux x64, macOS Intel und macOS Apple Silicon auf jeweils nativen GitHub-Runnern. Ein Push auf `main` oder ein `v*`-Tag veröffentlicht alle vier ZIPs erst, wenn alle Builds erfolgreich sind. Bei einem Push auf `main` wird ein Release-Tag `v1.0.<Workflow-Nummer>` erzeugt. Manuell ausgelöste Builds erscheinen unter Actions → Artifacts. Die Binärpakete werden nicht als bereits vorhanden dargestellt, bevor ein Build tatsächlich abgeschlossen wurde.

### Windows

1. Für das Skriptpaket Python von https://www.python.org/downloads/windows/ installieren; Python zum PATH hinzufügen. Bei fertigen Release-Binärpaketen entfällt dies.
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

Alternativ nach der Einrichtung `Start.command` doppelklicken. Im Binärpaket die enthaltene `Start.command` öffnen. Intel und Apple Silicon haben getrennte ZIPs. Die Builds sind nicht mit einem Apple-Developer-Zertifikat signiert oder notarisiert; macOS kann beim ersten Start eine Freigabe unter Datenschutz & Sicherheit verlangen.

## Einmalige Einrichtung über die Oberfläche

1. **Einstellungen** öffnen.
2. Für Spreaker Client-ID, Client-Secret, Show-ID und Redirect-URI eintragen.
3. Für Drive die OAuth-Desktop-JSON auswählen, optional eine Ordner-ID eintragen.
4. Speichern, anschließend **Spreaker anmelden** und/oder **Drive anmelden**.
5. WAV-Dateien in der jeweiligen Liste auswählen.
6. Optional Worship normalisieren; optional Parallelbetrieb ausschalten.
7. **Konvertierung / Upload starten**.

Der Episodentitel und der Drive-Dateiname werden aus dem WAV-Dateinamen abgeleitet. Zum Beispiel `Predigt 04.10.2026.wav` → Titel `Predigt 04.10.2026`. Eine Beschreibung für Spreaker lässt sich in `config.json` setzen.

**Spreaker ist standardmäßig privat.** Erst die Option „Spreaker öffentlich veröffentlichen“ bzw. `--public` macht die neue Episode öffentlich. Privat ist kein Entwurf. Die öffentliche Sichtbarkeit des GitHub-Projekts beeinflusst diese Einstellung nicht. Spreaker verarbeitet eine angenommene Episode noch serverseitig; die Uploadbestätigung bedeutet nicht, dass sie sofort abspielbar ist.

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

Auf Windows `start-windows.bat` statt `./start.sh` verwenden. Im Binärpaket `WorshipUploader` bzw. `WorshipUploader.exe` aufrufen. `--sequential` deaktiviert parallele Verarbeitung. Exit-Codes: 0 erfolgreich, 1 Fehler, 130 Abbruch.

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

Die Audio-Integrationstests benötigen `ffmpeg` und `ffprobe`; ohne diese werden nur die Audiotests übersprungen. Die übrigen Tests prüfen Parallelbetrieb, getrennte Normalisierung, Fehlerisolation und das Überspringen bereits bestätigter Uploads.

Repository: https://github.com/marushan491/lwmc-nbg-uploader

Ein Push auf `main` startet automatisch die Builds und erstellt anschließend einen Release mit allen Downloads. Alternativ lässt sich eine feste Version über ein Tag veröffentlichen:



```bash
git tag v1.0.0
git push origin v1.0.0
```

GitHub Actions muss aktiviert sein. Der Workflow veröffentlicht Download-ZIPs mit Drittanbieter-Lizenzhinweisen. Keine Spreaker-/Google-Zugangsdaten sind für den Build nötig. Plattform-Builds werden erst durch tatsächliche GitHub-Actions-Läufe geprüft; lokale Tests beweisen keine native Windows-/macOS-Ausführung. Live-Uploads benötigen eigene Konten und wurden nicht durch die automatischen Tests ausgelöst.

## API-Referenzen

- Spreaker Upload: https://developers.spreaker.com/guides/upload-an-episode/
- Spreaker OAuth: https://developers.spreaker.com/guides/authentication/
- Google Drive Upload: https://developers.google.com/workspace/drive/api/guides/manage-uploads
- Google Drive Scopes: https://developers.google.com/workspace/drive/api/guides/api-specific-auth
- FFmpeg loudnorm: https://ffmpeg.org/ffmpeg-filters.html#loudnorm

MIT-Lizenz für diese Anwendung; externe Programme und Python-Bibliotheken haben eigene Lizenzen.

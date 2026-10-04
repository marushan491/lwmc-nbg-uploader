"""Account setup guidance, without collecting credentials."""
import webbrowser


def show_setup_help(parent):
    import tkinter as tk
    from tkinter import ttk
    window = tk.Toplevel(parent)
    window.title('Spreaker und Google Drive einrichten')
    window.geometry('820x610')
    notebook = ttk.Notebook(window)
    notebook.pack(fill='both', expand=True, padx=15, pady=15)
    sections = [
        ('Spreaker', '''1. Im eigenen Spreaker-Konto die Developer Tools aktivieren.
2. Eine eigene OAuth-Anwendung registrieren.
3. Client-ID und Client-Secret dieser Anwendung kopieren.
   Diese Werte sind NICHT dein Spreaker-Benutzername und Passwort.
4. Als Redirect-URI exakt http://127.0.0.1:8765/callback registrieren
   und denselben Wert in den App-Einstellungen eintragen.
5. Show-ID deiner eigenen Podcast-Show in die Einstellungen eintragen.
6. Speichern und „Spreaker anmelden“ starten.

403 auf der Browserseite:
Die Freigabe wurde noch nicht erteilt. Prüfe die OAuth-App, die Client-ID,
die exakt passende registrierte Redirect-URI und ob du im richtigen
Spreaker-Konto angemeldet bist. Ein 403 kann außerdem eine Sperre oder
Berechtigungsbeschränkung beim Anbieter sein. Eine Show-ID wird erst
beim Upload gebraucht und löst keinen Browser-Loginfehler.

Bleibt die Browserseite blockiert, „Anmeldung abbrechen“ verwenden.
Für die genaue Ursache die Browserfehlermeldung prüfen oder den
Spreaker-Support kontaktieren; Passwörter und Tokens nicht teilen.''',
         [('Offizielle Spreaker-Anleitung', 'https://developers.spreaker.com/guides/authentication/')]),
        ('Google Drive', '''So bekommst du die Google-Zugangsdaten:
1. Google Cloud Console öffnen und ein Projekt erstellen/auswählen.
2. Unter „APIs & Dienste“ die Google Drive API aktivieren.
3. Unter „Google Auth Platform“ den OAuth-Zustimmungsbildschirm
   einrichten (App-Name und Kontakt-E-Mail).
4. Für die persönliche Test-App Zielgruppe „External“ auswählen und
   dein Google-Konto unter „Audience / Test users“ hinzufügen.
5. Unter „Clients“ einen OAuth-Client erstellen: Typ „Desktop app“.
6. Die Client-JSON herunterladen (nicht einen Service-Account-Key).
7. In dieser App: Einstellungen → Google JSON auswählen → Speichern.
8. „Drive anmelden“ und genau den eingetragenen Testnutzer auswählen.

403 / access_denied im Google-Browserdialog:
Oft fehlt der verwendete Account in der Testnutzerliste. Prüfe auch,
ob die Drive API aktiviert ist und die Desktop-JSON zum richtigen
Cloud-Projekt gehört. Bei Workspace-Konten kann der Administrator
OAuth-Zugriff beschränken. Die vollständige Meldung nennt den Grund.

Ohne Ordner-ID erstellt die App einen eigenen „Worship“-Ordner.
Für einen vorhandenen Ordner: ID eintragen, Drive-Vollzugriff aktivieren
und erneut anmelden. Dies ist eine weitergehende Google-Berechtigung.
Die Standardoption drive.file reicht für den eigenen neuen Ordner.''',
         [('Google Cloud Console', 'https://console.cloud.google.com/'),
          ('Offizielle Einrichtung', 'https://developers.google.com/workspace/drive/api/quickstart/python')])]
    for title, text, links in sections:
        frame = ttk.Frame(notebook, padding=12)
        notebook.add(frame, text=title)
        body = tk.Text(frame, wrap='word', height=24, padx=8, pady=8)
        body.insert('1.0', text)
        body.configure(state='disabled')
        body.pack(fill='both', expand=True)
        for label, url in links:
            ttk.Button(frame, text=label, command=lambda value=url: webbrowser.open(value)).pack(fill='x', pady=(5, 0))
    ttk.Button(window, text='Schließen', command=window.destroy).pack(pady=(0, 12))

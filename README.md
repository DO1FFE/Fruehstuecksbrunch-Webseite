# FrühstücksBrunchManager

## Überblick
Das Projekt *FrühstücksBrunchManager* ist eine Flask-basierte Webanwendung, die zur Verwaltung von Teilnehmern und Mitbringseln für Frühstücksbrunches dient. Benutzer können sich anmelden, um etwas beizutragen oder einfach nur zum Kaffee zu kommen. Die Admin-Seite ermöglicht es, alle Teilnehmer zu sehen und eine E-Mail an alle zu senden.

## Features
- Anmeldung für Teilnehmer mit Namen und E-Mail-Adresse
- Auswahl von Mitbringseln oder Anmeldung nur zum Kaffee
- Admin-Bereich zum Überblick aller Teilnehmer
- Mailto-Link zur Kontaktaufnahme mit allen Teilnehmern

## Voraussetzungen
- Python 3.10 oder höher
- Flask
- SQLite3

## Installation
1. Klone das Repository:
   ```
   git clone [URL-des-Repository]
   ```
2. Installiere die benötigten Python-Pakete:
   ```
   pip install -r requirements.txt
   ```
3. Erstellen Sie eine `.pwd`-Datei im Hauptverzeichnis mit den Admin-Anmeldedaten im Format:
   ```
   ADMIN_1:ADMIN_PASSWORD_1
   ADMIN_2:ADMIN_PASSWORD_2
   ```
4. Starte die Anwendung:
   ```
   python brunch.py
   ```

## Benutzung
Öffne deinen Webbrowser und gehe zu `http://localhost:8082/`, um die Anwendung zu verwenden. Für den Zugriff auf den Admin-Bereich ist eine Authentifizierung erforderlich.

## Autor
Erik Schauer, DO1FFE - do1ffe@darc.de

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
   git clone https://github.com/DO1FFE/Fruehstuecksbrunch-Webseite.git
   ```
2. Installiere die benötigten Python-Pakete:
   ```
   pip install -r requirements.txt
   ```
3. Erstellen Sie eine `.pwd`-Datei im Hauptverzeichnis mit den Admin-Anmeldedaten sowie den DAPNET-Zugangsdaten im Format (alle vier Einträge werden benötigt):
   ```
   ADMIN_1:ADMIN_PASSWORD_1
   ADMIN_2:ADMIN_PASSWORD_2
   dapnet_username:DAPNET_USER
   dapnet_password:DAPNET_PASS
   ```
4. Starte die Anwendung:
   ```
   python brunch.py
   ```

## Benutzung
Öffne deinen Webbrowser und gehe zu `http://localhost:8082/`, um die Anwendung zu verwenden. Für den Zugriff auf den Admin-Bereich `http://localhost:8082/admin` ist eine Authentifizierung erforderlich.

## Abweichende Termine
Sondertermine müssen nicht im Code gepflegt werden. Im Admin-Bereich gibt es
ein Feld **Abweichendes Datum**, über das sich das Datum des nächsten Brunches
nun über einen kleinen Kalender auswählen lässt. Zur Auswahl stehen ausschließlich
Sonntage. Setze optional das Kontrollkästchen
**Nächsten Termin ausfallen lassen**, um das Treffen komplett abzusagen. Bei
abweichenden oder abgesagten Terminen erscheint automatisch ein Hinweistext auf
der Startseite.

Die Datenbank der Anmeldungen wird jeweils um 15:00 Uhr des eingestellten
Brunch-Termins automatisch geleert. Dies gilt auch für verschobene Termine.

## Autor
Erik Schauer, DO1FFE - do1ffe@darc.de

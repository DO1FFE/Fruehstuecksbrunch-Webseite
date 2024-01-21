# Programm: FrühstücksBrunchManager
# Autor: Erik Schauer, DO1FFE, do1ffe@darc.de
# Erstelldatum: 2023-12-16

from flask import Flask, request, render_template_string, Response, redirect, url_for, send_from_directory, send_file
from functools import wraps
from datetime import datetime, timedelta
import logging
from logging.handlers import RotatingFileHandler
import sqlite3
import re
import threading
import time
import pytz
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from io import BytesIO
import requests

class DAPNET:
    """
    Diese Klasse implementiert einen Client für die DAPNET API.
    Sie ermöglicht das Senden von Nachrichten über das DAPNET-Netzwerk.
    """

    def __init__(self, callsign, password, url='http://www.hampager.de:8080/calls'):
        self.callsign = callsign
        self.password = password
        self.url = url
        self.headers = {'Content-type': 'application/json'}

    def send_message(self, message, destination_callsign, tx_group, emergency=False):
        data = {
            "text": message,
            "callSignNames": [destination_callsign] if isinstance(destination_callsign, str) else destination_callsign,
            "transmitterGroupNames": [tx_group] if isinstance(tx_group, str) else tx_group,
            "emergency": emergency
        }
        response = requests.post(self.url, headers=self.headers, auth=(self.callsign, self.password), json=data)
        return response

    def log_message(self, message, destination_callsigns, transmitter_group, emergency=False):
        """
        Sendet eine Logging-Nachricht über das DAPNET-Netzwerk.

        :param message: Der Inhalt der Nachricht.
        :param destination_callsigns: Eine Liste von Zielrufzeichen für die Nachricht.
        :param transmitter_group: Die Transmittergruppe für die Nachricht.
        :param emergency: Notfall-Flag (Standard False).
        :return: Das Response-Objekt der HTTP-Anfrage.
        """
        if isinstance(destination_callsigns, str):
            destination_callsigns = [destination_callsigns]
        return self.send_message(message, destination_callsigns, transmitter_group, emergency)

def setup_logger():
    logger = logging.getLogger('BrunchLogger')
    logger.setLevel(logging.DEBUG)
    handler = RotatingFileHandler('brunch.log', maxBytes=10000, backupCount=5)
    handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)
    return logger

logger = setup_logger()

def load_credentials():
    with open('.pwd', 'r') as file:
        credentials = {}
        for line in file:
            username, password = line.strip().split(':')
            credentials[username] = password
        return credentials

credentials = load_credentials()
dapnet_client = DAPNET(credentials['dapnet_username'], credentials['dapnet_password'])

# Überprüfen der Anmeldedaten
def check_auth(username, password):
    return username in credentials and credentials[username] == password

# Aufforderung zur Authentifizierung
def authenticate():
    return Response(
    'Zugriff verweigert. Bitte Authentifizieren.', 401,
    {'WWW-Authenticate': 'Basic realm="Login Required"'})

# Dekorator für Authentifizierung
def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

class DatabaseManager:
    def __init__(self, db_name='brunch.db'):
        self.db_name = db_name
        self.conn = None
        self.init_db()

    def get_connection(self):
        if not self.conn:
            self.conn = sqlite3.connect(self.db_name, check_same_thread=False)
        return self.conn

    def close_connection(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    def init_db(self):
        conn = self.get_connection()
        c = conn.cursor()
        # Hinzufügen der E-Mail-Spalte in der Datenbanktabelle
        c.execute('''CREATE TABLE IF NOT EXISTS brunch_participants 
                     (name TEXT, email TEXT, item TEXT, for_coffee_only INTEGER)''')
        conn.commit()

    def add_brunch_entry(self, name, email, item, for_coffee_only):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute('INSERT INTO brunch_participants (name, email, item, for_coffee_only) VALUES (?, ?, ?, ?)', 
                  (name, email, item, for_coffee_only))
        conn.commit()
        logger.debug(f"Neuer Eintrag: {name}, {email}, {item}, {for_coffee_only}.")
        dapnet_client.log_message(
            f"Frühstück: Neuer Eintrag: {name}, {email}, {item}, {for_coffee_only}.",
            ['DO1FFE', 'DO1EMC'],  # Mehrere Empfänger als Liste
            'all',
            False
        )

    def get_brunch_info(self):
        conn = self.get_connection()
        c = conn.cursor()
        # Anpassung der Abfrage, um die E-Mail-Adresse einzuschließen
        c.execute('SELECT name, email, item, for_coffee_only FROM brunch_participants')
        return c.fetchall()

    def reset_db(self):
        logger.debug("Resetting the database")
        conn = self.get_connection()
        c = conn.cursor()
        c.execute('DELETE FROM brunch_participants')
        conn.commit()

    def delete_entry(self, name):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute('DELETE FROM brunch_participants WHERE name = ?', (name,))
        conn.commit()

    def participant_exists(self, name):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute('SELECT * FROM brunch_participants WHERE name = ?', (name,))
        return c.fetchone() is not None

    def count_participants_excluding_coffee_only(self):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM brunch_participants WHERE for_coffee_only = 0')
        return c.fetchone()[0]

    def count_coffee_only_participants(self):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM brunch_participants WHERE for_coffee_only = 1')
        return c.fetchone()[0]

    def update_entry(self, old_name, new_name, email, item, for_coffee_only):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute('UPDATE brunch_participants SET name = ?, email = ?, item = ?, for_coffee_only = ? WHERE name = ?',
                  (new_name, email, item, for_coffee_only, old_name))
        conn.commit()

    def get_entry(self, name):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute('SELECT * FROM brunch_participants WHERE name = ?', (name,))
        return c.fetchone()
        
db_manager = DatabaseManager()

def next_brunch_date():
    # Zeitzone für Europe/Berlin definieren
    berlin_tz = pytz.timezone('Europe/Berlin')

    # Aktuelle Zeit in Berliner Zeitzone
    now = datetime.now(berlin_tz)
    month = now.month
    year = now.year

    # Erster Tag des Monats in Berliner Zeitzone
    first_day_of_month = berlin_tz.localize(datetime(year, month, 1))
    first_sunday = first_day_of_month + timedelta(days=(6 - first_day_of_month.weekday()) % 7)
    third_sunday = first_sunday + timedelta(days=14)

    # Überprüfen, ob das aktuelle Datum und die aktuelle Uhrzeit nach 15 Uhr am Tag des dritten Sonntags liegen
    if now > third_sunday.replace(hour=15, minute=0, second=0, microsecond=0):
        month = month % 12 + 1
        year = year + (month == 1)
        first_day_of_next_month = berlin_tz.localize(datetime(year, month, 1))
        first_sunday_next_month = first_day_of_next_month + timedelta(days=(6 - first_day_of_next_month.weekday()) % 7)
        third_sunday = first_sunday_next_month + timedelta(days=14)

    return third_sunday.strftime('%d.%m.%Y')

def is_registration_open():
    # Zeitzone für Europe/Berlin definieren
    berlin_tz = pytz.timezone('Europe/Berlin')

    # Aktuelle Zeit in Berliner Zeitzone
    now = datetime.now(berlin_tz)
    next_brunch = berlin_tz.localize(datetime.strptime(next_brunch_date(), '%d.%m.%Y'))
    friday_before_brunch = next_brunch - timedelta(days=2)

    # Stellen Sie sicher, dass friday_before_brunch auf Mitternacht gesetzt ist
    friday_before_brunch = friday_before_brunch.replace(hour=0, minute=0, second=0, microsecond=0)

    return now < friday_before_brunch

def validate_name_or_call(text):
    """
    Überprüft, ob der Text ein gültiges Rufzeichen oder einen Namen darstellt.
    Erlaubt sind Buchstaben, Zahlen, Leerzeichen und bestimmte Sonderzeichen.
    """
    return re.match(r'^[A-Za-z0-9äöüÄÖÜß\- ]+$', text) is not None

def validate_bringalong(text):
    """
    Überprüft, ob das Mitbringsel gültig ist.
    Gültig ist nur ein Wort, Sonderzeichen wie Bindestriche sind erlaubt.
    """
    return re.match(r'^[A-Za-zäöüÄÖÜß\-]+$', text) is not None

# Funktion zur Überprüfung der E-Mail-Adresse
def validate_email(email):
    return re.match(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}$', email) is not None

def read_items_from_file():
    try:
        with open('mitbringsel.txt', 'r') as file:
            return [line.strip() for line in file if line.strip()]
    except FileNotFoundError:
        return []

def add_item_to_file(item):
    formatted_item = item.lower().capitalize()
    with open('mitbringsel.txt', 'a') as file:
        file.write(f"{formatted_item}\n")
    logger.debug(f"Neues Mitbringsel {formatted_item} hinzugefügt.")

def get_available_items():
    all_items = read_items_from_file()
    taken_items = [entry[2] for entry in db_manager.get_brunch_info() if entry[2]]
    return [item for item in all_items if item not in taken_items]

brunch = Flask(__name__)

@brunch.route('/', methods=['GET', 'POST'])
def index():
    current_year = datetime.now().year
    next_brunch_date_str = next_brunch_date()
    error_message = ""
    available_items = get_available_items()
    no_items_available = len(available_items) == 0 and not any(item.lower() not in [entry[2].lower() for entry in db_manager.get_brunch_info()] for item in read_items_from_file())
    total_participants_excluding_coffee_only = db_manager.count_participants_excluding_coffee_only()
    coffee_only_participants = db_manager.count_coffee_only_participants()
    logger.debug(f"Anfrage an die Startseite erhalten: Methode {request.method}")

    registration_open = is_registration_open()

    if request.method == 'POST':
        if registration_open:
            name = request.form.get('name', '').strip()
            email = request.form.get('email', '').strip()
            selected_item = request.form.get('selected_item', '').strip()
            custom_item = request.form.get('custom_item', '').strip()
            for_coffee_only = 'for_coffee_only' in request.form

            if not validate_email(email):
                error_message = "Bitte eine gültige E-Mail-Adresse eingeben."
            elif not validate_name_or_call(name):
                error_message = "Bitte ein gültiges Rufzeichen oder einen vollständigen Namen eingeben."
            elif custom_item and not validate_bringalong(custom_item):
                error_message = "Das Mitbringsel darf nur aus maximal zwei Worten ohne Sonderzeichen bestehen."
            elif db_manager.participant_exists(name):
                return redirect(url_for('confirm_delete', name=name))
            else:
                if for_coffee_only:
                    db_manager.add_brunch_entry(name, email, '', 1)
                    error_message = f"Teilnehmer '{name}' als Kaffeetrinker hinzugefügt."
                else:
                    item_lower = (custom_item if custom_item else selected_item).lower()
                    if item_lower in [item.lower() for _, _, item, _ in db_manager.get_brunch_info()]:
                        error_message = f"Mitbringsel '{custom_item if custom_item else selected_item}' ist bereits vergeben."
                    else:
                        item_to_add = custom_item.lower().capitalize() if custom_item else selected_item
                        if custom_item and item_lower not in [item.lower() for item in read_items_from_file()]:
                            add_item_to_file(custom_item)
                        db_manager.add_brunch_entry(name, email, item_to_add, 0)
                        error_message = f"Teilnehmer '{name}' mit Mitbringsel '{item_to_add}' hinzugefügt."

                total_participants_excluding_coffee_only = db_manager.count_participants_excluding_coffee_only()
                coffee_only_participants = db_manager.count_coffee_only_participants()
                available_items = get_available_items()  # Update available items list
        else:
            error_message = "Die Anmeldung ist derzeit nicht möglich."

    taken_items_info = db_manager.get_brunch_info()
    taken_items = [item for _, _, item, _ in taken_items_info if item]
    taken_items_str = ', '.join(taken_items)

    return render_template_string("""
        <!DOCTYPE html>
        <html lang="de">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>L11 Frühstücksbrunch Anmeldung</title>
            <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
            <style>
                .small-text {
                    font-size: 0.7em;
                    font-weight: normal;
                }
                body {
                    background-color: #2aa6da;
                    color: white;
                }
                input,
                select {
                    color: black;
                }
                input[type="checkbox"] {
                    transform: scale(2);
                    margin: 5px;
                }
                .disabled-field {
                    background-color: #f0f0f0;
                }
            </style>
        </head>
        <body>
            <div class="container mx-auto px-4">
                <h1 class="text-3xl font-bold text-center my-6">L11 Frühstücksbrunch Anmeldung - Sonntag, {{ next_brunch_date_str }} 10 Uhr</h1>
                <h2 class="text-xl font-bold text-center my-6">Teilnehmende Personen (ohne Kaffeetrinker): {{ total_participants_excluding_coffee_only }}, Kaffeetrinker: {{ coffee_only_participants }}</h2>
                <p class="text-red-500">{{ error_message }}</p>
                <form method="post" class="mb-4">
                    <table>
                        <tr>
                            <td><label for="name">Rufzeichen oder vollständiger Name:</label></td>
                            <td><input type="text" name="name" class="border p-2" id="name" {{ 'disabled' if not registration_open }}></td>
                        </tr>
                        <tr>
                            <td><label for="email">E-Mail:</label></td>
                            <td><input type="email" name="email" class="border p-2" id="email" {{ 'disabled' if not registration_open }}></td>
                        </tr>
                        <tr>
                            <td><label for="selected_item">Mitbringsel:</label></td>
                            <td>
                                {% if no_items_available %}
                                    <input type="text" name="selected_item" class="border p-2 disabled-field" id="selected_item" value="Bitte selbst hinzufügen" disabled>
                                {% else %}
                                    <select name="selected_item" class="border p-2" id="selected_item" {{ 'disabled' if not registration_open }}>
                                        {% for item in available_items %}
                                            <option value="{{ item }}">{{ item }}</option>
                                        {% endfor %}
                                    </select>
                                {% endif %}
                            </td>
                            <td class="small-text">
                                <div><b>Von anderen bereits ausgewählte Mitbringsel:</b></div>
                                <div>{{ taken_items_str }}</div>
                            </td>
                        </tr>
                        <tr>
                            <td><label for="custom_item">Oder neues Mitbringsel hinzufügen:</label></td>
                            <td><input type="text" name="custom_item" class="border p-2" id="custom_item" {{ 'disabled' if not registration_open }}></td>
                        </tr>
                        <tr>
                            <td><label for="for_coffee_only">Nur zum Kaffeetrinken:<br>(Mitbringsel wird ignoriert)</label></td>
                            <td><input type="checkbox" name="for_coffee_only" id="for_coffee_only" {{ 'disabled' if not registration_open }}></td>
                        </tr>
                        <tr>
                            <td></td>
                            <td><button type="submit" class="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded" {{ 'disabled' if not registration_open }}>Anmelden / Abmelden</button></td>
                        </tr>
                    </table>
                </form>
            </div>
            <footer class="bg-white text-center text-gray-700 p-4">
                © 2023 - {{ current_year }} Erik Schauer, DO1FFE - <a href="mailto:do1ffe@darc.de" class="text-blue-500">do1ffe@darc.de</a>
            </footer>
        </body>
        </html>
    """, total_participants_excluding_coffee_only=total_participants_excluding_coffee_only, coffee_only_participants=coffee_only_participants, available_items=available_items, taken_items_str=taken_items_str, error_message=error_message, next_brunch_date_str=next_brunch_date_str, current_year=current_year, no_items_available=no_items_available)

@brunch.route('/confirm_delete/<name>', methods=['GET', 'POST'])
def confirm_delete(name):
    if request.method == 'POST':
        db_manager.delete_entry(name)
        logger.debug(f"Eintrag für {name} aus Datenbank gelöscht.")
        dapnet_client.log_message(
            f"Frühstück: Eintrag für {name} aus Datenbank gelöscht.",
            ['DO1FFE', 'DO1EMC'],  # Mehrere Empfänger als Liste
            'all',
            False
        )

        return redirect(url_for('index'))

    return render_template_string("""
        <!DOCTYPE html>
        <html lang="de">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Teilnehmer löschen</title>
            <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
            <style>
                body {
                    background-color: #2aa6da;
                    color: white; /* Setzt die Textfarbe auf Weiß */
                }
            </style>
        </head>
        <body>
            <div class="container mx-auto px-4">
                <h1 class="text-3xl font-bold text-center my-6">Teilnehmer löschen</h1>
                <p>Möchtest du <b> {{ name }} </b> wirklich löschen?</p>
                <form method="POST">
                    <button type="submit" class="bg-red-500 hover:bg-red-700 text-white font-bold py-2 px-4 rounded">Löschen</button>
                    <a href="{{ url_for('index') }}" class="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded">Abbrechen</a>
                </form>
            </div>
        </body>
        </html>
    """, name=name)

@brunch.route('/admin/delete/<name>', methods=['POST'])
@requires_auth
def delete_entry(name):
    db_manager.delete_entry(name)
    logger.debug(f"Eintrag für {name} aus der Datenbank gelöscht.")
    dapnet_client.log_message(
        f"Frühstück: Eintrag für {name} aus der Datenbank gelöscht.",
        ['DO1FFE', 'DO1EMC'],  # Mehrere Empfänger als Liste
        'all',
        False
    )
    return redirect(url_for('admin_page'))

@brunch.route('/admin')
@requires_auth
def admin_page():
    auth = request.authorization
    if auth:
        logger.debug(f"***** Admin-Bereich aufgerufen von Benutzer: {auth.username}")
    else:
        logger.debug("***** Admin-Bereich aufgerufen ohne Authentifizierungsinformationen")
        
    brunch_info = db_manager.get_brunch_info()
    email_addresses = [entry[1] for entry in brunch_info if entry[1]]
    mailto_link = f"mailto:do1emc@darc.de?bcc={','.join(email_addresses)}&subject=Frühstücksbrunch {next_brunch_date()}"

    return render_template_string("""
        <!DOCTYPE html>
        <html lang="de">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Admin - Frühstücks-Brunch</title>
            <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
            <style>
                body {
                    background-color: #2aa6da;
                    color: white;
                }
                thead th {
                    color: black;
                }
            </style>
        </head>
        <body>
            <div class="container mx-auto px-4">
                <h1 class="text-3xl font-bold text-center my-6">Admin-Seite: Frühstücks-Brunch</h1>
                <table class="table-auto w-full mb-6">
                    <thead>
                        <tr class="bg-gray-200">
                            <th class="px-4 py-2">Name</th>
                            <th class="px-4 py-2">E-Mail</th>
                            <th class="px-4 py-2">Mitbringsel</th>
                            <th class="px-4 py-2">Nur zum Kaffee</th>
                            <th class="px-4 py-2">Aktionen</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for name, email, item, for_coffee_only in brunch_info %}
                        <tr>
                            <td class="border px-4 py-2">{{ name }}</td>
                            <td class="border px-4 py-2">{{ email }}</td>
                            <td class="border px-4 py-2">{{ item }}</td>
                            <td class="border px-4 py-2">{{ 'Ja' if for_coffee_only else 'Nein' }}</td>
                            <td class="border px-4 py-2">
                                <a href="{{ url_for('edit_entry', name=name) }}" class="bg-green-500 hover:bg-green-700 text-white font-bold py-2 px-4 rounded">Bearbeiten</a>
                                <form action="{{ url_for('delete_entry', name=name) }}" method="post" style="display: inline;">
                                    <button type="submit" class="bg-red-500 hover:bg-red-700 text-white font-bold py-2 px-4 rounded">Löschen</button>
                                </form>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
                <a href="{{ mailto_link }}" class="bg-green-500 hover:bg-green-700 text-white font-bold py-2 px-4 rounded">E-Mail an alle Teilnehmer senden</a>
                &nbsp;&nbsp;
                <a href="{{ url_for('download_pdf') }}" class="bg-green-500 hover:bg-green-700 text-white font-bold py-2 px-4 rounded">Tabelle als PDF herunterladen</a>
                &nbsp;&nbsp;
                <a href="{{ url_for('admin_mitbringsel') }}" class="bg-green-500 hover:bg-green-700 text-white font-bold py-2 px-4 rounded">Mitbringsel editieren</a>
                <br><br><br><br>
                <img src="/statistik/teilnahmen_statistik.png" alt="Statistik">
                <br><br>
            </div>
        </body>
        </html>
    """, brunch_info=brunch_info, current_year=datetime.now().year, mailto_link=mailto_link)

# Route zum Anzeigen und Bearbeiten der Mitbringsel-Liste
@brunch.route('/admin/mitbringsel', methods=['GET', 'POST'])
@requires_auth
def admin_mitbringsel():
    if request.method == 'POST':
        # Aktualisierte Liste der Mitbringsel aus dem Formular erhalten
        updated_items = request.form.get('mitbringsel_list').split('\n')
        updated_items = [item.strip() for item in updated_items if item.strip()]
        
        # Aktualisierte Liste in die Datei schreiben
        with open('mitbringsel.txt', 'w') as file:
            for item in updated_items:
                file.write(f"{item}\n")

        return redirect(url_for('admin_mitbringsel'))

    # Vorhandene Mitbringsel aus der Datei lesen
    items = read_items_from_file()
    items_str = '\n'.join(items)

    return render_template_string("""
        <!DOCTYPE html>
        <html lang="de">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Admin - Mitbringsel bearbeiten</title>
            <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
            <style>
                body {
                    background-color: #2aa6da;
                    color: white;
                }
                textarea {
                    width: 100%;
                    height: 200px;
                    color: black;
                }
            </style>
        </head>
        <body>
            <div class="container mx-auto px-4">
                <h1 class="text-3xl font-bold text-center my-6">Mitbringsel bearbeiten</h1>
                <form method="post">
                    <textarea name="mitbringsel_list">{{ items_str }}</textarea><br>
                    <button type="submit" class="bg-green-500 hover:bg-green-700 text-white font-bold py-2 px-4 rounded">Speichern</button>
                    <a href="{{ url_for('admin_page') }}" class="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded">Zurück zum Admin-Bereich</a>
                </form>
            </div>
        </body>
        </html>
    """, items_str=items_str)

@brunch.route('/admin/edit/<name>', methods=['GET', 'POST'])
@requires_auth
def edit_entry(name):
    entry = db_manager.get_entry(name)

    if request.method == 'POST':
        # Daten aus dem Formular auslesen
        updated_name = request.form['name']
        updated_email = request.form['email']
        updated_item = request.form['item']
        updated_for_coffee_only = 'for_coffee_only' in request.form

        # Update in der Datenbank durchführen
        db_manager.update_entry(name, updated_name, updated_email, updated_item, updated_for_coffee_only)
        
        return redirect(url_for('admin_page'))

    return render_template_string("""
        <!DOCTYPE html>
        <html lang="de">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Eintrag Bearbeiten</title>
            <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
        </head>
        <body>
            <div class="container mx-auto px-4">
                <h1 class="text-3xl font-bold text-center my-6">Eintrag Bearbeiten</h1>
                <style>
                    .form-input {
                        border: 1px solid #ccc;
                        border-radius: 4px;
                        padding: 8px 12px;
                        margin: 8px 0;
                    }
                    .form-label {
                        font-weight: bold;
                        margin-top: 12px;
                    }
                    .form-submit {
                        background-color: #4CAF50;
                        color: white;
                        padding: 12px 20px;
                        border: none;
                        border-radius: 4px;
                        cursor: pointer;
                    }
                    .form-submit:hover {
                        background-color: #45a049;
                    }
                </style>

                <script>
                    function handleCoffeeOnlyChange() {
                        var checkBox = document.getElementById('for_coffee_only');
                        var itemInput = document.getElementById('item');
                        if (checkBox.checked) {
                            itemInput.value = '';
                        }
                    }
                </script>
                
                <form method="post">
                    <label for="name" class="form-label">Name:</label><br>
                    <input type="text" id="name" name="name" value="{{ entry[0] }}" class="form-input"><br>
                
                    <label for="email" class="form-label">E-Mail:</label><br>
                    <input type="email" id="email" name="email" value="{{ entry[1] }}" class="form-input"><br>
                
                    <label for="item" class="form-label">Mitbringsel:</label><br>
                    <input type="text" id="item" name="item" value="{{ entry[2] }}" class="form-input"><br>
                
                    <input type="checkbox" id="for_coffee_only" name="for_coffee_only" {{ 'checked' if entry[3] else '' }} onchange="handleCoffeeOnlyChange()">
                    <label for="for_coffee_only" class="form-label">Nur zum Kaffeetrinken</label><br><br>

                    <button type="submit" class="bg-green-500 hover:bg-green-700 text-white font-bold py-2 px-4 rounded">Änderungen Speichern</button>
                    <a href="{{ url_for('admin_page') }}" class="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded">Abbruch und zurück zum Admin-Bereich</a>
                    </form>
            </div>
        </body>
        </html>
    """, entry=entry)

# Route für das Ausliefern von Statistiken hinzufügen
@brunch.route('/statistik/<filename>')
def statistik(filename):
    return send_from_directory('statistik', filename)

@brunch.route('/admin/download_pdf')
@requires_auth
def download_pdf():
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)

    # Überschriftstil definieren
    header_style = ParagraphStyle(
        'header_style',
        fontSize=14,
        alignment=1,  # zentriert
        spaceAfter=20,  # Abstand nach dem Paragraphen
    )

    # Daten für die Tabelle
    brunch_info = db_manager.get_brunch_info()
    data = [["Name", "E-Mail", "Mitbringsel", "Nur zum Kaffee"]]
    data += [[entry[0], entry[1], entry[2], 'Ja' if entry[3] else 'Nein'] for entry in brunch_info]

    # Tabelle erstellen
    table = Table(data)

    # Stil der Tabelle
    style = TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.grey),
        ('TEXTCOLOR',(0,0),(-1,0),colors.whitesmoke),
        ('ALIGN',(0,0),(-1,-1),'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,0), 12),
        ('BACKGROUND',(0,1),(-1,-1),colors.beige),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
    ])
    table.setStyle(style)

    # Überschrift hinzufügen
    next_brunch_date_str = next_brunch_date()
    elements = [Paragraph(f"L11 Frühstücksbrunch am {next_brunch_date_str}", header_style), table]

    doc.build(elements)

    buffer.seek(0)
    return send_file(buffer, as_attachment=True, attachment_filename='brunch_liste.pdf', mimetype='application/pdf')

def save_participant_log():
    brunch_info = db_manager.get_brunch_info()

    # Zeitzone für Europe/Berlin definieren
    berlin_tz = pytz.timezone('Europe/Berlin')

    # Aktuelle Zeit in Berliner Zeitzone
    current_date = datetime.now(berlin_tz).strftime('%d.%m.%Y')

    with open('teilnehmer.log', 'a') as log_file:
        for name, _, item, _ in brunch_info:
            log_file.write(f"{current_date} - {name} - {item}\n")
    logger.debug("Teilnehmerlog wurde gespeichert.")

def should_reset_database():
    berlin_tz = pytz.timezone('Europe/Berlin')
    now = datetime.now(berlin_tz)
    next_brunch_str = next_brunch_date()
    next_brunch = berlin_tz.localize(datetime.strptime(next_brunch_str, '%d.%m.%Y'))
    reset_time = next_brunch.replace(hour=15, minute=30, second=0, microsecond=0)

    logger.debug(f"Aktuelle Zeit: {now}, Nächstes Brunch: {next_brunch}, Reset-Zeit: {reset_time}")
    return now >= reset_time

def reset_database_at_event_time():
    while True:
        if should_reset_database():
            # Speichern der Teilnehmerinformationen in eine Log-Datei
            save_participant_log()

            # Zurücksetzen der Datenbank
            db_manager.reset_db()
            logger.debug("Datenbank wurde resettet.")

            # Warte bis zum nächsten Tag, um erneut zu prüfen
            time.sleep(24 * 60 * 60)
        else:
            # Kurze Pause, um kontinuierliche Überprüfung zu vermeiden
            time.sleep(60)

reset_thread = threading.Thread(target=reset_database_at_event_time)
reset_thread.start()

if __name__ == '__main__':
    brunch.run(host='0.0.0.0', port=8082, debug=True, use_reloader=False)

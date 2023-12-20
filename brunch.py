# Programm: FrühstücksBrunchManager
# Autor: Erik Schauer, DO1FFE, do1ffe@darc.de
# Erstelldatum: 2023-12-16

from flask import Flask, request, render_template_string, Response, redirect, url_for
from functools import wraps
from datetime import datetime, timedelta
import logging
from logging.handlers import RotatingFileHandler
import sqlite3
import re
import threading
import time

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
        c.execute('''CREATE TABLE IF NOT EXISTS brunch_participants 
                     (name TEXT, item TEXT, for_coffee_only INTEGER)''')
        conn.commit()

    def add_brunch_entry(self, name, item, for_coffee_only):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute('INSERT INTO brunch_participants (name, item, for_coffee_only) VALUES (?, ?, ?)', 
                  (name, item, for_coffee_only))
        conn.commit()

    def get_brunch_info(self):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute('SELECT name, item, for_coffee_only FROM brunch_participants')
        return c.fetchall()

    def reset_db(self):
        logger.info("Resetting the database")
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

db_manager = DatabaseManager()

def next_brunch_date():
    now = datetime.now()
    month = now.month
    year = now.year
    first_day_of_month = datetime(year, month, 1)
    first_sunday = first_day_of_month + timedelta(days=(6 - first_day_of_month.weekday()) % 7)
    third_sunday = first_sunday + timedelta(days=14)
    if now > third_sunday:
        month = month % 12 + 1
        year = year + (month == 1)
        first_day_of_next_month = datetime(year, month, 1)
        first_sunday_next_month = first_day_of_next_month + timedelta(days=(6 - first_day_of_next_month.weekday()) % 7)
        third_sunday = first_sunday_next_month + timedelta(days=14)
    return third_sunday.strftime('%d.%m.%Y')

def validate_input(text):
    if text is None or text.strip() == "":
        return False
    return re.match(r'^[A-Za-z0-9äöüÄÖÜß\s\-]+$', text) is not None

def read_items_from_file():
    try:
        with open('mitbringsel.txt', 'r') as file:
            return [line.strip() for line in file if line.strip()]
    except FileNotFoundError:
        return []

def add_item_to_file(item):
    with open('mitbringsel.txt', 'a') as file:
        file.write(f"{item}\n")

def get_available_items():
    all_items = read_items_from_file()
    taken_items = [entry[1] for entry in db_manager.get_brunch_info() if entry[1]]
    return [item for item in all_items if item not in taken_items]

brunch = Flask(__name__)

@brunch.route('/', methods=['GET', 'POST'])
def index():
    current_year = datetime.now().year
    next_brunch_date_str = next_brunch_date()
    error_message = ""
    available_items = get_available_items()
    total_participants_excluding_coffee_only = db_manager.count_participants_excluding_coffee_only()
    coffee_only_participants = db_manager.count_coffee_only_participants()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        selected_item = request.form.get('selected_item', '').strip()
        custom_item = request.form.get('custom_item', '').strip()
        for_coffee_only = 'for_coffee_only' in request.form

        if not validate_input(name):
            error_message = "Bitte einen gültigen Namen eingeben."
        elif db_manager.participant_exists(name):
            return redirect(url_for('confirm_delete', name=name))
        else:
            if for_coffee_only:
                item = ''
                db_manager.add_brunch_entry(name, item, for_coffee_only)
                error_message = f"Teilnehmer '{name}' als Kaffeetrinker hinzugefügt."
            else:
                item = custom_item if custom_item else selected_item
                if custom_item and custom_item not in available_items:
                    add_item_to_file(custom_item)
                db_manager.add_brunch_entry(name, item, for_coffee_only)
                error_message = f"Teilnehmer '{name}' mit Mitbringsel '{item}' hinzugefügt."

            total_participants_excluding_coffee_only = db_manager.count_participants_excluding_coffee_only()
            coffee_only_participants = db_manager.count_coffee_only_participants()
            available_items = get_available_items()  # Update available items list

    taken_items_info = db_manager.get_brunch_info()
    taken_items = [item for _, item, _ in taken_items_info if item]
    taken_items_str = ', '.join(taken_items)

    return render_template_string("""
        <!DOCTYPE html>
        <html lang="de">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Frühstücks-Brunch Anmeldung - {{ next_brunch_date_str }}</title>
            <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
        </head>
        <body class="bg-gray-100">
            <div class="container mx-auto px-4">
                <h1 class="text-3xl font-bold text-center my-6">Frühstücks-Brunch Anmeldung - {{ next_brunch_date_str }}</h1>
                <h2 class="text-xl font-bold text-center my-6">Teilnehmende Personen (ohne Kaffeetrinker): {{ total_participants_excluding_coffee_only }}, Kaffeetrinker: {{ coffee_only_participants }}</h2>
                <p class="text-red-500">{{ error_message }}</p>
                <form method="post" class="mb-4">
                    <table>
                        <tr>
                            <td><label for="name">Rufzeichen oder vollständiger Name:</label></td>
                            <td><input type="text" name="name" class="border p-2" id="name"></td>
                        </tr>
                        <tr>
                            <td><label for="selected_item">Mitbringsel:</label></td>
                            <td>
                                <select name="selected_item" class="border p-2" id="selected_item">
                                    {% for item in available_items %}
                                        <option value="{{ item }}">{{ item }}</option>
                                    {% endfor %}
                                </select>
                            </td>
                        </tr>
                        <tr>
                            <td><label for="custom_item">Oder neues Mitbringsel hinzufügen:</label></td>
                            <td><input type="text" name="custom_item" class="border p-2" id="custom_item"></td>
                        </tr>
                        <tr>
                            <td><label for="for_coffee_only">Nur zum Kaffee:<br>(Mitbringsel wird ignoriert)</label></td>
                            <td><input type="checkbox" name="for_coffee_only" id="for_coffee_only"></td>
                        </tr>
                        <tr>
                        </tr>
                        <tr>
                            <td></td>
                            <td><button type="submit" class="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded">Anmelden / Abmelden</button></td>
                        </tr>
                    </table>
                </form>
                <h2>Bereits gewählte Mitbringsel:</h2>
                <p>{{ taken_items_str }}</p>
            </div>
            <footer class="bg-white text-center text-gray-700 p-4">
                © {{ current_year }} Erik Schauer, DO1FFE - <a href="mailto:do1ffe@darc.de" class="text-blue-500">do1ffe@darc.de</a>
            </footer>
        </body>
        </html>
    """, total_participants_excluding_coffee_only=total_participants_excluding_coffee_only, coffee_only_participants=coffee_only_participants, available_items=available_items, taken_items_str=taken_items_str, error_message=error_message, next_brunch_date_str=next_brunch_date_str, current_year=current_year)

@brunch.route('/confirm_delete/<name>', methods=['GET', 'POST'])
def confirm_delete(name):
    if request.method == 'POST':
        db_manager.delete_entry(name)
        return redirect(url_for('index'))

    return render_template_string("""
        <!DOCTYPE html>
        <html lang="de">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Teilnehmer löschen</title>
            <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
        </head>
        <body class="bg-gray-100">
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

@brunch.route('/admin')
@requires_auth
def admin_page():
    brunch_info = db_manager.get_brunch_info()
    return render_template_string("""
        <!DOCTYPE html>
        <html lang="de">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Admin - Frühstücks-Brunch</title>
            <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
        </head>
        <body class="bg-gray-100">
            <div class="container mx-auto px-4">
                <h1 class="text-3xl font-bold text-center my-6">Admin-Seite: Frühstücks-Brunch</h1>
                <table class="table-auto w-full mb-6">
                    <thead>
                        <tr class="bg-gray-200">
                            <th class="px-4 py-2">Name</th>
                            <th class="px-4 py-2">Mitbringsel</th>
                            <th class="px-4 py-2">Nur zum Kaffee</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for name, item, for_coffee_only in brunch_info %}
                        <tr>
                            <td class="border px-4 py-2">{{ name }}</td>
                            <td class="border px-4 py-2">{{ item }}</td>
                            <td class="border px-4 py-2">{{ 'Ja' if for_coffee_only else 'Nein' }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </body>
        </html>
    """, brunch_info=brunch_info, current_year=datetime.now().year)

def reset_database_at_event_time():
    while True:
        now = datetime.now()
        next_brunch = datetime.strptime(next_brunch_date(), '%d.%m.%Y')
        next_reset_time = next_brunch.replace(hour=15, minute=0, second=0, microsecond=0)

        if now >= next_reset_time:
            db_manager.reset_db()
            # Warte bis zum nächsten Tag, um erneut zu prüfen
            time.sleep(24 * 60 * 60)
        else:
            # Warte bis zum Reset-Zeitpunkt
            time.sleep((next_reset_time - now).total_seconds())

reset_thread = threading.Thread(target=reset_database_at_event_time)
reset_thread.start()

if __name__ == '__main__':
    brunch.run(host='0.0.0.0', port=8082, use_reloader=False)

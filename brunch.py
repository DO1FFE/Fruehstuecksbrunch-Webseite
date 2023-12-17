# Programm: FrühstücksBrunchManager
# Autor: Erik Schauer, DO1FFE, do1ffe@darc.de
# Erstelldatum: 2023-12-16

from flask import Flask, request, render_template_string, Response, redirect, url_for
from datetime import datetime, timedelta
import logging
from logging.handlers import RotatingFileHandler
import sqlite3
import re
import os
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
        c.execute('CREATE TABLE IF NOT EXISTS brunch_participants (name TEXT, item TEXT, for_coffee_only INTEGER)')
        conn.commit()

    def add_brunch_entry(self, name, item, for_coffee_only):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute('INSERT INTO brunch_participants (name, item, for_coffee_only) VALUES (?, ?, ?)', (name, item, for_coffee_only))
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

brunch = Flask(__name__)

@brunch.route('/', methods=['GET', 'POST'])
def index():
    current_year = datetime.now().year
    error_message = ""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        item = request.form.get('item', '').strip()
        for_coffee_only = 'for_coffee_only' in request.form

        if not validate_input(name):
            error_message = "Bitte einen gültigen Namen eingeben."
        elif for_coffee_only:
            db_manager.add_brunch_entry(name, None, 1)
        elif item:
            db_manager.add_brunch_entry(name, item, 0)
        else:
            error_message = "Bitte ein Mitbringsel auswählen oder nur zum Kaffee anmelden."

    participant_count = len(db_manager.get_brunch_info())

    return render_template_string("""
        <!DOCTYPE html>
        <html lang="de">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Frühstücks-Brunch Anmeldung</title>
            <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
        </head>
        <body class="bg-gray-100">
            <div class="container mx-auto px-4">
                <h1 class="text-3xl font-bold text-center my-6">Frühstücks-Brunch Anmeldung</h1>
                <p class="text-red-500">{{ error_message }}</p>
                <form method="post" class="mb-4">
                    <label class="block mb-2">Name: <input type="text" name="name" class="border p-2"></label>
                    <label class="block mb-2">Mitbringsel: <input type="text" name="item" class="border p-2"></label>
                    <label class="block mb-4">Nur zum Kaffee: <input type="checkbox" name="for_coffee_only"></label>
                    <button type="submit" class="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded">Anmelden</button>
                </form>
                <p>Anzahl der Teilnehmer: {{ participant_count }}</p>
            </div>
            <footer class="bg-white text-center text-gray-700 p-4">
                © {{ current_year }} Erik Schauer, DO1FFE - <a href="mailto:do1ffe@darc.de" class="text-blue-500">do1ffe@darc.de</a>
            </footer>
        </body>
        </html>
    """, participant_count=participant_count, error_message=error_message, current_year=current_year)

def check_auth(username, password):
    return username in credentials and credentials[username] == password

def authenticate():
    return Response('Zugriff verweigert', 401, {'WWW-Authenticate': 'Basic realm="Login Required"'})

def requires_auth(f):
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

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
                <ul>
                    {% for name, item, for_coffee_only in brunch_info %}
                        <li>{{ name }} - {{ 'Nur Kaffee' if for_coffee_only else item }}</li>
                    {% endfor %}
                </ul>
            </div>
            <footer class="bg-white text-center text-gray-700 p-4">
                © {{ current_year }} Erik Schauer, DO1FFE - <a href="mailto:do1ffe@darc.de" class="text-blue-500">do1ffe@darc.de</a>
            </footer>
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
            time.sleep(24 * 60 * 60)  # Warte einen Tag bis zur nächsten Überprüfung
        else:
            time.sleep((next_reset_time - now).total_seconds())

reset_thread = threading.Thread(target=reset_database_at_event_time)
reset_thread.start()

if __name__ == '__main__':
    brunch.run(host='0.0.0.0', port=8082, use_reloader=False)

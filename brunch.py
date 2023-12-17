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
            <link href="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css" rel="stylesheet">
        </head>
        <body>
            <div class="container">
                <h1 class="my-4">Frühstücks-Brunch Anmeldung</h1>
                <p>Nächster Termin: {{ next_brunch }}</p>
                <p>Anzahl der angemeldeten Teilnehmer: {{ participant_count }}</p>
                <p style="color: red;">{{ error_message }}</p>
                <form method="post">
                    Name: <input type="text" name="name"><br>
                    Mitbringsel: <input type="text" name="item"><br>
                    Nur zum Kaffee: <input type="checkbox" name="for_coffee_only"><br>
                    <input type="submit" value="Anmelden">
                </form>
            </div>
        </body>
        </html>
    """, next_brunch=next_brunch_date(), participant_count=participant_count, error_message=error_message)

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
            <link href="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css" rel="stylesheet">
        </head>
        <body>
            <div class="container">
                <h1 class="my-4">Admin-Seite: Frühstücks-Brunch</h1>
                <h2>Teilnehmerliste</h2>
                <ul>
                {% for name, item, for_coffee_only in brunch_info %}
                    <li>{{ name }} - {{ 'Nur Kaffee' if for_coffee_only else item }}</li>
                {% endfor %}
                </ul>
            </div>
        </body>
        </html>
    """, brunch_info=brunch_info)

if __name__ == '__main__':
    brunch.run(host='0.0.0.0', port=8082, use_reloader=False)

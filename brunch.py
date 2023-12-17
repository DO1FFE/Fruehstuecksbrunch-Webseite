# Programm: FrühstücksBrunchManager
# Autor: Erik Schauer, DO1FFE, do1ffe@darc.de
# Erstelldatum: 2023-12-16

from flask import Flask, request, render_template_string, Response, redirect, url_for
from datetime import datetime, timedelta
import calendar
import logging
from logging.handlers import RotatingFileHandler
import sqlite3
import atexit
import threading
import time
import pytz
import re
import os

# Admin-Anmeldedaten einlesen aus .pwd Datei
def load_credentials():
    with open('.pwd', 'r') as file:
        lines = file.readlines()
        credentials = {}
        for line in lines:
            key, value = line.strip().split('=')
            credentials[key] = value
        return credentials

credentials = load_credentials()
ADMIN_USERNAME = credentials['ADMIN_USERNAME']
ADMIN_PASSWORD = credentials['ADMIN_PASSWORD']

# Logger konfigurieren
def setup_logger():
    logger = logging.getLogger('BrunchLogger')
    logger.setLevel(logging.INFO)

    handler = RotatingFileHandler('brunch.log', maxBytes=10000, backupCount=5)
    handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)
    return logger

logger = setup_logger()

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
        conn = self.get_connection()
        c = conn.cursor()
        c.execute('DELETE FROM brunch_participants')
        conn.commit()

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

def calculate_bread_count():
    participants = db_manager.get_brunch_info()
    return sum(1 for _, _, for_coffee_only in participants if not for_coffee_only) * 3

def validate_input(text):
    if text is None or text.strip() == "":
        return True
    if not re.match(r'^[A-Za-z0-9äöüÄÖÜß\s\-]+$', text):
        return False
    return True

brunch = Flask(__name__)

@brunch.route('/', methods=['GET', 'POST'])
def index():
    error_message = ""
    if request.method == 'POST':
        name = request.form['name'].upper()
        item = request.form['item']
        for_coffee_only = 'for_coffee_only' in request.form

        if not validate_input(name):
            error_message = "Ungültige Eingabe. Bitte nur Buchstaben, Zahlen und Bindestriche verwenden."
        else:
            db_manager.add_brunch_entry(name, item if not for_coffee_only else '', for_coffee_only)

    brunch_info = db_manager.get_brunch_info()
    bread_count = calculate_bread_count()
    next_brunch = next_brunch_date()
    participant_count = len(brunch_info)

    return render_template_string("""
        <html>
        <head>
            <title>Frühstücks-Brunch Anmeldung</title>
        </head>
        <body>
            <h1>Frühstücks-Brunch Anmeldung</h1>
            <p>Nächster Termin: {{ next_brunch }}</p>
            <p>Fehlermeldung: {{ error_message }}</p>
            <form method="post">
                Name: <input type="text" name="name"><br>
                Mitbringsel: 
                <select name="item">
                    <option value="Brötchen">Brötchen</option>
                    <option value="Margarine">Margarine</option>
                    <option value="Wurst">Wurst</option>
                    <option value="Käse">Käse</option>
                    <option value="">Nichts, nur Kaffee</option>
                </select><br>
                Nur zum Kaffee: <input type="checkbox" name="for_coffee_only"><br>
                <input type="submit" value="Anmelden">
            </form>
            <h2>Teilnehmerliste</h2>
            <ul>
            {% for name, item, for_coffee_only in brunch_info %}
                <li>{{ name }} - {{ item if not for_coffee_only else 'Nur Kaffee' }}</li>
            {% endfor %}
            </ul>
            <p>Benötigte Anzahl Brötchen: {{ bread_count }}</p>
        </body>
        </html>
    """, brunch_info=brunch_info, bread_count=bread_count, next_brunch=next_brunch, error_message=error_message, participant_count=participant_count)

if __name__ == '__main__':
    db_manager = DatabaseManager()
    brunch.run(host='0.0.0.0', port=8082, use_reloader=False)

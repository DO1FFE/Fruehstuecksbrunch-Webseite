# Programm: FrühstücksBrunchManager
# Autor: Erik Schauer, DO1FFE, do1ffe@darc.de
# Erstelldatum: 2023-12-16

from flask import Flask, request, render_template_string, Response, redirect, url_for, send_from_directory, send_file, jsonify
from functools import wraps
from datetime import datetime, timedelta
import logging
from logging.handlers import RotatingFileHandler
import os
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
from markupsafe import Markup
from urllib.parse import quote_plus


ERSTELLUNGSJAHR = 2023
COPYRIGHT_EMAIL = 'do1ffe@darc.de'
COPYRIGHT_INHABER = f'Erik Schauer, {COPYRIGHT_EMAIL}'
VERANSTALTUNGSORT_NAME = 'Haus der Begegnung'
VERANSTALTUNGSORT_STRASSE = 'I.Weberstr. 28'
VERANSTALTUNGSORT_ORT = '45127 Essen'
VERANSTALTUNGSORT_NAVIGATIONSZIEL = 'Deutscher Amateur-Radio-Club (DARC) e.V. Ortsverband Essen-Mitte L11'
VERANSTALTUNGSORT_ROUTE_URL = (
    f'https://www.google.com/maps/search/?api=1&query={quote_plus(VERANSTALTUNGSORT_NAVIGATIONSZIEL)}'
)


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
        if not self.callsign or not self.password:
            logger.info("DAPNET-Nachricht übersprungen, weil Zugangsdaten fehlen.")
            return None

        data = {
            "text": message,
            "callSignNames": [destination_callsign] if isinstance(destination_callsign, str) else destination_callsign,
            "transmitterGroupNames": [tx_group] if isinstance(tx_group, str) else tx_group,
            "emergency": emergency
        }
        try:
            response = requests.post(
                self.url,
                headers=self.headers,
                auth=(self.callsign, self.password),
                json=data,
                timeout=5
            )
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            logger.warning("DAPNET-Nachricht konnte nicht gesendet werden: %s", exc)
            return None

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
    if logger.handlers:
        return logger
    handler = RotatingFileHandler('brunch.log', maxBytes=10000, backupCount=5)
    handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)
    return logger

logger = setup_logger()

def load_credentials():
    credentials = {}
    try:
        with open('.pwd', 'r', encoding='utf-8') as file:
            for line in file:
                line = line.strip()
                if not line or line.startswith('#') or ':' not in line:
                    continue
                username, password = line.split(':', 1)
                credentials[username.strip()] = password.strip()
    except FileNotFoundError:
        logger.warning(".pwd-Datei nicht gefunden. Admin-Login und DAPNET sind deaktiviert.")
    return credentials

credentials = load_credentials()
dapnet_client = DAPNET(credentials.get('dapnet_username', ''), credentials.get('dapnet_password', ''))

# Überprüfen der Anmeldedaten
def check_auth(username, password):
    return username in credentials and credentials[username] == password

# Aufforderung zur Authentifizierung
def authenticate():
    return Response(
    'Zugriff verweigert. Bitte authentifizieren.', 401,
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
        self.lock = threading.RLock()
        self.init_db()

    def get_connection(self):
        with self.lock:
            if not self.conn:
                self.conn = sqlite3.connect(self.db_name, check_same_thread=False)
            return self.conn

    def close_connection(self):
        with self.lock:
            if self.conn:
                self.conn.close()
                self.conn = None

    def init_db(self):
        with self.lock:
            conn = self.get_connection()
            c = conn.cursor()
            # Tabelle fuer Teilnehmer
            c.execute('''CREATE TABLE IF NOT EXISTS brunch_participants
                         (name TEXT, email TEXT, item TEXT, for_coffee_only INTEGER)''')
            # Neue Tabelle fuer Konfiguration
            c.execute('''CREATE TABLE IF NOT EXISTS config
                         (key TEXT PRIMARY KEY, value TEXT)''')
            conn.commit()

    def add_brunch_entry(self, name, email, item, for_coffee_only):
        with self.lock:
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
        with self.lock:
            conn = self.get_connection()
            c = conn.cursor()
            # Anpassung der Abfrage, um die E-Mail-Adresse einzuschließen
            c.execute('SELECT name, email, item, for_coffee_only FROM brunch_participants')
            return c.fetchall()

    def reset_db(self):
        logger.debug("Resetting the database")
        with self.lock:
            conn = self.get_connection()
            c = conn.cursor()
            c.execute('DELETE FROM brunch_participants')
            conn.commit()

    def delete_entry(self, name):
        with self.lock:
            conn = self.get_connection()
            c = conn.cursor()
            c.execute('DELETE FROM brunch_participants WHERE name = ?', (name,))
            conn.commit()

    def participant_exists(self, name):
        with self.lock:
            conn = self.get_connection()
            c = conn.cursor()
            c.execute('SELECT * FROM brunch_participants WHERE name = ?', (name,))
            return c.fetchone() is not None

    def count_participants_excluding_coffee_only(self):
        with self.lock:
            conn = self.get_connection()
            c = conn.cursor()
            c.execute('SELECT COUNT(*) FROM brunch_participants WHERE for_coffee_only = 0')
            return c.fetchone()[0]

    def count_coffee_only_participants(self):
        with self.lock:
            conn = self.get_connection()
            c = conn.cursor()
            c.execute('SELECT COUNT(*) FROM brunch_participants WHERE for_coffee_only = 1')
            return c.fetchone()[0]

    def update_entry(self, old_name, new_name, email, item, for_coffee_only):
        with self.lock:
            conn = self.get_connection()
            c = conn.cursor()
            c.execute('UPDATE brunch_participants SET name = ?, email = ?, item = ?, for_coffee_only = ? WHERE name = ?',
                      (new_name, email, item, for_coffee_only, old_name))
            conn.commit()

    def get_entry(self, name):
        with self.lock:
            conn = self.get_connection()
            c = conn.cursor()
            c.execute('SELECT * FROM brunch_participants WHERE name = ?', (name,))
            return c.fetchone()

    # -- Konfigurationsfunktionen --
    def get_config(self, key):
        with self.lock:
            conn = self.get_connection()
            c = conn.cursor()
            c.execute('SELECT value FROM config WHERE key = ?', (key,))
            row = c.fetchone()
            return row[0] if row else None

    def set_config(self, key, value):
        with self.lock:
            conn = self.get_connection()
            c = conn.cursor()
            c.execute('REPLACE INTO config (key, value) VALUES (?, ?)', (key, value))
            conn.commit()

    def clear_special_dates(self):
        """Setzt abweichende Termine und Ausfälle zurück."""
        self.set_config('next_date_override', '')
        self.set_config('next_date_cancelled', '0')
        
db_manager = DatabaseManager()

def event_date_for_month(year, month):
    """Bestimmt das Brunch-Datum fuer einen gegebenen Monat."""
    berlin_tz = pytz.timezone('Europe/Berlin')


    first_day = berlin_tz.localize(datetime(year, month, 1))
    first_sunday = first_day + timedelta(days=(6 - first_day.weekday()) % 7)
    third_sunday = first_sunday + timedelta(days=14)

    return third_sunday

def should_show_exception_notice():
    """Bestimmt, ob ein Hinweis auf einen Sondertermin angezeigt werden soll."""
    berlin_tz = pytz.timezone('Europe/Berlin')
    override = db_manager.get_config('next_date_override')
    try:
        if override:
            next_date = berlin_tz.localize(datetime.strptime(override, '%d.%m.%Y'))
            default_date = event_date_for_month(next_date.year, next_date.month)
            return next_date.date() != default_date.date()
    except ValueError:
        pass

    return False

def next_brunch_date():
    """Liefert das Datum des naechsten Brunch-Termins als String."""
    berlin_tz = pytz.timezone('Europe/Berlin')

    override = db_manager.get_config('next_date_override')
    if override:
        try:
            datetime.strptime(override, '%d.%m.%Y')
            return override
        except ValueError:
            pass

    now = datetime.now(berlin_tz)
    month = now.month
    year = now.year

    event_day = event_date_for_month(year, month)

    if now > event_day.replace(hour=15, minute=0, second=0, microsecond=0):
        month = month % 12 + 1
        year = year + (month == 1)
        event_day = event_date_for_month(year, month)

    return event_day.strftime('%d.%m.%Y')

def is_registration_open():
    if is_event_cancelled():
        return False

    berlin_tz = pytz.timezone('Europe/Berlin')
    now = datetime.now(berlin_tz)
    next_brunch = berlin_tz.localize(datetime.strptime(next_brunch_date(), '%d.%m.%Y'))

    friday_before_brunch = next_brunch - timedelta(days=2)
    friday_before_brunch = friday_before_brunch.replace(hour=0, minute=0, second=0, microsecond=0)
    brunch_end_time = next_brunch.replace(hour=15, minute=0, second=0, microsecond=0)

    registration_open = not (friday_before_brunch <= now <= brunch_end_time)

    # Loggen der aktuellen Zeit, des nächsten Brunch-Datums und des Status
    logger.debug(f"Aktuelle Zeit: {now}, Nächstes Brunch-Datum: {next_brunch_date()}, Registrierung offen: {registration_open}")

    return registration_open

def is_event_cancelled():
    return db_manager.get_config('next_date_cancelled') == '1'

def validate_name_or_call(text):
    """
    Überprüft, ob der Text ein gültiges Rufzeichen oder einen Namen darstellt.
    Erlaubt sind Buchstaben, Zahlen, Leerzeichen und bestimmte Sonderzeichen.
    """
    return re.fullmatch(r'[A-Za-z0-9äöüÄÖÜß\- ]+', text.strip()) is not None

def validate_bringalong(text):
    """
    Überprüft, ob das Mitbringsel gültig ist.
    Gültig sind maximal zwei Wörter; Bindestriche innerhalb eines Wortes sind erlaubt.
    """
    wort = r'[A-Za-zäöüÄÖÜß]+(?:-[A-Za-zäöüÄÖÜß]+)*'
    return re.fullmatch(rf'{wort}(?: {wort})?', text.strip()) is not None

# Funktion zur Überprüfung der E-Mail-Adresse
def validate_email(email):
    return re.fullmatch(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', email.strip()) is not None

def read_items_from_file():
    try:
        with open('mitbringsel.txt', 'r', encoding='utf-8') as file:
            return [line.strip() for line in file if line.strip()]
    except FileNotFoundError:
        return []

def add_item_to_file(item):
    formatted_item = item.lower().capitalize()
    with open('mitbringsel.txt', 'a', encoding='utf-8') as file:
        file.write(f"{formatted_item}\n")
    logger.debug(f"Neues Mitbringsel {formatted_item} hinzugefügt.")

def get_available_items():
    all_items = read_items_from_file()
    taken_items = [entry[2] for entry in db_manager.get_brunch_info() if entry[2]]
    return [item for item in all_items if item not in taken_items]

def current_brunch_date():
    """Liefert das Datum des aktuell relevanten Brunch-Termins."""
    override = db_manager.get_config('next_date_override')
    if override:
        try:
            datetime.strptime(override, '%d.%m.%Y')
            return override
        except ValueError:
            logger.error("Ungültiges Format für abweichendes Datum: %s", override)

    berlin_tz = pytz.timezone('Europe/Berlin')
    now = datetime.now(berlin_tz)
    event_day = event_date_for_month(now.year, now.month)

    return event_day.strftime('%d.%m.%Y')

def should_reset_database():
    berlin_tz = pytz.timezone('Europe/Berlin')
    now = datetime.now(berlin_tz)
    current_brunch_str = current_brunch_date()
    current_brunch = berlin_tz.localize(datetime.strptime(current_brunch_str, '%d.%m.%Y'))
    reset_time = current_brunch.replace(hour=15, minute=0, second=0, microsecond=0)
    last_reset_for_date = db_manager.get_config('last_reset_for_date')

    return now > reset_time and last_reset_for_date != current_brunch_str

def reset_database_if_needed():
    if should_reset_database():
        current_brunch_str = current_brunch_date()
        save_participant_log()
        db_manager.reset_db()
        db_manager.set_config('last_reset_for_date', current_brunch_str)
        db_manager.clear_special_dates()
        
def schedule_database_reset():
    while True:
        reset_database_if_needed()
        # Warte 1 Stunde bevor die nächste Überprüfung durchgeführt wird, um Ressourcen zu sparen.
        time.sleep(3600)

brunch = Flask(__name__)


SEITEN_STIL = """
    :root {
        --farbe-text: #273d5e;
        --farbe-muted: #595e65;
        --farbe-linie: #d6dde5;
        --farbe-flaeche: #ffffff;
        --farbe-hintergrund: #000000;
        --farbe-primaer: #273d5e;
        --farbe-primaer-dunkel: #0d3444;
        --farbe-darc-blau: #2aa6da;
        --farbe-akzent: #f7a900;
        --farbe-warnung: #d42020;
        --farbe-erfolg: #53a062;
        --schatten: 0 18px 50px rgba(0, 0, 0, 0.28);
    }

    * {
        box-sizing: border-box;
    }

    body.app-shell {
        min-height: 100vh;
        margin: 0;
        background:
            linear-gradient(180deg, #0d3444 0, #000000 260px),
            #000000;
        color: var(--farbe-text);
        font-family: Arial, Helvetica, sans-serif;
    }

    a {
        color: inherit;
    }

    .seitenrahmen {
        width: min(1120px, calc(100% - 32px));
        margin: 0 auto;
        padding: 32px 0 48px;
    }

    .kopfbereich,
    .aktionskarte,
    .tabellenkarte {
        background: rgba(255, 255, 255, 0.98);
        border: 1px solid rgba(42, 166, 218, 0.30);
        border-radius: 8px;
        box-shadow: var(--schatten);
    }

    .kopfbereich {
        position: relative;
        overflow: hidden;
        padding: 34px;
        background:
            linear-gradient(135deg, rgba(39, 61, 94, 0.98), rgba(13, 52, 68, 0.98)),
            #273d5e;
        color: #ffffff;
    }

    .kopfbereich::after {
        position: absolute;
        right: 0;
        bottom: 0;
        left: 0;
        height: 6px;
        background: linear-gradient(90deg, var(--farbe-darc-blau), var(--farbe-akzent));
        content: "";
    }

    .bereichstitel {
        margin: 0 0 10px;
        color: var(--farbe-darc-blau);
        font-size: 0.88rem;
        font-weight: 700;
        letter-spacing: 0;
        text-transform: uppercase;
    }

    h1,
    h2,
    h3,
    p {
        margin-top: 0;
    }

    .kopfbereich h1 {
        max-width: 820px;
        margin-bottom: 12px;
        color: #ffffff;
        font-size: 2.3rem;
        line-height: 1.08;
        letter-spacing: 0;
    }

    .terminzeile {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 8px 14px;
        width: fit-content;
        margin: 0;
        padding: 10px 14px;
        border: 1px solid var(--farbe-akzent);
        border-radius: 8px;
        background: var(--farbe-akzent);
        color: #000000;
        font-weight: 700;
    }

    .terminzeile span {
        display: inline-flex;
        align-items: center;
    }

    .terminzeile span + span::before {
        margin-right: 14px;
        color: rgba(0, 0, 0, 0.42);
        content: "|";
    }

    .ortskarte {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 18px;
        align-items: center;
        max-width: 680px;
        margin-top: 14px;
        padding: 16px;
        border: 1px solid rgba(42, 166, 218, 0.55);
        border-radius: 8px;
        background: rgba(255, 255, 255, 0.10);
    }

    .ortskarte p {
        margin: 0;
        color: #ffffff;
    }

    .ortskarte strong {
        display: block;
        margin-bottom: 4px;
        color: #ffffff;
        font-size: 1.05rem;
    }

    .ortskarte a {
        color: #000000;
        white-space: nowrap;
    }

    .kennzahlen {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 16px;
        margin: 22px 0;
    }

    .kennzahl {
        padding: 20px;
    }

    .kennzahl span {
        display: block;
        color: var(--farbe-muted);
        font-size: 0.95rem;
    }

    .kennzahl strong {
        display: block;
        margin-top: 8px;
        color: var(--farbe-primaer);
        font-size: 2.4rem;
        line-height: 1;
    }

    .formularbereich {
        display: grid;
        grid-template-columns: minmax(0, 1fr) 340px;
        gap: 20px;
        align-items: start;
    }

    .aktionskarte,
    .tabellenkarte {
        padding: 24px;
    }

    .aktionskarte h2 {
        margin-bottom: 16px;
        font-size: 1.35rem;
        line-height: 1.2;
    }

    .formularraster {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 18px;
    }

    .formulargruppe {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .ganze-breite {
        grid-column: 1 / -1;
    }

    label {
        color: var(--farbe-primaer);
        font-weight: 700;
    }

    .eingabe,
    .auswahl,
    textarea {
        width: 100%;
        min-height: 48px;
        border: 1px solid #c8d3dc;
        border-radius: 8px;
        background: #ffffff;
        color: #101828;
        padding: 12px 14px;
        font: inherit;
    }

    textarea {
        min-height: 220px;
        resize: vertical;
    }

    .eingabe:focus,
    .auswahl:focus,
    textarea:focus {
        border-color: var(--farbe-darc-blau);
        box-shadow: 0 0 0 3px rgba(42, 166, 218, 0.24);
        outline: none;
    }

    .eingabe:disabled,
    .auswahl:disabled,
    .schaltflaeche:disabled {
        cursor: not-allowed;
        opacity: 0.62;
    }

    .checkbox-zeile {
        display: flex;
        align-items: flex-start;
        gap: 12px;
        padding: 14px;
        border: 1px solid #d6dde5;
        border-radius: 8px;
        background: #eef3f6;
    }

    .checkbox-zeile input[type="checkbox"] {
        width: 22px;
        height: 22px;
        margin-top: 1px;
        accent-color: var(--farbe-darc-blau);
    }

    .hilfetext,
    .kleiner-text {
        color: var(--farbe-muted);
        font-size: 0.95rem;
        line-height: 1.5;
    }

    .mitbringsel-liste {
        padding: 14px;
        border: 1px solid #d6dde5;
        border-radius: 8px;
        background: #eef3f6;
        color: var(--farbe-primaer);
        line-height: 1.5;
    }

    .meldung {
        margin: 18px 0;
        padding: 14px 16px;
        border-radius: 8px;
        font-weight: 700;
    }

    .meldung-fehler {
        border: 1px solid #f3b5b5;
        background: #fff0f0;
        color: var(--farbe-warnung);
    }

    .meldung-erfolg {
        border: 1px solid #bfe2c7;
        background: #f0fbf2;
        color: var(--farbe-erfolg);
    }

    .hinweisband {
        margin: 18px 0;
        padding: 16px 18px;
        border: 1px solid var(--farbe-akzent);
        border-radius: 8px;
        background: #fdf4e7;
        color: #273d5e;
        font-weight: 700;
    }

    .hinweisband.warnung {
        border-color: #f3b5b5;
        background: #fff0f0;
        color: var(--farbe-warnung);
    }

    .schaltflaeche {
        display: inline-flex;
        min-height: 44px;
        align-items: center;
        justify-content: center;
        gap: 8px;
        border: 0;
        border-radius: 8px;
        padding: 11px 16px;
        font-weight: 800;
        text-decoration: none;
        transition: transform 0.15s ease, background-color 0.15s ease;
    }

    .schaltflaeche:hover {
        transform: translateY(-1px);
    }

    .schaltflaeche-primaer {
        background: var(--farbe-primaer);
        color: #ffffff;
    }

    .schaltflaeche-primaer:hover {
        background: #1b5771;
    }

    .schaltflaeche-sekundaer {
        background: #e8e8e8;
        color: var(--farbe-primaer);
    }

    .schaltflaeche-erfolg {
        background: #1b5771;
        color: #ffffff;
    }

    .schaltflaeche-gefahr {
        background: var(--farbe-warnung);
        color: #ffffff;
    }

    .aktionsleiste {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin: 18px 0;
    }

    .tabellenkarte {
        overflow-x: auto;
    }

    .daten-tabelle {
        width: 100%;
        border-collapse: collapse;
        min-width: 720px;
    }

    .daten-tabelle th,
    .daten-tabelle td {
        border-bottom: 1px solid #d6dde5;
        padding: 13px 14px;
        text-align: left;
        vertical-align: middle;
    }

    .daten-tabelle th {
        background: #eef3f6;
        color: var(--farbe-primaer);
        font-size: 0.92rem;
    }

    .daten-tabelle tr:last-child td {
        border-bottom: 0;
    }

    .zeilenaktionen {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
    }

    .admin-raster {
        display: grid;
        grid-template-columns: minmax(0, 1fr) 320px;
        gap: 20px;
        margin-top: 20px;
    }

    .kopfbereich + .aktionskarte,
    .kopfbereich + .formularbereich,
    .kopfbereich + .tabellenkarte,
    .admin-raster + .aktionskarte {
        margin-top: 20px;
    }

    .app-footer {
        width: min(1120px, calc(100% - 32px));
        margin: 0 auto 24px;
        padding: 18px;
        border-top: 1px solid rgba(42, 166, 218, 0.45);
        color: #ffffff;
        text-align: center;
    }

    .app-footer a {
        color: var(--farbe-darc-blau);
        font-weight: 700;
    }

    img {
        max-width: 100%;
        height: auto;
        border-radius: 8px;
    }

    @media (min-width: 760px) {
        .kopfbereich h1 {
            font-size: 3.25rem;
        }
    }

    @media (max-width: 860px) {
        .formularbereich,
        .admin-raster,
        .kennzahlen {
            grid-template-columns: 1fr;
        }

        .formularraster {
            grid-template-columns: 1fr;
        }

        .kopfbereich {
            padding: 26px;
        }
    }

    @media (max-width: 560px) {
        .seitenrahmen {
            width: min(100% - 20px, 1120px);
            padding-top: 18px;
        }

        .aktionskarte,
        .tabellenkarte {
            padding: 18px;
        }

        .kopfbereich h1 {
            font-size: 2rem;
        }

        .terminzeile,
        .schaltflaeche {
            width: 100%;
        }

        .terminzeile span {
            width: 100%;
        }

        .terminzeile span + span::before {
            content: none;
        }

        .ortskarte {
            grid-template-columns: 1fr;
        }
    }
"""


def copyright_text():
    aktuelles_jahr = datetime.now().year
    jahre = str(ERSTELLUNGSJAHR)
    if aktuelles_jahr > ERSTELLUNGSJAHR:
        jahre = f"{ERSTELLUNGSJAHR} - {aktuelles_jahr}"
    return f"© {jahre} {COPYRIGHT_INHABER}"


def footer_html():
    return Markup(f'<footer class="app-footer">{copyright_text()}</footer>')


def render_seite(template, **context):
    context.setdefault('seiten_stil', SEITEN_STIL)
    context.setdefault('footer_html', footer_html())
    context.setdefault('veranstaltungsort_name', VERANSTALTUNGSORT_NAME)
    context.setdefault('veranstaltungsort_strasse', VERANSTALTUNGSORT_STRASSE)
    context.setdefault('veranstaltungsort_ort', VERANSTALTUNGSORT_ORT)
    context.setdefault('veranstaltungsort_route_url', VERANSTALTUNGSORT_ROUTE_URL)
    return render_template_string(template, **context)


@brunch.route('/', methods=['GET', 'POST'])
def index():
    next_brunch_date_str = next_brunch_date()
    error_message = ""
    meldung_typ = "fehler"
    available_items = get_available_items()
    no_items_available = len(available_items) == 0 and not any(item.lower() not in [entry[2].lower() for entry in db_manager.get_brunch_info()] for item in read_items_from_file())
    total_participants_excluding_coffee_only = db_manager.count_participants_excluding_coffee_only()
    coffee_only_participants = db_manager.count_coffee_only_participants()
    logger.debug(f"Anfrage an die Startseite erhalten: Methode {request.method}")

    event_cancelled = is_event_cancelled()
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
                error_message = "Das Mitbringsel darf aus maximal zwei Wörtern mit Buchstaben oder Bindestrichen bestehen."
            elif not for_coffee_only and not (custom_item or selected_item):
                error_message = "Bitte ein Mitbringsel auswählen, ein neues eintragen oder „Nur zum Kaffeetrinken“ wählen."
            elif db_manager.participant_exists(name):
                return redirect(url_for('confirm_delete', name=name))
            else:
                if for_coffee_only:
                    db_manager.add_brunch_entry(name, email, '', 1)
                    error_message = f"Teilnehmer '{name}' als Kaffeetrinker hinzugefügt."
                    meldung_typ = "erfolg"
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
                        meldung_typ = "erfolg"

                total_participants_excluding_coffee_only = db_manager.count_participants_excluding_coffee_only()
                coffee_only_participants = db_manager.count_coffee_only_participants()
                available_items = get_available_items()  # Update available items list
        else:
            error_message = "Die Anmeldung ist derzeit nicht möglich."

    taken_items_info = db_manager.get_brunch_info()
    taken_items = [item for _, _, item, _ in taken_items_info if item]
    taken_items_str = ', '.join(taken_items)

    return render_seite("""
        <!DOCTYPE html>
        <html lang="de">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>L11 Frühstücksbrunch Anmeldung</title>
            <style>{{ seiten_stil | safe }}</style>
        </head>
        <body class="app-shell">
            <main class="seitenrahmen">
                <section class="kopfbereich">
                    <p class="bereichstitel">L11 Frühstücksbrunch</p>
                    <h1>Anmeldung zum gemeinsamen Frühstück</h1>
                    <p class="terminzeile">
                        <span>Sonntag, {{ next_brunch_date_str }} um 10 Uhr</span>
                        <span>{{ veranstaltungsort_strasse }}, {{ veranstaltungsort_ort }}</span>
                    </p>
                    <div class="ortskarte" aria-label="Veranstaltungsort">
                        <p>
                            <strong>{{ veranstaltungsort_name }}</strong>
                            Navigationsziel: DARC Ortsverband Essen-Mitte L11
                        </p>
                        <a href="{{ veranstaltungsort_route_url }}" class="schaltflaeche schaltflaeche-sekundaer" target="_blank" rel="noopener">Route planen</a>
                    </div>
                </section>

                {% if event_cancelled %}
                <div class="hinweisband warnung">Der nächste Termin fällt aus.</div>
                {% endif %}
                {% if show_exception_notice %}
                <div class="hinweisband">Aus organisatorischen Gründen weichen wir einmalig vom normalen Rhythmus ab.</div>
                {% endif %}

                <section class="kennzahlen" aria-label="Aktueller Stand">
                    <article class="aktionskarte kennzahl">
                        <span>Teilnehmende Personen</span>
                        <strong>{{ total_participants_excluding_coffee_only }}</strong>
                    </article>
                    <article class="aktionskarte kennzahl">
                        <span>Kaffeetrinker</span>
                        <strong>{{ coffee_only_participants }}</strong>
                    </article>
                </section>

                {% if error_message %}
                <div class="meldung {{ 'meldung-erfolg' if meldung_typ == 'erfolg' else 'meldung-fehler' }}" role="status">
                    {{ error_message }}
                </div>
                {% endif %}

                <section class="formularbereich">
                    <form method="post" class="aktionskarte">
                        <div class="formularraster">
                            <div class="formulargruppe">
                                <label for="name">Rufzeichen oder vollständiger Name</label>
                                <input type="text" name="name" class="eingabe" id="name" autocomplete="name" required {% if not registration_open %}disabled{% endif %}>
                            </div>
                            <div class="formulargruppe">
                                <label for="email">E-Mail</label>
                                <input type="email" name="email" class="eingabe" id="email" autocomplete="email" required {% if not registration_open %}disabled{% endif %}>
                            </div>
                            <div class="formulargruppe ganze-breite">
                                <label for="selected_item">Mitbringsel</label>
                                {% if no_items_available %}
                                    <input type="text" name="selected_item" class="eingabe" id="selected_item" value="Bitte selbst hinzufügen" disabled>
                                {% else %}
                                    <select name="selected_item" class="auswahl" id="selected_item" {% if not registration_open %}disabled{% endif %}>
                                        {% for item in available_items %}
                                            <option value="{{ item }}">{{ item }}</option>
                                        {% endfor %}
                                    </select>
                                {% endif %}
                            </div>
                            <div class="formulargruppe ganze-breite">
                                <label for="custom_item">Oder neues Mitbringsel hinzufügen</label>
                                <input type="text" name="custom_item" class="eingabe" id="custom_item" placeholder="z. B. Obstsalat" {% if not registration_open %}disabled{% endif %}>
                            </div>
                            <label class="checkbox-zeile ganze-breite" for="for_coffee_only">
                                <input type="checkbox" name="for_coffee_only" id="for_coffee_only" {% if not registration_open %}disabled{% endif %}>
                                <span>Nur zum Kaffeetrinken <span class="kleiner-text">(Mitbringsel wird ignoriert)</span></span>
                            </label>
                            <div class="formulargruppe ganze-breite">
                                <button type="submit" class="schaltflaeche schaltflaeche-primaer" {% if not registration_open %}disabled{% endif %}>Anmelden / Abmelden</button>
                            </div>
                        </div>
                    </form>

                    <aside class="aktionskarte">
                        <h2>Aktuelle Mitbringsel</h2>
                        {% if taken_items_str %}
                        <p class="mitbringsel-liste">{{ taken_items_str }}</p>
                        {% else %}
                        <p class="mitbringsel-liste">Noch keine Mitbringsel vergeben.</p>
                        {% endif %}
                        <p class="hilfetext">Die Anmeldung ist ab Freitag 0 Uhr vor dem Brunch geschlossen und wird am Brunch-Sonntag um 15 Uhr wieder geöffnet.</p>
                    </aside>
                </section>
            </main>
            {{ footer_html }}
        </body>
        </html>
    """, total_participants_excluding_coffee_only=total_participants_excluding_coffee_only, coffee_only_participants=coffee_only_participants, available_items=available_items, taken_items_str=taken_items_str, error_message=error_message, meldung_typ=meldung_typ, next_brunch_date_str=next_brunch_date_str, no_items_available=no_items_available, registration_open=registration_open, show_exception_notice=should_show_exception_notice(), event_cancelled=event_cancelled)

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

    return render_seite("""
        <!DOCTYPE html>
        <html lang="de">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Teilnehmer löschen</title>
            <style>{{ seiten_stil | safe }}</style>
        </head>
        <body class="app-shell">
            <main class="seitenrahmen">
                <section class="kopfbereich">
                    <p class="bereichstitel">Anmeldung ändern</p>
                    <h1>Teilnehmer löschen</h1>
                </section>
                <form method="POST" class="aktionskarte">
                    <p>Möchtest du <b>{{ name }}</b> wirklich löschen?</p>
                    <div class="aktionsleiste">
                        <button type="submit" class="schaltflaeche schaltflaeche-gefahr">Löschen</button>
                        <a href="{{ url_for('index') }}" class="schaltflaeche schaltflaeche-sekundaer">Abbrechen</a>
                    </div>
                </form>
            </main>
            {{ footer_html }}
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

@brunch.route('/admin/update_settings', methods=['POST'])
@requires_auth
def update_settings():
    override_date = request.form.get('override_date', '').strip()
    cancel_next = 'cancel_next' in request.form

    if override_date:
        try:
            override_dt = datetime.strptime(override_date, '%Y-%m-%d')
            formatted = override_dt.strftime('%d.%m.%Y')
            db_manager.set_config('next_date_override', formatted)
        except ValueError:
            db_manager.set_config('next_date_override', '')
    else:
        db_manager.set_config('next_date_override', '')

    db_manager.set_config('next_date_cancelled', '1' if cancel_next else '0')
    return redirect(url_for('admin_page'))


@brunch.route('/admin/reset_special_dates', methods=['POST'])
@requires_auth
def reset_special_dates():
    """Entfernt abweichende Termine und setzt Ausfälle zurück."""
    db_manager.clear_special_dates()
    logger.debug("Abweichende Termine und Ausfallmarkierungen zurückgesetzt.")
    return redirect(url_for('admin_page'))

# Import-Anweisungen und Klassen wie zuvor definiert bleiben unverändert

# Hinzufügen einer neuen Route für das Admin-Formular zum Hinzufügen von Teilnehmern
@brunch.route('/admin/add', methods=['GET', 'POST'])
@requires_auth
def admin_add_participant():
    """Teilnehmer über die Admin-Oberfläche hinzufügen."""
    error_message = ""
    # Verfügbare und bereits genutzte Mitbringsel bestimmen
    available_items = get_available_items()
    taken_items_info = db_manager.get_brunch_info()
    taken_items = [item for _, _, item, _ in taken_items_info if item]
    taken_items_str = ', '.join(taken_items)
    no_items_available = len(available_items) == 0 and not any(
        item.lower() not in [entry[2].lower() for entry in taken_items_info]
        for item in read_items_from_file()
    )

    if request.method == 'POST':
        # Aktuelle Daten berücksichtigen, falls andere Teilnehmer zwischenzeitlich etwas eingetragen haben
        taken_items_info = db_manager.get_brunch_info()
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
            error_message = "Das Mitbringsel darf aus maximal zwei Wörtern mit Buchstaben oder Bindestrichen bestehen."
        elif not for_coffee_only and not (custom_item or selected_item):
            error_message = "Bitte ein Mitbringsel auswählen, ein neues eintragen oder „Nur zum Kaffeetrinken“ wählen."
        elif db_manager.participant_exists(name):
            error_message = f"Teilnehmer '{name}' ist bereits eingetragen."
        elif for_coffee_only:
            db_manager.add_brunch_entry(name, email, '', 1)
            return redirect(url_for('admin_page'))
        else:
            item_lower = (custom_item if custom_item else selected_item).lower()
            if item_lower in [i.lower() for _, _, i, _ in taken_items_info]:
                error_message = (
                    f"Mitbringsel '{custom_item if custom_item else selected_item}' ist bereits vergeben."
                )
            else:
                item_to_add = custom_item.lower().capitalize() if custom_item else selected_item
                if custom_item and item_lower not in [i.lower() for i in read_items_from_file()]:
                    add_item_to_file(custom_item)
                db_manager.add_brunch_entry(name, email, item_to_add, 0)
                return redirect(url_for('admin_page'))

        # Bei Fehler oder erneutem Anzeigen die Listen aktualisieren
        available_items = get_available_items()
        taken_items_info = db_manager.get_brunch_info()
        taken_items = [item for _, _, item, _ in taken_items_info if item]
        taken_items_str = ', '.join(taken_items)

    return render_seite(
        """
        <!DOCTYPE html>
        <html lang="de">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Teilnehmer hinzufügen - Admin</title>
            <style>{{ seiten_stil | safe }}</style>
        </head>
        <body class="app-shell">
            <main class="seitenrahmen">
                <section class="kopfbereich">
                    <p class="bereichstitel">Admin</p>
                    <h1>Teilnehmer hinzufügen</h1>
                </section>

                {% if error_message %}
                <div class="meldung meldung-fehler" role="status">{{ error_message }}</div>
                {% endif %}

                <section class="formularbereich">
                    <form method="post" class="aktionskarte">
                        <div class="formularraster">
                            <div class="formulargruppe">
                                <label for="name">Name</label>
                                <input type="text" id="name" name="name" required class="eingabe">
                            </div>
                            <div class="formulargruppe">
                                <label for="email">E-Mail</label>
                                <input type="email" id="email" name="email" required class="eingabe">
                            </div>
                            <div class="formulargruppe ganze-breite">
                                <label for="selected_item">Mitbringsel</label>
                                {% if no_items_available %}
                                    <input type="text" id="selected_item" name="selected_item" class="eingabe" value="Bitte selbst hinzufügen" disabled>
                                {% else %}
                                    <select id="selected_item" name="selected_item" class="auswahl">
                                        {% for item in available_items %}
                                            <option value="{{ item }}">{{ item }}</option>
                                        {% endfor %}
                                    </select>
                                {% endif %}
                            </div>
                            <div class="formulargruppe ganze-breite">
                                <label for="custom_item">Oder neues Mitbringsel hinzufügen</label>
                                <input type="text" id="custom_item" name="custom_item" class="eingabe">
                            </div>
                            <label class="checkbox-zeile ganze-breite" for="for_coffee_only">
                                <input type="checkbox" id="for_coffee_only" name="for_coffee_only">
                                <span>Nur zum Kaffeetrinken</span>
                            </label>
                            <div class="aktionsleiste ganze-breite">
                                <button type="submit" class="schaltflaeche schaltflaeche-primaer">Teilnehmer hinzufügen</button>
                                <a href="{{ url_for('admin_page') }}" class="schaltflaeche schaltflaeche-sekundaer">Zurück</a>
                            </div>
                        </div>
                    </form>

                    <aside class="aktionskarte">
                        <h2>Bereits vergeben</h2>
                        {% if taken_items_str %}
                        <p class="mitbringsel-liste">{{ taken_items_str }}</p>
                        {% else %}
                        <p class="mitbringsel-liste">Noch keine Mitbringsel vergeben.</p>
                        {% endif %}
                    </aside>
                </section>
            </main>
            {{ footer_html }}
        </body>
        </html>
        """,
        available_items=available_items,
        taken_items_str=taken_items_str,
        no_items_available=no_items_available,
        error_message=error_message,
    )

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
    override_date = db_manager.get_config('next_date_override') or ''
    override_date_iso = ''
    if override_date:
        try:
            override_dt = datetime.strptime(override_date, '%d.%m.%Y')
            override_date_iso = override_dt.strftime('%Y-%m-%d')
        except ValueError:
            override_date_iso = ''
    event_cancelled = is_event_cancelled()
    exception_notice = should_show_exception_notice()
    next_date = next_brunch_date()
    statistik_verfuegbar = os.path.exists(os.path.join('statistik', 'teilnahmen_statistik.png'))

    return render_seite("""
        <!DOCTYPE html>
        <html lang="de">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Admin - Frühstücks-Brunch</title>
            <style>{{ seiten_stil | safe }}</style>
        </head>
        <body class="app-shell">
            <main class="seitenrahmen">
                <section class="kopfbereich">
                    <p class="bereichstitel">Admin</p>
                    <h1>Frühstücks-Brunch verwalten</h1>
                    <p class="terminzeile">Nächster Termin: {{ next_date }}</p>
                </section>

                {% if event_cancelled %}
                <div class="hinweisband warnung">Der nächste Termin fällt aus.</div>
                {% endif %}
                {% if exception_notice %}
                <div class="hinweisband">Aus organisatorischen Gründen weichen wir einmalig vom normalen Rhythmus ab.</div>
                {% endif %}

                <section class="tabellenkarte">
                    <table class="daten-tabelle">
                        <thead>
                            <tr>
                                <th>Name</th>
                                <th>E-Mail</th>
                                <th>Mitbringsel</th>
                                <th>Nur zum Kaffee</th>
                                <th>Aktionen</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for name, email, item, for_coffee_only in brunch_info %}
                            <tr>
                                <td>{{ name }}</td>
                                <td>{{ email }}</td>
                                <td>{{ item }}</td>
                                <td>{{ 'Ja' if for_coffee_only else 'Nein' }}</td>
                                <td>
                                    <div class="zeilenaktionen">
                                        <a href="{{ url_for('edit_entry', name=name) }}" class="schaltflaeche schaltflaeche-erfolg">Bearbeiten</a>
                                        <form action="{{ url_for('delete_entry', name=name) }}" method="post">
                                            <button type="submit" class="schaltflaeche schaltflaeche-gefahr">Löschen</button>
                                        </form>
                                    </div>
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </section>

                <section class="admin-raster">
                    <div class="aktionskarte">
                        <h2>Aktionen</h2>
                        <div class="aktionsleiste">
                            <a href="{{ mailto_link }}" class="schaltflaeche schaltflaeche-erfolg">E-Mail an alle Teilnehmer senden</a>
                            <a href="{{ url_for('download_pdf') }}" class="schaltflaeche schaltflaeche-sekundaer">Tabelle als PDF herunterladen</a>
                            <a href="{{ url_for('admin_mitbringsel') }}" class="schaltflaeche schaltflaeche-sekundaer">Mitbringsel editieren</a>
                            <a href="{{ url_for('admin_add_participant') }}" class="schaltflaeche schaltflaeche-primaer">Teilnehmer hinzufügen</a>
                        </div>
                    </div>

                    <div class="aktionskarte">
                        <h2>Termin</h2>
                        <form method="post" action="{{ url_for('update_settings') }}" class="formulargruppe">
                            <label for="override_date">Abweichendes Datum</label>
                            <input type="date" id="override_date" name="override_date" value="{{ override_date_iso }}" class="eingabe" min="2025-07-06" step="7">
                            <label class="checkbox-zeile" for="cancel_next">
                                <input type="checkbox" id="cancel_next" name="cancel_next" {% if event_cancelled %}checked{% endif %}>
                                <span>Nächsten Termin ausfallen lassen</span>
                            </label>
                            <button type="submit" class="schaltflaeche schaltflaeche-primaer">Speichern</button>
                        </form>
                        <form method="post" action="{{ url_for('reset_special_dates') }}" class="aktionsleiste">
                            <button type="submit" class="schaltflaeche schaltflaeche-gefahr">Ausfall/Abweichung zurücksetzen</button>
                        </form>
                    </div>
                </section>

                <section class="aktionskarte">
                    <h2>Statistik</h2>
                    {% if statistik_verfuegbar %}
                    <img src="/statistik/teilnahmen_statistik.png" alt="Statistik">
                    {% else %}
                    <p class="hilfetext">Es ist noch keine Statistikdatei vorhanden.</p>
                    {% endif %}
                </section>
            </main>
            {{ footer_html }}
        </body>
        </html>
    """, brunch_info=brunch_info, current_year=datetime.now().year, mailto_link=mailto_link,
           override_date=override_date, override_date_iso=override_date_iso,
           event_cancelled=event_cancelled, exception_notice=exception_notice,
           next_date=next_date, statistik_verfuegbar=statistik_verfuegbar)

# Route zum Anzeigen und Bearbeiten der Mitbringsel-Liste
@brunch.route('/admin/mitbringsel', methods=['GET', 'POST'])
@requires_auth
def admin_mitbringsel():
    if request.method == 'POST':
        # Aktualisierte Liste der Mitbringsel aus dem Formular erhalten
        updated_items = request.form.get('mitbringsel_list').split('\n')
        updated_items = [item.strip() for item in updated_items if item.strip()]
        
        # Aktualisierte Liste in die Datei schreiben
        with open('mitbringsel.txt', 'w', encoding='utf-8') as file:
            for item in updated_items:
                file.write(f"{item}\n")

        return redirect(url_for('admin_mitbringsel'))

    # Vorhandene Mitbringsel aus der Datei lesen
    items = read_items_from_file()
    items_str = '\n'.join(items)

    return render_seite("""
        <!DOCTYPE html>
        <html lang="de">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Admin - Mitbringsel bearbeiten</title>
            <style>{{ seiten_stil | safe }}</style>
        </head>
        <body class="app-shell">
            <main class="seitenrahmen">
                <section class="kopfbereich">
                    <p class="bereichstitel">Admin</p>
                    <h1>Mitbringsel bearbeiten</h1>
                </section>
                <form method="post" class="aktionskarte">
                    <div class="formulargruppe">
                        <label for="mitbringsel_list">Mitbringsel-Liste</label>
                        <textarea id="mitbringsel_list" name="mitbringsel_list">{{ items_str }}</textarea>
                    </div>
                    <div class="aktionsleiste">
                        <button type="submit" class="schaltflaeche schaltflaeche-primaer">Speichern</button>
                        <a href="{{ url_for('admin_page') }}" class="schaltflaeche schaltflaeche-sekundaer">Zurück zum Admin-Bereich</a>
                    </div>
                </form>
            </main>
            {{ footer_html }}
        </body>
        </html>
    """, items_str=items_str)

@brunch.route('/admin/edit/<name>', methods=['GET', 'POST'])
@requires_auth
def edit_entry(name):
    entry = db_manager.get_entry(name)
    if not entry:
        return redirect(url_for('admin_page'))
    error_message = ""

    if request.method == 'POST':
        # Daten aus dem Formular auslesen
        updated_name = request.form['name'].strip()
        updated_email = request.form['email'].strip()
        updated_item = request.form['item'].strip()
        updated_for_coffee_only = 'for_coffee_only' in request.form
        if updated_for_coffee_only:
            updated_item = ''

        if not validate_email(updated_email):
            error_message = "Bitte eine gültige E-Mail-Adresse eingeben."
        elif not validate_name_or_call(updated_name):
            error_message = "Bitte ein gültiges Rufzeichen oder einen vollständigen Namen eingeben."
        elif not updated_for_coffee_only and not updated_item:
            error_message = "Bitte ein Mitbringsel eintragen oder „Nur zum Kaffeetrinken“ wählen."
        elif updated_item and not validate_bringalong(updated_item):
            error_message = "Das Mitbringsel darf aus maximal zwei Wörtern mit Buchstaben oder Bindestrichen bestehen."
        else:
            # Update in der Datenbank durchführen
            db_manager.update_entry(name, updated_name, updated_email, updated_item, updated_for_coffee_only)
            return redirect(url_for('admin_page'))

        entry = (updated_name, updated_email, updated_item, int(updated_for_coffee_only))

    return render_seite("""
        <!DOCTYPE html>
        <html lang="de">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Eintrag Bearbeiten</title>
            <style>{{ seiten_stil | safe }}</style>
        </head>
        <body class="app-shell">
            <main class="seitenrahmen">
                <section class="kopfbereich">
                    <p class="bereichstitel">Admin</p>
                    <h1>Eintrag bearbeiten</h1>
                </section>
                <script>
                    function handleCoffeeOnlyChange() {
                        var checkBox = document.getElementById('for_coffee_only');
                        var itemInput = document.getElementById('item');
                        if (checkBox.checked) {
                            itemInput.value = '';
                        }
                    }
                </script>

                {% if error_message %}
                <div class="meldung meldung-fehler" role="status">{{ error_message }}</div>
                {% endif %}

                <form method="post" class="aktionskarte">
                    <div class="formularraster">
                        <div class="formulargruppe">
                            <label for="name">Name</label>
                            <input type="text" id="name" name="name" value="{{ entry[0] }}" class="eingabe" required>
                        </div>
                        <div class="formulargruppe">
                            <label for="email">E-Mail</label>
                            <input type="email" id="email" name="email" value="{{ entry[1] }}" class="eingabe" required>
                        </div>
                        <div class="formulargruppe ganze-breite">
                            <label for="item">Mitbringsel</label>
                            <input type="text" id="item" name="item" value="{{ entry[2] }}" class="eingabe">
                        </div>
                        <label class="checkbox-zeile ganze-breite" for="for_coffee_only">
                            <input type="checkbox" id="for_coffee_only" name="for_coffee_only" {{ 'checked' if entry[3] else '' }} onchange="handleCoffeeOnlyChange()">
                            <span>Nur zum Kaffeetrinken</span>
                        </label>
                        <div class="aktionsleiste ganze-breite">
                            <button type="submit" class="schaltflaeche schaltflaeche-primaer">Änderungen speichern</button>
                            <a href="{{ url_for('admin_page') }}" class="schaltflaeche schaltflaeche-sekundaer">Abbruch und zurück zum Admin-Bereich</a>
                        </div>
                    </div>
                </form>
            </main>
            {{ footer_html }}
        </body>
        </html>
    """, entry=entry, error_message=error_message)

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
    return send_file(buffer, as_attachment=True, download_name='brunch_liste.pdf', mimetype='application/pdf')

def save_participant_log():
    brunch_info = db_manager.get_brunch_info()

    # Zeitzone für Europe/Berlin definieren
    berlin_tz = pytz.timezone('Europe/Berlin')

    # Aktuelle Zeit in Berliner Zeitzone
    current_date = datetime.now(berlin_tz).strftime('%d.%m.%Y')

    with open('teilnahmen.log', 'a', encoding='utf-8') as log_file:
        for name, _, item, _ in brunch_info:
            log_file.write(f"{current_date}, {name}, {item}\n")
    logger.debug("Teilnehmerlog wurde gespeichert.")

def reset_database_at_event_time():
    while True:
        if should_reset_database():
            current_brunch_str = current_brunch_date()
            # Speichern der Teilnehmerinformationen in eine Log-Datei
            save_participant_log()

            # Zurücksetzen der Datenbank
            db_manager.reset_db()
            db_manager.set_config('last_reset_for_date', current_brunch_str)
            db_manager.clear_special_dates()
            logger.debug("Datenbank wurde resettet.")

            # Warte bis zum nächsten Tag, um erneut zu prüfen
            time.sleep(24 * 60 * 60)
        else:
            # Kurze Pause, um kontinuierliche Überprüfung zu vermeiden
            time.sleep(60)

@brunch.route('/reset_db', methods=['POST'])
@requires_auth
def reset_db():
    try:
        db_manager.reset_db()
        db_manager.clear_special_dates()
        return jsonify({"success": "Datenbank erfolgreich zurückgesetzt"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Starten des Threads zur Überwachung und zum Zurücksetzen der Datenbank
# Nutzt reset_database_at_event_time, um die Datenbank pünktlich zum Ende des
# Brunchs zu leeren. Diese Implementierung prüft minütlich, ob das gesetzte
# Veranstaltungsdatum überschritten wurde und vermeidet dadurch Verzögerungen
# durch eine stündliche Überprüfung.
reset_thread = threading.Thread(target=reset_database_at_event_time)
reset_thread.daemon = True  # Markieren Sie den Thread als Daemon, damit er automatisch beendet wird, wenn das Hauptprogramm beendet wird.
reset_thread.start()

if __name__ == '__main__':
    brunch.run(host='0.0.0.0', port=8082, debug=True, use_reloader=False)

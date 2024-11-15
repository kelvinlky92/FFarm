import sqlite3
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

# SQLite setup
DATABASE_NAME = os.getenv('DATABASE_NAME')  # Define your SQLite database name

def create_connection():
    """Create a database connection to the SQLite database."""
    conn = sqlite3.connect(DATABASE_NAME)
    return conn

def create_tables():
    """Create tables in the SQLite database if they don't exist."""
    conn = create_connection()
    cursor = conn.cursor()
    
    # Create users table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER UNIQUE,
        username TEXT,
        created_at TEXT,
        manager_on_off INTEGER,
        is_admin INTEGER DEFAULT 0
    )
    ''')
    
    # Create cashflow_ledger table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS cashflow_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        description TEXT,
        transaction_date TEXT,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    ''')
    
    # Create plants_listing table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS plants_listing (
        id INTEGER PRIMARY KEY,
        name TEXT,
        category TEXT,
        emoji TEXT,
        min_harvesting_ratio REAL,
        max_harvesting_ratio REAL,
        seed_purchase_price INTEGER,
        harvest_time INTEGER,
        selling_price INTEGER,
        upgrade_id INTEGER,
        FOREIGN KEY (upgrade_id) REFERENCES upgrade_listings (id)
    )
    ''')
    
    # Create user_crops table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_crops (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        item_id INTEGER,
        planted_at TEXT,
        status TEXT,
        planted_quantity INTEGER,
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (item_id) REFERENCES plants_listing (id)           
    )
    ''')

    # Create upgrade_listings table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS upgrade_listings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        level INTEGER,
        category TEXT,
        description TEXT,
        price INTEGER
    )
    ''')

    # Create user_upgrades table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_upgrades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        upgrade_id INTEGER,
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (upgrade_id) REFERENCES upgrade_listings (id)
    )
    ''')

    # Create user_auto_planting table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_auto_planting (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        item_id INTEGER,
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (item_id) REFERENCES plants_listing (id)
    )
    ''')
    
    conn.commit()
    conn.close()
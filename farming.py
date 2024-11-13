from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import JSONResponse
import telegram
import logging
import os
import subprocess
import time
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
import random  # Import random for generating harvest ratios
import sqlite3
import asyncio
from contextlib import asynccontextmanager
import sys
import io
from collections import defaultdict

load_dotenv()

# Set the console encoding to UTF-8 for Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create a logs directory if it doesn't exist
if not os.path.exists('logs'):
    os.makedirs('logs')

# Create a logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)  # Set the logging level

# Create a formatter
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# Create a file handler for logging to a file with date and time in the filename
current_time = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')  # Format the current time
log_file_name = f'logs/app_{current_time}.log'  # Create a log file name with date and time
file_handler = logging.FileHandler(log_file_name, mode='a', encoding='utf-8')  # Append mode with UTF-8 encoding
file_handler.setLevel(logging.INFO)  # Set the level for the file handler
file_handler.setFormatter(formatter)  # Set the formatter for the file handler

# Add both handlers to the logger
logger.addHandler(file_handler)

# Replace with your actual bot token
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
bot = telegram.Bot(token=TOKEN)

# SQLite setup
DATABASE_NAME = os.getenv('DATABASE_NAME')  # Define your SQLite database name

#app = FastAPI()

# Global variable to store ngrok process
ngrok_process = None  # Declare the ngrok_process variable

# Global variable to store plant data
plant_data = {}
user_data = {}  # Game state (in-memory for simplicity; consider using a database for persistence)
users_to_notify = set()

# Create a queue for incoming messages
message_queue = asyncio.Queue()

# Rate limiting configuration
RATE_LIMIT = 20  # Maximum number of requests
TIME_FRAME = 60  # Time frame in seconds

# Dictionary to store user request timestamps
user_requests = defaultdict(list)

def rate_limiter(chat_id):
    current_time = time.time()
    # Remove timestamps that are outside the time frame
    user_requests[chat_id] = [timestamp for timestamp in user_requests[chat_id] if current_time - timestamp < TIME_FRAME]
    
    if len(user_requests[chat_id]) < RATE_LIMIT:
        # Allow the request
        user_requests[chat_id].append(current_time)
        return True
    else:
        # Deny the request
        return False

def start_ngrok():
    logger.info("Starting ngrok...")
    # Start ngrok process
    ngrok_process = subprocess.Popen(['ngrok', 'http', '8000'], stdout=subprocess.PIPE)
    time.sleep(2)  # Wait for ngrok to initialize
    logger.info("ngrok started.")
    return ngrok_process

def get_ngrok_url():
    logger.info("Getting ngrok URL...")
    # Get the public URL from ngrok
    response = requests.get('http://localhost:4040/api/tunnels')
    tunnels = response.json().get('tunnels', [])
    if tunnels:
        ngrok_url = tunnels[0]['public_url']
        logger.info(f"ngrok URL obtained: {ngrok_url}")
        return ngrok_url
    logger.warning("No tunnels found.")
    return None

def set_telegram_webhook(ngrok_url):
    logger.info("Setting Telegram webhook...")
    webhook_url = f"{ngrok_url}/webhook"
    logger.info(f"Webhook URL: {webhook_url}")
    response = requests.post(f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={webhook_url}")
    logger.info(f"Webhook set to: {webhook_url}")
    logger.info(f"Response: {response.json()}")
    return response.json()

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

def get_available_plots_slots(upgrade_level):
    """Return the number of available planting slots based on the user's upgrade level."""
    slots = {
        1: 1000,
        2: 10000,
        3: 100000,
        4: 1000000,
        5: 10000000
    }
    return slots.get(upgrade_level, 100)  # Default to 0 if level is not found

async def process_queue():
    while True:
        chat_id, text = await message_queue.get()  # Wait for an item from the queue
        await handle_message(chat_id, text)  # Process the message
        message_queue.task_done()  # Mark the task as done

async def fetch_plant_data():
    """Fetch plant data from the plants_listing table and store it in a global variable."""
    global plant_data
    conn = create_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM plants_listing")
    plants = cursor.fetchall()

    if plants:
        for plant in plants:
            category = plant[2]  # Assuming category is the third column
            if category not in plant_data:
                plant_data[category] = []
            plant_info = {
                'id': plant[0],  # ID
                'name': plant[1],  # Name
                'emoji': plant[3],  # Emoji
                'seed_purchase_price': plant[6],  # Seed purchase price
                'min_harvesting_ratio': plant[4],  # Min harvesting ratio
                'max_harvesting_ratio': plant[5],  # Max harvesting ratio
                'harvest_time': plant[7],  # Harvest time
                'selling_price': plant[8],  # Selling price
                'upgrade_id': plant[9]  # Upgrade ID
            }
            plant_data[category].append(plant_info)

    conn.close()

async def register_user(chat_id, update):
    """Register the user if they are not already registered."""
    conn = create_connection()
    cursor = conn.cursor()

    # Check if user exists
    cursor.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,))
    user = cursor.fetchone()

    if not user:
        logger.info(f"User {chat_id} not found. Creating new user entry.")
        local_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')  # Get local time
        
        # Extract username from the update (if available)
        username = update['message']['from'].get('username') if 'message' in update and 'from' in update['message'] else None

        # Insert new user into the database
        cursor.execute("INSERT INTO users (chat_id, username, created_at) VALUES (?, ?, ?)", (chat_id, username, local_time))
        user_id = cursor.lastrowid  # Get the last inserted user ID

        # Initialize user cashflow
        cursor.execute("INSERT INTO cashflow_ledger (user_id, amount, description, transaction_date) VALUES (?, ?, ?, ?)", 
                       (user_id, 50, 'Initial cashflow upon registration.', local_time))

        conn.commit()
        await bot.send_message(chat_id=chat_id, text='Welcome to FFarm 🌾\nYou have been registered with $50 in your wallet.')

    conn.close()

async def show_game_menu(chat_id):
    """Display the game menu with wallet balance and options."""
    conn = create_connection()  # Create a connection to the SQLite database
    cursor = conn.cursor()

    # Fetch user ID based on chat_id
    cursor.execute("SELECT id, manager_on_off FROM users WHERE chat_id = ?", (chat_id,))
    user = cursor.fetchone()
    user_id, manager_on_off = user[0], user[1] if user else (None, None)

    # Fetch cashflow entries for the user
    cursor.execute("SELECT amount FROM cashflow_ledger WHERE user_id = ?", (user_id,))
    balance_response = cursor.fetchall()

    # Calculate total balance
    total_balance = sum(entry[0] for entry in balance_response) if balance_response else 0
    total_balance = f"{total_balance:,}"

    # Fetch all upgrade IDs for the user
    cursor.execute("SELECT upgrade_id FROM user_upgrades WHERE user_id = ?", (user_id,))
    user_upgrades = cursor.fetchall()  # Fetch all upgrades

    # Determine the highest upgrade level of manager
    current_manager_upgrade_level = 0  # Default to 0 if no upgrades
    if user_upgrades:
        # Extract upgrade IDs
        upgrade_ids = [upgrade[0] for upgrade in user_upgrades]

        # Fetch levels for all upgrade IDs, filtering by category 'manager'
        cursor.execute("SELECT level FROM upgrade_listings WHERE id IN ({}) AND category = ?".format(','.join('?' * len(upgrade_ids))), (upgrade_ids + ['manager']))
        levels = cursor.fetchall()

        # Find the maximum level
        current_manager_upgrade_level = max(level[0] for level in levels) if levels else 0

    if current_manager_upgrade_level == 0:
        # Create inline keyboard for the game menu
        keyboard = [
            [telegram.InlineKeyboardButton("🌾 Plant Status", callback_data='plant_status')],
            [telegram.InlineKeyboardButton("🪴 Planting", callback_data='planting')],
            [telegram.InlineKeyboardButton("👨‍🌾 Harvest", callback_data='harvest')],
            [telegram.InlineKeyboardButton("🏆 Rankings", callback_data='rankings')],
            [telegram.InlineKeyboardButton("🚧 Upgrades", callback_data='upgrades')]
        ]
    
    elif manager_on_off == 0:
        # Create inline keyboard for the game menu
        keyboard = [
            [telegram.InlineKeyboardButton("🌾 Plant Status", callback_data='plant_status')],
            [telegram.InlineKeyboardButton("🪴 Planting", callback_data='planting')],
            [telegram.InlineKeyboardButton("👨‍🌾 Harvest", callback_data='harvest')],
            [telegram.InlineKeyboardButton("🧑‍💼 Manager", callback_data='manager')],
            [telegram.InlineKeyboardButton("🏆 Rankings", callback_data='rankings')],
            [telegram.InlineKeyboardButton("🚧 Upgrades", callback_data='upgrades')]
        ]
    
    elif manager_on_off == 1:
        # Create inline keyboard for the game menu
        keyboard = [
            [telegram.InlineKeyboardButton("🌾 Plant Status", callback_data='plant_status')],
            [telegram.InlineKeyboardButton("🧑‍💼 Manager", callback_data='manager')],
            [telegram.InlineKeyboardButton("🏆 Rankings", callback_data='rankings')],
            [telegram.InlineKeyboardButton("🚧 Upgrades", callback_data='upgrades')]
        ]

    reply_markup = telegram.InlineKeyboardMarkup(keyboard)

    await bot.send_message(chat_id=chat_id, text=f'Welcome to FFarm 🌾\n💰: ${total_balance}\nChoose an option:', reply_markup=reply_markup)

    conn.close()  # Close the database connection

async def show_upgrades_menu(chat_id):
    """Display the upgrades menu with options for plot upgrades."""
    keyboard = [
        [telegram.InlineKeyboardButton("🌱 Plot", callback_data='plot_upgrade')],
        [telegram.InlineKeyboardButton("👨‍🌾 Manager", callback_data='manager_upgrade')],
        [telegram.InlineKeyboardButton("☘️ Crops", callback_data='crops_upgrade')]
    ]
    reply_markup = telegram.InlineKeyboardMarkup(keyboard)

    await bot.send_message(chat_id=chat_id, text='Choose an upgrade option:', reply_markup=reply_markup)

async def show_planting_menu(chat_id):
    """Display the planting menu with options for fruits, vegetables, and grains."""
    keyboard = [
        [telegram.InlineKeyboardButton("🍉 Fruits", callback_data='Fruits')],
        [telegram.InlineKeyboardButton("🥬 Vegetables", callback_data='Vegetables')],
        [telegram.InlineKeyboardButton("🌾 Grains", callback_data='Grain')]
    ]
    reply_markup = telegram.InlineKeyboardMarkup(keyboard)

    await bot.send_message(chat_id=chat_id, text='Choose a category to plant:', reply_markup=reply_markup)

async def show_plants(chat_id, category):
    """Display specific plants based on the selected category."""
    if category not in plant_data:
        await bot.send_message(chat_id=chat_id, text='No plants available in this category.')
        return

    conn = create_connection()
    cursor = conn.cursor()

    # Fetch user ID based on chat_id
    cursor.execute("SELECT id FROM users WHERE chat_id = ?", (chat_id,))
    user = cursor.fetchone()
    user_id = user[0] if user else None

    # Fetch all upgrade IDs for the user
    cursor.execute("SELECT upgrade_id FROM user_upgrades WHERE user_id = ?", (user_id,))
    user_upgrades = cursor.fetchall()  # Fetch all upgrades

    # Filter the plants in the category to only include the ones with NULL upgrade_id or the plants with upgrade_id that is in the user_upgrades
    filtered_plants = [plant for plant in plant_data[category] if plant['upgrade_id'] is None or plant['upgrade_id'] in [upgrade_id[0] for upgrade_id in user_upgrades]]
    
    keyboard = [
        [telegram.InlineKeyboardButton(
            f"{plant['emoji']} {plant['name']} - ⬇${plant['seed_purchase_price']}/⬆${plant['selling_price']} - {plant['harvest_time']} min",
            callback_data=f"plant_{category}_{plant['id']}_{plant['seed_purchase_price']}"
        )]
        for plant in filtered_plants
    ]
    reply_markup = telegram.InlineKeyboardMarkup(keyboard)

    await bot.send_message(chat_id=chat_id, text=f"Choose a plant to purchase from {category.capitalize()}:", reply_markup=reply_markup)

async def show_manager_menu(chat_id):
    """Display the manager menu with options for plant selection."""
    keyboard = [
        [telegram.InlineKeyboardButton("👨‍🌾 Manager On/Off", callback_data='manager_on_off')],
        [telegram.InlineKeyboardButton("👨‍🌾 Auto Planting", callback_data='auto_planting')]
    ]
    reply_markup = telegram.InlineKeyboardMarkup(keyboard)
    await bot.send_message(chat_id=chat_id, text='Choose an option:', reply_markup=reply_markup)

async def show_rankings(chat_id):
    """Display the rankings menu with options for plant selection."""
    conn = create_connection()
    cursor = conn.cursor()
    
    # Fetch top 10 the username and total amount from the cashflow_ledger table, grouped by user_id, and order by the total amount in descending order
    cursor.execute("SELECT users.username, SUM(cashflow_ledger.amount) FROM cashflow_ledger LEFT JOIN users ON cashflow_ledger.user_id = users.id GROUP BY users.id ORDER BY SUM(cashflow_ledger.amount) DESC LIMIT 10")
    rankings = cursor.fetchall()

    rankings_message = "🏆 **Top 10 Rankings**:\n\n"  # Added header
    for index, rank in enumerate(rankings, start=1):
        username = rank[0][:15] + '...' if len(rank[0]) > 15 else rank[0]  # Truncate long usernames
        rankings_message += f"{index}️⃣ {username} - ${rank[1]:,}\n"  # Added ordinal numbers

    photo_path = 'images/rankings.jpeg'
    await bot.send_photo(chat_id=chat_id, photo=photo_path, caption=rankings_message)

async def handle_manager_on_off(chat_id):
    """Handle the manager on/off selection for the user."""
    conn = create_connection()
    cursor = conn.cursor()

    # Fetch manager_on_off based on chat_id
    cursor.execute("SELECT manager_on_off FROM users WHERE chat_id = ?", (chat_id,))
    result = cursor.fetchone()  # Fetch the result once

    # Check if result is None
    manager_on_off = result[0] if result else 0  # Default to 0 if no result found

    if manager_on_off == 0:
        message = ('Manager is currently off.\n'
                   'Do you want to turn it on?'
                   )
        keyboard = [
            [telegram.InlineKeyboardButton("✅", callback_data='manager_on')]
        ]
    else:
        message = ('Manager is currently on.\n'
                   'Do you want to turn it off?'
                   )
        keyboard = [
            [telegram.InlineKeyboardButton("✅", callback_data='manager_off')]
        ]

    # Create inline keyboard for confirmation
    reply_markup = telegram.InlineKeyboardMarkup(keyboard)

    await bot.send_message(chat_id=chat_id, text=message, reply_markup=reply_markup)

    conn.close()

async def show_admin_menu(chat_id):
    """Display the admin menu with options for announcement."""
    conn = create_connection()
    cursor = conn.cursor()
    
    # Fetch user ID based on chat_id
    cursor.execute("SELECT id FROM users WHERE chat_id = ?", (chat_id,))
    user = cursor.fetchone()
    
    # Ensure user_id is a single value
    user_id = user[0] if user else None  # Extract the first element if user is found

    if user_id is not None:
        cursor.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,))
        result = cursor.fetchone()  # Fetch the result once

        if result is not None:
            is_admin = result[0]  # Access the first element if result is not None
        else:
            is_admin = 0  # Default to 0 if no result found

        if is_admin == 1:
            keyboard = [
                [telegram.InlineKeyboardButton("📢 Announcement", callback_data='admin_announcement')]
            ]
            reply_markup = telegram.InlineKeyboardMarkup(keyboard)
            await bot.send_message(chat_id=chat_id, text='Choose an option:', reply_markup=reply_markup)
        else:
            await bot.send_message(chat_id=chat_id, text='You are not authorized to access this menu.')
    else:
        await bot.send_message(chat_id=chat_id, text='User not found.')

    conn.close()

async def select_admin_announcement_type(chat_id):
    """Select the type of announcement to send."""
    keyboard = [
        [telegram.InlineKeyboardButton("📝 Text", callback_data='admin_announcement_text')],
        [telegram.InlineKeyboardButton("🖼️ Photo", callback_data='admin_announcement_photo')]
    ]
    reply_markup = telegram.InlineKeyboardMarkup(keyboard)
    await bot.send_message(chat_id=chat_id, text='Choose the type of announcement:', reply_markup=reply_markup)

async def admin_announcement_text(chat_id):
    """Prompt the admin to enter the announcement message."""
    await bot.send_message(chat_id=chat_id, text='Please enter the announcement message:')
    
    # Set a state to capture the next message from the admin
    # You can use a dictionary to store the state for each chat_id
    user_data[chat_id]['waiting_for_announcement'] = True
    
async def send_admin_announcement_text(chat_id, message):
    """Send an announcement to the users."""
    conn = create_connection()
    cursor = conn.cursor()
    
    # Fetch user ID based on chat_id
    cursor.execute("SELECT id FROM users WHERE chat_id = ?", (chat_id,))
    user = cursor.fetchone()
    
    # Ensure user_id is a single value
    user_id = user[0] if user else None  # Extract the first element if user is found

    if user_id is not None:
        cursor.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,))
        result = cursor.fetchone()  # Fetch the result once

        if result is not None:
            is_admin = result[0]  # Access the first element if result is not None
        else:
            is_admin = 0  # Default to 0 if no result found

        if is_admin == 1:
            cursor.execute("SELECT chat_id FROM users")
            tosend_chat_ids = cursor.fetchall()
            
            for user_chat_id in tosend_chat_ids:
                try:
                    await bot.send_message(chat_id=user_chat_id[0], text=message)
                except Exception as e:
                    logger.error(f"Failed to send message to {user_chat_id[0]}: {e}")
        else:
            await bot.send_message(chat_id=chat_id, text='You are not authorized to send announcements.')

    conn.close()
    user_data[chat_id]['waiting_for_announcement'] = False

async def admin_announcement_photo(chat_id):
    """Prompt the admin to upload the announcement photo."""
    await bot.send_message(chat_id=chat_id, text='Please upload the announcement photo:')

    # Set a state to capture the next photo from the admin
    user_data[chat_id]['waiting_for_photo'] = True

async def send_admin_announcement_photo(chat_id, photo):
    """Send an announcement to the users."""
    conn = create_connection()
    cursor = conn.cursor()
    
    # Fetch user ID based on chat_id
    cursor.execute("SELECT id FROM users WHERE chat_id = ?", (chat_id,))
    user = cursor.fetchone()
    
    # Ensure user_id is a single value
    user_id = user[0] if user else None  # Extract the first element if user is found

    if user_id is not None:
        cursor.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,))
        result = cursor.fetchone()  # Fetch the result once

        if result is not None:
            is_admin = result[0]  # Access the first element if result is not None
        else:
            is_admin = 0  # Default to 0 if no result found

        if is_admin == 1:
            # Rate limiting check
            if not rate_limiter(chat_id):
                await bot.send_message(chat_id=chat_id, text='You are sending requests too quickly. Please wait a moment.')
                return
            
            cursor.execute("SELECT chat_id FROM users") 
            tosend_chat_ids = cursor.fetchall()
            
            for user_chat_id in tosend_chat_ids:
                try:
                    await bot.send_photo(chat_id=user_chat_id[0], photo=photo)
                except Exception as e:
                    logger.error(f"Failed to send message to {user_chat_id[0]}: {e}")
        else:
            await bot.send_message(chat_id=chat_id, text='You are not authorized to send announcements.')

    user_data[chat_id]['waiting_for_photo'] = False

async def handle_manager_on(chat_id):
    """Handle the manager on selection for the user."""
    if not rate_limiter(chat_id):  # Use chat_id or user_id for rate limiting
        await bot.send_message(chat_id=chat_id, text='You are sending requests too quickly. Please wait a moment.')
        return

    conn = create_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET manager_on_off = 1 WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()
    await bot.send_message(chat_id=chat_id, text='Manager has been turned on.')

async def handle_manager_off(chat_id):
    """Handle the manager off selection for the user."""
    conn = create_connection()
    cursor = conn.cursor()

    cursor.execute("UPDATE users SET manager_on_off = 0 WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()
    await bot.send_message(chat_id=chat_id, text='Manager has been turned off.')

async def handle_plant_selection(chat_id, plant_id, price):
    """Handle the selection of a plant for planting."""
    # Initialize user_data for the chat_id if it doesn't exist
    if chat_id not in user_data:
        user_data[chat_id] = {}

    # Store the selected plant information
    user_data[chat_id]['selected_plant'] = {'plant_id': plant_id, 'price': price}

    # Log the plant_id being fetched
    logger.info(f"Attempting to fetch plant with ID: {plant_id}")
    plant = next((plant for category in plant_data.values() for plant in category if plant['id'] == plant_id), None)

    if plant:
        # Calculate the total cost of the plant
        total_cost = plant['seed_purchase_price']
        conn = create_connection()
        cursor = conn.cursor()
        
        # Fetch user ID based on chat_id
        cursor.execute("SELECT id FROM users WHERE chat_id = ?", (chat_id,))
        user = cursor.fetchone()
        user_id = user[0] if user else None

        # Fetch the user's current upgrade level
        cursor.execute("SELECT upgrade_id FROM user_upgrades WHERE user_id = ?", (user_id,))
        user_upgrades = cursor.fetchall()  # Fetch all upgrades

        # Determine the highest upgrade level
        current_upgrade_level = 0  # Default to 0 if no upgrades
        if user_upgrades:
            # Extract upgrade IDs
            upgrade_ids = [upgrade[0] for upgrade in user_upgrades]

            # Fetch levels for all upgrade IDs, filtering by category 'plot'
            cursor.execute("SELECT level FROM upgrade_listings WHERE id IN ({}) AND category = ?".format(','.join('?' * len(upgrade_ids))), upgrade_ids + ['plot'])
            levels = cursor.fetchall()

            # Find the maximum level
            current_upgrade_level = max(level[0] for level in levels) if levels else 0

        # Get available slots based on the current upgrade level
        available_slots = get_available_plots_slots(current_upgrade_level)

        # Fetch crops for the user from the user_crops table
        cursor.execute("SELECT SUM(planted_quantity) FROM user_crops WHERE user_id = ? AND (status = 'planted' OR status = 'Ready for Harvest')", (user_id,))
        occupied_slots = cursor.fetchone()[0] or 0  # Default to 0 if no crops planted

        # Calculate max quantity based on balance
        cursor.execute("SELECT amount FROM cashflow_ledger WHERE user_id = ?", (user_id,))
        balance_response = cursor.fetchall()
        total_balance = sum(entry[0] for entry in balance_response) if balance_response else 0
        max_quantity_by_balance = total_balance // total_cost if total_cost > 0 else 0

        # Check if the user can plant more crops by balance
        if max_quantity_by_balance <= 0:
            await bot.send_message(chat_id=chat_id, text='You do not have enough balance to plant more crops.')
            return  # Exit the function if no balance
        
        # Check if the user can plant more crops by available slots
        if available_slots - occupied_slots <= 0:
            await bot.send_message(chat_id=chat_id, text='You do not have enough available slots to plant more crops.')
            return  # Exit the function if no slots are available

        # Calculate the actual maximum quantity the user can plant
        max_quantity = min(max_quantity_by_balance, available_slots - occupied_slots)

        # Construct the message with the plant emoji, name, seed purchase price, and harvesting time
        harvest_time = plant['harvest_time']  # Get the harvesting time
        await bot.send_message(chat_id=chat_id, text=f'You have selected {plant["emoji"]} {plant["name"]}.\nSeed Purchase Price: ${plant["seed_purchase_price"]}\nHarvesting Time: {harvest_time} mins.\nPlease enter the quantity you want to plant or click "Max" to plant the maximum quantity {max_quantity:,}.')

        # Create inline keyboard with Max option
        keyboard = [
            [telegram.InlineKeyboardButton("Max", callback_data=f"max_{plant_id}_{total_cost}")]
        ]
        reply_markup = telegram.InlineKeyboardMarkup(keyboard)
        await bot.send_message(chat_id=chat_id, text='Choose a quantity to plant:', reply_markup=reply_markup)      
    
    else:
        logger.error(f"Plant with ID {plant_id} not found in plant_data.")
        await bot.send_message(chat_id=chat_id, text='Error: Plant not found.')

async def handle_plot_upgrade(chat_id):
    """Handle the plot upgrade selection for the user."""
    conn = create_connection()
    cursor = conn.cursor()

    # Fetch user ID based on chat_id
    cursor.execute("SELECT id FROM users WHERE chat_id = ?", (chat_id,))
    user = cursor.fetchone()
    user_id = user[0] if user else None

    # Fetch all upgrade IDs for the user
    cursor.execute("SELECT upgrade_id FROM user_upgrades WHERE user_id = ?", (user_id,))
    user_upgrades = cursor.fetchall()  # Fetch all upgrades

    # Determine the highest upgrade level
    current_upgrade_level = 0  # Default to 0 if no upgrades
    if user_upgrades:
        # Extract upgrade IDs
        upgrade_ids = [upgrade[0] for upgrade in user_upgrades]

        # Fetch levels for all upgrade IDs, filtering by category 'plot'
        cursor.execute("SELECT level FROM upgrade_listings WHERE id IN ({}) AND category = ?".format(','.join('?' * len(upgrade_ids))), (upgrade_ids + ['plot']))
        levels = cursor.fetchall()

        # Find the maximum level
        current_upgrade_level = max(level[0] for level in levels) if levels else 0

    # Determine the next upgrade level
    next_upgrade_level = current_upgrade_level + 1

    # Fetch the next upgrade details, filtering by category 'plot'
    cursor.execute("SELECT * FROM upgrade_listings WHERE level = ? AND category = ?", (next_upgrade_level, 'plot'))
    next_upgrade = cursor.fetchone()

    if next_upgrade:
        level, description, price = next_upgrade[1], next_upgrade[3], next_upgrade[4]  # Unpack the details

        # Construct the message with upgrade details
        upgrade_message = (
            f'Current Upgrade Level: {current_upgrade_level}\n'
            f'Next Upgrade Level: {level}\n'
            f'Description: {description}\n'
            f'Cost: ${price:,}\n'
            'Do you want to proceed with the upgrade?'
        )

        # Create inline keyboard for confirmation
        keyboard = [
            [telegram.InlineKeyboardButton("✅", callback_data=f'confirm_upgrade_{next_upgrade[0]}')],
            [telegram.InlineKeyboardButton("❌", callback_data=f'show_game_menu')]
        ]
        reply_markup = telegram.InlineKeyboardMarkup(keyboard)

        await bot.send_message(chat_id=chat_id, text=upgrade_message, reply_markup=reply_markup)
    else:
        await bot.send_message(chat_id=chat_id, text='You have reached the maximum upgrade level for your plot.')

    conn.close()

async def handle_manager_upgrade(chat_id):
    """Handle the manager upgrade selection for the user."""
    conn = create_connection()
    cursor = conn.cursor()

    # Fetch user ID based on chat_id
    cursor.execute("SELECT id FROM users WHERE chat_id = ?", (chat_id,))
    user = cursor.fetchone()
    user_id = user[0] if user else None

    # Fetch all upgrade IDs for the user
    cursor.execute("SELECT upgrade_id FROM user_upgrades WHERE user_id = ?", (user_id,))
    user_upgrades = cursor.fetchall()  # Fetch all upgrades

    # Determine the highest upgrade level
    current_upgrade_level = 0  # Default to 0 if no upgrades
    if user_upgrades:
        # Extract upgrade IDs
        upgrade_ids = [upgrade[0] for upgrade in user_upgrades]

        # Fetch levels for all upgrade IDs, filtering by category 'plot'
        cursor.execute("SELECT level FROM upgrade_listings WHERE id IN ({}) AND category = ?".format(','.join('?' * len(upgrade_ids))), (upgrade_ids + ['manager']))
        levels = cursor.fetchall()

        # Find the maximum level
        current_upgrade_level = max(level[0] for level in levels) if levels else 0

    # Determine the next upgrade level
    next_upgrade_level = current_upgrade_level + 1

    # Fetch the next upgrade details, filtering by category 'manager'
    cursor.execute("SELECT * FROM upgrade_listings WHERE level = ? AND category = ?", (next_upgrade_level, 'manager'))
    next_upgrade = cursor.fetchone()

    if next_upgrade:
        level, description, price = next_upgrade[1], next_upgrade[3], next_upgrade[4]  # Unpack the details

        # Construct the message with upgrade details
        upgrade_message = (
            f'Current Upgrade Level: {current_upgrade_level}\n'
            f'Next Upgrade Level: {level}\n'
            f'Description: {description}\n'
            f'Cost: ${price:,}\n'
            'Do you want to proceed with the upgrade?'
        )

        # Create inline keyboard for confirmation
        keyboard = [
            [telegram.InlineKeyboardButton("✅", callback_data=f'confirm_upgrade_{next_upgrade[0]}')],
            [telegram.InlineKeyboardButton("❌", callback_data=f'show_game_menu')]
        ]
        reply_markup = telegram.InlineKeyboardMarkup(keyboard)

        await bot.send_message(chat_id=chat_id, text=upgrade_message, reply_markup=reply_markup)
    else:
        await bot.send_message(chat_id=chat_id, text='You have reached the maximum upgrade level for your manager.')

    conn.close()

async def handle_crops_upgrade(chat_id):
    """Handle the crops upgrade selection for the user."""
    conn = create_connection()
    cursor = conn.cursor()

    # Fetch user ID based on chat_id
    cursor.execute("SELECT id FROM users WHERE chat_id = ?", (chat_id,))
    user = cursor.fetchone()
    user_id = user[0] if user else None

    # Fetch upgrades that is in the crops category and merge with the plants_listing table
    cursor.execute("SELECT upgrade_listings.id, upgrade_listings.description, upgrade_listings.price, plants_listing.name, plants_listing.category, plants_listing.emoji FROM upgrade_listings LEFT JOIN plants_listing ON upgrade_listings.id = plants_listing.upgrade_id WHERE upgrade_listings.category = 'crops'")
    crops_upgrades = cursor.fetchall()

    # Fetch all upgrade IDs for the user
    cursor.execute("SELECT upgrade_id FROM user_upgrades WHERE user_id = ?", (user_id,))
    user_upgrades = cursor.fetchall()  # Fetch all upgrades

    # Filter the crops_upgrades to only include the ones that are in the user_upgrades
    filtered_crops_upgrades = [upgrade for upgrade in crops_upgrades if upgrade[0] in [upgrade_id[0] for upgrade_id in user_upgrades]]

    # Filter the crops_upgrades to only include the ones that are not in the user_upgrades
    locked_crops_upgrades = [upgrade for upgrade in crops_upgrades if upgrade[0] not in [upgrade_id[0] for upgrade_id in user_upgrades]]

    # Message to user
    if filtered_crops_upgrades:
        if locked_crops_upgrades:
            upgrades_message = 'You have the following crops upgrades unlocked:\n' + '\n'.join([f'{upgrade[5]} {upgrade[3]}' for upgrade in filtered_crops_upgrades]) + '\n\n' + 'Please select the crops upgrade you want to purchase:'
        else:
            upgrades_message = 'You have the following crops upgrades:\n' + '\n'.join([f'{upgrade[5]} {upgrade[3]}' for upgrade in filtered_crops_upgrades]) + '\n\n' + 'You have no crops upgrades to be unlocked.'
    else:
        upgrades_message = 'You have no crops upgrades unlocked.\n\n' + 'Please select the crops upgrade you want to purchase:'

    # Please select the crops upgrade you want to purchase
    keyboard = [
        [telegram.InlineKeyboardButton(f'{upgrade[5]} {upgrade[3]} ${upgrade[2]:,} - {upgrade[1]}', callback_data=f'confirm_upgrade_{upgrade[0]}')] for upgrade in locked_crops_upgrades
    ]
    reply_markup = telegram.InlineKeyboardMarkup(keyboard)
    await bot.send_message(chat_id=chat_id, text=upgrades_message, reply_markup=reply_markup)

    conn.close()

# Handle the confirmation of the upgrade
async def handle_upgrade_confirmation(chat_id, upgrade_id):
    """Handle the confirmation of the plot upgrade."""
    await bot.send_message(chat_id=chat_id, text='Please wait while we confirm your upgrade...')  # Optional: Inform the user
    conn = create_connection()
    cursor = conn.cursor()

    # Fetch user ID based on chat_id
    cursor.execute("SELECT id FROM users WHERE chat_id = ?", (chat_id,))
    user = cursor.fetchone()
    user_id = user[0] if user else None

    # Fetch the upgrade details
    cursor.execute("SELECT * FROM upgrade_listings WHERE id = ?", (upgrade_id,))
    upgrade = cursor.fetchone()

    if upgrade:
        level, category, description, price = upgrade[1], upgrade[2], upgrade[3], upgrade[4]  # Unpack the details

        # Check if the user has enough balance
        cursor.execute("SELECT amount FROM cashflow_ledger WHERE user_id = ?", (user_id,))
        balance_response = cursor.fetchall()
        total_balance = sum(entry[0] for entry in balance_response) if balance_response else 0

        if total_balance >= price:
            # Deduct the upgrade price from the user's balance
            transaction_date = datetime.now().isoformat()
            cursor.execute("INSERT INTO cashflow_ledger (user_id, amount, description, transaction_date) VALUES (?, ?, ?, ?)", 
                           (user_id, -price, f'Purchased {category} upgrade to level {level}', transaction_date))

            # Insert the upgrade into user_upgrades
            cursor.execute("INSERT INTO user_upgrades (user_id, upgrade_id) VALUES (?, ?)", (user_id, upgrade[0]))

            conn.commit()  # Commit the transaction

            await bot.send_message(chat_id=chat_id, text=f'Congratulations! You have successfully upgraded your {category} to level {level} - {description}!')

            # Send a small-sized picture to the user
            if category == 'plot':
                photo_path = 'images/plot_upgrade.webp'  # Replace with the path to your image file
            elif category == 'manager':
                photo_path = 'images/manager_upgrade.webp'  # Replace with the path to your image file
            elif category == 'crops':
                photo_path = 'images/crops_upgrade.jpg'  # Replace with the path to your image file
            await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption='Upgrade successful! 🎉')  # Optional caption

        else:
            await bot.send_message(chat_id=chat_id, text='You do not have enough balance to purchase this upgrade.')
    else:
        await bot.send_message(chat_id=chat_id, text='Error: Upgrade not found.')

    conn.close()

async def harvest_crops(chat_id):
    """Handle the harvesting of crops for the user."""
    
    # First, check the planting status
    await check_auto_planting_status(chat_id)  # Show the current status of the crops

    conn = create_connection()
    cursor = conn.cursor()

    # Fetch user ID from the database
    cursor.execute("SELECT id, manager_on_off FROM users WHERE chat_id = ?", (chat_id,))
    user = cursor.fetchone()
    user_id, manager_on_off = user[0], user[1] if user else (None, None)

    # Fetch user balance
    cursor.execute("SELECT amount FROM cashflow_ledger WHERE user_id = ?", (user_id,))
    balance_response = cursor.fetchall()
    total_balance = sum(entry[0] for entry in balance_response) if balance_response else 0

    if manager_on_off == 0:
        logger.info(f"User {chat_id} is attempting to harvest crops.")

    if user_id:
        # Fetch crops for the user from the user_crops table
        cursor.execute("SELECT * FROM user_crops WHERE user_id = ? AND status = 'Ready for Harvest'", (user_id,))
        crops_response = cursor.fetchall()
        
        if crops_response:
            for crop in crops_response:
                # Fetch plant details using the item_id
                cursor.execute("SELECT * FROM plants_listing WHERE id = ?", (crop[2],))  # Assuming item_id is the third column
                plant = cursor.fetchone()
                
                if plant:
                    # Calculate the harvested quantity
                    min_ratio = plant[4]  # Min harvesting ratio
                    max_ratio = plant[5]  # Max harvesting ratio
                    selling_price = plant[8]  # Selling price

                    # Get a random factor for harvest event
                    harvest_event = random.choices(
                        ['extreme_disaster', 'mild_disaster', 'minimum_harvest', 'normal_season', 'good_season'],
                        weights=[1, 4, 15, 60, 20],
                        k=1
                    )[0]

                    # Determine the harvest quantity based on the event
                    if harvest_event == 'extreme_disaster':
                        if total_balance >= 1000000000:
                            harvested_quantity = 0  # All crops destroyed
                            photo_path = 'images/extreme_disaster.jpeg'
                            await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption='🌪️ Extreme disaster! All your crops have been destroyed!')
                        else:
                            harvested_quantity = crop[5] * min_ratio  # Minimum harvest rate
                            photo_path = 'images/minimum_harvest.jpeg'
                            await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption='🌾 Low season! Your crops have been grown at a minimum rate.')
                    elif harvest_event == 'mild_disaster':
                        if total_balance >= 1000000000:
                            harvested_quantity = int(crop[5] * min_ratio * 0.5)  # Half of the crops destroyed
                            photo_path = 'images/mild_disaster.jpeg'
                            await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption='🌪️ Mild disaster! Half of your crops have been destroyed!')
                        else:
                            harvested_quantity = crop[5] * min_ratio  # Minimum harvest rate
                            photo_path = 'images/minimum_harvest.jpeg'
                            await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption='🌾 Low season! Your crops have been grown at a minimum rate.')
                    elif harvest_event == 'minimum_harvest':
                        harvested_quantity = crop[5] * min_ratio  # Minimum harvest rate
                        photo_path = 'images/minimum_harvest.jpeg'
                        await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption='🌾 Low season! Your crops have been grown at a minimum rate.')
                    elif harvest_event == 'normal_season':
                        harvested_quantity = crop[5] * ((min_ratio + max_ratio) / 2)  # Average harvest rate
                        photo_path = 'images/normal_season.jpeg'
                        await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption='🌾 Normal season! Your crops have been grown at a normal rate.')
                    elif harvest_event == 'good_season':
                        harvested_quantity = crop[5] * max_ratio  # Maximum harvest rate
                        photo_path = 'images/good_season.jpeg'
                        await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption='🌾 Good season! Your crops have been grown at a good rate.')
                    

                    harvested_quantity_rounded = int(harvested_quantity) + (1 if harvested_quantity % 1 > 0 else 0)  # Round up to the nearest whole number

                    # Calculate cash flow
                    cashflow_amount = harvested_quantity_rounded * selling_price  # Calculate cashflow

                    # Insert into cashflow ledger
                    if harvested_quantity_rounded > 0:
                        local_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')  # Get local time for transaction date
                        harvested_quantity_rounded_formatted = f"{harvested_quantity_rounded:,}"  # Format for display
                        cursor.execute("INSERT INTO cashflow_ledger (user_id, amount, description, transaction_date) VALUES (?, ?, ?, ?)", 
                                       (user_id, cashflow_amount, f'Harvested {harvested_quantity_rounded_formatted} {plant[1]}(s).', local_time))

                    # Update the crop status to "Harvested"
                    cursor.execute("UPDATE user_crops SET status = 'Harvested' WHERE id = ?", (crop[0],))  # Assuming crop ID is the first column

                    # Manager user message
                    if manager_on_off == 1 and harvested_quantity_rounded > 0:
                        photo_path = 'images/manager_harvest.webp'  # Replace with the path to your image file
                        await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption=f'Manager has directed to harvest {harvested_quantity_rounded} {plant[1]}(s) and sell them for ${cashflow_amount:,}!')  # Optional caption
                        
                        manager_payroll = int(cashflow_amount * 0.08)
                        cursor.execute("INSERT INTO cashflow_ledger (user_id, amount, description, transaction_date) VALUES (?, ?, ?, ?)", 
                                       (user_id, -manager_payroll, f'Manager payroll for harvesting {harvested_quantity_rounded} {plant[1]}(s).', local_time))
                        photo_path = 'images/manager_payroll.webp'  # Replace with the path to your image file
                        await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption=f'Manager payroll of ${manager_payroll:,} has been deducted from your account.')  # Optional caption
                    
                    # Normal user message
                    elif harvested_quantity_rounded > 0:
                        await bot.send_message(chat_id=chat_id, text=f'You have successfully harvested {harvested_quantity_rounded} {plant[1]}(s) for ${cashflow_amount:,}!')
                        photo_path = 'images/harvested.webp'  # Replace with the path to your image file
                        await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption='Happy harvesting! 🌾')  # Optional caption
                    
                else:
                    await bot.send_message(chat_id=chat_id, text='Error: Plant not found.')
        else:
            if manager_on_off == 0:
                await bot.send_message(chat_id=chat_id, text='You have no crops ready for harvest.')
    else:
        await bot.send_message(chat_id=chat_id, text='User not found.')

    conn.commit()
    conn.close()

async def check_planting_status(chat_id):
    """Check the planting status of the user's crops and update if ready for harvest."""
    logger.info(f"Checking planting status for user {chat_id}.")
    
    conn = create_connection()  # Create a connection to the SQLite database
    cursor = conn.cursor()

    # Fetch user ID from the database
    cursor.execute("SELECT id FROM users WHERE chat_id = ?", (chat_id,))
    user = cursor.fetchone()
    user_id = user[0] if user else None

    if user_id:
        # Fetch crops for the user from the user_crops table
        cursor.execute("SELECT * FROM user_crops WHERE user_id = ?", (user_id,))
        crops_response = cursor.fetchall()
        
        if crops_response:
            crops_status = []
            current_time = datetime.now()  # Get current local time

            # Get the user's current upgrade level
            cursor.execute("SELECT upgrade_id FROM user_upgrades WHERE user_id = ?", (user_id,))
            user_upgrades = cursor.fetchall()  # Fetch all upgrades

            # Determine the highest upgrade level
            current_upgrade_level = 0  # Default to 0 if no upgrades
            if user_upgrades:
                # Extract upgrade IDs
                upgrade_ids = [upgrade[0] for upgrade in user_upgrades]

                # Fetch levels for all upgrade IDs, filtering by category 'plot'
                cursor.execute("SELECT level FROM upgrade_listings WHERE id IN ({}) AND category = ?".format(','.join('?' * len(upgrade_ids))), upgrade_ids + ['plot'])
                levels = cursor.fetchall()

                # Find the maximum level
                current_upgrade_level = max(level[0] for level in levels) if levels else 0

            # Get available slots based on the current upgrade level
            available_slots = get_available_plots_slots(current_upgrade_level)

            # Calculate occupied slots
            occupied_slots = sum(crop[5] for crop in crops_response if crop[4] != 'Harvested')

            for crop in crops_response:
                # Skip crops that are already harvested
                if crop[4] == 'Harvested':  # Assuming status is the fifth column
                    continue

                # Fetch plant details using the item_id
                cursor.execute("SELECT * FROM plants_listing WHERE id = ?", (crop[2],))  # Assuming item_id is the third column
                plant = cursor.fetchone()

                if plant:
                    # Convert planted_at to a local datetime
                    planted_at = datetime.fromisoformat(crop[3].replace('Z', ''))  # Assuming planted_at is the fourth column
                    # Calculate harvest ready time
                    harvest_time_minutes = plant[7]  # Assuming harvest_time is the seventh column
                    harvest_ready_time = planted_at + timedelta(minutes=harvest_time_minutes)  # Calculate harvest ready time

                    # Initialize status variable
                    status = ""

                    # Check if the crop is ready for harvest
                    if current_time >= harvest_ready_time:
                        # Only update status if it is not already harvested
                        if crop[4] == 'planted':  # Assuming status is the fifth column
                            # Update the crop status to "Ready for Harvest"
                            cursor.execute("UPDATE user_crops SET status = ? WHERE id = ?", ('Ready for Harvest', crop[0]))  # Assuming crop ID is the first column
                            status = "Ready for Harvest"
                        if crop[4] == 'Ready for Harvest':  # Assuming status is the fifth column
                            status = "Ready for Harvest"
                    else:
                        # Calculate remaining time until harvest
                        remaining_time = harvest_ready_time - current_time
                        remaining_minutes = int(remaining_time.total_seconds() // 60)  # Convert to minutes
                        status = f"Planted - {remaining_minutes} mins left"

                    # Ensure crop quantity is treated as an integer
                    quantity = int(crop[5])  # Assuming crop[5] is the quantity
                    crops_status.append(f"{plant[3]} {plant[1]} - {status} - Qty: {quantity:,}")  # Assuming emoji is the third column and name is the second
                else:
                    crops_status.append(f"Crop ID: {crop[2]} - Status: {crop[4]} - Quantity: {crop[5]} (Plant details not found)")  # Assuming item_id is the third column

            await bot.send_message(chat_id=chat_id, text=f'Your planting status:\n' + '\n'.join(crops_status) + f'\nYou have {occupied_slots:,} / {available_slots:,} plots occupied.')
        else:
            await bot.send_message(chat_id=chat_id, text='You have not planted any crops yet.')
    else:
        await bot.send_message(chat_id=chat_id, text='User not found.')

    conn.commit()  # Commit any changes made
    conn.close()  # Close the database connection

async def check_auto_planting_status(chat_id):
    """Check the auto planting status of the user's crops and update if ready for harvest."""

    conn = create_connection()  # Create a connection to the SQLite database
    cursor = conn.cursor()

    # Fetch user ID from the database
    cursor.execute("SELECT id FROM users WHERE chat_id = ?", (chat_id,))
    user = cursor.fetchone()
    user_id = user[0] if user else None

    if user_id:
        # Fetch crops for the user from the user_crops table
        cursor.execute("SELECT * FROM user_crops WHERE user_id = ?", (user_id,))
        crops_response = cursor.fetchall()
        
        if crops_response:
            crops_status = []
            current_time = datetime.now()  # Get current local time

            # Get the user's current upgrade level
            cursor.execute("SELECT upgrade_id FROM user_upgrades WHERE user_id = ?", (user_id,))
            user_upgrades = cursor.fetchall()  # Fetch all upgrades

            # Determine the highest upgrade level
            current_upgrade_level = 0  # Default to 0 if no upgrades
            if user_upgrades:
                # Extract upgrade IDs
                upgrade_ids = [upgrade[0] for upgrade in user_upgrades]

                # Fetch levels for all upgrade IDs, filtering by category 'plot'
                cursor.execute("SELECT level FROM upgrade_listings WHERE id IN ({}) AND category = ?".format(','.join('?' * len(upgrade_ids))), upgrade_ids + ['plot'])
                levels = cursor.fetchall()

                # Find the maximum level
                current_upgrade_level = max(level[0] for level in levels) if levels else 0

            for crop in crops_response:
                # Skip crops that are already harvested
                if crop[4] == 'Harvested':  # Assuming status is the fifth column
                    continue

                # Fetch plant details using the item_id
                cursor.execute("SELECT * FROM plants_listing WHERE id = ?", (crop[2],))  # Assuming item_id is the third column
                plant = cursor.fetchone()

                if plant:
                    # Convert planted_at to a local datetime
                    planted_at = datetime.fromisoformat(crop[3].replace('Z', ''))  # Assuming planted_at is the fourth column
                    # Calculate harvest ready time
                    harvest_time_minutes = plant[7]  # Assuming harvest_time is the seventh column
                    harvest_ready_time = planted_at + timedelta(minutes=harvest_time_minutes)  # Calculate harvest ready time

                    # Initialize status variable
                    status = ""

                    # Check if the crop is ready for harvest
                    if current_time >= harvest_ready_time:
                        # Only update status if it is not already harvested
                        if crop[4] == 'planted':  # Assuming status is the fifth column
                            # Update the crop status to "Ready for Harvest"
                            cursor.execute("UPDATE user_crops SET status = ? WHERE id = ?", ('Ready for Harvest', crop[0]))  # Assuming crop ID is the first column
                            status = "Ready for Harvest"
                        if crop[4] == 'Ready for Harvest':  # Assuming status is the fifth column
                            status = "Ready for Harvest"
                    else:
                        # Calculate remaining time until harvest
                        remaining_time = harvest_ready_time - current_time
                        remaining_minutes = int(remaining_time.total_seconds() // 60)  # Convert to minutes
                        status = f"Planted - {remaining_minutes} mins left"

                    # Ensure crop quantity is treated as an integer
                    quantity = int(crop[5])  # Assuming crop[5] is the quantity
                    crops_status.append(f"{plant[3]} {plant[1]} - {status} - Qty: {quantity:,}")  # Assuming emoji is the third column and name is the second
                else:
                    crops_status.append(f"Crop ID: {crop[2]} - Status: {crop[4]} - Quantity: {crop[5]} (Plant details not found)")  # Assuming item_id is the third column

    else:
        await bot.send_message(chat_id=chat_id, text='User not found.')

    conn.commit()  # Commit any changes made
    conn.close()  # Close the database connection


async def check_ready_for_harvest():
    """Check for crops that are ready for harvest and notify users."""
    while True:
        await asyncio.sleep(60)  # Check every 60 seconds

        try:
            conn = create_connection()
            cursor = conn.cursor()

            # Get current time
            current_time = datetime.now()

            # Fetch crops that are ready for harvest
            cursor.execute("""SELECT user_id, id, planted_at, item_id FROM user_crops WHERE status = 'planted'""")
            crops_response = cursor.fetchall()

            for crop in crops_response:
                user_id = crop[0]
                crop_id = crop[1]
                planted_at = datetime.fromisoformat(crop[2].replace('Z', ''))  # Adjust if necessary
                item_id = crop[3]

                # Fetch plant details to get harvest time
                cursor.execute("SELECT harvest_time FROM plants_listing WHERE id = ?", (item_id,))
                plant = cursor.fetchone()

                if plant:
                    harvest_time_minutes = plant[0]
                    harvest_ready_time = planted_at + timedelta(minutes=harvest_time_minutes)

                    # Check if the crop is ready for harvest
                    if current_time >= harvest_ready_time:
                        # Update crop status to "Ready for Harvest"
                        cursor.execute("UPDATE user_crops SET status = ? WHERE id = ?", ('Ready for Harvest', crop_id))

                        # Fetch the chat_id from the users table
                        cursor.execute("SELECT chat_id, username FROM users WHERE id = ?", (user_id,))
                        user = cursor.fetchone()
                        if user:
                            chat_id = user[0]
                            users_to_notify.add(chat_id)  # Add chat_id to notify list
                            username = user[1]
                            logger.info(f"User {username} with chat_id {chat_id} has crops ready for harvest.")
                        else:
                            logger.error(f"No chat_id found for user_id {user_id}")

            conn.commit()
        except Exception as e:
            logger.error(f"Error checking for ready crops: {e}")
        finally:
            conn.close()

        # Notify users
        for chat_id in users_to_notify:
            try:
                photo_path = 'images/ready_for_harvest.jpg'  # Replace with the path to your image file
                await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption='Your crops are ready for harvest! 🌾')     
            except telegram.error.BadRequest as e:
                logger.error(f"Failed to send message to chat_id {chat_id}: {e}")  # Log the error
            except Exception as e:
                logger.error(f"An unexpected error occurred: {e}")  # Log any other unexpected errors

        # Clear the notify list for the next check
        users_to_notify.clear()

        await handle_manager_auto_harvest()      

async def handle_manager_auto_harvest():
    """Handle the manager auto harvest for the user."""
    conn = create_connection()
    cursor = conn.cursor()

    # Fetch user ID based on chat_id
    cursor.execute("SELECT chat_id, manager_on_off FROM users")
    users = cursor.fetchall()

    for user in users:
        chat_id = user[0]
        manager_on_off = user[1]

        if manager_on_off == 1:
            await harvest_crops(chat_id)
    
    conn.commit()
    conn.close()

    await handle_manager_auto_planting()

async def handle_manager_auto_planting():
    """Handle the manager auto planting for the user."""
    conn = create_connection()
    cursor = conn.cursor()

    # Fetch user ID based on chat_id
    cursor.execute("SELECT id, chat_id, manager_on_off FROM users")
    users = cursor.fetchall()

    for user in users:
        user_id = user[0]
        chat_id = user[1]
        manager_on_off = user[2]

        if manager_on_off == 1:
            # Handle the max planting callback
            cursor.execute("SELECT item_id FROM user_auto_planting WHERE user_id = ?", (user_id,))
            item_id = cursor.fetchone()
            plant_id = item_id[0]

            if plant_id:
                plant_id = int(plant_id)  # Ensure plant_id is an integer

                # Fetch the plant details for the description
                cursor.execute("SELECT seed_purchase_price, emoji, name FROM plants_listing WHERE id = ?", (plant_id,))
                price, emoji, name = cursor.fetchone()

                # Fetch cashflow entries for the user
                cursor.execute("SELECT amount FROM cashflow_ledger WHERE user_id = ?", (user_id,))
                balance_response = cursor.fetchall()

                # Calculate total balance
                total_balance = sum(entry[0] for entry in balance_response) if balance_response else 0

                # Calculate max quantity
                max_affordable_quantity = int(total_balance // price) if price > 0 else 0

                # Fetch the user's current upgrade level
                cursor.execute("SELECT upgrade_id FROM user_upgrades WHERE user_id = ?", (user_id,))
                user_upgrades = cursor.fetchall()  # Fetch all upgrades

                # Determine the highest upgrade level
                current_upgrade_level = 0  # Default to 0 if no upgrades
                if user_upgrades:
                    # Extract upgrade IDs
                    upgrade_ids = [upgrade[0] for upgrade in user_upgrades]

                    # Fetch levels for all upgrade IDs, filtering by category 'plot'
                    cursor.execute("SELECT level FROM upgrade_listings WHERE id IN ({}) AND category = ?".format(','.join('?' * len(upgrade_ids))), upgrade_ids + ['plot'])
                    levels = cursor.fetchall()

                    # Find the maximum level
                    current_upgrade_level = max(level[0] for level in levels) if levels else 0

                    # Get available slots based on the current upgrade level
                    available_slots = get_available_plots_slots(current_upgrade_level)

                    # Fetch crops for the user from the user_crops table
                    cursor.execute("SELECT SUM(planted_quantity) FROM user_crops WHERE user_id = ? AND (status = 'planted' OR status = 'Ready for Harvest')", (user_id,))
                    occupied_slots = cursor.fetchone()[0] or 0  # Default to 0 if no crops planted

                    # Ensure max quantity does not exceed available slots   
                    max_quantity = min(max_affordable_quantity, available_slots - occupied_slots)

                    if max_quantity > 0:
                        # Deduct cashflow
                        transaction_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')  # Format as 'YYYY-MM-DD HH:MM:SS'

                        total_cost = max_quantity * price
                            
                        description = f'Planted {max_quantity} {emoji} {name}(s).'  # Use plant name and emoji

                        cursor.execute("INSERT INTO cashflow_ledger (user_id, amount, description, transaction_date) VALUES (?, ?, ?, ?)", 
                                       (user_id, -total_cost, description, transaction_date))

                        # Insert into user_crops
                        cursor.execute("INSERT INTO user_crops (user_id, item_id, planted_at, status, planted_quantity) VALUES (?, ?, ?, ?, ?)",
                                       (user_id, plant_id, transaction_date, 'planted', max_quantity))

                        # Commit the transaction
                        conn.commit()  # Ensure changes are saved to the database

                        # Send a small-sized picture to the user
                        photo_path = 'images/manager_planting.webp'  # Replace with the path to your image file
                        await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption=f'Farm Manager has directed to plant {max_quantity:,} {name}(s)!')  # Optional caption

    conn.commit()
    conn.close()

async def handle_auto_planting(chat_id):
    """Handle the auto planting selection for the user."""
    conn = create_connection()
    cursor = conn.cursor()
    
    # Fetch user ID based on chat_id
    cursor.execute("SELECT id FROM users WHERE chat_id = ?", (chat_id,))
    user = cursor.fetchone()  # Fetch the result once

    if user is None:
        await bot.send_message(chat_id=chat_id, text='User not found. Please register first.')
        conn.close()
        return  # Exit the function if user is not found

    user_id = user[0]  # Now it's safe to access user[0]

    # Fetch item_id for the user's auto planting
    cursor.execute("SELECT item_id FROM user_auto_planting WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()  # Fetch the result once

    if result is None:
        item_id = None  # No item_id found
    else:
        item_id = result[0]  # Now it's safe to access result[0]

    if item_id:
        cursor.execute("SELECT emoji, name, seed_purchase_price, selling_price, harvest_time FROM plants_listing WHERE id = ?", (item_id,))
        plant_data = cursor.fetchone()  # Fetch plant data

        if plant_data is None:
            await bot.send_message(chat_id=chat_id, text='Error: Plant not found.')
            conn.close()
            return  # Exit if plant data is not found

        emoji, name, seed_purchase_price, selling_price, harvest_time = plant_data

        # Construct the message with upgrade details
        current_auto_planting_message = (
            f'Current Auto Planting: {emoji} {name}\n'
            f'Seed Purchase Price: ${seed_purchase_price:,}\n'
            f'Selling Price: ${selling_price:,}\n'
            f'Harvest Time: {harvest_time} mins\n'
            'Do you want to change your auto planting seeds?'
        )

        # Create inline keyboard for confirmation
        keyboard = [
            [telegram.InlineKeyboardButton("✅", callback_data='change_auto_planting')],
            [telegram.InlineKeyboardButton("❌", callback_data='show_game_menu')]
        ]
        reply_markup = telegram.InlineKeyboardMarkup(keyboard)

        await bot.send_message(chat_id=chat_id, text=current_auto_planting_message, reply_markup=reply_markup)
    else:
        # Construct the message with upgrade details
        current_auto_planting_message = (
            'You have not selected any auto planting seeds yet.\n'
            'Do you want to change your auto planting seeds?'
        )

        # Create inline keyboard for confirmation
        keyboard = [
            [telegram.InlineKeyboardButton("✅", callback_data='change_auto_planting')],
            [telegram.InlineKeyboardButton("❌", callback_data='show_game_menu')]
        ]
        reply_markup = telegram.InlineKeyboardMarkup(keyboard)

        await bot.send_message(chat_id=chat_id, text=current_auto_planting_message, reply_markup=reply_markup)

    conn.close()

async def handle_change_auto_planting_category(chat_id):
    """Handle the change auto planting category selection for the user."""
    keyboard = [
        [telegram.InlineKeyboardButton("🍉 Fruits", callback_data='auto_planting_Fruits')],
        [telegram.InlineKeyboardButton("🥬 Vegetables", callback_data='auto_planting_Vegetables')],
        [telegram.InlineKeyboardButton("🌾 Grains", callback_data='auto_planting_Grain')]
    ]
    reply_markup = telegram.InlineKeyboardMarkup(keyboard)

    await bot.send_message(chat_id=chat_id, text='Choose a category to auto plant:', reply_markup=reply_markup)

async def show_auto_planting_plants(chat_id, category):
    """Display specific plants based on the selected category."""
    if category not in plant_data:
        await bot.send_message(chat_id=chat_id, text='No plants available in this category.')
        return

    conn = create_connection()
    cursor = conn.cursor()

    # Fetch user ID based on chat_id
    cursor.execute("SELECT id FROM users WHERE chat_id = ?", (chat_id,))
    user = cursor.fetchone()
    user_id = user[0] if user else None

    # Fetch all upgrade IDs for the user
    cursor.execute("SELECT upgrade_id FROM user_upgrades WHERE user_id = ?", (user_id,))
    user_upgrades = cursor.fetchall()  # Fetch all upgrades

    # Filter the plants in the category to only include the ones with NULL upgrade_id or the plants with upgrade_id that is in the user_upgrades
    filtered_plants = [plant for plant in plant_data[category] if plant['upgrade_id'] is None or plant['upgrade_id'] in [upgrade_id[0] for upgrade_id in user_upgrades]]
    
    keyboard = [
        [telegram.InlineKeyboardButton(
            f"{plant['emoji']} {plant['name']} - ⬇${plant['seed_purchase_price']}/⬆${plant['selling_price']} - {plant['harvest_time']} min",
            callback_data=f"auto_plant_{plant['id']}"
        )]
        for plant in filtered_plants
    ]
    reply_markup = telegram.InlineKeyboardMarkup(keyboard)

    await bot.send_message(chat_id=chat_id, text=f"Choose a plant to auto plant from {category.capitalize()}:", reply_markup=reply_markup)

async def handle_auto_planting_plant_selection(chat_id, callback_data):
    """Handle the auto planting plant selection for the user."""
    conn = create_connection()
    cursor = conn.cursor()
    plant_id = callback_data.split('_')[2]
    cursor.execute("SELECT name FROM plants_listing WHERE id = ?", (plant_id,))
    plant_name = cursor.fetchone()[0]

    #register the plant selection
    conn = create_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE chat_id = ?", (chat_id,))
    user_id = cursor.fetchone()[0]

    # Check if the existing entry is already in the user_auto_planting table
    cursor.execute("SELECT id FROM user_auto_planting WHERE user_id = ?", (user_id,))
    existing_entry = cursor.fetchone()

    if existing_entry:
        cursor.execute("UPDATE user_auto_planting SET item_id = ? WHERE id = ?", (plant_id, existing_entry[0],))
        conn.commit()
        await bot.send_message(chat_id=chat_id, text='You have successfully changed your auto planting seeds.')
    
    else:
        cursor.execute("INSERT INTO user_auto_planting (user_id, item_id) VALUES (?, ?)", (user_id, plant_id))
        conn.commit()
        await bot.send_message(chat_id=chat_id, text=f'You have successfully selected {plant_name} to auto plant.')

    conn.close()

async def handle_message(chat_id, text, update, callback_data):
    # Your existing message handling logic goes here
    # For example, checking commands, processing user input, etc.
    # Initialize user_data for the chat_id if it doesn't exist
        if chat_id not in user_data:
            user_data[chat_id] = {}

        if chat_id in user_data:
            # Check if the user is waiting for an announcement message
            if user_data[chat_id].get('waiting_for_announcement'):
                # Call the function to send the announcement
                await send_admin_announcement_text(chat_id, text)

            # Check if the user is waiting for an announcement photo
            if user_data[chat_id].get('waiting_for_photo'):
                # Call the function to send the announcement photo
                photo_file_id = update['message'].get('photo', [])
                if photo_file_id:
                    # Get the file ID of the largest photo
                    file_id = photo_file_id[-1]['file_id']
                    await send_admin_announcement_photo(chat_id, file_id)
                    user_data[chat_id]['waiting_for_photo'] = False
                else:
                    await bot.send_message(chat_id=chat_id, text='No photo received. Please try again.')

        # Register the user only if the command is /home
        if text == '/home':
            await register_user(chat_id, update)  # Register the user
            await show_game_menu(chat_id)  # Show the game menu

        # Handle commands
        elif text == '/plant':
            await show_planting_menu(chat_id)  # Show planting menu

        elif text == '/status':
            await check_planting_status(chat_id)  # Check planting status

        elif text == '/harvest':
            await harvest_crops(chat_id)  # Call the harvest function

        elif text == '/upgrades':
            await show_upgrades_menu(chat_id)  # Show upgrades menu
        
        elif text == '/manager':
            await show_manager_menu(chat_id)

        elif text == '/admin':
            await show_admin_menu(chat_id)

        elif text == '/rankings':
            await show_rankings(chat_id)

        # Handle quantity input after plant selection
        elif 'selected_plant' in user_data[chat_id] and callback_data is None:
            # Rate limiting check
            if not rate_limiter(chat_id):
                await bot.send_message(chat_id=chat_id, text='You are sending requests too quickly. Please wait a moment.')
                return JSONResponse(content={"status": "ok"})  # Early return

            try:
                selected_plant = user_data[chat_id]['selected_plant']

                quantity = 0  # Default value

                # Check if the text is a valid quantity
                if text.isdigit():
                    quantity = int(text)
                
                total_cost = quantity * selected_plant['price']

                conn = create_connection()  # Create a connection to the SQLite database
                cursor = conn.cursor()

                # Verify wallet balance
                cursor.execute("SELECT id FROM users WHERE chat_id = ?", (chat_id,))
                user = cursor.fetchone()
                user_id = user[0] if user else None

                # Fetch cashflow entries for the user
                cursor.execute("SELECT amount FROM cashflow_ledger WHERE user_id = ?", (user_id,))
                balance_response = cursor.fetchall()
                total_balance = sum(entry[0] for entry in balance_response) if balance_response else 0

                # Fetch the user's current upgrade level
                cursor.execute("SELECT upgrade_id FROM user_upgrades WHERE user_id = ?", (user_id,))
                user_upgrades = cursor.fetchall()  # Fetch all upgrades

                # Determine the highest upgrade level   
                current_upgrade_level = 0  # Default to 0 if no upgrades
                if user_upgrades:
                    # Extract upgrade IDs
                    upgrade_ids = [upgrade[0] for upgrade in user_upgrades]

                    # Fetch levels for all upgrade IDs, filtering by category 'plot'
                    cursor.execute("SELECT level FROM upgrade_listings WHERE id IN ({}) AND category = ?".format(','.join('?' * len(upgrade_ids))), upgrade_ids + ['plot'])
                    levels = cursor.fetchall()

                    # Find the maximum level
                    current_upgrade_level = max(level[0] for level in levels) if levels else 0

                # Get available slots based on the current upgrade level
                available_slots = get_available_plots_slots(current_upgrade_level)

                # Fetch crops for the user from the user_crops table
                cursor.execute("SELECT SUM(planted_quantity) FROM user_crops WHERE user_id = ? AND (status = 'planted' OR status = 'Ready for Harvest')", (user_id,))
                occupied_slots = cursor.fetchone()[0] or 0  # Default to 0 if no crops planted

                # Check if the quantity exceeds available slots
                if quantity > (available_slots - occupied_slots):
                    await bot.send_message(chat_id=chat_id, text='You cannot plant more than the available slots.')
                    return

                if total_balance >= total_cost:
                    # Deduct cashflow
                    transaction_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')  # Format as 'YYYY-MM-DD HH:MM:SS'
                    
                    # Fetch the plant details for the description
                    plant = next((plant for category in plant_data.values() for plant in category if plant['id'] == selected_plant['plant_id']), None)
                    
                    if plant:
                        description = f'Planted {quantity} {plant["emoji"]} {plant["name"]}(s).'  # Use plant name and emoji
                    else:
                        description = f'Planted {quantity} plants with ID {selected_plant["plant_id"]}.'  # Fallback description

                    cursor.execute("INSERT INTO cashflow_ledger (user_id, amount, description, transaction_date) VALUES (?, ?, ?, ?)", 
                                   (user_id, -total_cost, description, transaction_date))

                    # Insert into user_crops
                    logger.info(f"user_id type: {type(user_id)}, item_id type: {type(selected_plant['plant_id'])}, planted_at type: {type(transaction_date)}, status type: {type('planted')}, planted_quantity type: {type(quantity)}")

                    # Ensure correct data types
                    user_id = int(user_id) if user_id is not None else None  # Ensure user_id is an integer
                    item_id = int(selected_plant['plant_id'])  # Ensure item_id is an integer
                    quantity = int(quantity)  # Ensure quantity is an integer

                    # Now perform the INSERT without specifying the id
                    cursor.execute("INSERT INTO user_crops (user_id, item_id, planted_at, status, planted_quantity) VALUES (?, ?, ?, ?, ?)",
                                   (user_id, item_id, transaction_date, 'planted', quantity))

                    # Commit the transaction
                    conn.commit()  # Ensure changes are saved to the database

                    # Log success
                    logger.info(f"Successfully inserted into user_crops: user_id={user_id}, item_id={item_id}, planted_at={transaction_date}, status='planted', planted_quantity={quantity}")

                    if plant:
                        plant_name = plant['name']  # Get the plant name
                        await bot.send_message(chat_id=chat_id, text=f'You have successfully planted {quantity:,} {plant_name}(s)!')
                    
                        # Send a small-sized picture to the user
                        photo_path = 'images/planted.webp'  # Replace with the path to your image file
                        await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption='Happy planting! 🌱')  # Optional caption   

                    else:
                        await bot.send_message(chat_id=chat_id, text='Error: Plant not found.')

                else:
                    await bot.send_message(chat_id=chat_id, text='You do not have enough balance to plant this quantity.')

                # Clear selected plant data
                del user_data[chat_id]['selected_plant']

            except ValueError as ve:
                logger.error(f"ValueError: {ve}")  # Log the specific ValueError
                await bot.send_message(chat_id=chat_id, text='Please enter a valid number for the quantity.')
        
        # Check if callback_data is None
        if callback_data is not None:
            if callback_data == 'planting':
                await show_planting_menu(chat_id)
            elif callback_data in ['Fruits', 'Vegetables', 'Grain']:
                await show_plants(chat_id, callback_data)
            elif callback_data.startswith('auto_planting_'):
                category = callback_data.split('_')[2]  # Extract the category from the callback data
                await show_auto_planting_plants(chat_id, category)
            elif callback_data == 'show_game_menu':
                await show_game_menu(chat_id)  # Show the game menu
            elif callback_data == 'rankings':
                await show_rankings(chat_id)
            elif callback_data == 'plant_status':  # Handle the plant status callback
                await check_planting_status(chat_id)  # Check planting status
            elif callback_data == 'admin_announcement':
                await select_admin_announcement_type(chat_id)
            elif callback_data == 'admin_announcement_text':
                await admin_announcement_text(chat_id)
            elif callback_data == 'admin_announcement_photo':
                await admin_announcement_photo(chat_id)
            elif callback_data == 'manager':
                await show_manager_menu(chat_id)
            elif callback_data == 'harvest':  # Handle the harvest callback
                await harvest_crops(chat_id)  # Call the harvest function
            elif callback_data == 'upgrades':
                await show_upgrades_menu(chat_id)  # Show upgrades menu
            elif callback_data == 'manager_on_off':
                await handle_manager_on_off(chat_id)  # Handle manager on/off
            elif callback_data == 'manager_on':
                await handle_manager_on(chat_id)  # Handle manager on
            elif callback_data == 'manager_off':
                await handle_manager_off(chat_id)  # Handle manager off
            elif callback_data == 'auto_planting':
                await handle_auto_planting(chat_id)  # Handle auto planting
            elif callback_data == 'change_auto_planting':
                await handle_change_auto_planting_category(chat_id)  # Handle change auto planting
            elif callback_data == 'plot_upgrade':
                await handle_plot_upgrade(chat_id)  # Handle plot upgrade
            elif callback_data == 'manager_upgrade':
                await handle_manager_upgrade(chat_id)  # Handle manager upgrade
            elif callback_data == 'crops_upgrade':
                await handle_crops_upgrade(chat_id)  # Handle crops upgrade
            elif callback_data.startswith('confirm_upgrade_'):
                upgrade_id = int(callback_data.split('_')[2])  # Extract the upgrade ID
                await handle_upgrade_confirmation(chat_id, upgrade_id)
            elif callback_data.startswith('plant_'):
                # Attempt to unpack the callback data
                parts = callback_data.split('_')
                if len(parts) == 4:
                    _, category, plant_id, price = parts
                    plant_id = int(plant_id)  # Ensure plant_id is an integer
                    price = int(price)
                    await handle_plant_selection(chat_id, plant_id, price)
                else:
                    logger.error(f"Unexpected callback data format: {callback_data}")
                    await bot.send_message(chat_id=chat_id, text='There was an error processing your request. Please try again.')
            elif callback_data.startswith('auto_plant_'):
                await handle_auto_planting_plant_selection(chat_id, callback_data)
            elif callback_data.startswith('max_'):
                # Handle the max planting callback
                parts = callback_data.split('_')
                if len(parts) == 3:
                    _, plant_id, price = parts
                    plant_id = int(plant_id)  # Ensure plant_id is an integer
                    price = int(price)

                    # Calculate the maximum quantity based on the user's balance
                    conn = create_connection()
                    cursor = conn.cursor()

                    # Fetch user ID based on chat_id
                    cursor.execute("SELECT id FROM users WHERE chat_id = ?", (chat_id,))
                    user = cursor.fetchone()
                    user_id = user[0] if user else None

                    # Fetch cashflow entries for the user
                    cursor.execute("SELECT amount FROM cashflow_ledger WHERE user_id = ?", (user_id,))
                    balance_response = cursor.fetchall()

                    # Calculate total balance
                    total_balance = sum(entry[0] for entry in balance_response) if balance_response else 0

                    # Calculate max quantity
                    max_quantity = total_balance // price if price > 0 else 0

                    # Fetch the user's current upgrade level
                    cursor.execute("SELECT upgrade_id FROM user_upgrades WHERE user_id = ?", (user_id,))
                    user_upgrades = cursor.fetchall()  # Fetch all upgrades

                    # Determine the highest upgrade level
                    current_upgrade_level = 0  # Default to 0 if no upgrades
                    if user_upgrades:
                        # Extract upgrade IDs
                        upgrade_ids = [upgrade[0] for upgrade in user_upgrades]

                        # Fetch levels for all upgrade IDs, filtering by category 'plot'
                        cursor.execute("SELECT level FROM upgrade_listings WHERE id IN ({}) AND category = ?".format(','.join('?' * len(upgrade_ids))), upgrade_ids + ['plot'])
                        levels = cursor.fetchall()

                        # Find the maximum level
                        current_upgrade_level = max(level[0] for level in levels) if levels else 0

                    # Get available slots based on the current upgrade level
                    available_slots = get_available_plots_slots(current_upgrade_level)

                    # Fetch crops for the user from the user_crops table
                    cursor.execute("SELECT SUM(planted_quantity) FROM user_crops WHERE user_id = ? AND (status = 'planted' OR status = 'Ready for Harvest')", (user_id,))
                    occupied_slots = cursor.fetchone()[0] or 0  # Default to 0 if no crops planted

                    # Ensure max quantity does not exceed available slots   
                    max_quantity = min(max_quantity, available_slots - occupied_slots)

                    if max_quantity > 0:
                        # Proceed to plant the maximum quantity
                        selected_plant = user_data[chat_id]['selected_plant']  # Ensure you have the selected plant data
                        total_cost = max_quantity * selected_plant['price']  # Calculate total cost for max quantity

                        # Check if the user can afford this total cost
                        if total_balance >= total_cost:
                            # Deduct cashflow
                            transaction_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')  # Format as 'YYYY-MM-DD HH:MM:SS'
                            
                            # Fetch the plant details for the description
                            plant = next((plant for category in plant_data.values() for plant in category if plant['id'] == selected_plant['plant_id']), None)
                            
                            if plant:
                                description = f'Planted {max_quantity} {plant["emoji"]} {plant["name"]}(s).'  # Use plant name and emoji
                            else:
                                description = f'Planted {max_quantity} plants with ID {selected_plant["plant_id"]}.'  # Fallback description

                            cursor.execute("INSERT INTO cashflow_ledger (user_id, amount, description, transaction_date) VALUES (?, ?, ?, ?)", 
                                       (user_id, -total_cost, description, transaction_date))

                            # Insert into user_crops
                            cursor.execute("INSERT INTO user_crops (user_id, item_id, planted_at, status, planted_quantity) VALUES (?, ?, ?, ?, ?)",
                                       (user_id, selected_plant['plant_id'], transaction_date, 'planted', max_quantity))

                            # Commit the transaction
                            conn.commit()  # Ensure changes are saved to the database

                            await bot.send_message(chat_id=chat_id, text=f'You have successfully planted {max_quantity:,} {plant["name"]}(s)!')

                            # Send a small-sized picture to the user
                            photo_path = 'images/planted.webp'  # Replace with the path to your image file
                            await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption='Happy planting! 🌱')  # Optional caption
                        else:
                            await bot.send_message(chat_id=chat_id, text='You do not have enough balance to plant this quantity.')
                    else:
                        logger.error(f"Unexpected max callback data format: {callback_data}")
                        await bot.send_message(chat_id=chat_id, text='There was an error processing your request. Please try again.')

        elif callback_data is None:
            # Handle the case where callback_data is None
            pass

async def process_queue():
    while True:
        chat_id, text_or_callback_data, update = await message_queue.get()
        if text_or_callback_data is not None:  # Message
            await handle_message(chat_id, text_or_callback_data, update, None)
        else:  # Callback query
            await handle_message(chat_id, None, update, text_or_callback_data)
        message_queue.task_done()

@asynccontextmanager
async def lifespan(app: FastAPI):
    global ngrok_process  # Declare the global variable

    # Startup logic
    create_tables()  # Create necessary tables
    ngrok_process = start_ngrok()  # Start ngrok and store the process
    ngrok_url = get_ngrok_url()  # Get ngrok URL
    set_telegram_webhook(ngrok_url)  # Set the Telegram webhook
    
    # Fetch plant data on startup
    await fetch_plant_data()  # Load plant data into memory

    logger.info("Startup logic completed.")

    # Start the check_ready_for_harvest task in the background
    asyncio.create_task(check_ready_for_harvest())  # Run the background task

    # Start the queue processing in the background
    asyncio.create_task(process_queue())

    yield  # This will pause the lifespan context until the app is shut down

    # Shutdown logic
    logger.info("Shutting down the application...")
    if ngrok_process:
        ngrok_process.terminate()  # Terminate the ngrok process

# Assign the lifespan context to the app
app = FastAPI(lifespan=lifespan)

@app.post("/webhook")
async def webhook(request: Request):
    update = await request.json()
    logger.info(f"Received update: {update}")

    # Check if the update contains a message
    if 'message' in update:
        chat_id = update['message']['chat']['id']
        text = update['message'].get('text', '')  # Use .get() to avoid KeyError

        logger.info(f"Received message: {text} from chat_id: {chat_id}")

        # Rate limiting check
        if not rate_limiter(chat_id):
            await bot.send_message(chat_id=chat_id, text='You are sending requests too quickly. Please wait a moment.')
            return JSONResponse(content={"status": "ok"})  # Early return

        logger.info(f"Received message: {text} from chat_id: {chat_id}") 

        # Add the message to the queue instead of processing it directly
        await handle_message(chat_id, text, update, None)  # For messages

    elif 'callback_query' in update:
        callback_query = update['callback_query']
        chat_id = callback_query['message']['chat']['id']
        callback_data = callback_query['data']

        logger.info(f"Received callback query: {callback_data} from chat_id: {chat_id}")

        # Rate limiting check
        if not rate_limiter(chat_id):
            await bot.send_message(chat_id=chat_id, text='You are sending requests too quickly. Please wait a moment.')
            return JSONResponse(content={"status": "ok"})  # Early return

        # Add the callback query to the queue
        await handle_message(chat_id, None, update, callback_data)  # For callback queries

    return JSONResponse(content={"status": "ok"})

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
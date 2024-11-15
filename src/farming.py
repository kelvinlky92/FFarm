from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import logging
import os
import subprocess
import time
import requests
from datetime import datetime
from dotenv import load_dotenv
import asyncio
from contextlib import asynccontextmanager
import sys
import io
from database import create_connection, create_tables
from telegram_bot import bot
from rate_limiter import rate_limiter
from background_task import check_ready_for_harvest
from message_handler import handle_message

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

# Set the console encoding to UTF-8 for Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create a logs directory if it doesn't exist
if not os.path.exists('../logs'):
    os.makedirs('../logs')

# Create a logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)  # Set the logging level

# Create a formatter
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# Create a file handler for logging to a file with date and time in the filename
current_time = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')  # Format the current time
log_file_name = f'../logs/app_{current_time}.log'  # Create a log file name with date and time
file_handler = logging.FileHandler(log_file_name, mode='a', encoding='utf-8')  # Append mode with UTF-8 encoding
file_handler.setLevel(logging.INFO)  # Set the level for the file handler
file_handler.setFormatter(formatter)  # Set the formatter for the file handler

# Add both handlers to the logger
logger.addHandler(file_handler)

# Replace with your actual bot token
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# Global variable to store ngrok process
ngrok_process = None  # Declare the ngrok_process variable

# Global variable to store plant data
plant_data = {}
user_data = {}  # Game state (in-memory for simplicity; consider using a database for persistence)
users_to_notify = set()

# Create a queue for incoming messages
message_queue = asyncio.Queue()

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
    asyncio.create_task(check_ready_for_harvest(users_to_notify))  # Run the background task

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
        await handle_message(chat_id, text, update, None, user_data, plant_data)  # For messages

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
        await handle_message(chat_id, None, update, callback_data, user_data, plant_data)  # For callback queries

    return JSONResponse(content={"status": "ok"})

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
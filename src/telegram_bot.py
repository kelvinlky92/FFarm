# src/bot.py
import telegram
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')  # Get the bot token from environment variables

bot = telegram.Bot(token=TOKEN)  # Initialize the bot instance
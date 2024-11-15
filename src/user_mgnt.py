from database import create_connection
from datetime import datetime
from telegram_bot import bot
import logging

logger = logging.getLogger(__name__)

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

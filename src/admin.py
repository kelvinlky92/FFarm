import telegram
from telegram_bot import bot
from database import create_connection
from rate_limiter import rate_limiter
import logging

logger = logging.getLogger(__name__)

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

async def admin_announcement_text(chat_id, user_data):
    """Prompt the admin to enter the announcement message."""
    await bot.send_message(chat_id=chat_id, text='Please enter the announcement message:')
    
    # Set a state to capture the next message from the admin
    # You can use a dictionary to store the state for each chat_id
    user_data[chat_id]['waiting_for_announcement'] = True
    
async def send_admin_announcement_text(chat_id, message, user_data):
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

async def admin_announcement_photo(chat_id, user_data):
    """Prompt the admin to upload the announcement photo."""
    await bot.send_message(chat_id=chat_id, text='Please upload the announcement photo:')

    # Set a state to capture the next photo from the admin
    user_data[chat_id]['waiting_for_photo'] = True

async def send_admin_announcement_photo(chat_id, photo, user_data):
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

import asyncio
from datetime import datetime, timedelta
import logging
import telegram
from database import create_connection
from telegram_bot import bot
from farm_manager import handle_manager_auto_harvest

logger = logging.getLogger(__name__)

async def check_ready_for_harvest(users_to_notify):
    """Check for crops that are ready for harvest and notify users."""
    while True:
        await asyncio.sleep(30)  # Check every 30 seconds
        
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
                photo_path = '../images/ready_for_harvest.jpg'  # Replace with the path to your image file
                await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption='Your crops are ready for harvest! 🌾')     
            except telegram.error.BadRequest as e:
                logger.error(f"Failed to send message to chat_id {chat_id}: {e}")  # Log the error
            except Exception as e:
                logger.error(f"An unexpected error occurred: {e}")  # Log any other unexpected errors

        # Clear the notify list for the next check
        users_to_notify.clear()

        await handle_manager_auto_harvest()      
from admin import show_admin_menu, select_admin_announcement_type, admin_announcement_text, admin_announcement_photo, send_admin_announcement_text, send_admin_announcement_photo
from database import create_connection
from datetime import datetime
from game_menu import show_game_menu
from telegram_bot import bot
from user_mgnt import register_user
from planting import show_planting_menu, show_plants, handle_plant_selection, check_planting_status
from harvest_crops import harvest_crops
from upgrades import show_upgrades_menu, handle_plot_upgrade, handle_crops_upgrade, handle_manager_upgrade, handle_upgrade_confirmation
from farm_manager import show_manager_menu, handle_manager_on_off, handle_manager_on, handle_manager_off, handle_auto_planting, handle_change_auto_planting_category, show_auto_planting_plants, handle_auto_planting_plant_selection
from rankings import show_rankings
from rate_limiter import rate_limiter
from plots import get_available_plots_slots
from fastapi.responses import JSONResponse
import logging

logger = logging.getLogger(__name__)

async def handle_message(chat_id, text, update, callback_data, user_data, plant_data):
    # Your existing message handling logic goes here
    # For example, checking commands, processing user input, etc.
    # Initialize user_data for the chat_id if it doesn't exist
        if chat_id not in user_data:
            user_data[chat_id] = {}

        if chat_id in user_data:
            # Check if the user is waiting for an announcement message
            if user_data[chat_id].get('waiting_for_announcement'):
                # Call the function to send the announcement
                await send_admin_announcement_text(chat_id, text, user_data)

            # Check if the user is waiting for an announcement photo
            if user_data[chat_id].get('waiting_for_photo'):
                # Call the function to send the announcement photo
                photo_file_id = update['message'].get('photo', [])
                if photo_file_id:
                    # Get the file ID of the largest photo
                    file_id = photo_file_id[-1]['file_id']
                    await send_admin_announcement_photo(chat_id, file_id, user_data)
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
                        await bot.send_message(chat_id=chat_id, text=f'You have successfully planted {quantity:,} {plant_name}(s) for ${total_cost:,}!')
                    
                        # Send a small-sized picture to the user
                        photo_path = '../images/planted.webp'  # Replace with the path to your image file
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
                await show_plants(chat_id, callback_data, plant_data)
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
                await admin_announcement_text(chat_id, user_data)
            elif callback_data == 'admin_announcement_photo':
                await admin_announcement_photo(chat_id, user_data)
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
                    await handle_plant_selection(chat_id, plant_id, price, user_data, plant_data)
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
                            photo_path = '../images/planted.webp'  # Replace with the path to your image file
                            await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption='Happy planting! 🌱')  # Optional caption
                        else:
                            await bot.send_message(chat_id=chat_id, text='You do not have enough balance to plant this quantity.')
                    else:
                        logger.error(f"Unexpected max callback data format: {callback_data}")
                        await bot.send_message(chat_id=chat_id, text='There was an error processing your request. Please try again.')

        elif callback_data is None:
            # Handle the case where callback_data is None
            pass
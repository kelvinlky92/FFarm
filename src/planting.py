import telegram
from telegram_bot import bot
from database import create_connection
import logging
from plots import get_available_plots_slots
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

async def show_planting_menu(chat_id):
    """Display the planting menu with options for fruits, vegetables, and grains."""
    keyboard = [
        [telegram.InlineKeyboardButton("🍉 Fruits", callback_data='Fruits')],
        [telegram.InlineKeyboardButton("🥬 Vegetables", callback_data='Vegetables')],
        [telegram.InlineKeyboardButton("🌾 Grains", callback_data='Grain')]
    ]
    reply_markup = telegram.InlineKeyboardMarkup(keyboard)

    await bot.send_message(chat_id=chat_id, text='Choose a category to plant:', reply_markup=reply_markup)

async def show_plants(chat_id, category, plant_data):
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

async def handle_plant_selection(chat_id, plant_id, price, user_data, plant_data):
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
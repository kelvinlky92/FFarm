import telegram
from datetime import datetime, timedelta
from telegram_bot import bot
from database import create_connection
from rate_limiter import rate_limiter
from plots import get_available_plots_slots
from harvest_crops import harvest_crops


async def show_manager_menu(chat_id):
    """Display the manager menu with options for plant selection."""
    keyboard = [
        [telegram.InlineKeyboardButton("👨‍🌾 Manager On/Off", callback_data='manager_on_off')],
        [telegram.InlineKeyboardButton("👨‍🌾 Auto Planting", callback_data='auto_planting')]
    ]
    reply_markup = telegram.InlineKeyboardMarkup(keyboard)
    await bot.send_message(chat_id=chat_id, text='Choose an option:', reply_markup=reply_markup)

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

async def show_auto_planting_plants(chat_id, category, plant_data):
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
                        photo_path = '../images/manager_planting.webp'  # Replace with the path to your image file
                        await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption=f'Farm Manager has directed to plant {max_quantity:,} {name}(s) for ${total_cost:,}!')  # Optional caption

    conn.commit()
    conn.close()

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
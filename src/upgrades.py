import telegram
from telegram_bot import bot
from database import create_connection
from datetime import datetime

async def show_upgrades_menu(chat_id):
    """Display the upgrades menu with options for plot upgrades."""
    keyboard = [
        [telegram.InlineKeyboardButton("🌱 Plot", callback_data='plot_upgrade')],
        [telegram.InlineKeyboardButton("👨‍🌾 Manager", callback_data='manager_upgrade')],
        [telegram.InlineKeyboardButton("☘️ Crops", callback_data='crops_upgrade')]
    ]
    reply_markup = telegram.InlineKeyboardMarkup(keyboard)

    await bot.send_message(chat_id=chat_id, text='Choose an upgrade option:', reply_markup=reply_markup)

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
                photo_path = '../images/plot_upgrade.webp'  # Replace with the path to your image file
            elif category == 'manager':
                photo_path = '../images/manager_upgrade.webp'  # Replace with the path to your image file
            elif category == 'crops':
                photo_path = '../images/crops_upgrade.jpg'  # Replace with the path to your image file
            await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption='Upgrade successful! 🎉')  # Optional caption

        else:
            await bot.send_message(chat_id=chat_id, text='You do not have enough balance to purchase this upgrade.')
    else:
        await bot.send_message(chat_id=chat_id, text='Error: Upgrade not found.')

    conn.close()
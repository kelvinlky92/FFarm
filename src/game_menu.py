import telegram
from database import create_connection
from telegram_bot import bot

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
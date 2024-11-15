import random
from datetime import datetime
from database import create_connection
from telegram_bot import bot
import logging

logger = logging.getLogger(__name__)

async def harvest_crops(chat_id):
    """Handle the harvesting of crops for the user."""
    from farm_manager import check_auto_planting_status
    # First, check the planting status
    await check_auto_planting_status(chat_id)  # Show the current status of the crops

    conn = create_connection()
    cursor = conn.cursor()

    # Fetch user ID from the database
    cursor.execute("SELECT id, manager_on_off FROM users WHERE chat_id = ?", (chat_id,))
    user = cursor.fetchone()
    user_id, manager_on_off = user[0], user[1] if user else (None, None)

    # Fetch user balance
    cursor.execute("SELECT amount FROM cashflow_ledger WHERE user_id = ?", (user_id,))
    balance_response = cursor.fetchall()
    total_balance = sum(entry[0] for entry in balance_response) if balance_response else 0

    if manager_on_off == 0:
        logger.info(f"User {chat_id} is attempting to harvest crops.")

    if user_id:
        # Fetch crops for the user from the user_crops table
        cursor.execute("SELECT * FROM user_crops WHERE user_id = ? AND status = 'Ready for Harvest'", (user_id,))
        crops_response = cursor.fetchall()
        
        if crops_response:
            for crop in crops_response:
                # Fetch plant details using the item_id
                cursor.execute("SELECT * FROM plants_listing WHERE id = ?", (crop[2],))  # Assuming item_id is the third column
                plant = cursor.fetchone()
                
                if plant:
                    # Calculate the harvested quantity
                    min_ratio = plant[4]  # Min harvesting ratio
                    max_ratio = plant[5]  # Max harvesting ratio
                    selling_price = plant[8]  # Selling price

                    # Get a random factor for harvest event
                    harvest_event = random.choices(
                        ['extreme_disaster', 'mild_disaster', 'minimum_harvest', 'normal_season', 'good_season'],
                        weights=[1, 4, 15, 60, 20],
                        k=1
                    )[0]

                    # Determine the harvest quantity based on the event
                    if harvest_event == 'extreme_disaster':
                        if total_balance >= 1000000000:
                            harvested_quantity = 0  # All crops destroyed
                            photo_path = '../images/extreme_disaster.jpeg'
                            await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption='🌪️ Extreme disaster! All your crops have been destroyed!')
                        else:
                            harvested_quantity = crop[5] * min_ratio  # Minimum harvest rate
                            photo_path = '../images/minimum_harvest.jpeg'
                            await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption='🌾 Low season! Your crops have been grown at a minimum rate.')
                    elif harvest_event == 'mild_disaster':
                        if total_balance >= 1000000000:
                            harvested_quantity = int(crop[5] * min_ratio * 0.5)  # Half of the crops destroyed
                            photo_path = '../images/mild_disaster.jpeg'
                            await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption='🌪️ Mild disaster! Half of your crops have been destroyed!')
                        else:
                            harvested_quantity = crop[5] * min_ratio  # Minimum harvest rate
                            photo_path = '../images/minimum_harvest.jpeg'
                            await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption='🌾 Low season! Your crops have been grown at a minimum rate.')
                    elif harvest_event == 'minimum_harvest':
                        harvested_quantity = crop[5] * min_ratio  # Minimum harvest rate
                        photo_path = '../images/minimum_harvest.jpeg'
                        await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption='🌾 Low season! Your crops have been grown at a minimum rate.')
                    elif harvest_event == 'normal_season':
                        harvested_quantity = crop[5] * ((min_ratio + max_ratio) / 2)  # Average harvest rate
                        photo_path = '../images/normal_season.jpeg'
                        await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption='🌾 Normal season! Your crops have been grown at a normal rate.')
                    elif harvest_event == 'good_season':
                        harvested_quantity = crop[5] * max_ratio  # Maximum harvest rate
                        photo_path = '../images/good_season.jpeg'
                        await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption='🌾 Good season! Your crops have been grown at a good rate.')
                    

                    harvested_quantity_rounded = int(harvested_quantity) + (1 if harvested_quantity % 1 > 0 else 0)  # Round up to the nearest whole number

                    # Calculate cash flow
                    cashflow_amount = harvested_quantity_rounded * selling_price  # Calculate cashflow

                    # Insert into cashflow ledger
                    if harvested_quantity_rounded > 0:
                        local_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')  # Get local time for transaction date
                        harvested_quantity_rounded_formatted = f"{harvested_quantity_rounded:,}"  # Format for display
                        cursor.execute("INSERT INTO cashflow_ledger (user_id, amount, description, transaction_date) VALUES (?, ?, ?, ?)", 
                                       (user_id, cashflow_amount, f'Harvested {harvested_quantity_rounded_formatted} {plant[1]}(s).', local_time))

                    # Update the crop status to "Harvested"
                    cursor.execute("UPDATE user_crops SET status = 'Harvested' WHERE id = ?", (crop[0],))  # Assuming crop ID is the first column

                    # Manager user message
                    if manager_on_off == 1 and harvested_quantity_rounded > 0:
                        photo_path = '../images/manager_harvest.webp'  # Replace with the path to your image file
                        await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption=f'Manager has directed to harvest {harvested_quantity_rounded_formatted} {plant[1]}(s) and sell them for ${cashflow_amount:,}!')  # Optional caption
                        
                        manager_payroll = int(cashflow_amount * 0.08)
                        cursor.execute("INSERT INTO cashflow_ledger (user_id, amount, description, transaction_date) VALUES (?, ?, ?, ?)", 
                                       (user_id, -manager_payroll, f'Manager payroll for harvesting {harvested_quantity_rounded_formatted} {plant[1]}(s).', local_time))
                        photo_path = '../images/manager_payroll.webp'  # Replace with the path to your image file
                        await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption=f'Manager payroll of ${manager_payroll:,} has been deducted from your account.')  # Optional caption

                    # Normal user message
                    elif harvested_quantity_rounded > 0:
                        await bot.send_message(chat_id=chat_id, text=f'You have successfully harvested {harvested_quantity_rounded_formatted} {plant[1]}(s) for ${cashflow_amount:,}!')
                        photo_path = '../images/harvested.webp'  # Replace with the path to your image file
                        await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption='Happy harvesting! 🌾')  # Optional caption
                    
                else:
                    await bot.send_message(chat_id=chat_id, text='Error: Plant not found.')
        else:
            if manager_on_off == 0:
                await bot.send_message(chat_id=chat_id, text='You have no crops ready for harvest.')
    else:
        await bot.send_message(chat_id=chat_id, text='User not found.')

    conn.commit()
    conn.close()
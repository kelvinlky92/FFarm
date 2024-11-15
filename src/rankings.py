from database import create_connection
from telegram_bot import bot

async def show_rankings(chat_id):
    """Display the rankings menu with options for plant selection."""
    conn = create_connection()
    cursor = conn.cursor()
    
    # Fetch top 10 the username and total amount from the cashflow_ledger table, grouped by user_id, and order by the total amount in descending order
    cursor.execute("SELECT users.username, SUM(cashflow_ledger.amount) FROM cashflow_ledger LEFT JOIN users ON cashflow_ledger.user_id = users.id GROUP BY users.id ORDER BY SUM(cashflow_ledger.amount) DESC LIMIT 10")
    rankings = cursor.fetchall()

    rankings_message = "🏆 **Top 10 Rankings**:\n\n"  # Added header
    for index, rank in enumerate(rankings, start=1):
        username = rank[0][:15] + '...' if len(rank[0]) > 15 else rank[0]  # Truncate long usernames
        rankings_message += f"{index}️⃣ {username} - ${rank[1]:,}\n"  # Added ordinal numbers

    photo_path = '../images/rankings.jpeg'
    await bot.send_photo(chat_id=chat_id, photo=photo_path, caption=rankings_message)
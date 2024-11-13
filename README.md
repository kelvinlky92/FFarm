# Farming Bot Application

## Description
The Farming Bot Application is a Telegram bot designed to help users manage their virtual farm. Users can plant crops, check their status, harvest them, and manage upgrades for their farming operations. The bot provides an interactive experience through Telegram, making farming fun and engaging. Please try the game at this link (https://t.me/FFarmKY_bot)

## Features
- **Planting Crops**: Users can choose from various crops to plant in their virtual farm.
- **Harvesting**: Users can harvest their crops once they are ready.
- **Manager Upgrades**: Users can upgrade their farming manager to improve efficiency.
- **Auto Planting**: Users can set up auto planting for their crops.
- **User Notifications**: The bot sends notifications to users when their crops are ready for harvest.
- **Rankings**: Users can now view the **Top 10 Rankings** to see how they compare with other players based on their total earnings! 🏆

## Updates
📢 **New Ranking Feature!** 🌟  
We are excited to announce the addition of a ranking feature! Players can now check the **Top 10 Rankings** to see the usernames and total amounts earned by our top players. Compete and climb the leaderboard!

## Requirements
- Python 3.x
- `python-dotenv` for environment variable management
- `fastapi` for the web framework
- `python-telegram-bot` for Telegram bot integration
- Other dependencies listed in `requirements.txt`

## Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/kelvinlky92/FFarm.git
   ```
2. Navigate to the project directory:
   ```bash
   cd Farm_Live
   ```
3. Install the required packages:
   ```bash
   pip install -r requirements.txt
   ```

## Configuration
- Create a `.env` file in the root directory and add your environment variables:
  ```plaintext
  TELEGRAM_BOT_TOKEN=your_token_here
  DATABASE_NAME=farming_game.db
  ```

## Usage
- Run the application:
  ```bash
  python farming.py
  ```
- Interact with the bot on Telegram by searching for your bot's username.

## Contributing
If you would like to contribute to this project, please fork the repository and submit a pull request. Contributions are welcome!

## License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments
- Special thanks to the developers of the libraries used in this project, including FastAPI and python-telegram-bot.
- Inspiration from various farming simulation games.

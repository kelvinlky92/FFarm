import time
from collections import defaultdict

# Rate limiting configuration
RATE_LIMIT = 20  # Maximum number of requests
TIME_FRAME = 60  # Time frame in seconds

# Dictionary to store user request timestamps
user_requests = defaultdict(list)

def rate_limiter(chat_id):
    current_time = time.time()
    # Remove timestamps that are outside the time frame
    user_requests[chat_id] = [timestamp for timestamp in user_requests[chat_id] if current_time - timestamp < TIME_FRAME]
    
    if len(user_requests[chat_id]) < RATE_LIMIT:
        # Allow the request
        user_requests[chat_id].append(current_time)
        return True
    else:
        # Deny the request
        return False
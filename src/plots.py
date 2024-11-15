

def get_available_plots_slots(upgrade_level):
    """Return the number of available planting slots based on the user's upgrade level."""
    slots = {
        1: 1000,
        2: 10000,
        3: 100000,
        4: 1000000,
        5: 10000000
    }
    return slots.get(upgrade_level, 100)  # Default to 0 if level is not found
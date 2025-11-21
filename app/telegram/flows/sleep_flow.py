from typing import Tuple, Optional, Dict, Any

def start_sleep_flow(chat_id: str) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    """
    Start the sleep logging flow.
    Returns: (text, reply_markup, new_state)
    """
    text = "Okay, let's log your sleep. How long did you sleep?"
    # For now, just a message, no complex state or markup
    reply_markup = None
    new_state = {"flow": "sleep", "step": "duration"}
    return text, reply_markup, new_state

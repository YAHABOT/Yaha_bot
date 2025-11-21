from typing import Tuple, Optional, Dict, Any

def start_exercise_flow(chat_id: str) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    """
    Start the exercise logging flow.
    Returns: (text, reply_markup, new_state)
    """
    text = "Okay, let's log a workout. What did you do?"
    # For now, just a message
    reply_markup = None
    new_state = {"flow": "exercise", "step": "type"}
    return text, reply_markup, new_state

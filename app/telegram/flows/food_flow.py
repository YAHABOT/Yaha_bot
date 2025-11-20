# app/telegram/flows/food_flow.py
from __future__ import annotations

from typing import Any, Dict, Tuple, Optional


FoodState = Dict[str, Any]
Reply = Tuple[str, Optional[Dict[str, Any]], Optional[FoodState]]


def _base_state() -> FoodState:
    """
    Initial state for the food flow.
    """
    return {
        "flow": "food",
        "step": "choose_meal_type",
        "data": {
            "meal_name": None,
            "calories": None,
            "protein_g": None,
            "carbs_g": None,
            "fat_g": None,
            "fiber_g": None,
            "notes": None,
        },
    }


def start_food_flow(chat_id: int | str) -> Reply:
    """
    Entry point: user tapped 'Log food' or used /food.
    """
    state = _base_state()

    text = (
        "🍽 Let’s log a meal.\n\n"
        "First, what kind of meal is this?"
    )

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "Breakfast", "callback_data": "food_mealtype_breakfast"},
                {"text": "Lunch", "callback_data": "food_mealtype_lunch"},
            ],
            [
                {"text": "Dinner", "callback_data": "food_mealtype_dinner"},
                {"text": "Snack", "callback_data": "food_mealtype_snack"},
            ],
            [
                {"text": "Cancel ❌", "callback_data": "food_cancel"},
            ],
        ]
    }

    return text, reply_markup, state


def handle_food_callback(
    chat_id: int | str,
    callback_data: str,
    state: FoodState,
) -> Reply:
    """
    Handle inline button presses while in the food flow.
    """
    step = state.get("step")
    data = state.get("data") or {}

    # Cancel at any time
    if callback_data == "food_cancel":
        text = "Okay, cancelled the food log."
        return text, None, None  # state cleared

    # Step: choose meal type
    if step == "choose_meal_type" and callback_data.startswith("food_mealtype_"):
        meal_type = callback_data.removeprefix("food_mealtype_")
        data["meal_type"] = meal_type  # not stored in DB yet, but useful later
        state["step"] = "await_description"

        text = (
            f"Got it: *{meal_type.capitalize()}*.\n\n"
            "What did you eat? You can type it in plain text (e.g. `oats with banana`) "
            "or something simple like `oats`."
        )

        return text, None, state

    # Step: ask whether to enter macros
    if step == "ask_macros_choice":
        if callback_data == "food_macros_yes":
            state["step"] = "await_calories"
            text = "Okay, let’s add macros.\n\nFirst, how many *calories*?"
            return text, None, state

        if callback_data == "food_macros_no":
            # Skip macros completely, go to notes choice
            state["step"] = "ask_notes_choice"
            text = (
                "No problem, we’ll log it without macros.\n\n"
                "Do you want to add any notes? (e.g. hunger, cravings, digestion)"
            )
            reply_markup = {
                "inline_keyboard": [
                    [
                        {"text": "Add notes ✍️", "callback_data": "food_notes_yes"},
                        {"text": "Skip", "callback_data": "food_notes_no"},
                    ],
                    [
                        {"text": "Cancel ❌", "callback_data": "food_cancel"},
                    ],
                ]
            }
            return text, reply_markup, state

    # Step: ask notes choice
    if step == "ask_notes_choice":
        if callback_data == "food_notes_yes":
            state["step"] = "await_notes"
            text = "Okay, type any notes you want to store with this meal."
            return text, None, state

        if callback_data == "food_notes_no":
            # No notes → directly show preview
            state["step"] = "preview"
            text, reply_markup = _build_preview(data)
            return text, reply_markup, state

    # Step: preview – confirm or cancel
    if step == "preview":
        if callback_data == "food_confirm":
            # Signal to caller that we are ready to write to DB
            # The webhook will handle DB insert using state["data"].
            text = "Logging your meal now…"
            # Returning None state here means the caller should clear state
            # *after* successful DB insert.
            return text, None, state

        if callback_data == "food_edit":
            # Simple implementation: jump back to description
            state["step"] = "await_description"
            text = (
                "Let’s edit this meal.\n\n"
                "Send the description again (e.g. `oats with banana`)."
            )
            return text, None, state

        if callback_data == "food_cancel":
            text = "Okay, cancelled the food log."
            return text, None, None

    # Fallback: unknown callback within food flow
    text = "I did not understand that option. Please continue or cancel."
    return text, None, state


def handle_food_text(
    chat_id: int | str,
    text: str,
    state: FoodState,
) -> Reply:
    """
    Handle incoming text while we are in the food flow.
    """
    step = state.get("step")
    data = state.get("data") or {}

    # STEP: await_description
    if step == "await_description":
        # For now, we keep this simple:
        # - We accept the user’s text as the meal_name.
        # - No GPT is used; this is deterministic.
        data["meal_name"] = text.strip()
        state["step"] = "ask_macros_choice"

        prompt = (
            f"Meal description saved as:\n`{data['meal_name']}`\n\n"
            "Do you want to enter full macros (calories, protein, carbs, fat, fibre)?"
        )
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "Yes, enter macros", "callback_data": "food_macros_yes"},
                    {"text": "No, skip macros", "callback_data": "food_macros_no"},
                ],
                [
                    {"text": "Cancel ❌", "callback_data": "food_cancel"},
                ],
            ]
        }

        return prompt, reply_markup, state

    # STEP: await_calories
    if step == "await_calories":
        val = _parse_number(text)
        if val is None:
            return "Please enter calories as a number (e.g. `520`).", None, state

        data["calories"] = val
        state["step"] = "await_protein"
        return "Protein in grams? (e.g. `32`)", None, state

    # STEP: await_protein
    if step == "await_protein":
        val = _parse_number(text)
        if val is None:
            return "Please enter protein as a number in grams (e.g. `32`).", None, state

        data["protein_g"] = val
        state["step"] = "await_carbs"
        return "Carbs in grams? (e.g. `45`).", None, state

    # STEP: await_carbs
    if step == "await_carbs":
        val = _parse_number(text)
        if val is None:
            return "Please enter carbs as a number in grams (e.g. `45`).", None, state

        data["carbs_g"] = val
        state["step"] = "await_fat"
        return "Fat in grams? (e.g. `18`).", None, state

    # STEP: await_fat
    if step == "await_fat":
        val = _parse_number(text)
        if val is None:
            return "Please enter fat as a number in grams (e.g. `18`).", None, state

        data["fat_g"] = val
        state["step"] = "await_fiber"
        return "Fibre in grams? (optional, you can also type `skip`).", None, state

    # STEP: await_fiber
    if step == "await_fiber":
        if text.strip().lower() == "skip":
            data["fiber_g"] = None
        else:
            val = _parse_number(text)
            if val is None:
                return (
                    "Please enter fibre as a number in grams (e.g. `8`) or type `skip`.",
                    None,
                    state,
                )
            data["fiber_g"] = val

        # After fibre we go to notes choice
        state["step"] = "ask_notes_choice"
        prompt = (
            "Do you want to add any notes? (e.g. hunger, cravings, digestion, context)"
        )
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "Add notes ✍️", "callback_data": "food_notes_yes"},
                    {"text": "Skip", "callback_data": "food_notes_no"},
                ],
                [
                    {"text": "Cancel ❌", "callback_data": "food_cancel"},
                ],
            ]
        }
        return prompt, reply_markup, state

    # STEP: await_notes
    if step == "await_notes":
        data["notes"] = text.strip()
        state["step"] = "preview"
        preview_text, reply_markup = _build_preview(data)
        return preview_text, reply_markup, state

    # Fallback
    return "I’m not sure where we are in the food flow. Let’s cancel and start again.", None, None


def _parse_number(text: str) -> Optional[float]:
    """
    Parse a numeric string into a float.
    Returns None if parsing fails.
    """
    text = text.strip().replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _build_preview(data: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """
    Build a preview message and inline keyboard for confirmation.
    """
    meal_name = data.get("meal_name") or "Meal"
    meal_type = data.get("meal_type") or "meal"

    calories = data.get("calories")
    protein = data.get("protein_g")
    carbs = data.get("carbs_g")
    fat = data.get("fat_g")
    fiber = data.get("fiber_g")
    notes = data.get("notes")

    lines = [
        "🍽 FOOD LOG (Preview)",
        f"• Type: {meal_type.capitalize()}",
        f"• Name: {meal_name}",
    ]

    macro_parts = []
    if calories is not None:
        macro_parts.append(f"{calories} kcal")
    if protein is not None:
        macro_parts.append(f"{protein} g P")
    if carbs is not None:
        macro_parts.append(f"{carbs} g C")
    if fat is not None:
        macro_parts.append(f"{fat} g F")
    if fiber is not None:
        macro_parts.append(f"{fiber} g fibre")

    if macro_parts:
        lines.append("• Macros: " + " | ".join(macro_parts))

    if notes:
        lines.append(f"• Notes: {notes}")

    lines.append("")
    lines.append("Confirm to log this meal or cancel to discard it.")

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "Confirm ✅", "callback_data": "food_confirm"},
                {"text": "Edit ✏️", "callback_data": "food_edit"},
            ],
            [
                {"text": "Cancel ❌", "callback_data": "food_cancel"},
            ],
        ]
    }

    return "\n".join(lines), reply_markup

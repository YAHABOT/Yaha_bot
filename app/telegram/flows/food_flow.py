from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from app.gpt_fallback import normalize_input

FoodState = Dict[str, Any]
Reply = Tuple[str, Optional[Dict[str, Any]], Optional[FoodState]]


def _base_state() -> FoodState:
    return {
        "flow": "food",
        "step": "choose_meal_type",
        "data": {
            "meal_type": None,
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
    state = _base_state()
    text = "🍽 Let’s log a meal.\n\nFirst, what kind of meal is this?"
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
            [{"text": "Cancel ❌", "callback_data": "food_cancel"}],
        ]
    }
    return text, reply_markup, state


def handle_food_callback(chat_id: int | str, callback_data: str, state: FoodState) -> Reply:
    step = state.get("step")
    data = state.get("data") or {}

    if callback_data == "food_cancel":
        return "Okay, cancelled the food log.", None, None

    # 1) Meal type selection
    if step == "choose_meal_type" and callback_data.startswith("food_mealtype_"):
        meal_type = callback_data.removeprefix("food_mealtype_")
        data["meal_type"] = meal_type
        state["step"] = "await_description"
        return (
            f"Got it: {meal_type.capitalize()}.\n\nWhat did you eat?",
            None,
            state,
        )

    # 2) After entering meal description: macros yes/no
    if step == "ask_macros_choice":
        if callback_data == "food_macros_yes":
            state["step"] = "await_calories"
            return "Okay. First, how many calories?", None, state

        if callback_data == "food_macros_no":
            state["step"] = "ask_notes_choice"
            return (
                "Do you want to add any notes?",
                {
                    "inline_keyboard": [
                        [
                            {"text": "Add notes ✍️", "callback_data": "food_notes_yes"},
                            {"text": "Skip", "callback_data": "food_notes_no"},
                        ],
                        [{"text": "Cancel ❌", "callback_data": "food_cancel"}],
                    ]
                },
                state,
            )

    # 3) Skip buttons for macros
    if step == "await_protein" and callback_data == "food_skip_protein":
        data["protein_g"] = None
        state["step"] = "await_carbs"
        return (
            "Carbs in grams?\nOr tap Skip.",
            {"inline_keyboard": [[{"text": "Skip", "callback_data": "food_skip_carbs"}]]},
            state,
        )

    if step == "await_carbs" and callback_data == "food_skip_carbs":
        data["carbs_g"] = None
        state["step"] = "await_fat"
        return (
            "Fat in grams?\nOr tap Skip.",
            {"inline_keyboard": [[{"text": "Skip", "callback_data": "food_skip_fat"}]]},
            state,
        )

    if step == "await_fat" and callback_data == "food_skip_fat":
        data["fat_g"] = None
        state["step"] = "await_fiber"
        return "Fibre in grams? (optional, or type `skip`)", None, state

    # 4) Notes skip
    if step == "ask_notes_choice":
        if callback_data == "food_notes_yes":
            state["step"] = "await_notes"
            return "Okay, type your notes.", None, state

        if callback_data == "food_notes_no":
            state["step"] = "preview"
            text, reply_markup = _build_preview(data)
            return text, reply_markup, state

    # 5) Preview screen
    if step == "preview":
        if callback_data == "food_confirm":
            return "Logging your meal now…", None, state

        if callback_data == "food_edit":
            state["step"] = "await_description"
            return "Let’s edit. Send the description again.", None, state

    return "I didn’t understand that option.", None, state


def handle_food_text(chat_id: int | str, text: str, state: FoodState) -> Reply:
    step = state.get("step")
    data = state.get("data") or {}

    # 1) Description
    if step == "await_description":
        data["meal_name"] = text.strip()
        state["step"] = "ask_macros_choice"
        return (
            f"Saved: `{data['meal_name']}`\n\nDo you want to enter full macros?",
            {
                "inline_keyboard": [
                    [
                        {"text": "Yes", "callback_data": "food_macros_yes"},
                        {"text": "No", "callback_data": "food_macros_no"},
                    ],
                    [{"text": "Cancel ❌", "callback_data": "food_cancel"}],
                ]
            },
            state,
        )

    # 2) Calories
    if step == "await_calories":
        normalized = normalize_input(text, "macros")
        val = normalized.get("calories") if normalized else None
        if val is None:
            try:
                val = float(text.strip())
            except ValueError:
                return "Please enter calories as a number.", None, state

        data["calories"] = val
        state["step"] = "await_protein"
        return (
            "Protein in grams?\nOr tap Skip.",
            {"inline_keyboard": [[{"text": "Skip", "callback_data": "food_skip_protein"}]]},
            state,
        )

    # 3) Protein
    if step == "await_protein":
        normalized = normalize_input(text, "macros")
        val = normalized.get("protein") if normalized else None
        if val is None:
            try:
                val = float(text.strip())
            except ValueError:
                return "Please enter protein as a number or tap Skip.", None, state

        data["protein_g"] = val
        state["step"] = "await_carbs"
        return (
            "Carbs in grams?\nOr tap Skip.",
            {"inline_keyboard": [[{"text": "Skip", "callback_data": "food_skip_carbs"}]]},
            state,
        )

    # 4) Carbs
    if step == "await_carbs":
        normalized = normalize_input(text, "macros")
        val = normalized.get("carbs") if normalized else None
        if val is None:
            try:
                val = float(text.strip())
            except ValueError:
                return "Please enter carbs as a number or tap Skip.", None, state

        data["carbs_g"] = val
        state["step"] = "await_fat"
        return (
            "Fat in grams?\nOr tap Skip.",
            {"inline_keyboard": [[{"text": "Skip", "callback_data": "food_skip_fat"}]]},
            state,
        )

    # 5) Fat
    if step == "await_fat":
        normalized = normalize_input(text, "macros")
        val = normalized.get("fat") if normalized else None
        if val is None:
            try:
                val = float(text.strip())
            except ValueError:
                return "Please enter fat as a number or tap Skip.", None, state

        data["fat_g"] = val
        state["step"] = "await_fiber"
        return "Fibre in grams? (optional, or type `skip`)", None, state

    # 6) Fibre
    if step == "await_fiber":
        if text.strip().lower() in {"skip", "no"}:
            data["fiber_g"] = None
        else:
            normalized = normalize_input(text, "macros")
            val = normalized.get("fiber") if normalized else None
            if val is None:
                try:
                    val = float(text.strip())
                except ValueError:
                    return "Please enter fibre as a number or type `skip`.", None, state
            data["fiber_g"] = val

        state["step"] = "ask_notes_choice"
        return (
            "Add notes?",
            {
                "inline_keyboard": [
                    [
                        {"text": "Yes ✍️", "callback_data": "food_notes_yes"},
                        {"text": "Skip", "callback_data": "food_notes_no"},
                    ],
                    [{"text": "Cancel ❌", "callback_data": "food_cancel"}],
                ]
            },
            state,
        )

    # 7) Notes
    if step == "await_notes":
        data["notes"] = text.strip()
        state["step"] = "preview"
        text_out, reply_markup = _build_preview(data)
        return text_out, reply_markup, state

    return "I’m lost. Let’s cancel this meal log.", None, None


def _build_preview(data: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    meal_name = data.get("meal_name") or "Meal"
    meal_type = data.get("meal_type") or "meal"

    def fmt(val, suffix):
        return f"{val}{suffix}" if val is not None else "—"

    lines = [
        "🍽 FOOD LOG (Preview)",
        f"• Type: {meal_type.capitalize()}",
        f"• Name: {meal_name}",
        "• Macros:",
        f"   - {fmt(data.get('calories'), ' kcal')}",
        f"   - {fmt(data.get('protein_g'), ' g P')}",
        f"   - {fmt(data.get('carbs_g'), ' g C')}",
        f"   - {fmt(data.get('fat_g'), ' g F')}",
        f"   - {fmt(data.get('fiber_g'), ' g fibre')}",
    ]

    if data.get("notes"):
        lines.append(f"• Notes: {data['notes']}")

    lines.append("")
    lines.append("Confirm to log this meal or cancel.")

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "Confirm ✅", "callback_data": "food_confirm"},
                {"text": "Edit ✏️", "callback_data": "food_edit"},
            ],
            [{"text": "Cancel ❌", "callback_data": "food_cancel"}],
        ]
    }

    return "\n".join(lines), reply_markup

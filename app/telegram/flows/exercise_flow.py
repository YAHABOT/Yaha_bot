from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from app.gpt_fallback import normalize_input

ExerciseState = Dict[str, Any]
Reply = Tuple[str, Optional[Dict[str, Any]], Optional[ExerciseState]]


def _base_state() -> ExerciseState:
    return {
        "flow": "exercise",
        "step": "ask_type",
        "data": {
            "workout_name": None,
            "training_type": None,
            "duration_min": None,
            "distance_km": None,
            "calories_burned": None,
            "avg_hr": None,
            "max_hr": None,
            "training_intensity": None,
            "tags": None,
            "notes": None,
        },
    }


def start_exercise_flow(chat_id: int | str) -> Reply:
    state = _base_state()
    text = "🏃‍♂️ Let’s log a workout.\n\nWhat kind of exercise was it?"
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "Run 🏃‍♂️", "callback_data": "ex_type_Run"},
                {"text": "Gym 🏋️‍♂️", "callback_data": "ex_type_Gym"},
            ],
            [
                {"text": "Walk 🚶", "callback_data": "ex_type_Walk"},
                {"text": "Cycle 🚴", "callback_data": "ex_type_Cycle"},
            ],
            [
                {"text": "Other", "callback_data": "ex_type_Other"},
                {"text": "Cancel ❌", "callback_data": "ex_cancel"},
            ],
        ]
    }
    return text, reply_markup, state


def handle_exercise_callback(chat_id: int | str, callback_data: str, state: ExerciseState) -> Reply:
    step = state.get("step")
    data = state.get("data") or {}

    if callback_data == "ex_cancel":
        return "Okay, cancelled the workout log.", None, None

    # Type selection
    if step == "ask_type" and callback_data.startswith("ex_type_"):
        w_type = callback_data.removeprefix("ex_type_")
        data["workout_name"] = w_type
        data["training_type"] = w_type.lower()
        state["step"] = "ask_duration"
        return (
            f"Got it: {w_type}.\n\nHow long did you go for? (minutes)",
            None,
            state,
        )

    # Skip chains
    if callback_data == "ex_skip_dist":
        state["step"] = "ask_calories"
        return (
            "Calories burned?\nOr tap Skip.",
            {"inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_cals"}]]},
            state,
        )

    if callback_data == "ex_skip_cals":
        state["step"] = "ask_avg_hr"
        return (
            "Average Heart Rate?\nOr tap Skip.",
            {"inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_avg_hr"}]]},
            state,
        )

    if callback_data == "ex_skip_avg_hr":
        state["step"] = "ask_max_hr"
        return (
            "Max Heart Rate?\nOr tap Skip.",
            {"inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_max_hr"}]]},
            state,
        )

    if callback_data == "ex_skip_max_hr":
        state["step"] = "ask_intensity"
        return (
            "Training Intensity (1–10)?",
            {"inline_keyboard": [[{"text": "Cancel ❌", "callback_data": "ex_cancel"}]]},
            state,
        )

    if callback_data == "ex_skip_tags":
        state["step"] = "ask_notes"
        return (
            "Any notes?\nOr tap Skip.",
            {"inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_notes"}]]},
            state,
        )

    if callback_data == "ex_skip_notes":
        state["step"] = "preview"
        text, reply_markup = _build_preview(data)
        return text, reply_markup, state

    # Preview buttons
    if step == "preview":
        if callback_data == "ex_confirm":
            return "Logging your workout now…", None, state
        if callback_data == "ex_edit":
            state["step"] = "ask_type"
            return (
                "Let’s start over. What kind of exercise was it?",
                {
                    "inline_keyboard": [
                        [
                            {"text": "Run 🏃‍♂️", "callback_data": "ex_type_Run"},
                            {"text": "Gym 🏋️‍♂️", "callback_data": "ex_type_Gym"},
                        ],
                        [
                            {"text": "Walk 🚶", "callback_data": "ex_type_Walk"},
                            {"text": "Cycle 🚴", "callback_data": "ex_type_Cycle"},
                        ],
                        [
                            {"text": "Other", "callback_data": "ex_type_Other"},
                            {"text": "Cancel ❌", "callback_data": "ex_cancel"},
                        ],
                    ]
                },
                state,
            )

    return "I didn’t understand that option.", None, state


def handle_exercise_text(chat_id: int | str, text: str, state: ExerciseState) -> Reply:
    step = state.get("step")
    data = state.get("data") or {}

    # 1) Duration
    if step == "ask_duration":
        normalized = normalize_input(text, "duration")
        val = normalized.get("duration") if normalized else None
        if val is None:
            try:
                val = int(text.strip())
            except ValueError:
                val = None

        if val is None:
            return "Please enter duration in minutes (e.g. 45).", None, state

        data["duration_min"] = val
        state["step"] = "ask_distance"
        return (
            "Distance in km? (e.g. 5.2)\nOr tap Skip.",
            {"inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_dist"}]]},
            state,
        )

    # 2) Distance
    if step == "ask_distance":
        normalized = normalize_input(text, "exercise_stats")
        val = normalized.get("distance") if normalized else None
        if val is None:
            try:
                val = float(text.strip())
            except ValueError:
                val = None

        if val is not None:
            data["distance_km"] = val

        state["step"] = "ask_calories"
        return (
            "Calories burned?\nOr tap Skip.",
            {"inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_cals"}]]},
            state,
        )

    # 3) Calories
    if step == "ask_calories":
        normalized = normalize_input(text, "exercise_stats")
        val = normalized.get("calories") if normalized else None
        if val is None:
            try:
                val = int(text.strip())
            except ValueError:
                val = None

        if val is not None:
            data["calories_burned"] = val

        state["step"] = "ask_avg_hr"
        return (
            "Average Heart Rate?\nOr tap Skip.",
            {"inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_avg_hr"}]]},
            state,
        )

    # 4) Avg HR
    if step == "ask_avg_hr":
        normalized = normalize_input(text, "exercise_stats")
        val = normalized.get("heart_rate") if normalized else None
        if val is None:
            try:
                val = int(text.strip())
            except ValueError:
                val = None

        if val is not None:
            data["avg_hr"] = val

        state["step"] = "ask_max_hr"
        return (
            "Max Heart Rate?\nOr tap Skip.",
            {"inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_max_hr"}]]},
            state,
        )

    # 5) Max HR
    if step == "ask_max_hr":
        normalized = normalize_input(text, "exercise_stats")
        val = normalized.get("heart_rate") if normalized else None
        if val is None:
            try:
                val = int(text.strip())
            except ValueError:
                val = None

        if val is not None:
            data["max_hr"] = val

        state["step"] = "ask_intensity"
        return (
            "Training Intensity (1–10)?",
            {"inline_keyboard": [[{"text": "Cancel ❌", "callback_data": "ex_cancel"}]]},
            state,
        )

    # 6) Intensity
    if step == "ask_intensity":
        normalized = normalize_input(text, "number")
        val = normalized.get("number") if normalized else None
        if val is None:
            try:
                val = int(text.strip())
            except ValueError:
                val = None

        if val is None:
            return "Please enter a number from 1 to 10.", None, state

        data["training_intensity"] = val
        state["step"] = "ask_tags"
        return (
            "Any tags? (comma separated)\nOr tap Skip.",
            {"inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_tags"}]]},
            state,
        )

    # 7) Tags
    if step == "ask_tags":
        data["tags"] = text.strip()
        state["step"] = "ask_notes"
        return (
            "Any notes?\nOr tap Skip.",
            {"inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_notes"}]]},
            state,
        )

    # 8) Notes
    if step == "ask_notes":
        data["notes"] = text.strip()
        state["step"] = "preview"
        text_out, reply_markup = _build_preview(data)
        return text_out, reply_markup, state

    return "I’m lost. Let’s cancel this workout log.", None, None


def _build_preview(data: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    name = data.get("workout_name") or "Workout"
    duration = data.get("duration_min")
    dist = data.get("distance_km") or "—"
    cals = data.get("calories_burned") or "—"
    intensity = data.get("training_intensity") or "—"
    tags = data.get("tags") or "—"
    notes = data.get("notes") or "—"

    lines = [
        "🏃‍♂️ EXERCISE LOG (Preview)",
        f"• Type: {name}",
        f"• Duration: {duration} min",
        f"• Dist: {dist} km",
        f"• Cals: {cals}",
        f"• Intensity: {intensity}/10",
        f"• Tags: {tags}",
        f"• Notes: {notes}",
        "",
        "Confirm to log this workout or cancel.",
    ]

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "Confirm ✅", "callback_data": "ex_confirm"},
                {"text": "Edit ✏️", "callback_data": "ex_edit"},
            ],
            [{"text": "Cancel ❌", "callback_data": "ex_cancel"}],
        ]
    }
    return "\n".join(lines), reply_markup

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

ExerciseState = Dict[str, Any]
Reply = Tuple[str, Optional[Dict[str, Any]], Optional[ExerciseState]]


def _base_state() -> ExerciseState:
    """
    Initial state for the exercise flow.
    """
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
            "perceived_intensity": None,
            "effort_description": None,
            "tags": None,
            "notes": None,
        },
    }


def start_exercise_flow(chat_id: int | str) -> Reply:
    """
    Entry point: user tapped 'Log exercise' or used /exercise.
    """
    state = _base_state()

    text = (
        "🏃‍♂️ Let’s log a workout.\n\n"
        "What kind of exercise was it?"
    )

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


def handle_exercise_callback(
    chat_id: int | str,
    callback_data: str,
    state: ExerciseState,
) -> Reply:
    """
    Handle inline button presses while in the exercise flow.
    """
    step = state.get("step")
    data = state.get("data") or {}

    # Cancel at any time
    if callback_data == "ex_cancel":
        text = "Okay, cancelled the workout log."
        return text, None, None

    # Step: ask_type
    if step == "ask_type" and callback_data.startswith("ex_type_"):
        w_type = callback_data.removeprefix("ex_type_")
        data["workout_name"] = w_type
        data["training_type"] = w_type.lower()  # Simple default mapping

        state["data"] = data
        state["step"] = "ask_duration"
        text = (
            f"Got it: *{w_type}*.\n\n"
            "How long did you go for? (in minutes, e.g. `45`)"
        )
        return text, None, state

    # Step: ask_intensity
    if step == "ask_intensity" and callback_data.startswith("ex_int_"):
        int_str = callback_data.removeprefix("ex_int_")
        try:
            data["training_intensity"] = int(int_str)
        except ValueError:
            data["training_intensity"] = 5

        state["data"] = data
        state["step"] = "ask_perceived"
        text = "Perceived intensity? (1–10)\nOr tap Skip."
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "Easy (1-3)", "callback_data": "ex_perc_2"},
                    {"text": "Moderate (4-6)", "callback_data": "ex_perc_5"},
                    {"text": "Hard (7-9)", "callback_data": "ex_perc_8"},
                ],
                [{"text": "Skip ⏩", "callback_data": "ex_skip_perc"}],
            ]
        }
        return text, reply_markup, state

    # Step: ask_perceived (Callback or Skip)
    if step == "ask_perceived":
        if callback_data.startswith("ex_perc_"):
            try:
                data["perceived_intensity"] = int(callback_data.removeprefix("ex_perc_"))
            except ValueError:
                pass
        elif callback_data == "ex_skip_perc":
            pass  # Skip

        state["data"] = data
        state["step"] = "ask_effort"
        text = "Describe the effort (optional).\nOr tap Skip."
        reply_markup = {
            "inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_effort"}]]
        }
        return text, reply_markup, state

    # Step: ask_effort (Skip)
    if step == "ask_effort" and callback_data == "ex_skip_effort":
        state["step"] = "ask_tags"
        text = "Any tags? (comma separated)\nOr tap Skip."
        reply_markup = {
            "inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_tags"}]]
        }
        return text, reply_markup, state

    # Step: ask_tags (Skip)
    if step == "ask_tags" and callback_data == "ex_skip_tags":
        state["step"] = "ask_notes"
        text = "Any notes?\nOr tap Skip."
        reply_markup = {
            "inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_notes"}]]
        }
        return text, reply_markup, state

    # Step: ask_notes (Skip)
    if step == "ask_notes" and callback_data == "ex_skip_notes":
        state["step"] = "preview"
        preview_text, reply_markup = _build_preview(data)
        return preview_text, reply_markup, state

    # Skips for other steps (if we add buttons for them later, but for now they are text-driven)
    if callback_data == "ex_skip_dist":
        state["step"] = "ask_calories"
        text = "Calories burned?\nOr tap Skip."
        reply_markup = {"inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_cals"}]]}
        return text, reply_markup, state

    if callback_data == "ex_skip_cals":
        state["step"] = "ask_avg_hr"
        text = "Average Heart Rate?\nOr tap Skip."
        reply_markup = {"inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_avg_hr"}]]}
        return text, reply_markup, state

    if callback_data == "ex_skip_avg_hr":
        state["step"] = "ask_max_hr"
        text = "Max Heart Rate?\nOr tap Skip."
        reply_markup = {"inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_max_hr"}]]}
        return text, reply_markup, state

    if callback_data == "ex_skip_max_hr":
        state["step"] = "ask_intensity"
        text = "Training Intensity (1-10)?"
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "Low (1-3)", "callback_data": "ex_int_3"},
                    {"text": "Medium (4-6)", "callback_data": "ex_int_5"},
                ],
                [
                    {"text": "High (7-8)", "callback_data": "ex_int_8"},
                    {"text": "Extreme (9-10)", "callback_data": "ex_int_10"},
                ],
            ]
        }
        return text, reply_markup, state

    # Step: preview – confirm or cancel
    if step == "preview":
        if callback_data == "ex_confirm":
            text = "Logging your workout now…"
            return text, None, state

        if callback_data == "ex_edit":
            new_state = _base_state()
            text = (
                "Okay, let’s start over.\n\n"
                "What kind of exercise was it?"
            )
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
            return text, reply_markup, new_state

        if callback_data == "ex_cancel":
            text = "Okay, cancelled the workout log."
            return text, None, None

    # Fallback
    text = "I did not understand that option. Please continue or cancel."
    return text, None, state


def handle_exercise_text(
    chat_id: int | str,
    text: str,
    state: ExerciseState,
) -> Reply:
    """
    Handle incoming text while in the exercise flow.
    """
    step = state.get("step")
    data = state.get("data") or {}
    raw = text.strip()

    # STEP: ask_duration
    if step == "ask_duration":
        val = _parse_number(raw)
        if val is None or val <= 0:
            return "Please enter duration as a number of minutes (e.g. `45`).", None, state

        data["duration_min"] = int(val)
        state["data"] = data
        state["step"] = "ask_distance"

        text = "Distance in km? (e.g. 5.2)\nOr tap Skip."
        reply_markup = {"inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_dist"}]]}
        return text, reply_markup, state

    # STEP: ask_distance
    if step == "ask_distance":
        val = _parse_number(raw)
        if val is not None and val > 0:
            data["distance_km"] = float(val)

        state["data"] = data
        state["step"] = "ask_calories"
        text = "Calories burned?\nOr tap Skip."
        reply_markup = {"inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_cals"}]]}
        return text, reply_markup, state

    # STEP: ask_calories
    if step == "ask_calories":
        val = _parse_number(raw)
        if val is not None and val > 0:
            data["calories_burned"] = int(val)

        state["data"] = data
        state["step"] = "ask_avg_hr"
        text = "Average Heart Rate?\nOr tap Skip."
        reply_markup = {"inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_avg_hr"}]]}
        return text, reply_markup, state

    # STEP: ask_avg_hr
    if step == "ask_avg_hr":
        val = _parse_number(raw)
        if val is not None and val > 0:
            data["avg_hr"] = int(val)

        state["data"] = data
        state["step"] = "ask_max_hr"
        text = "Max Heart Rate?\nOr tap Skip."
        reply_markup = {"inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_max_hr"}]]}
        return text, reply_markup, state

    # STEP: ask_max_hr
    if step == "ask_max_hr":
        val = _parse_number(raw)
        if val is not None and val > 0:
            data["max_hr"] = int(val)

        state["data"] = data
        state["step"] = "ask_intensity"
        text = "Training Intensity (1-10)?"
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "Low (1-3)", "callback_data": "ex_int_3"},
                    {"text": "Medium (4-6)", "callback_data": "ex_int_5"},
                ],
                [
                    {"text": "High (7-8)", "callback_data": "ex_int_8"},
                    {"text": "Extreme (9-10)", "callback_data": "ex_int_10"},
                ],
            ]
        }
        return text, reply_markup, state

    # STEP: ask_effort
    if step == "ask_effort":
        if raw.lower() != "skip":
            data["effort_description"] = raw

        state["data"] = data
        state["step"] = "ask_tags"
        text = "Any tags? (comma separated)\nOr tap Skip."
        reply_markup = {
            "inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_tags"}]]
        }
        return text, reply_markup, state

    # STEP: ask_tags
    if step == "ask_tags":
        if raw.lower() != "skip":
            data["tags"] = raw

        state["data"] = data
        state["step"] = "ask_notes"
        text = "Any notes?\nOr tap Skip."
        reply_markup = {
            "inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_notes"}]]
        }
        return text, reply_markup, state

    # STEP: ask_notes
    if step == "ask_notes":
        if raw.lower() != "skip":
            data["notes"] = raw

        state["data"] = data
        state["step"] = "preview"
        preview_text, reply_markup = _build_preview(data)
        return preview_text, reply_markup, state

    # Fallback
    return "I’m not sure where we are in the exercise flow. Let’s cancel and start again.", None, None


def _parse_number(text: str) -> Optional[float]:
    text = text.strip().replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _build_preview(data: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    name = data.get("workout_name") or "Exercise"
    duration = data.get("duration_min")
    dist = data.get("distance_km") if data.get("distance_km") is not None else "—"
    cals = data.get("calories_burned") if data.get("calories_burned") is not None else "—"
    intensity = data.get("training_intensity")
    perc = data.get("perceived_intensity") if data.get("perceived_intensity") is not None else "—"
    effort = data.get("effort_description") or "—"
    tags = data.get("tags") or "—"
    notes = data.get("notes") or "—"

    lines = [
        "🏃‍♂️ EXERCISE LOG (Preview)",
        f"• Type: {name}",
        f"• Duration: {duration} min" if duration is not None else "• Duration: —",
        f"• Dist: {dist} km",
        f"• Cals: {cals}",
        f"• Intensity: {intensity}/10" if intensity is not None else "• Intensity: —",
        f"• Perceived: {perc}/10",
        f"• Effort: {effort}",
        f"• Tags: {tags}",
        f"• Notes: {notes}",
    ]

    lines.append("")
    lines.append("Confirm to log this workout or cancel.")

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "Confirm ✅", "callback_data": "ex_confirm"},
                {"text": "Edit ✏️", "callback_data": "ex_edit"},
            ],
            [
                {"text": "Cancel ❌", "callback_data": "ex_cancel"},
            ],
        ]
    }

    return "\n".join(lines), reply_markup
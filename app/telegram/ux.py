# app/telegram/ux.py
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

ContainerDict = Dict[str, Any]
ReplyTuple = Tuple[str, Optional[Dict[str, Any]]]

VALID_CONTAINERS = {"food", "sleep", "exercise"}


def build_main_menu() -> ReplyTuple:
    """
    Build the main menu with 4 buttons.
    """
    text = "Okay, what would you like to log?"
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "🥗 Log Food", "callback_data": "log_food"},
                {"text": "😴 Log Sleep", "callback_data": "log_sleep"},
            ],
            [
                {"text": "🏋🏻 Log Exercise", "callback_data": "log_exercise"},
                {"text": "📋 View Day", "callback_data": "view_day"},
            ],
        ]
    }
    return text, reply_markup


def _safe(value: Any, default: str = "—") -> str:
    if value is None:
        return default
    return str(value)


def build_reply_for_parsed(raw_text: str, parsed: ContainerDict) -> ReplyTuple:
    """
    Build a *user-facing* reply + optional inline keyboard from the parsed payload.

    Returns:
        (text, reply_markup_dict_or_None)
    """
    container = parsed.get("container", "unknown")
    data = parsed.get("data") or {}
    issues = parsed.get("issues") or []

    # --- UNKNOWN / FALLBACK -------------------------------------------------
    if container not in VALID_CONTAINERS:
        tips = [
            "• Food:  `oats 520 32p 45c 18f`",
            "• Sleep: `slept 7h energy 8/10`",
            "• Exercise: `45 min walk 4km`",
        ]
        text_lines = [
            "⚠️ I couldn’t classify that as food, sleep, or exercise.",
            "",
            "Try sending it like one of these:",
            *tips,
        ]
        if issues:
            text_lines.append("")
            text_lines.append("Notes:")
            for issue in issues:
                text_lines.append(f"• {issue}")

        # Inline buttons to *guide* flows (callback-based)
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "Log food 🍽", "callback_data": "start_food"},
                    {"text": "Log sleep 😴", "callback_data": "start_sleep"},
                ],
                [
                    {"text": "Log exercise 🏃‍♂️", "callback_data": "start_exercise"},
                ],
            ]
        }
        return "\n".join(text_lines), reply_markup

    # --- FOOD ---------------------------------------------------------------
    if container == "food":
        meal = _safe(data.get("meal_name"), "Meal")
        calories = data.get("calories")
        protein = data.get("protein_g")
        carbs = data.get("carbs_g")
        fat = data.get("fat_g")
        fiber = data.get("fiber_g")
        notes = data.get("notes")

        lines = [
            "🍽 Food logged:",
            f"• Meal: {meal}",
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

        if issues:
            lines.append("")
            lines.append("Notes:")
            for issue in issues:
                lines.append(f"• {issue}")

        lines.append("")
        lines.append("If anything looks off, just send the corrected meal and I’ll log the new one.")

        return "\n".join(lines), None

    # --- SLEEP --------------------------------------------------------------
    if container == "sleep":
        duration = data.get("duration_hr")
        sleep_score = data.get("sleep_score")
        energy_score = data.get("energy_score")
        sleep_start = data.get("sleep_start")
        sleep_end = data.get("sleep_end")
        notes = data.get("notes")

        lines = ["😴 Sleep logged:"]

        if duration is not None:
            lines.append(f"• Duration: {duration} h")

        if sleep_score is not None:
            lines.append(f"• Sleep score: {sleep_score}")

        if energy_score is not None:
            lines.append(f"• Energy score: {energy_score}")

        if sleep_start or sleep_end:
            start_txt = _safe(sleep_start)
            end_txt = _safe(sleep_end)
            lines.append(f"• Window: {start_txt} → {end_txt}")

        if notes:
            lines.append(f"• Notes: {notes}")

        if issues:
            lines.append("")
            lines.append("Notes:")
            for issue in issues:
                lines.append(f"• {issue}")

        lines.append("")
        lines.append("You can update this by sending a new sleep message for today.")

        return "\n".join(lines), None

    # --- EXERCISE -----------------------------------------------------------
    if container == "exercise":
        workout_type = _safe(data.get("workout_type"), "Exercise")
        duration_min = data.get("duration_min")
        distance_km = data.get("distance_km")
        calories = data.get("calories")
        intensity = data.get("intensity")
        notes = data.get("notes")

        lines = [f"🏃‍♂️ Exercise logged: {workout_type}"]

        if duration_min is not None:
            lines.append(f"• Duration: {duration_min} min")

        if distance_km is not None:
            lines.append(f"• Distance: {distance_km} km")

        macro_parts = []
        if calories is not None:
            macro_parts.append(f"{calories} kcal")
        if intensity is not None:
            macro_parts.append(f"intensity {intensity}/10")
        if macro_parts:
            lines.append("• Effort: " + " | ".join(macro_parts))

        if notes:
            lines.append(f"• Notes: {notes}")

        if issues:
            lines.append("")
            lines.append("Notes:")
            for issue in issues:
                lines.append(f"• {issue}")

        lines.append("")
        lines.append("Keep it up. Send your next workout the same way and I’ll keep stacking them.")

        return "\n".join(lines), None

    # Safety net – should never hit if we covered all containers
    return parsed.get("reply_text") or "Logged.", None


def build_callback_reply(callback_data: str) -> Optional[ReplyTuple]:
    """
    Turn inline button callback data into guidance messages.

    Returns:
        (text, reply_markup) or None if we ignore the callback.
    """
    if callback_data == "start_food":
        text = (
            "🍽 Let’s log some food.\n\n"
            "Send me your meal like this:\n"
            "• `oats 520 32p 45c 18f`\n"
            "• `chicken wrap 430 32p 40c 12f`\n\n"
            "Include calories + macros when you can. I’ll store it and keep totals clean."
        )
        return text, None

    if callback_data == "start_sleep":
        text = (
            "😴 Let’s log your sleep.\n\n"
            "Example:\n"
            "• `slept 7.5h energy 8/10 sleep was okay`\n\n"
            "You can also include start/end times later; for now duration + how you feel is enough."
        )
        return text, None

    if callback_data == "start_exercise":
        text = (
            "🏃‍♂️ Let’s log exercise.\n\n"
            "Examples:\n"
            "• `45 min walk 4km`\n"
            "• `gym 60min push session intensity 7`\n\n"
            "Just describe what you did, how long, and optionally distance or intensity."
        )
        return text, None

    # Unknown callback – ignore gracefully
    return None

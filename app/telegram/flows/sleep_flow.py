from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from app.gpt_fallback import normalize_input

SleepState = Dict[str, Any]
Reply = Tuple[str, Optional[Dict[str, Any]], Optional[SleepState]]


def _base_state() -> SleepState:
    return {
        "flow": "sleep",
        "step": "ask_quality",
        "data": {
            "sleep_score": None,
            "energy_score": None,
            "duration_hr": None,
            "sleep_start": None,
            "sleep_end": None,
            "resting_hr": None,
            "notes": None,
        },
    }


def start_sleep_flow(chat_id: int | str) -> Reply:  # chat_id kept for symmetry
    state = _base_state()
    text = (
        "😴 Let’s log your sleep.\n\n"
        "First, how would you rate your sleep quality? (0–100)\n"
        "You can just type a number like 75."
    )
    reply_markup = {
        "inline_keyboard": [
            [{"text": "Cancel ❌", "callback_data": "sleep_cancel"}],
        ]
    }
    return text, reply_markup, state


def handle_sleep_callback(chat_id: int | str, callback_data: str, state: SleepState) -> Reply:
    step = state.get("step")
    data = state.get("data") or {}

    if callback_data == "sleep_cancel":
        return "Okay, cancelled the sleep log.", None, None

    # Skip chains
    if step == "ask_start" and callback_data == "sleep_skip_start":
        state["step"] = "ask_end"
        return (
            "When did you wake up? (HH:MM, 24h, or things like '6am')\nOr tap Skip.",
            {"inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "sleep_skip_end"}]]},
            state,
        )

    if step == "ask_end" and callback_data == "sleep_skip_end":
        state["step"] = "ask_rhr"
        return (
            "Resting heart rate on waking? (bpm)\nOr tap Skip.",
            {"inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "sleep_skip_rhr"}]]},
            state,
        )

    if step == "ask_rhr" and callback_data == "sleep_skip_rhr":
        state["step"] = "ask_notes"
        return (
            "Any notes about your sleep? (optional)\nOr tap Skip.",
            {"inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "sleep_skip_notes"}]]},
            state,
        )

    if step == "ask_notes" and callback_data == "sleep_skip_notes":
        state["step"] = "preview"
        text, reply_markup = _build_preview(data)
        return text, reply_markup, state

    # Preview actions
    if step == "preview":
        if callback_data == "sleep_confirm":
            # DB write happens in callbacks.py
            return "Logging your sleep now…", None, state
        if callback_data == "sleep_edit":
            state["step"] = "ask_quality"
            return (
                "Let’s start over.\nSleep quality (0–100)?",
                {"inline_keyboard": [[{"text": "Cancel ❌", "callback_data": "sleep_cancel"}]]},
                state,
            )

    return "I didn’t understand that option.", None, state


def handle_sleep_text(chat_id: int | str, text: str, state: SleepState) -> Reply:
    step = state.get("step")
    data = state.get("data") or {}

    # 1) Sleep quality
    if step == "ask_quality":
        normalized = normalize_input(text, "number")
        val = normalized.get("number") if normalized else None
        if val is None:
            try:
                val = int(text.strip())
            except ValueError:
                val = None

        if val is None:
            return "Please enter a number from 0 to 100 for sleep quality.", None, state

        data["sleep_score"] = val
        state["step"] = "ask_duration"
        return (
            "How many hours did you sleep? (e.g. 7.5 or 'around 8 hours')",
            {"inline_keyboard": [[{"text": "Cancel ❌", "callback_data": "sleep_cancel"}]]},
            state,
        )

    # 2) Duration
    if step == "ask_duration":
        normalized = normalize_input(text, "duration")
        val = normalized.get("duration") if normalized else None
        if val is None:
            try:
                val = float(text.strip())
            except ValueError:
                val = None

        if val is None:
            return "Please enter duration in hours (e.g. 7.5).", None, state

        data["duration_hr"] = val
        state["step"] = "ask_energy"
        return (
            "How is your morning energy level? (0–100)",
            {"inline_keyboard": [[{"text": "Cancel ❌", "callback_data": "sleep_cancel"}]]},
            state,
        )

    # 3) Energy
    if step == "ask_energy":
        normalized = normalize_input(text, "number")
        val = normalized.get("number") if normalized else None
        if val is None:
            try:
                val = int(text.strip())
            except ValueError:
                val = None

        if val is None:
            return "Please enter a number from 0 to 100 for energy.", None, state

        data["energy_score"] = val
        state["step"] = "ask_start"
        return (
            "When did you fall asleep? (HH:MM 24h, or '11pm', 'midnight')",
            {
                "inline_keyboard": [
                    [{"text": "Skip ⏩", "callback_data": "sleep_skip_start"}],
                ]
            },
            state,
        )

    # 4) Sleep start
    if step == "ask_start":
        normalized = normalize_input(text, "time")
        val = normalized.get("time") if normalized else None
        data["sleep_start"] = val or text.strip()
        state["step"] = "ask_end"
        return (
            "When did you wake up? (HH:MM 24h, or '6am')",
            {
                "inline_keyboard": [
                    [{"text": "Skip ⏩", "callback_data": "sleep_skip_end"}],
                ]
            },
            state,
        )

    # 5) Sleep end
    if step == "ask_end":
        normalized = normalize_input(text, "time")
        val = normalized.get("time") if normalized else None
        data["sleep_end"] = val or text.strip()
        state["step"] = "ask_rhr"
        return (
            "Resting heart rate on waking? (bpm)\nOr tap Skip.",
            {
                "inline_keyboard": [
                    [{"text": "Skip ⏩", "callback_data": "sleep_skip_rhr"}],
                ]
            },
            state,
        )

    # 6) Resting HR
    if step == "ask_rhr":
        normalized = normalize_input(text, "number")
        val = normalized.get("number") if normalized else None
        if val is None:
            try:
                val = int(text.strip())
            except ValueError:
                return "Please enter a number for heart rate, or tap Skip.", None, state
        data["resting_hr"] = val
        state["step"] = "ask_notes"
        return (
            "Any notes about your sleep? (optional)\nOr tap Skip.",
            {
                "inline_keyboard": [
                    [{"text": "Skip ⏩", "callback_data": "sleep_skip_notes"}],
                ]
            },
            state,
        )

    # 7) Notes
    if step == "ask_notes":
        data["notes"] = text.strip()
        state["step"] = "preview"
        text_out, reply_markup = _build_preview(data)
        return text_out, reply_markup, state

    # Fallback
    return "I’m lost. Let’s cancel this sleep log.", None, None


def _build_preview(data: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    duration = data.get("duration_hr")
    sleep_score = data.get("sleep_score")
    energy_score = data.get("energy_score")
    start = data.get("sleep_start") or "—"
    end = data.get("sleep_end") or "—"
    rhr = data.get("resting_hr") or "—"
    notes = data.get("notes") or "—"

    lines = [
        "😴 SLEEP LOG (Preview)",
        f"• Quality: {sleep_score}/100",
        f"• Duration: {duration} h",
        f"• Morning energy: {energy_score}/100",
        f"• Window: {start} → {end}",
        f"• Resting HR: {rhr} bpm",
        f"• Notes: {notes}",
        "",
        "Confirm to log this sleep or cancel.",
    ]

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "Confirm ✅", "callback_data": "sleep_confirm"},
                {"text": "Edit ✏️", "callback_data": "sleep_edit"},
            ],
            [{"text": "Cancel ❌", "callback_data": "sleep_cancel"}],
        ]
    }
    return "\n".join(lines), reply_markup

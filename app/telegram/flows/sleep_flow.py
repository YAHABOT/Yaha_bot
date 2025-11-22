from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

SleepState = Dict[str, Any]
Reply = Tuple[str, Optional[Dict[str, Any]], Optional[SleepState]]


def _base_state() -> SleepState:
    """
    Initial state for the sleep flow.
    """
    return {
        "flow": "sleep",
        "step": "ask_quality",
            "data": {
            "sleep_score": None,
            "duration_hr": None,
            "energy_score": None,
            "sleep_start": None,
            "sleep_end": None,
            "resting_hr": None,
            "notes": None,
        },
    }


def start_sleep_flow(chat_id: int | str) -> Reply:
    """
    Entry point: user tapped 'Log Sleep' or used a sleep command.
    """
    state = _base_state()
    text = (
        "😴 Let’s log your sleep.\n\n"
        "First, how would you rate your sleep quality? (0–100)"
    )

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "Terrible (0–40)", "callback_data": "sleep_q_20"},
                {"text": "Okay (40–70)", "callback_data": "sleep_q_55"},
            ],
            [
                {"text": "Good (70–85)", "callback_data": "sleep_q_80"},
                {"text": "Great (85–100)", "callback_data": "sleep_q_95"},
            ],
            [
                {"text": "Cancel ❌", "callback_data": "sleep_cancel"},
            ],
        ]
    }

    return text, reply_markup, state


def handle_sleep_callback(
    chat_id: int | str,
    callback_data: str,
    state: SleepState,
) -> Reply:
    """
    Handle inline button presses while in the sleep flow.
    """
    step = state.get("step")
    data = state.get("data") or {}

    # Cancel at any time
    if callback_data == "sleep_cancel":
        text = "Okay, cancelled the sleep log."
        return text, None, None

    # Step: ask_quality
    if step == "ask_quality" and callback_data.startswith("sleep_q_"):
        try:
            score = int(callback_data.removeprefix("sleep_q_"))
        except ValueError:
            score = None

        if score is None or score < 0 or score > 100:
            text = "Please choose a valid sleep quality between 0 and 100."
            return text, None, state

        data["sleep_score"] = score
        state["data"] = data
        state["step"] = "ask_duration"

        text = "How many hours did you sleep? (e.g. 7.5)"
        return text, None, state

    # Step: ask_energy (buttons)
    if step == "ask_energy" and callback_data.startswith("sleep_e_"):
        try:
            energy = int(callback_data.removeprefix("sleep_e_"))
        except ValueError:
            energy = None

        if energy is None or energy < 0 or energy > 100:
            text = "Please choose a valid energy score between 0 and 100."
            return text, None, state

        data["energy_score"] = energy
        state["data"] = data
        state["step"] = "ask_sleep_start"

        text = (
            "When did you fall asleep? (HH:MM, 24h)\n"
            "Example: 23:30"
        )
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "Skip ⏩", "callback_data": "sleep_skip_start"},
                ]
            ]
        }
        return text, reply_markup, state

    # Step: ask_sleep_start (Skip via button)
    if step == "ask_sleep_start" and callback_data == "sleep_skip_start":
        state["step"] = "ask_sleep_end"
        text = (
            "When did you wake up? (HH:MM, 24h)\n"
            "Example: 07:30"
        )
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "Skip ⏩", "callback_data": "sleep_skip_end"},
                ]
            ]
        }
        return text, reply_markup, state

    # Step: ask_sleep_end (Skip via button)
    if step == "ask_sleep_end" and callback_data == "sleep_skip_end":
        state["step"] = "ask_resting_hr"
        text = "Resting heart rate on waking? (optional, bpm)\nType a number or tap Skip."
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "Skip ⏩", "callback_data": "sleep_skip_rhr"},
                ]
            ]
        }
        return text, reply_markup, state

    # Step: ask_resting_hr (Skip via button)
    if step == "ask_resting_hr" and callback_data == "sleep_skip_rhr":
        state["step"] = "ask_notes"
        text = "Any notes about your sleep? (optional)\nType your note or tap Skip."
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "Skip ⏩", "callback_data": "sleep_skip_notes"},
                ]
            ]
        }
        return text, reply_markup, state

    # Step: ask_notes (Skip via button)
    if step == "ask_notes" and callback_data == "sleep_skip_notes":
        # Build preview
        state["step"] = "preview"
        preview_text, reply_markup = _build_preview(data)
        return preview_text, reply_markup, state

    # Step: preview – confirm / edit / cancel
    if step == "preview":
        if callback_data == "sleep_confirm":
            # Callbacks router will perform DB write when seeing this.
            text = "Logging your sleep now…"
            return text, None, state

        if callback_data == "sleep_edit":
            # Reset state and restart
            new_state = _base_state()
            text = (
                "Okay, let’s edit your sleep log.\n\n"
                "First, how would you rate your sleep quality? (0–100)"
            )
            reply_markup = {
                "inline_keyboard": [
                    [
                        {"text": "Terrible (0–40)", "callback_data": "sleep_q_20"},
                        {"text": "Okay (40–70)", "callback_data": "sleep_q_55"},
                    ],
                    [
                        {"text": "Good (70–85)", "callback_data": "sleep_q_80"},
                        {"text": "Great (85–100)", "callback_data": "sleep_q_95"},
                    ],
                    [
                        {"text": "Cancel ❌", "callback_data": "sleep_cancel"},
                    ],
                ]
            }
            return text, reply_markup, new_state

        if callback_data == "sleep_cancel":
            text = "Okay, cancelled the sleep log."
            return text, None, None

    # Fallback
    text = "I didn’t understand that option. Please continue or cancel."
    return text, None, state


def handle_sleep_text(
    chat_id: int | str,
    text: str,
    state: SleepState,
) -> Reply:
    """
    Handle incoming text while in the sleep flow.
    """
    step = state.get("step")
    data = state.get("data") or {}
    raw = text.strip()

    # STEP: ask_duration
    if step == "ask_duration":
        val = _parse_number(raw)
        if val is None or val <= 0 or val > 24:
            reply = "Please enter your sleep duration in hours (e.g. 7.5)."
            return reply, None, state

        data["duration_hr"] = float(val)
        state["data"] = data
        state["step"] = "ask_energy"

        reply = "How is your morning energy level? (0–100)"
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "Very low (0–30)", "callback_data": "sleep_e_20"},
                    {"text": "Okay (30–60)", "callback_data": "sleep_e_45"},
                ],
                [
                    {"text": "Good (60–80)", "callback_data": "sleep_e_70"},
                    {"text": "Great (80–100)", "callback_data": "sleep_e_90"},
                ],
            ]
        }
        return reply, reply_markup, state

    # STEP: ask_sleep_start (text path)
    if step == "ask_sleep_start":
        if raw.lower() == "skip":
            state["step"] = "ask_sleep_end"
            reply = (
                "When did you wake up? (HH:MM, 24h)\n"
                "Example: 07:30"
            )
            reply_markup = {
                "inline_keyboard": [
                    [
                        {"text": "Skip ⏩", "callback_data": "sleep_skip_end"},
                    ]
                ]
            }
            return reply, reply_markup, state

        if not _valid_time(raw):
            reply = "I couldn’t read that time. Please use HH:MM, e.g. 23:30, or type 'skip'."
            return reply, None, state

        data["sleep_start"] = raw
        state["data"] = data
        state["step"] = "ask_sleep_end"

        reply = (
            "When did you wake up? (HH:MM, 24h)\n"
            "Example: 07:30"
        )
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "Skip ⏩", "callback_data": "sleep_skip_end"},
                ]
            ]
        }
        return reply, reply_markup, state

    # STEP: ask_sleep_end (text path)
    if step == "ask_sleep_end":
        if raw.lower() == "skip":
            state["step"] = "ask_resting_hr"
            reply = "Resting heart rate on waking? (optional, bpm)\nType a number or tap Skip."
            reply_markup = {
                "inline_keyboard": [
                    [
                        {"text": "Skip ⏩", "callback_data": "sleep_skip_rhr"},
                    ]
                ]
            }
            return reply, reply_markup, state

        if not _valid_time(raw):
            reply = "I couldn’t read that time. Please use HH:MM, e.g. 07:30, or type 'skip'."
            return reply, None, state

        data["sleep_end"] = raw
        state["data"] = data
        state["step"] = "ask_resting_hr"

        reply = "Resting heart rate on waking? (optional, bpm)\nType a number or tap Skip."
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "Skip ⏩", "callback_data": "sleep_skip_rhr"},
                ]
            ]
        }
        return reply, reply_markup, state

    # STEP: ask_resting_hr (text path)
    if step == "ask_resting_hr":
        if raw.lower() == "skip":
            state["step"] = "ask_notes"
            reply = "Any notes about your sleep? (optional)\nType your note or tap Skip."
            reply_markup = {
                "inline_keyboard": [
                    [
                        {"text": "Skip ⏩", "callback_data": "sleep_skip_notes"},
                    ]
                ]
            }
            return reply, reply_markup, state

        val = _parse_number(raw)
        if val is None or val <= 0:
            reply = "Please enter resting heart rate as a number in bpm, or type 'skip'."
            return reply, None, state

        data["resting_hr"] = int(val)
        state["data"] = data
        state["step"] = "ask_notes"

        reply = "Any notes about your sleep? (optional)\nType your note or tap Skip."
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "Skip ⏩", "callback_data": "sleep_skip_notes"},
                ]
            ]
        }
        return reply, reply_markup, state

    # STEP: ask_notes (text path)
    if step == "ask_notes":
        if raw.lower() != "skip":
            data["notes"] = raw

        state["data"] = data
        state["step"] = "preview"

        preview_text, reply_markup = _build_preview(data)
        return preview_text, reply_markup, state

    # Fallback
    reply = "I’m not sure where we are in the sleep flow. Let’s cancel and start again."
    return reply, None, None


def _parse_number(text: str) -> Optional[float]:
    text = text.strip().replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _valid_time(text: str) -> bool:
    parts = text.split(":")
    if len(parts) != 2:
        return False
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return False
    if hour < 0 or hour > 23:
        return False
    if minute < 0 or minute > 59:
        return False
    return True


def _build_preview(data: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    sleep_score = data.get("sleep_score")
    duration_hr = data.get("duration_hr")
    energy_score = data.get("energy_score")
    sleep_start = data.get("sleep_start") or "—"
    sleep_end = data.get("sleep_end") or "—"
    resting_hr = data.get("resting_hr")
    notes = data.get("notes") or "—"

    lines = [
        "😴 SLEEP LOG (Preview)",
    ]

    if sleep_score is not None:
        lines.append(f"• Quality: {sleep_score}/100")
    if duration_hr is not None:
        lines.append(f"• Duration: {duration_hr} h")
    if energy_score is not None:
        lines.append(f"• Morning energy: {energy_score}/100")

    if sleep_start != "—" or sleep_end != "—":
        lines.append(f"• Window: {sleep_start} → {sleep_end}")

    if resting_hr is not None:
        lines.append(f"• Resting HR: {resting_hr} bpm")

    lines.append(f"• Notes: {notes}")

    lines.append("")
    lines.append("Confirm to log this sleep or cancel.")

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "Confirm ✅", "callback_data": "sleep_confirm"},
                {"text": "Edit ✏️", "callback_data": "sleep_edit"},
            ],
            [
                {"text": "Cancel ❌", "callback_data": "sleep_cancel"},
            ],
        ]
    }

    return "\n".join(lines), reply_markup
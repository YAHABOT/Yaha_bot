diff --git a/app/telegram/flows/exercise_flow.py b/app/telegram/flows/exercise_flow.py
index b08db4dcf9f8d21ac325bf8290aac76aa842953c..4a3af6a2b07cefbacbf6bf12d44b6974e18e983e 100644
--- a/app/telegram/flows/exercise_flow.py
+++ b/app/telegram/flows/exercise_flow.py
@@ -31,111 +31,135 @@ def start_exercise_flow(chat_id: int | str) -> Reply:
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
 
+    text_steps = {
+        "ask_duration",
+        "ask_distance",
+        "ask_calories",
+        "ask_avg_hr",
+        "ask_max_hr",
+        "ask_intensity",
+        "ask_tags",
+        "ask_notes",
+    }
+
     if callback_data == "ex_cancel":
         return "Okay, cancelled the workout log.", None, None
 
+    if step in text_steps:
+        if callback_data == "ex_skip_dist" and step == "ask_distance":
+            state["step"] = "ask_calories"
+            return (
+                "Calories burned?\nOr tap Skip.",
+                {"inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_cals"}]]},
+                state,
+            )
+
+        if callback_data == "ex_skip_cals" and step == "ask_calories":
+            state["step"] = "ask_avg_hr"
+            return (
+                "Average Heart Rate?\nOr tap Skip.",
+                {"inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_avg_hr"}]]},
+                state,
+            )
+
+        if callback_data == "ex_skip_avg_hr" and step == "ask_avg_hr":
+            state["step"] = "ask_max_hr"
+            return (
+                "Max Heart Rate?\nOr tap Skip.",
+                {"inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_max_hr"}]]},
+                state,
+            )
+
+        if callback_data == "ex_skip_max_hr" and step == "ask_max_hr":
+            state["step"] = "ask_intensity"
+            return (
+                "Training Intensity (1–10)?",
+                {"inline_keyboard": [[{"text": "Cancel ❌", "callback_data": "ex_cancel"}]]},
+                state,
+            )
+
+        if callback_data == "ex_skip_tags" and step == "ask_tags":
+            state["step"] = "ask_notes"
+            return (
+                "Any notes?\nOr tap Skip.",
+                {"inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_notes"}]]},
+                state,
+            )
+
+        if callback_data == "ex_skip_notes" and step == "ask_notes":
+            state["step"] = "preview"
+            text_out, reply_markup = _build_preview(data)
+            return text_out, reply_markup, state
+
+        prompt_reminders = {
+            "ask_duration": "How long did you go for? (minutes)",
+            "ask_distance": "Distance in km? (e.g. 5.2)\nOr tap Skip.",
+            "ask_calories": "Calories burned?\nOr tap Skip.",
+            "ask_avg_hr": "Average Heart Rate?\nOr tap Skip.",
+            "ask_max_hr": "Max Heart Rate?\nOr tap Skip.",
+            "ask_intensity": "Training Intensity (1–10)?",
+            "ask_tags": "Any tags? (comma separated)\nOr tap Skip.",
+            "ask_notes": "Any notes?\nOr tap Skip.",
+        }
+
+        return prompt_reminders.get(step, "Please send the requested information."), None, state
+
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
 
-    # Skip chains
-    if callback_data == "ex_skip_dist":
-        state["step"] = "ask_calories"
-        return (
-            "Calories burned?\nOr tap Skip.",
-            {"inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_cals"}]]},
-            state,
-        )
-
-    if callback_data == "ex_skip_cals":
-        state["step"] = "ask_avg_hr"
-        return (
-            "Average Heart Rate?\nOr tap Skip.",
-            {"inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_avg_hr"}]]},
-            state,
-        )
-
-    if callback_data == "ex_skip_avg_hr":
-        state["step"] = "ask_max_hr"
-        return (
-            "Max Heart Rate?\nOr tap Skip.",
-            {"inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_max_hr"}]]},
-            state,
-        )
-
-    if callback_data == "ex_skip_max_hr":
-        state["step"] = "ask_intensity"
-        return (
-            "Training Intensity (1–10)?",
-            {"inline_keyboard": [[{"text": "Cancel ❌", "callback_data": "ex_cancel"}]]},
-            state,
-        )
-
-    if callback_data == "ex_skip_tags":
-        state["step"] = "ask_notes"
-        return (
-            "Any notes?\nOr tap Skip.",
-            {"inline_keyboard": [[{"text": "Skip ⏩", "callback_data": "ex_skip_notes"}]]},
-            state,
-        )
-
-    if callback_data == "ex_skip_notes":
-        state["step"] = "preview"
-        text, reply_markup = _build_preview(data)
-        return text, reply_markup, state
-
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

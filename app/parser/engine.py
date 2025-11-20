import os
import json
from openai import OpenAI

# Load OpenAI configuration from environment
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GPT_PROMPT_ID = os.getenv("GPT_PROMPT_ID")

client = OpenAI(api_key=OPENAI_API_KEY)


def parse_message(message_text: str):
    """
    Sends the user's text to the GPT prompt and expects strict JSON back.
    This is the same logic that previously lived in main.py.
    """
    response = client.responses.create(
        prompt={"id": GPT_PROMPT_ID, "version": "1"},
        input=[{"role": "user", "content": message_text}],
        max_output_tokens=512,
    )

    raw = response.output[0].content[0].text
    print("[GPT RAW]", raw)

    return json.loads(raw)


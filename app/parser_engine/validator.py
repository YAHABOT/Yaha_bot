import json
import os
from typing import Dict, Any, Tuple

from jsonschema import validate, ValidationError

SCHEMA_DIR = os.path.join(
    os.path.dirname(__file__),
    "schemas"
)

# Map container → schema filename
CONTAINER_SCHEMAS = {
    "food": "food.json",
    "sleep": "sleep.json",
    "exercise": "exercise.json",
    "unknown": "unknown.json",
}


def load_schema(container: str) -> Dict[str, Any]:
    """
    Load JSON schema file for given container.
    """
    filename = CONTAINER_SCHEMAS.get(container, "unknown.json")
    path = os.path.join(SCHEMA_DIR, filename)

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_container(container: str, data: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Validate the data object against the container-specific JSON schema.

    Returns (is_valid, error_message)
    """
    schema = load_schema(container)

    try:
        validate(instance=data, schema=schema)
        return True, ""
    except ValidationError as e:
        return False, str(e)

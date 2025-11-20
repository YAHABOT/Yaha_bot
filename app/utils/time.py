from datetime import datetime
import pytz

UTC = pytz.UTC

def today():
    """
    Returns the current date in YYYY-MM-DD format using UTC timezone.
    This matches the previous behavior in main.py.
    """
    return datetime.now(UTC).strftime("%Y-%m-%d")

import os, json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Rome")
DATA_DIR = os.environ.get("DATA_DIR", "data")
LAST_RUN_PATH = os.path.join(DATA_DIR, "last_run.json")

def _now_date():
    return datetime.now(TZ).date()

def load_last_run_date():
    if not os.path.exists(LAST_RUN_PATH):
        return _now_date() - timedelta(days=1)
    try:
        with open(LAST_RUN_PATH, "r", encoding="utf-8") as f:
            obj = json.load(f)
            return datetime.fromisoformat(obj["last_run"]).date()
    except:
        return _now_date() - timedelta(days=1)

def save_last_run_now():
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LAST_RUN_PATH, "w", encoding="utf-8") as f:
        json.dump({"last_run": datetime.now(TZ).isoformat()}, f, ensure_ascii=False)

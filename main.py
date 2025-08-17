from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime, timezone
import os, json, uuid, hashlib, re

APP_VERSION = "1.1.0"

# === CONFIG / STORAGE ===
DATA_DIR = os.environ.get("DATA_DIR", "data")
os.makedirs(DATA_DIR, exist_ok=True)
RECORDS_PATH = os.path.join(DATA_DIR, "records.json")
AUTH_PATH = os.path.join(DATA_DIR, "auth.json")
EMAILS_PATH = os.path.join(DATA_DIR, "sent_emails.json")

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def _load_json(path: str, default):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, ensure_ascii=False, indent=2)
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# === AUTH init (password demo) ===
def _ensure_auth():
    data = _load_json(AUTH_PATH, {"password_sha": _sha("demo")})
    if "password_sha" not in data:
        data["password_sha"] = _sha("demo")
        _save_json(AUTH_PATH, data)
    return data
_ensure_auth()

# === MODELS ===
class LoginRequest(BaseModel):
    email: Optional[EmailStr] = None
    password: str

class LoginResponse(BaseModel):
    token: str

class ChangePassword(BaseModel):
    old_password: str
    new_password: str

class Record(BaseModel):
    id: Optional[str] = None
    nome: str = ""
    cognome: str = ""
    telefono_prefisso: Optional[str] = "+39"
    telefono_numero: Optional[str] = None
    email: Optional[EmailStr] = None

    # nuovi campi richiesti
    def_nome: Optional[str] = None
    def_cognome: Optional[str] = None
    def_data: Optional[str] = None   # ISO YYYY-MM-DD
    giorni_prima: Optional[int] = None
    oggetto: Optional[str] = None
    corpo: Optional[str] = None

    created_at: Optional[str] = None
    updated_at: Optional[str] = None

# === APP ===
app = FastAPI(title="Damiano API", version=APP_VERSION)

# CORS aperto (per GitHub Pages / Render)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # in futuro restringi a "https://damiano-frontend.onrender.com"
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === HELPERS RECORDS ===
def load_records() -> List[dict]:
    data = _load_json(RECORDS_PATH, [])
    changed = False
    for r in data:
        if not r.get("id"):
            r["id"] = uuid.uuid4().hex; changed = True
        if not r.get("created_at"):
            r["created_at"] = _now_iso(); changed = True
        if not r.get("updated_at"):
            r["updated_at"] = r["created_at"]; changed = True
    if changed:
        _save_json(RECORDS_PATH, data)
    return data

def save_records(data: List[dict]):
    _save_json(RECORDS_PATH, data)

# === ENDPOINTS ===
@app.get("/health")
def health():
    return {"status": "ok", "version": APP_VERSION, "time": _now_iso()}

# --- AUTH ---
@app.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest):
    auth = _ensure_auth()
    if _sha(body.password) != auth.get("password_sha"):
        raise HTTPException(status_code=401, detail="Credenziali non valide")
    return {"token": "damiano-token"}

@app.post("/auth/change-password")
def change_password(body: ChangePassword):
    auth = _ensure_auth()
    if _sha(body.old_password) != auth.get("password_sha"):
        raise HTTPException(status_code=401, detail="Password attuale errata")
    if not re.match(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9])\S{8,}$", body.new_password):
        raise HTTPException(status_code=400, detail="Password non conforme alla policy")
    auth["password_sha"] = _sha(body.new_password)
    _save_json(AUTH_PATH, auth)
    return {"ok": True}

# --- RECORDS CRUD ---
@app.get("/records")
def list_records():
    return {"records": load_records()}

@app.post("/records")
def create_record(rec: Record):
    data = load_records()
    now = _now_iso()

    # controllo duplicato (nome + cognome + email + telefono_numero)
    for r in data:
        if (r.get("nome") == rec.nome and
            r.get("cognome") == rec.cognome and
            r.get("email") == rec.email and
            r.get("telefono_numero") == rec.telefono_numero):
            raise HTTPException(status_code=409, detail="Contatto duplicato")

    obj = rec.model_dump()
    obj["id"] = uuid.uuid4().hex
    obj["created_at"] = now
    obj["updated_at"] = now
    data.append(obj)
    save_records(data)
    return obj

@app.put("/records/{rid}")
def update_record(rid: str, rec: Record):
    data = load_records()
    for i, r in enumerate(data):
        if r["id"] == rid:
            updated = r.copy()
            incoming = rec.model_dump()
            incoming["id"] = rid
            updated.update(incoming)
            updated["updated_at"] = _now_iso()
            data[i] = updated
            save_records(data)
            return updated
    raise HTTPException(status_code=404, detail="Not found")

# --- EMAILS (demo) ---
@app.get("/emails/sent")
def emails_sent():
    sample = _load_json(EMAILS_PATH, [
        {"to":"luca.rossi@example.com","subject":"Benvenuto","sent_at":"2025-08-01T10:00:00Z","status":"ok"},
        {"to":"sara.bianchi@example.com","subject":"Aggiornamento","sent_at":"2025-08-05T15:30:00Z","status":"ok"}
    ])
    return {"emails": sample}



from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime, timezone
from fastapi import Query
from datetime import date, timedelta
from zoneinfo import ZoneInfo  # per fuso Europe/Rome
import os, json, uuid, hashlib, re

APP_VERSION = "1.1.0"

# === CONFIG / STORAGE ===
DATA_DIR = os.environ.get("DATA_DIR", "data")
os.makedirs(DATA_DIR, exist_ok=True)
RECORDS_PATH = os.path.join(DATA_DIR, "records.json")
AUTH_PATH = os.path.join(DATA_DIR, "auth.json")
EMAILS_PATH = os.path.join(DATA_DIR, "sent_emails.json")
EMAIL_SETTINGS_PATH = os.path.join(DATA_DIR, "email_settings.json")
EMAIL_TEMPLATES_PATH = os.path.join(DATA_DIR, "email_templates.json")

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

def _norm(s: Optional[str]) -> str:
    """Normalizza per confronto: toglie spazi e rende minuscolo."""
    return (s or "").strip().lower()
    SCHEDULER_SECRET = os.environ.get("SCHEDULER_SECRET", "demo")  # <-- cambia in produzione
    TZ_ROME = ZoneInfo("Europe/Rome")

# === AUTH init (password demo) ===
def _ensure_auth():
    data = _load_json(AUTH_PATH, {"password_sha": _sha("demo")})
    if "password_sha" not in data:
        data["password_sha"] = _sha("demo")
        _save_json(AUTH_PATH, data)
    return data
_ensure_auth()

# === EMAIL SETTINGS/TEMPLATES init ===
def _ensure_email_files():
    # Valori ATTIVI (quelli che "si vedono sempre")
    _load_json(EMAIL_SETTINGS_PATH, {
        "subject": "In memoria di {{NOME}} {{COGNOME}}",
        "body": "Gentile {{NOME}} {{COGNOME}},\nTi ricordiamo con affetto in questa ricorrenza."
    })
    # Modelli salvati (richiamabili per nome)
    _load_json(EMAIL_TEMPLATES_PATH, {
        "subject": [],  # es: [{"id":"...","name":"Damiano1","content":"...","created_at":"..."}]
        "body": []
    })

_ensure_email_files()
def load_email_settings():
    # Ritorna i valori ATTIVI (quelli che si vedono sempre)
    return _load_json(EMAIL_SETTINGS_PATH, {"subject": "", "body": ""})

def save_email_settings(data: dict):
    # Salva i valori ATTIVI
    _save_json(EMAIL_SETTINGS_PATH, data)

def load_email_templates():
    # Ritorna i modelli salvati (richiamabili per nome)
    return _load_json(EMAIL_TEMPLATES_PATH, {"subject": [], "body": []})

def save_email_templates(data: dict):
    # Salva l’archivio dei modelli
    _save_json(EMAIL_TEMPLATES_PATH, data)

def _parse_yyyy_mm_dd(s: Optional[str]) -> Optional[date]:
    try:
        if not s: return None
        y, m, d = map(int, s.split("-"))
        return date(y, m, d)
    except Exception:
        return None

def _today_rome_date() -> date:
    return datetime.now(TZ_ROME).date()

def _due_today(rec: dict, today: date) -> bool:
    """
    True se OGGI è il giorno di invio: anniversario(def_data) - giorni_prima == today
    """
    gd = _parse_yyyy_mm_dd(rec.get("def_data"))
    gp = rec.get("giorni_prima")
    if not gd or gp is None:
        return False
    try:
        gp = int(gp)
    except Exception:
        return False

    ann_this = date(today.year, gd.month, gd.day)
    reminder = ann_this - timedelta(days=gp)
    if reminder == today:
        return True

    # se promemoria di quest'anno è passato, consideriamo quello per l'anno prossimo
    ann_next = date(today.year + 1, gd.month, gd.day)
    reminder_next = ann_next - timedelta(days=gp)
    return reminder_next == today

def _parse_recipients(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    parts = []
    for sep in [",", ";"]:
        raw = raw.replace(sep, " ")
    for token in raw.split():
        t = token.strip()
        if "@" in t and "." in t:
            parts.append(t)
    # deduplica preservando l'ordine
    seen = set()
    out = []
    for x in parts:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def _fill_placeholders(text: str, rec: dict) -> str:
    rep = {
        "{{NOME}}": rec.get("nome") or "",
        "{{COGNOME}}": rec.get("cognome") or "",
        "{{DEF_NOME}}": rec.get("def_nome") or "",
        "{{DEF_COGNOME}}": rec.get("def_cognome") or "",
        "{{DATA_DEF}}": rec.get("def_data") or "",
    }
    for k, v in rep.items():
        text = (text or "").replace(k, v)
    return text

def _load_sent() -> list:
    return _load_json(EMAILS_PATH, [])

def _save_sent(rows: list):
    _save_json(EMAILS_PATH, rows)

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
    
     # nuovo flag per controllare invio mail
    sospendi_invio: Optional[bool] = False
    
class EmailSettingsIn(BaseModel):
    # Valori ATTIVI (quelli visibili sempre nella pagina)
    subject: Optional[str] = None
    body: Optional[str] = None
    # opzionali: se vuoi tracciare quale modello è attivo
    subject_template_id: Optional[str] = None
    body_template_id: Optional[str] = None

class EmailTemplateIn(BaseModel):
    # Modello salvabile/richiamabile: 'subject' oppure 'body'
    type: str  # 'subject' | 'body'
    name: str  # es. "Damiano1"
    content: str


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
    
    # --- RECORDS LIST/READ ---
@app.get("/records")
def list_records():
    return load_records()

@app.get("/records/{rid}")
def read_record(rid: str):
    data = load_records()
    for r in data:
        if r["id"] == rid:
            return r
    raise HTTPException(status_code=404, detail="Not found")

from fastapi import Header

@app.post("/admin/send-due-emails")
def send_due_emails(x_secret: Optional[str] = Header(None)):
    # Protezione semplice via header
    if x_secret != SCHEDULER_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    today = _today_rome_date()
    records = load_records()
    sent_rows = _load_sent()

    # testi attivi globali (fallback)
    settings = load_email_settings()
    default_subject = settings.get("subject") or "In memoria"
    default_body = settings.get("body") or "Un pensiero in questa ricorrenza."

    processed, skipped, errors = [], [], []

    for r in records:
        try:
            # esclusione tramite flag
            if r.get("sospendi_invio") is True:
                skipped.append({"id": r.get("id"), "reason": "blocked_by_flag"})
                continue

            # deve essere "in scadenza" oggi
            if not _due_today(r, today):
                continue

            # destinatari
            to_list = _parse_recipients(r.get("email"))
            if not to_list:
                skipped.append({"id": r.get("id"), "reason": "no_email"})
                continue

            # priorità: testi per-record se presenti, altrimenti globali
            subject_raw = r.get("oggetto") or default_subject
            body_raw = r.get("corpo") or default_body

            subject = _fill_placeholders(subject_raw, r)
            body = _fill_placeholders(body_raw, r)

            # FASE 1: simulazione → non inviamo davvero, ma logghiamo l'operazione come "ok"
            log_row = {
                "record_id": r.get("id"),
                "to": to_list,
                "subject": subject,
                "body_usato": body,
                "nome": r.get("nome"),
                "cognome": r.get("cognome"),
                "def_nome": r.get("def_nome"),
                "def_cognome": r.get("def_cognome"),
                "scheduled_for": today.isoformat(),
                "sent_at": _now_iso(),
                "stato": "ok",
                "errore": None,
            }
            sent_rows.append(log_row)
            processed.append({"id": r.get("id"), "to": to_list})

        except Exception as e:
            errors.append({"id": r.get("id"), "error": str(e)})

    _save_sent(sent_rows)
    return {
        "date": today.isoformat(),
        "counts": {
            "processed": len(processed),
            "skipped": len(skipped),
            "errors": len(errors),
        },
        "processed": processed,
        "skipped": skipped,
        "errors": errors,
    }

# --- AUTH ---
@app.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest):
    auth = _ensure_auth()
    if _sha(body.password) != auth.get("password_sha"):
        raise HTTPException(status_code=401, detail="Credenziali non valide")
    return {"token": "damiano-token"}


@app.delete("/api/email/templates/{tid}")
def delete_email_template(tid: str, type: str = Query(..., description="'subject' o 'body'")):
    if type not in ("subject", "body"):
        raise HTTPException(status_code=400, detail="type deve essere 'subject' o 'body'")

    tpls = load_email_templates()
    arr = tpls.get(type, [])
    new_arr = [x for x in arr if x.get("id") != tid]

    if len(new_arr) == len(arr):
        raise HTTPException(status_code=404, detail="Template non trovato")

    tpls[type] = new_arr
    save_email_templates(tpls)

    s = load_email_settings()
    if type == "subject" and s.get("subject_template_id") == tid:
        s["subject_template_id"] = None
        save_email_settings(s)
    if type == "body" and s.get("body_template_id") == tid:
        s["body_template_id"] = None
        save_email_settings(s)

    return {"ok": True, "deleted_id": tid, "type": type}

    # carica archivio modelli
    tpls = load_email_templates()
    arr = tpls.get(type, [])
    new_arr = [x for x in arr if x.get("id") != tid]

    if len(new_arr) == len(arr):
        raise HTTPException(status_code=404, detail="Template non trovato")

    # salva archivio aggiornato
    tpls[type] = new_arr
    save_email_templates(tpls)

    # se era agganciato come "attivo" nei settings, sgancialo
    s = load_email_settings()
    if type == "subject" and s.get("subject_template_id") == tid:
        s["subject_template_id"] = None
        save_email_settings(s)
    if type == "body" and s.get("body_template_id") == tid:
        s["body_template_id"] = None
        save_email_settings(s)

    return {"ok": True, "deleted_id": tid, "type": type}


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
@app.post("/records")
def create_record(rec: Record):
    data = load_records()
    now = _now_iso()

    # Duplicate se coincidono: persona + defunto (normalizzati)
    for r in data:
        if (
            _norm(r.get("nome")) == _norm(rec.nome) and
            _norm(r.get("cognome")) == _norm(rec.cognome) and
            _norm(r.get("email")) == _norm(rec.email) and
            _norm(r.get("telefono_numero")) == _norm(rec.telefono_numero) and
            _norm(r.get("def_nome")) == _norm(rec.def_nome) and
            _norm(r.get("def_cognome")) == _norm(rec.def_cognome)
            # Se vuoi includere anche la data del decesso, togli il commento qui sotto:
            # and _norm(r.get("def_data")) == _norm(rec.def_data)
        ):
            raise HTTPException(
                status_code=409,
                detail="Contatto duplicato (persona + defunto già presente)"
            )

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
# === EMAIL: SETTINGS (valori ATTIVI) ===
@app.get("/api/email/settings")
def get_email_settings():
    s = load_email_settings()
    return {
        "subject": s.get("subject", ""),
        "body": s.get("body", ""),
        "subject_template_id": s.get("subject_template_id"),
        "body_template_id": s.get("body_template_id"),
        "updated_at": s.get("updated_at"),
    }

@app.put("/api/email/settings")
def update_email_settings(body: EmailSettingsIn):
    s = load_email_settings()
    if body.subject is not None:
        s["subject"] = body.subject
    if body.body is not None:
        s["body"] = body.body
    if body.subject_template_id is not None:
        s["subject_template_id"] = body.subject_template_id
    if body.body_template_id is not None:
        s["body_template_id"] = body.body_template_id

    s["updated_at"] = _now_iso()
    save_email_settings(s)
    return {"ok": True}


# === EMAIL: TEMPLATES (modelli salvati/richiamabili) ===
@app.get("/api/email/templates")
def list_email_templates(type: str):
    """
    Query string: ?type=subject | body
    Ritorna la lista dei modelli salvati per il tipo richiesto.
    """
    if type not in ("subject", "body"):
        raise HTTPException(status_code=400, detail="type deve essere 'subject' o 'body'")
    alltpl = load_email_templates()
    return alltpl.get(type, [])

@app.post("/api/email/templates")
def create_email_template(tpl: EmailTemplateIn):
    """
    Crea un nuovo modello (subject/body).
    Per comodità, lo rende anche 'attivo' aggiornando email_settings.
    """
    t = tpl.type
    if t not in ("subject", "body"):
        raise HTTPException(status_code=400, detail="type deve essere 'subject' o 'body'")

    alltpl = load_email_templates()
    new_item = {
        "id": uuid.uuid4().hex,
        "name": tpl.name,
        "content": tpl.content,
        "created_at": _now_iso(),
    }
    # inserisco in testa alla lista del tipo
    alltpl.setdefault(t, [])
    alltpl[t].insert(0, new_item)
    save_email_templates(alltpl)

    # aggiorno anche i valori ATTIVI
    s = load_email_settings()
    if t == "subject":
        s["subject"] = tpl.content
        s["subject_template_id"] = new_item["id"]
    else:
        s["body"] = tpl.content
        s["body_template_id"] = new_item["id"]
    s["updated_at"] = _now_iso()
    save_email_settings(s)

    return {"id": new_item["id"], "ok": True}



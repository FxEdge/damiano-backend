from fastapi import FastAPI, HTTPException, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime, timezone, date, timedelta
from zoneinfo import ZoneInfo  # per fuso Europe/Rome
import os, json, uuid, hashlib, re
# Import servizi email
from email_service import send_email, render_template
# ⬅️ Import funzioni di scheduling (punto 2)
from utils_scheduler import load_last_run_date, save_last_run_now, _now_date

APP_VERSION = "1.1.0"

# === APP ===
app = FastAPI(title="Damiano API", version=APP_VERSION)

# === CONFIG / STORAGE ===
import shutil

# file di settings per ricordare la cartella scelta anche ai riavvii
SETTINGS_PATH = os.environ.get("SETTINGS_PATH", "app_settings.json")

def _load_settings():
    return _load_json(SETTINGS_PATH, {})

def get_data_dir() -> str:
    """Ordine di priorità: setting salvato -> ENV DATA_DIR -> 'data'"""
    s = _load_settings()
    return s.get("data_dir") or os.environ.get("DATA_DIR", "data")

def _recompute_paths():
    """(Ri)calcola tutte le path quando cambia la cartella dati."""
    global DATA_DIR, RECORDS_PATH, AUTH_PATH, EMAILS_PATH, EMAIL_SETTINGS_PATH, EMAIL_TEMPLATES_PATH
    DATA_DIR = get_data_dir()
    os.makedirs(DATA_DIR, exist_ok=True)
    RECORDS_PATH = os.path.join(DATA_DIR, "records.json")
    AUTH_PATH = os.path.join(DATA_DIR, "auth.json")
    EMAILS_PATH = os.path.join(DATA_DIR, "sent_emails.json")
    EMAIL_SETTINGS_PATH = os.path.join(DATA_DIR, "email_settings.json")
    EMAIL_TEMPLATES_PATH = os.path.join(DATA_DIR, "email_templates.json")

_recompute_paths()  # inizializza una volta


# --- CONFIG GLOBALI ---
SCHEDULER_SECRET = os.environ.get("SCHEDULER_SECRET", "demo")  # <-- cambia in produzione
TZ_ROME = ZoneInfo("Europe/Rome")

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
    _load_json(EMAIL_SETTINGS_PATH, {
        "subject": "In memoria di {{NOME}} {{COGNOME}}",
        "body": "Gentile {{NOME}} {{COGNOME}},\nTi ricordiamo con affetto in questa ricorrenza."
    })
    _load_json(EMAIL_TEMPLATES_PATH, {"subject": [], "body": []})
_ensure_email_files()

def load_email_settings():
    return _load_json(EMAIL_SETTINGS_PATH, {"subject": "", "body": ""})

def save_email_settings(data: dict):
    _save_json(EMAIL_SETTINGS_PATH, data)

def load_email_templates():
    return _load_json(EMAIL_TEMPLATES_PATH, {"subject": [], "body": []})

def save_email_templates(data: dict):
    _save_json(EMAIL_TEMPLATES_PATH, data)

# === DATE HELPERS ===
def _parse_yyyy_mm_dd(s: Optional[str]) -> Optional[date]:
    try:
        if not s: return None
        y, m, d = map(int, s.split("-"))
        return date(y, m, d)
    except Exception:
        return None

def _today_rome_date() -> date:
    return datetime.now(TZ_ROME).date()

def _add_years_safe(d: date, years: int) -> date:
    """Aggiunge anni gestendo il 29/02 -> 28/02 se anno non bisestile."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # 29/02 -> 28/02 nell'anno non bisestile
        return d.replace(month=2, day=28, year=d.year + years)

def _compute_first_ricorrenza(def_d: Optional[str]) -> Optional[str]:
    """Prima ricorrenza = def_data + 1 anno."""
    gd = _parse_yyyy_mm_dd(def_d)
    if not gd:
        return None
    return _add_years_safe(gd, 1).isoformat()

def _due_today(rec: dict, today: date) -> bool:
    """
    True se OGGI è il giorno di invio:
    (prossima_ricorrenza - giorni_prima) == today
    """
    pr = _parse_yyyy_mm_dd(rec.get("prossima_ricorrenza"))
    gp = rec.get("giorni_prima")
    if not pr or gp is None:
        return False
    try:
        gp = int(gp)
    except Exception:
        return False
    reminder = pr - timedelta(days=gp)
    return reminder == today

def _parse_recipients(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    for sep in [",", ";"]:
        raw = raw.replace(sep, " ")
    parts = [t.strip() for t in raw.split() if "@" in t and "." in t]
    seen, out = set(), []
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
        "{{DATA_RIC}}": rec.get("prossima_ricorrenza") or "",
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
    def_nome: Optional[str] = None
    def_cognome: Optional[str] = None
    def_data: Optional[str] = None
    giorni_prima: Optional[int] = None
    oggetto: Optional[str] = None
    corpo: Optional[str] = None

    # NUOVO
    prossima_ricorrenza: Optional[str] = None

    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    sospendi_invio: Optional[bool] = False

class EmailSettingsIn(BaseModel):
    subject: Optional[str] = None
    body: Optional[str] = None
    subject_template_id: Optional[str] = None
    body_template_id: Optional[str] = None

class EmailTemplateIn(BaseModel):
    type: str  # 'subject' | 'body'
    name: str
    content: str

# === CORS ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === HEALTH ===
@app.get("/health")
def health():
    return {"status": "ok", "version": APP_VERSION, "time": _now_iso()}

# === TEST INVIO REALE (NEW) ===
@app.post("/admin/send-test-email")
def send_test_email(to: str, x_secret: Optional[str] = Header(None)):
    if x_secret != SCHEDULER_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    subject = "Test Damiano – invio email"
    html = "<div style='font-family:system-ui'>Ciao 👋<br>Questa è una mail di TEST dal backend Damiano.</div>"
    try:
        send_email(to, subject, html, plain_fallback="Ciao, questa è una mail di TEST dal backend Damiano.")
        return {"ok": True, "to": to}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore invio: {e}")

# === GENERIC EMAIL SENDER (NEW) ===
class SendEmailIn(BaseModel):
    to: str         # uno o più indirizzi (separati da virgola o punto e virgola)
    subject: str
    message: str    # testo semplice; verrà inviato anche come HTML minimale

@app.post("/send-email")
def send_email_generic(body: SendEmailIn, x_secret: Optional[str] = Header(None)):
    if x_secret != SCHEDULER_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    recipients = _parse_recipients(body.to)
    if not recipients:
        raise HTTPException(status_code=400, detail="Nessun indirizzo email valido in 'to'.")

    sent, failed = [], []
    for addr in recipients:
        try:
            html = f"<div style='font-family:system-ui; white-space:pre-wrap'>{body.message}</div>"
            send_email(addr, body.subject, html, plain_fallback=body.message)
            sent.append(addr)
        except Exception as e:
            failed.append({"to": addr, "error": str(e)})

    return {"ok": len(failed) == 0, "sent": sent, "failed": failed}

# === INVIO IMMEDIATO (con modalità test) ===
from fastapi import Query

@app.post("/admin/send-now/{rid}")
def admin_send_now(
    rid: str,
    x_secret: Optional[str] = Header(None),
    test: bool = Query(False)   # <-- se True non avanza la ricorrenza
):
    if x_secret != SCHEDULER_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    records = load_records()
    rec = next((r for r in records if r.get("id") == rid), None)
    if not rec:
        raise HTTPException(status_code=404, detail="Record non trovato")

    # destinatari
    to_list = _parse_recipients(rec.get("email"))
    if not to_list:
        raise HTTPException(status_code=400, detail="Record senza email valida")

    # subject/body (per-record se presenti, altrimenti globali)
    settings = load_email_settings()
    subject_raw = rec.get("oggetto") or (settings.get("subject") or "In memoria")
    body_raw    = rec.get("corpo")   or (settings.get("body")    or "Un pensiero in questa ricorrenza.")
    subject = _fill_placeholders(subject_raw, rec)
    body    = _fill_placeholders(body_raw, rec)

    # invio reale
    try:
        html = f"<div style='font-family:system-ui; white-space:pre-wrap'>{body}</div>"
        send_email(to_list[0], subject, html, plain_fallback=body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore invio: {e}")

    # log invio
    sent_rows = _load_sent()
    today = _today_rome_date().isoformat()
    sent_rows.append({
        "record_id": rid,
        "to": to_list,
        "subject": subject,
        "body_usato": body,
        "scheduled_for": today,
        "due_date": today,
        "sent_at": _now_iso(),
        "stato": "test" if test else "ok",   # <-- segna test
        "errore": None,
    })
    _save_sent(sent_rows)

    # se NON test, avanza la prossima ricorrenza di 1 anno
    if not test:
        pr = _parse_yyyy_mm_dd(rec.get("prossima_ricorrenza"))
        if pr:
            rec["prossima_ricorrenza"] = _add_years_safe(pr, 1).isoformat()
            save_records(records)

    return {"ok": True, "record_id": rid, "test": test}

# === CATCH-UP HELPERS (NEW) ===
def _already_sent(sent_log: list, record_id: Optional[str], due_date_iso: str) -> bool:
    """
    Ritorna True se per questo record è già stato loggato un invio
    per la ricorrenza 'due_date_iso' (idempotenza).
    """
    if not record_id:
        return False
    for e in sent_log:
        if e.get("record_id") == record_id and e.get("due_date") == due_date_iso:
            return True
    return False

def _date_range(d0: date, d1: date):
    cur = d0
    while cur <= d1:
        yield cur
        cur = cur + timedelta(days=1)
# === INVIO CON CATCH-UP (NEW) ===
def send_emails_catchup():
    """
    Alla prima esecuzione utile, recupera e invia tutte le mail
    non inviate dei giorni passati (tra last_run+1 e oggi) evitando duplicati.
    Mantiene lo stesso comportamento della /admin/send-due-emails:
    - usa subject/body per-record se presenti, altrimenti globali
    - avanza 'prossima_ricorrenza' di +1 anno quando invia
    - logga in sent_emails.json
    """
    today = _today_rome_date()
    records = load_records()
    sent_rows = _load_sent()

    settings = load_email_settings()
    default_subject = settings.get("subject") or "In memoria"
    default_body    = settings.get("body") or "Un pensiero in questa ricorrenza."

    # intervallo: (last_run + 1) .. today
    last_run_day = load_last_run_date()
    start_day = last_run_day + timedelta(days=1)

    processed, skipped, errors = [], [], []

    for day in _date_range(start_day, today):
        day_iso = day.isoformat()

        for r in records:
            try:
                if r.get("sospendi_invio") is True:
                    continue
                # Ricicliamo la logica già esistente: "è dovuto in questo giorno?"
                if not _due_today(r, day):
                    continue

                rid = r.get("id")
                if _already_sent(sent_rows, rid, day_iso):
                    # già loggata per quella ricorrenza -> salta (idempotenza)
                    continue

                to_list = _parse_recipients(r.get("email"))
                if not to_list:
                    skipped.append({"id": rid, "reason": "no_email", "due_date": day_iso})
                    continue

                subject_raw = r.get("oggetto") or default_subject
                body_raw    = r.get("corpo")   or default_body
                subject = _fill_placeholders(subject_raw, r)
                body    = _fill_placeholders(body_raw, r)

                # --- qui puoi passare a invio reale con send_email(...) se vuoi ---
                # Esempio (HTML semplice = body, fallback = body):
                # send_email(to_list[0], subject, f"<pre>{body}</pre>", plain_fallback=body)

                # Per ora manteniamo stesso comportamento della tua rotta: log simulato
                log_row = {
                    "record_id": rid,
                    "to": to_list,
                    "subject": subject,
                    "body_usato": body,
                    "nome": r.get("nome"),
                    "cognome": r.get("cognome"),
                    "def_nome": r.get("def_nome"),
                    "def_cognome": r.get("def_cognome"),
                    "scheduled_for": day_iso,
                    "due_date": day_iso,              # <-- chiave per anti-duplicato
                    "sent_at": _now_iso(),
                    "stato": "ok",
                    "errore": None,
                }
                sent_rows.append(log_row)
                processed.append({"id": rid, "to": to_list, "due_date": day_iso})

                # Avanza la prossima ricorrenza di +1 anno (coerente con /admin/send-due-emails)
                pr = _parse_yyyy_mm_dd(r.get("prossima_ricorrenza"))
                if pr:
                    r["prossima_ricorrenza"] = _add_years_safe(pr, 1).isoformat()

            except Exception as e:
                errors.append({"id": r.get("id"), "due_date": day_iso, "error": str(e)})

    # salva aggiornamenti (ricorrenze avanzate) + log
    save_records(records)
    _save_sent(sent_rows)

    # aggiorna il last_run
    save_last_run_now()

    return {
        "processed_range": [start_day.isoformat(), today.isoformat()],
        "counts": {"processed": len(processed), "skipped": len(skipped), "errors": len(errors)},
        "processed": processed,
        "skipped": skipped,
        "errors": errors,
    }
# === SCHEDULER: CATCH-UP ENDPOINT (NEW) ===
@app.post("/admin/catchup")
def run_catchup(x_secret: Optional[str] = Header(None)):
    if x_secret != SCHEDULER_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return send_emails_catchup()
# === ADMIN: STORAGE PATH (leggi/imposta cartella dati) ===
class StorageIn(BaseModel):
    path: str

@app.get("/admin/storage")
def admin_get_storage(x_secret: Optional[str] = Header(None)):
    if x_secret != SCHEDULER_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
    files = []
    try:
        if os.path.isdir(DATA_DIR):
            files = sorted(os.listdir(DATA_DIR))
    except Exception:
        files = []
    return {"data_dir": DATA_DIR, "files": files}

@app.put("/admin/storage")
def admin_set_storage(body: StorageIn, x_secret: Optional[str] = Header(None)):
    if x_secret != SCHEDULER_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not body.path or not str(body.path).strip():
        raise HTTPException(status_code=400, detail="Percorso non valido")

    new_dir = os.path.abspath(str(body.path).strip())
    try:
        os.makedirs(new_dir, exist_ok=True)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Impossibile creare cartella: {e}")

    old_dir = DATA_DIR
    # migra i file noti se non esistono già nella nuova cartella
    if os.path.isdir(old_dir) and os.path.abspath(old_dir) != new_dir:
        for name in ["records.json", "auth.json", "sent_emails.json", "email_settings.json", "email_templates.json"]:
            src = os.path.join(old_dir, name)
            dst = os.path.join(new_dir, name)
            if os.path.exists(src) and not os.path.exists(dst):
                try:
                    shutil.copy2(src, dst)
                except Exception:
                    pass

    # salva scelta in settings e ricalcola le path globali
    s = _load_settings()
    s["data_dir"] = new_dir
    _save_json(SETTINGS_PATH, s)

    _recompute_paths()
    _ensure_email_files()  # assicura i file minimi nella nuova cartella

    return {"ok": True, "data_dir": DATA_DIR}

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
        # MIGRAZIONE: se manca prossima_ricorrenza ma c'è def_data -> calcola
        if not r.get("prossima_ricorrenza") and r.get("def_data"):
            pr = _compute_first_ricorrenza(r.get("def_data"))
            if pr:
                r["prossima_ricorrenza"] = pr
                changed = True
    if changed:
        _save_json(RECORDS_PATH, data)
    return data

def save_records(data: List[dict]):
    _save_json(RECORDS_PATH, data)

# === AUTH ===
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

# === RECORDS CRUD ===
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
            # volendo aggiungere anche la data del decesso, decommentare:
            # and _norm(r.get("def_data")) == _norm(rec.def_data)
        ):
            raise HTTPException(status_code=409, detail="Contatto duplicato")

    obj = rec.model_dump()
    obj["id"] = uuid.uuid4().hex
    obj["created_at"] = now
    obj["updated_at"] = now

    # Imposta la prima ricorrenza se possibile
    if not obj.get("prossima_ricorrenza"):
        obj["prossima_ricorrenza"] = _compute_first_ricorrenza(obj.get("def_data"))

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

            # Se la def_data è cambiata -> reset prima ricorrenza = def_data + 1 anno
            if incoming.get("def_data") != r.get("def_data"):
                updated["prossima_ricorrenza"] = _compute_first_ricorrenza(incoming.get("def_data"))

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

# === EMAIL: SETTINGS ===
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
    if body.subject is not None: s["subject"] = body.subject
    if body.body is not None: s["body"] = body.body
    if body.subject_template_id is not None: s["subject_template_id"] = body.subject_template_id
    if body.body_template_id is not None: s["body_template_id"] = body.body_template_id
    s["updated_at"] = _now_iso()
    save_email_settings(s)
    return {"ok": True}

# === EMAIL: TEMPLATES ===
@app.get("/api/email/templates")
def list_email_templates(type: str):
    if type not in ("subject", "body"):
        raise HTTPException(status_code=400, detail="type deve essere 'subject' o 'body'" )
    alltpl = load_email_templates()
    return alltpl.get(type, [])

@app.post("/api/email/templates")
def create_email_template(tpl: EmailTemplateIn):
    t = tpl.type
    if t not in ("subject", "body"):
        raise HTTPException(status_code=400, detail="type deve essere 'subject' o 'body'")
    alltpl = load_email_templates()
    new_item = {"id": uuid.uuid4().hex, "name": tpl.name, "content": tpl.content, "created_at": _now_iso()}
    alltpl.setdefault(t, [])
    alltpl[t].insert(0, new_item)
    save_email_templates(alltpl)
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

@app.delete("/api/email/templates/{tid}")
def delete_email_template(tid: str, type: str = Query(...)):
    if type not in ("subject", "body"):
        raise HTTPException(status_code=400, detail="type deve essere 'subject' o 'body'" )
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
    if type == "body" and s.get("body_template_id") == tid:
        s["body_template_id"] = None
    save_email_settings(s)
    return {"ok": True, "deleted_id": tid, "type": type}





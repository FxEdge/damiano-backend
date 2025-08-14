from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Damiano API")

# Per test lascia "*". Poi limita a: ["https://damiano-frontend.onrender.com"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- MODELS ----
class LoginRequest(BaseModel):
    email: str | None = None
    password: str

class LoginResponse(BaseModel):
    token: str

# ---- ROUTES ESISTENTI ----
@app.get("/")
def root():
    return {"status": "ok", "service": "damiano-backend"}

@app.get("/health")
def health_plain():
    return "ok"

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/api/ping")
def ping():
    return {"pong": True}

# ---- AUTH (NUOVO) ----
@app.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest):
    # password iniziale: demo
    if body.password != "demo":
        raise HTTPException(status_code=401, detail="Credenziali non valide")
    return {"token": "damiano-token"}


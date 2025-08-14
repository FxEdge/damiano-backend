from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# CORS aperto per test. Poi limita a: ["https://damiano-frontend.onrender.com"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


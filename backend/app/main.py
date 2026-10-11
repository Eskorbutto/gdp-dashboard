from fastapi import FastAPI

from app.rutas import auth, catalogo

app = FastAPI(title="Plataforma Call Center", version="0.1.0")
app.include_router(auth.router)
app.include_router(catalogo.router)


@app.get("/salud", tags=["sistema"])
def salud() -> dict[str, str]:
    return {"estado": "ok"}

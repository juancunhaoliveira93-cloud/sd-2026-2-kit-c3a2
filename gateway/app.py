"""
API Gateway - porta de entrada ÚNICA da plataforma (C3.A2).

Une os módulos da equipe:
  auth.py        JWT (login + proteção das rotas)            -> Carine
  ratelimit.py   limite de requisições por cliente           -> Carine
  resiliencia.py timeout + retentativa + circuit breaker     -> Gustavo
  telemetria.py  rastreamento distribuído (OpenTelemetry)    -> Lucas

Rotas:
  GET  /saude                público   estado do gateway e dos circuitos
  POST /login                público   emite o JWT (limite por IP)
  POST /predict              JWT       enfileira (202) via serviço de inferência
  GET  /resultado/{id}       JWT       consulta o resultado
  POST /predict-sync         JWT       inferência síncrona (para comparar latência)
  POST /similares            JWT       busca por similaridade (armazenamento vetorial)

Rodar local: uvicorn app:app --port 8000
"""
import os
import time

from fastapi import Depends, FastAPI, HTTPException, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import telemetria
from auth import Credenciais, emitir_token
from ratelimit import limitar_cliente, limitar_login
from resiliencia import CircuitBreaker, ServicoIndisponivel, chamar

URL_INFERENCIA = os.getenv("URL_INFERENCIA", "http://localhost:8001")
URL_VETORIAL = os.getenv("URL_VETORIAL", "http://localhost:8002")

breaker_inferencia = CircuitBreaker("inferencia")
breaker_vetorial = CircuitBreaker("vetorial")

app = FastAPI(title="Gateway - C3.A2", version="1.0.0")
telemetria.configurar("gateway", app)


class Entrada(BaseModel):
    texto: str = Field(min_length=1, max_length=2000)


class PedidoSimilares(BaseModel):
    texto: str = Field(min_length=1, max_length=2000)
    k: int = Field(default=3, ge=1, le=20)


@app.middleware("http")
async def registrar(request: Request, call_next):
    """Log de requisições: método, rota, status e tempo (sem query string, sem corpo)."""
    inicio = time.time()
    resposta = await call_next(request)
    print(f"[gateway] {request.method} {request.url.path} "
          f"-> {resposta.status_code} ({(time.time() - inicio) * 1000:.1f}ms)")
    return resposta


@app.exception_handler(ServicoIndisponivel)
async def servico_indisponivel(_request: Request, exc: ServicoIndisponivel):
    cabecalhos = {"Retry-After": str(exc.retry_after)} if exc.retry_after else {}
    return JSONResponse(status_code=503, content={"detail": exc.detalhe}, headers=cabecalhos)


def _repassar(resposta):
    """Devolve o JSON do serviço interno; repassa erros 4xx (ex.: 404) ao cliente."""
    try:
        corpo = resposta.json()
    except ValueError:
        corpo = {"detail": "resposta invalida do servico interno"}
    if resposta.status_code >= 400:
        raise HTTPException(status_code=resposta.status_code,
                            detail=corpo.get("detail", corpo) if isinstance(corpo, dict) else corpo)
    return corpo


@app.get("/saude")
def saude():
    return {"status": "ok",
            "circuitos": {"inferencia": breaker_inferencia.estado,
                          "vetorial": breaker_vetorial.estado}}


@app.post("/login", dependencies=[Depends(limitar_login)])
def login(credenciais: Credenciais):
    return emitir_token(credenciais.usuario, credenciais.senha)


@app.post("/predict", status_code=202)
def predict(entrada: Entrada, _usuario: str = Depends(limitar_cliente)):
    r = chamar("POST", f"{URL_INFERENCIA}/predict", breaker_inferencia,
               json=entrada.model_dump())
    return _repassar(r)


@app.get("/resultado/{tarefa_id}")
def resultado(tarefa_id: str = Path(pattern=r"^[0-9a-fA-F-]{36}$"),
              _usuario: str = Depends(limitar_cliente)):
    r = chamar("GET", f"{URL_INFERENCIA}/resultado/{tarefa_id}", breaker_inferencia)
    return _repassar(r)


@app.post("/predict-sync")
def predict_sync(entrada: Entrada, _usuario: str = Depends(limitar_cliente)):
    r = chamar("POST", f"{URL_INFERENCIA}/predict-sync", breaker_inferencia,
               json=entrada.model_dump())
    return _repassar(r)


@app.post("/similares")
def similares(pedido: PedidoSimilares, _usuario: str = Depends(limitar_cliente)):
    r = chamar("POST", f"{URL_VETORIAL}/buscar", breaker_vetorial,
               json=pedido.model_dump())
    return _repassar(r)

"""
Serviço de inferência - interface REST (C1.A2 adaptado para a plataforma C3.A2).

  POST /predict        -> enfileira e devolve {"id"} com 202 (assíncrono)
  GET  /resultado/{id} -> status/resultado (404 se não existe ou expirou)
  POST /predict-sync   -> inferência síncrona (usada na comparação de latência)
  GET  /saude

Este serviço NÃO é exposto ao público: só o gateway fala com ele.
Rodar local: uvicorn app.api_rest:app --port 8001
"""
import time

import redis
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import fila, telemetria
from app.modelo import carregar_modelo

app = FastAPI(title="Servico de Inferencia - C3.A2", version="1.0.0")
telemetria.configurar("inferencia", app)

modelo = None


class Entrada(BaseModel):
    texto: str = Field(min_length=1, max_length=2000)


@app.on_event("startup")
def _subir():
    """Carrega o modelo UMA vez, na subida."""
    global modelo
    inicio = time.time()
    modelo = carregar_modelo()
    print(f"[inferencia] modelo carregado em {time.time() - inicio:.3f}s")


@app.middleware("http")
async def registrar(request: Request, call_next):
    """Log de requisições: método, rota, status e tempo. Nunca o conteúdo (LGPD)."""
    inicio = time.time()
    resposta = await call_next(request)
    print(f"[inferencia] {request.method} {request.url.path} "
          f"-> {resposta.status_code} ({(time.time() - inicio) * 1000:.1f}ms)")
    return resposta


@app.exception_handler(Exception)
async def erro_inesperado(request: Request, exc: Exception):
    """Último recurso: erro não previsto vira 500 com mensagem clara (sem vazar detalhes)."""
    print(f"[inferencia] ERRO {request.method} {request.url.path}: {type(exc).__name__}")
    return JSONResponse(status_code=500, content={"detail": "erro interno no servico de inferencia"})


def _exigir_modelo():
    if modelo is None:
        raise HTTPException(status_code=503, detail="modelo ainda nao carregado")


def _prever(texto: str) -> dict:
    """Executa o modelo; falha do modelo vira 500 explícito."""
    _exigir_modelo()
    try:
        return modelo.prever(texto)
    except Exception as erro:  # noqa: BLE001
        print(f"[inferencia] ERRO no modelo: {type(erro).__name__}")
        raise HTTPException(status_code=500, detail="falha ao executar o modelo")


@app.get("/saude")
def saude():
    return {"status": "ok", "modelo_carregado": modelo is not None, "redis": fila.ping()}


@app.post("/predict-sync")
def predict_sync(entrada: Entrada):
    if not entrada.texto.strip():
        raise HTTPException(status_code=400, detail="texto vazio")
    inicio = time.time()
    resultado = _prever(entrada.texto)
    resultado["tempo_ms"] = round((time.time() - inicio) * 1000, 2)
    return resultado


@app.post("/predict", status_code=202)
def predict(entrada: Entrada):
    if not entrada.texto.strip():
        raise HTTPException(status_code=400, detail="texto vazio")
    try:
        return {"id": fila.enfileirar(entrada.texto), "status": "processando"}
    except redis.RedisError as erro:
        print(f"[inferencia] ERRO na fila: {type(erro).__name__}")
        raise HTTPException(status_code=503, detail="fila indisponivel, tente novamente")


@app.get("/resultado/{tarefa_id}")
def resultado(tarefa_id: str):
    try:
        encontrado = fila.buscar_resultado(tarefa_id)
    except redis.RedisError as erro:
        print(f"[inferencia] ERRO na fila: {type(erro).__name__}")
        raise HTTPException(status_code=503, detail="fila indisponivel, tente novamente")
    if encontrado is None:
        raise HTTPException(status_code=404, detail="resultado nao encontrado ou expirado")
    return encontrado

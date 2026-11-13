"""
Auxiliares de fila (Redis) - lado PRODUTOR (usado pela API REST).

Mudanças em relação ao C1.A2:
  - o status "na_fila" é gravado ANTES do rpush (antes, o worker podia terminar e o
    status "na_fila" sobrescrevia o resultado "pronto": condição de corrida);
  - resultados expiram sozinhos (RESULTADO_TTL_S) -> LGPD, retenção limitada;
  - a tarefa carrega o contexto de rastreamento (traceparent) para o worker.
"""
import json
import os
import uuid

import redis

from app import telemetria

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
FILA_TAREFAS = "tarefas"
PREFIXO_RESULTADO = "resultado:"
RESULTADO_TTL_S = int(os.getenv("RESULTADO_TTL_S", "3600"))

_cliente = None


def cliente():
    global _cliente
    if _cliente is None:
        _cliente = redis.from_url(REDIS_URL, decode_responses=True)
    return _cliente


def enfileirar(texto: str) -> str:
    """Coloca uma tarefa na fila e devolve o id para consulta posterior."""
    tarefa_id = str(uuid.uuid4())
    with telemetria.tracer().start_as_current_span("fila.enfileirar") as span:
        span.set_attribute("tarefa.id", tarefa_id)
        r = cliente()
        r.set(PREFIXO_RESULTADO + tarefa_id, json.dumps({"status": "na_fila"}),
              ex=RESULTADO_TTL_S)
        r.rpush(FILA_TAREFAS, json.dumps({
            "id": tarefa_id,
            "texto": texto,
            "traceparent": telemetria.injetar_contexto(),
        }))
    return tarefa_id


def buscar_resultado(tarefa_id: str):
    bruto = cliente().get(PREFIXO_RESULTADO + tarefa_id)
    return json.loads(bruto) if bruto else None


def ping() -> bool:
    try:
        return bool(cliente().ping())
    except redis.RedisError:
        return False

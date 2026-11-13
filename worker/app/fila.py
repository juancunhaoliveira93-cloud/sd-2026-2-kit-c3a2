"""
Fila (Redis) - lado CONSUMIDOR (usado pelo worker).

  - proxima_tarefa()       : BLPOP (bloqueia até chegar tarefa)
  - guardar_resultado()    : grava com TTL (LGPD)
  - enviar_dead_letter()   : tarefa que falhou 3x vai para a DLQ.
      O conteúdo fica em "dlq:<id>" COM expiração (DLQ_TTL_S); a lista "tarefas_dlq"
      guarda só os ids. Assim o texto do usuário não fica retido para sempre.
"""
import json
import os

import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
FILA_TAREFAS = "tarefas"
FILA_DLQ = "tarefas_dlq"
PREFIXO_RESULTADO = "resultado:"
PREFIXO_DLQ = "dlq:"
RESULTADO_TTL_S = int(os.getenv("RESULTADO_TTL_S", "3600"))
DLQ_TTL_S = int(os.getenv("DLQ_TTL_S", "86400"))

_cliente = None


def cliente():
    global _cliente
    if _cliente is None:
        _cliente = redis.from_url(REDIS_URL, decode_responses=True)
    return _cliente


def proxima_tarefa(timeout: int = 5):
    item = cliente().blpop(FILA_TAREFAS, timeout=timeout)
    return None if item is None else json.loads(item[1])


def guardar_resultado(tarefa_id: str, resultado: dict) -> None:
    cliente().set(PREFIXO_RESULTADO + tarefa_id, json.dumps(resultado), ex=RESULTADO_TTL_S)


def enviar_dead_letter(tarefa: dict, motivo: str) -> None:
    r = cliente()
    r.set(PREFIXO_DLQ + tarefa["id"],
          json.dumps({"tarefa": tarefa, "motivo": motivo}), ex=DLQ_TTL_S)
    r.rpush(FILA_DLQ, tarefa["id"])
    guardar_resultado(tarefa["id"], {"status": "erro",
                                     "detalhe": "falha apos todas as tentativas (DLQ)"})

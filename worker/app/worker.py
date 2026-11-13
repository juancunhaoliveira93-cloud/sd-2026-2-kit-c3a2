"""
Worker: consome a fila, executa a inferência e guarda o resultado.

  - Continua o TRACE iniciado no gateway (span "worker.processar" é filho do
    span que enfileirou) -> rastreamento gateway -> fila -> worker.
  - Retentativa com espera progressiva (1s, 2s, 4s); depois de MAX_TENTATIVAS, DLQ.
  - Indexa o vetor no serviço vetorial em "melhor esforço": se ele estiver fora do ar,
    a tarefa NÃO falha (degradação graciosa).
  - Log: id, tamanho e tempo. NUNCA o texto (LGPD).

Rodar: python -m app.worker     (suba N réplicas: docker compose up --scale worker=3)
"""
import os
import time

import redis
import requests
from opentelemetry.trace import SpanKind, Status, StatusCode

from app import fila, telemetria
from app.modelo import carregar_modelo

MAX_TENTATIVAS = int(os.getenv("MAX_TENTATIVAS", "3"))
ESPERA_BASE_S = float(os.getenv("RETRY_ESPERA_BASE_S", "1"))
URL_VETORIAL = os.getenv("URL_VETORIAL", "")


def indexar_vetor(tarefa_id: str, texto: str, sentimento: str) -> None:
    if not URL_VETORIAL:
        return
    try:
        requests.post(f"{URL_VETORIAL}/indexar", timeout=(1.5, 3), json={
            "id": tarefa_id, "texto": texto, "metadados": {"sentimento": sentimento}})
    except requests.RequestException as e:
        print(f"[worker] AVISO: vetorial indisponivel ({type(e).__name__}); seguindo sem indexar")


def processar(modelo, tarefa: dict) -> bool:
    tarefa_id = tarefa["id"]
    texto = tarefa.get("texto", "")
    fila.guardar_resultado(tarefa_id, {"status": "processando"})

    for tentativa in range(1, MAX_TENTATIVAS + 1):
        inicio = time.time()
        try:
            resultado = modelo.prever(texto)
            resultado["status"] = "pronto"
            resultado["tempo_ms"] = round((time.time() - inicio) * 1000, 2)
            fila.guardar_resultado(tarefa_id, resultado)
            indexar_vetor(tarefa_id, texto, resultado["sentimento"])
            print(f"[worker] OK id={tarefa_id} tamanho={len(texto)} "
                  f"tempo={resultado['tempo_ms']}ms tentativa={tentativa}")
            return True
        except Exception as erro:  # noqa: BLE001
            print(f"[worker] ERRO id={tarefa_id} tentativa {tentativa}/{MAX_TENTATIVAS}: "
                  f"{type(erro).__name__}")
            if tentativa < MAX_TENTATIVAS:
                time.sleep(ESPERA_BASE_S * 2 ** (tentativa - 1))

    print(f"[worker] FALHA id={tarefa_id}: enviando para dead-letter")
    fila.enviar_dead_letter(tarefa, "falhou apos todas as tentativas")
    return False


def main():
    telemetria.configurar("worker")
    tracer = telemetria.tracer("worker")
    print("[worker] carregando modelo...")
    modelo = carregar_modelo()
    print("[worker] pronto. aguardando tarefas (Ctrl+C para sair)")

    while True:
        try:
            tarefa = fila.proxima_tarefa(timeout=5)
        except redis.RedisError as e:
            print(f"[worker] Redis indisponivel ({type(e).__name__}); tentando em 2s")
            time.sleep(2)
            continue
        if tarefa is None:
            continue

        contexto = telemetria.extrair_contexto(tarefa.get("traceparent"))
        with tracer.start_as_current_span("worker.processar", context=contexto,
                                          kind=SpanKind.CONSUMER) as span:
            span.set_attribute("tarefa.id", tarefa["id"])
            try:
                ok = processar(modelo, tarefa)
            except redis.RedisError as e:
                print(f"[worker] Redis falhou ao gravar ({type(e).__name__})")
                ok = False
            if not ok:
                span.set_status(Status(StatusCode.ERROR))


if __name__ == "__main__":
    main()

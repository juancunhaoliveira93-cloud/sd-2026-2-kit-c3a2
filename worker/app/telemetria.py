"""
Observabilidade: rastreamento distribuído com OpenTelemetry.
(Responsável: Lucas — TAREFA 7 do edital)

Este MESMO arquivo é copiado para 4 lugares (cada serviço tem o seu):
    gateway/telemetria.py      vetorial/telemetria.py
    inferencia/app/telemetria.py   worker/app/telemetria.py

Como o rastro atravessa o sistema (um único trace_id do começo ao fim):

  cliente -> [gateway] --HTTP--> [inferencia] --Redis--> [worker] --HTTP--> [vetorial]
              span              span           (fila)     span              span
  - Entre serviços HTTP: o cabeçalho W3C "traceparent" é enviado/lido automaticamente
    pelas instrumentações do FastAPI e do requests.
  - Pela FILA (Redis) não existe cabeçalho HTTP: por isso injetar_contexto() grava o
    "traceparent" dentro da mensagem da tarefa e extrair_contexto() o recupera no worker.

Variáveis de ambiente:
  OTEL_EXPORTER_OTLP_ENDPOINT   ex.: http://jaeger:4318  (vazio = não exporta)
  OTEL_CONSOLE                  "true" imprime os spans no log (útil sem Jaeger)

LGPD: os spans guardam só método, rota, status e tempos. NUNCA colocar o texto do
usuário em atributos de span.
"""
import os

from opentelemetry import propagate, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (BatchSpanProcessor,
                                            ConsoleSpanExporter,
                                            SimpleSpanProcessor)

_configurado = False


def configurar(nome_servico: str, app=None):
    """Liga o rastreamento. Chame UMA vez na subida do serviço.
    Se `app` (FastAPI) for passado, instrumenta as rotas automaticamente."""
    global _configurado
    if not _configurado:
        provider = TracerProvider(resource=Resource.create({"service.name": nome_servico}))

        if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import \
                OTLPSpanExporter
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        if os.getenv("OTEL_CONSOLE", "false").lower() == "true":
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

        trace.set_tracer_provider(provider)

        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        RequestsInstrumentor().instrument()   # propaga traceparent nas chamadas HTTP
        _configurado = True

    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
    return trace.get_tracer(nome_servico)


def tracer(nome: str = "plataforma-ia"):
    return trace.get_tracer(nome)


def injetar_contexto() -> dict:
    """Devolve {'traceparent': ...} do span atual, para viajar dentro da mensagem da fila."""
    carrier: dict = {}
    propagate.inject(carrier)
    return carrier


def extrair_contexto(carrier: dict | None):
    """Reconstrói o contexto a partir do que veio na mensagem da fila."""
    return propagate.extract(carrier or {})

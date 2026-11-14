# Observabilidade — rastreamento distribuído

> Responsável: Lucas

## Como funciona

Usamos **OpenTelemetry** e o **Jaeger** (UI em http://localhost:16686 ao subir o compose).
Uma requisição gera **um único `trace_id`** atravessando todos os serviços:

```
cliente → gateway ──HTTP──▶ inferencia ──Redis (fila)──▶ worker ──HTTP──▶ vetorial
          span POST /predict   span POST /predict   fila.enfileirar   span worker.processar   span POST /indexar
```

- **HTTP** (gateway → inferência, worker → vetorial): o cabeçalho W3C `traceparent` é enviado e lido
  automaticamente pelas instrumentações do `requests` e do FastAPI.
- **Fila (Redis):** não há cabeçalho HTTP, então `injetar_contexto()` grava o `traceparent` **dentro da
  mensagem da tarefa** e o worker usa `extrair_contexto()` para continuar o mesmo trace
  (`worker.processar` vira filho do span que enfileirou).
- O arquivo `telemetria.py` é o mesmo nos 4 serviços (`gateway/`, `vetorial/`, `inferencia/app/`, `worker/app/`).

## Como ver

1. `docker compose up --build`
2. Faça login e um `POST /predict` (ou rode `python scripts/smoke_test.py`).
3. Abra http://localhost:16686 → *Service*: `gateway` → *Find Traces* → abra o trace: aparecem
   `gateway`, `inferencia`, `worker` e `vetorial` no mesmo rastro.

Sem Jaeger: `OTEL_CONSOLE=true` imprime os spans no log de cada container (compare o `trace_id`).

## LGPD
Os spans guardam só método, rota, status e tempos — nunca o texto do usuário.

> 📸 Anexar aqui um print do trace no Jaeger (evidência para o professor).

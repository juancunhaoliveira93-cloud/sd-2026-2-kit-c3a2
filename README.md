# Plataforma de IA como Serviço — C3.A2

**Sistemas Distribuídos e Computação em Nuvem · FAESA · 2026/2**
**Integrantes:** Carine, Gustavo, Juan, Lucas e Victor.

Plataforma cloud-native de inferência de IA (análise de sentimento): microsserviços **conteinerizados**,
**publicados** na nuvem com HTTPS, **observáveis** (rastreamento distribuído) e **protegidos** (JWT, rate limit, LGPD).

> **URL pública:** `https://<PREENCHER-APOS-O-DEPLOY>` — veja [deploy/INSTRUCOES.md](deploy/INSTRUCOES.md)

## Arquitetura

```
                       ┌────────────── rede interna do Docker ──────────────┐
cliente ──HTTPS──▶ Caddy ─▶ GATEWAY ──HTTP──▶ INFERÊNCIA ──┐                 │
 (JWT)              :443     :8000   │          (API + gRPC)  │ enfileira      │
                              │      │                        ▼                │
                              │      └──HTTP──▶ VETORIAL ◀── REDIS (fila) ─▶ WORKER(s)
                              │                (busca por     tarefas            │ │
                              └──────────────▶  similaridade)  resultados/DLQ    │ │
                                                                 ▲───indexa─────┘ │
                          Jaeger ◀── spans OpenTelemetry de todos os serviços ───┘
```

| Serviço | Pasta | Função |
|---|---|---|
| **Gateway** | `gateway/` | Única porta de entrada: JWT, rate limit, roteamento, resiliência (timeout, retentativa, circuit breaker) |
| **Inferência** | `inferencia/` | API REST (+ gRPC) do C1.A2; carrega o modelo uma vez e enfileira tarefas (202) |
| **Worker** | `worker/` | Consome a fila Redis, executa o modelo, grava resultado; retentativa e dead-letter |
| **Armazenamento vetorial** | `vetorial/` | Guarda vetores (não o texto) e busca por similaridade |
| Redis | — | Fila de tarefas, resultados (com TTL) e DLQ |
| Jaeger | — | Visualização dos traces |

**Comunicação:** REST (cliente→gateway→serviços), mensageria via fila Redis (inferência→worker), gRPC opcional no C1.A2.

## Como executar do zero (um comando)

Pré-requisitos: Docker + Docker Compose.

```bash
git clone https://github.com/juancunhaoliveira93-cloud/sd-2026-2-kit-c3a2.git
cd sd-2026-2-kit-c3a2
cp .env.example .env          # opcional: já existem valores padrão
docker compose up --build     # UM comando sobe tudo
```

Em outro terminal:

```bash
# 1) Login (usuário demo / senha demo123 por padrão)
TOKEN=$(curl -s -X POST http://localhost:8000/login -H "Content-Type: application/json" \
  -d '{"usuario":"demo","senha":"demo123"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2) Enviar uma análise (retorna 202 e um id)
curl -X POST http://localhost:8000/predict -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"texto":"o atendimento foi excelente"}'

# 3) Consultar o resultado
curl http://localhost:8000/resultado/<ID> -H "Authorization: Bearer $TOKEN"

# 4) Buscar textos parecidos
curl -X POST http://localhost:8000/similares -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"texto":"atendimento excelente","k":3}'
```

Teste automático ponta a ponta: `pip install requests && python scripts/smoke_test.py`
Traces: http://localhost:16686 · Mais workers: `docker compose up --build --scale worker=3`
gRPC do C1.A2 (opcional): `docker compose --profile grpc up --build`

### Rotas do gateway

| Rota | Auth | Descrição |
|---|---|---|
| `GET /saude` | não | Estado do gateway e dos circuitos |
| `POST /login` | não (limite por IP) | Emite o JWT |
| `POST /predict` | JWT | Enfileira a análise → `202 {id}` |
| `GET /resultado/{id}` | JWT | Resultado (`na_fila` → `processando` → `pronto`/`erro`) |
| `POST /predict-sync` | JWT | Inferência síncrona (comparação de latência) |
| `POST /similares` | JWT | Busca no armazenamento vetorial |

Sem token → `401`. Excesso de requisições → `429` + `Retry-After`. Serviço interno fora do ar → `503`.

## Resiliência
- **Tempo-limite:** 1,5 s (conexão) e 5 s (leitura) em toda chamada interna.
- **Retentativa:** até 3 tentativas com espera progressiva (0,3 s, 0,6 s) + jitter.
- **Circuit breaker:** após 5 falhas seguidas o circuito abre (falha em ~2 ms com `Retry-After`), passa a meio-aberto após 15 s e deixa uma chamada de teste.
- **Worker:** 3 tentativas (1 s, 2 s, 4 s) e depois **dead-letter**; se o vetorial cair, a tarefa continua (degradação graciosa).
- Documentação: [docs/OBSERVABILIDADE.md](docs/OBSERVABILIDADE.md) · [docs/TRADEOFFS.md](docs/TRADEOFFS.md)

## Segurança e conformidade (LGPD)

| Dado | Finalidade | Retenção |
|---|---|---|
| Texto enviado (pode conter dado pessoal) | Executar a inferência e devolver ao solicitante | Resultado expira em **1 h**; DLQ em **24 h** |
| Vetor + id + sentimento (sem o texto) | Busca por similaridade | **24 h** |
| Usuário (login) | Autenticação e limite por cliente | Token válido por **30 min** |
| IP | Limitar tentativas de login | **60 s**, só em memória |
| Logs e traces | Operação | Sem texto, token ou senha; somente rota, status e tempo |

Detalhes e limitações: [docs/LGPD.md](docs/LGPD.md). Segurança: JWT (HS256) com expiração, HTTPS via Caddy,
rate limit, serviços internos sem porta pública, toda configuração em variáveis de ambiente (`.env.example`).

## Testes

```bash
pip install -r requirements-dev.txt
(cd gateway && python -m pytest -q tests)
(cd vetorial && python -m pytest -q tests)
```

## Estrutura

```
gateway/      app.py auth.py ratelimit.py resiliencia.py telemetria.py Dockerfile tests/
inferencia/   app/ (api_rest, fila, modelo, servidor_grpc, telemetria) proto/ Dockerfile
worker/       app/ (worker, fila, modelo, telemetria) Dockerfile
vetorial/     main.py telemetria.py Dockerfile tests/
deploy/       INSTRUCOES.md Caddyfile
docs/         LGPD.md OBSERVABILIDADE.md TRADEOFFS.md
scripts/      smoke_test.py medir_latencia.py
docker-compose.yml  docker-compose.prod.yml  .github/workflows/ci.yml
```

## Origem do código
O serviço de inferência e o worker partem do projeto **C1.A2**
([sd-2026-2-kit-c1a2](https://github.com/juancunhaoliveira93-cloud/sd-2026-2-kit-c1a2)), adaptado para a plataforma.

## Divisão do trabalho

| Integrante | Entrega |
|---|---|
| Carine | JWT, rate limit, LGPD |
| Gustavo | Resiliência (timeout, retry, circuit breaker) e armazenamento vetorial |
| Lucas | Observabilidade (OpenTelemetry/Jaeger), relatório de trade-offs, medição de latência |
| Juan | Integração (gateway, C1.A2 → inferência/worker, Dockerfiles, compose, README) |
| Victor | Deploy em nuvem com HTTPS, CI/CD, smoke test |

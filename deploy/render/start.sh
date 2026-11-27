#!/bin/bash
# Sobe a plataforma INTEIRA dentro de um único container (deploy no Render free tier).
#   - Só o GATEWAY escuta em 0.0.0.0:$PORT (porta pública, HTTPS feito pelo Render).
#   - Inferência, vetorial e Redis escutam só em 127.0.0.1 (não ficam expostos).
#   - Se qualquer processo morrer, o container encerra e o Render o reinicia.
set -u
ROOT="${APP_ROOT:-/srv}"
PORT="${PORT:-10000}"

# ---- Segurança: recusa subir com credenciais padrão (estão públicas no repositório) ----
if [ -z "${JWT_SEGREDO:-}" ] || [ "${JWT_SEGREDO}" = "troque-este-segredo" ]; then
  echo "ERRO: defina JWT_SEGREDO (variavel de ambiente no Render) com um valor secreto proprio."
  exit 1
fi
if [ -z "${USUARIOS:-}" ] || [[ "${USUARIOS}" == *"demo:demo123"* ]]; then
  echo "ERRO: defina USUARIOS (ex.: admin:senha-forte) no Render; nao use o usuario demo."
  exit 1
fi

export REDIS_URL="redis://127.0.0.1:6379/0"
export URL_INFERENCIA="http://127.0.0.1:8001"
export URL_VETORIAL="http://127.0.0.1:8002"
export CONFIAR_PROXY="true"        # IP real do cliente vem em X-Forwarded-For (proxy do Render)

trap 'echo "[start] encerrando..."; kill 0' TERM INT

echo "[start] Redis"
redis-server --bind 127.0.0.1 --port 6379 --save "" --appendonly no \
             --maxmemory 64mb --maxmemory-policy volatile-lru &
for _ in $(seq 1 30); do redis-cli -h 127.0.0.1 ping >/dev/null 2>&1 && break; sleep 0.5; done

echo "[start] vetorial :8002"
(cd "$ROOT/vetorial"   && exec uvicorn main:app --host 127.0.0.1 --port 8002) &
echo "[start] inferencia :8001"
(cd "$ROOT/inferencia" && exec uvicorn app.api_rest:app --host 127.0.0.1 --port 8001) &
echo "[start] worker"
(cd "$ROOT/worker"     && exec python -m app.worker) &
echo "[start] gateway :$PORT"
(cd "$ROOT/gateway"    && exec uvicorn app:app --host 0.0.0.0 --port "$PORT") &

wait -n
echo "[start] um processo terminou; derrubando o container para o Render reiniciar"
kill 0
exit 1

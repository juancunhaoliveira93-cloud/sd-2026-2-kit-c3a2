"""
Mede a latência da plataforma para o relatório de trade-offs.  (Responsável: Lucas)

    python scripts/medir_latencia.py                 # 30 amostras em http://localhost:8000
    BASE_URL=https://... N=50 python scripts/medir_latencia.py

Mede, em milissegundos (p50 / p95 / máx):
  1. /predict-sync        : resposta síncrona (cliente espera a inferência)
  2. /predict             : tempo até o 202 (só enfileirar)
  3. fim a fim assíncrono : do POST até o resultado ficar "pronto" (fila + worker)
Cole a tabela impressa em docs/TRADEOFFS.md.

ATENÇÃO: cada amostra faz vários requests e o gateway limita 30 req/min por usuário.
Antes de medir, suba a stack com o limite alto (isso é só para o teste):
    RATE_LIMIT_POR_MINUTO=100000 docker compose up -d --build
"""
import os
import statistics
import time

import requests

BASE = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
N = int(os.getenv("N", "30"))
USUARIO, SENHA = os.getenv("API_USUARIO", "demo"), os.getenv("API_SENHA", "demo123")
TEXTO = "o atendimento foi excelente e muito rapido"


def pct(valores, p):
    valores = sorted(valores)
    return valores[min(int(len(valores) * p), len(valores) - 1)]


def linha(nome, v):
    print(f"| {nome:<24} | {statistics.median(v):8.1f} | {pct(v, 0.95):8.1f} | {max(v):8.1f} |")


def conferir(r):
    if r.status_code == 429:
        raise SystemExit("429: rate limit atingido. Suba a stack com RATE_LIMIT_POR_MINUTO=100000 para medir.")
    r.raise_for_status()
    return r


def main():
    token = requests.post(f"{BASE}/login", json={"usuario": USUARIO, "senha": SENHA}, timeout=15).json()["access_token"]
    cab = {"Authorization": f"Bearer {token}"}
    sync, enfileirar, fim_a_fim = [], [], []

    for _ in range(N):
        t = time.perf_counter()
        conferir(requests.post(f"{BASE}/predict-sync", json={"texto": TEXTO}, headers=cab, timeout=15))
        sync.append((time.perf_counter() - t) * 1000)

        t = time.perf_counter()
        r = conferir(requests.post(f"{BASE}/predict", json={"texto": TEXTO}, headers=cab, timeout=15))
        enfileirar.append((time.perf_counter() - t) * 1000)
        tid = r.json()["id"]
        while time.perf_counter() - t < 30:
            if conferir(requests.get(f"{BASE}/resultado/{tid}", headers=cab, timeout=15)).json().get("status") == "pronto":
                fim_a_fim.append((time.perf_counter() - t) * 1000)
                break
            time.sleep(0.05)

    print(f"\nLatência ({N} amostras) em ms\n")
    print("| Operação                 |      p50 |      p95 |      máx |")
    print("|--------------------------|----------|----------|----------|")
    linha("/predict-sync", sync)
    linha("/predict (até o 202)", enfileirar)
    if fim_a_fim:
        linha("fim a fim assíncrono", fim_a_fim)


if __name__ == "__main__":
    main()

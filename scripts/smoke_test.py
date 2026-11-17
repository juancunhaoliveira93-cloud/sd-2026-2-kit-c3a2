"""
Smoke test: confere se a plataforma (local OU publicada) está funcionando de ponta a ponta.
(Responsável: Victor)

Uso:
    python scripts/smoke_test.py                              # http://localhost:8000
    BASE_URL=https://meu-dominio.sslip.io python scripts/smoke_test.py
Variáveis: BASE_URL, API_USUARIO (demo), API_SENHA (demo123)
Sai com código 0 se tudo passou, 1 se algo falhou (serve também para o CI).
"""
import os
import sys
import time

import requests

BASE = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
USUARIO = os.getenv("API_USUARIO", "demo")
SENHA = os.getenv("API_SENHA", "demo123")
falhas = 0


def checar(nome, condicao, detalhe=""):
    global falhas
    print(f"[{'OK' if condicao else 'FALHOU'}] {nome} {detalhe}")
    if not condicao:
        falhas += 1


def main():
    r = requests.get(f"{BASE}/saude", timeout=15)
    checar("GET /saude responde 200", r.status_code == 200, f"({BASE})")
    checar("HTTPS ativo", BASE.startswith("https://") or "localhost" in BASE,
           "(URL pública deve ser https)")

    r = requests.post(f"{BASE}/predict", json={"texto": "oi"}, timeout=15)
    checar("rota protegida sem token -> 401", r.status_code == 401)

    r = requests.post(f"{BASE}/login", json={"usuario": USUARIO, "senha": "senha-errada"}, timeout=15)
    checar("login com senha errada -> 401", r.status_code == 401)

    r = requests.post(f"{BASE}/login", json={"usuario": USUARIO, "senha": SENHA}, timeout=15)
    checar("login correto -> 200 + token", r.status_code == 200 and "access_token" in r.json())
    if r.status_code != 200:
        return
    cab = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r = requests.post(f"{BASE}/predict", json={"texto": "o atendimento foi excelente"}, headers=cab, timeout=15)
    checar("POST /predict -> 202 + id", r.status_code == 202 and "id" in r.json())
    tarefa_id = r.json().get("id")

    final = None
    for _ in range(40):                      # até ~20s (worker pode estar "acordando")
        time.sleep(0.5)
        d = requests.get(f"{BASE}/resultado/{tarefa_id}", headers=cab, timeout=15).json()
        if d.get("status") in ("pronto", "erro"):
            final = d
            break
    checar("worker processou a tarefa (fila -> worker)", bool(final) and final["status"] == "pronto",
           f"-> {final.get('sentimento') if final else 'timeout'}")

    r = requests.post(f"{BASE}/similares", json={"texto": "atendimento excelente", "k": 2}, headers=cab, timeout=15)
    checar("POST /similares (armazenamento vetorial)", r.status_code == 200 and "resultados" in r.json())

    r = requests.get(f"{BASE}/resultado/00000000-0000-0000-0000-000000000000", headers=cab, timeout=15)
    checar("id inexistente -> 404", r.status_code == 404)


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as e:
        print(f"[FALHOU] nao consegui falar com {BASE}: {e}")
        sys.exit(1)
    print("\nRESULTADO:", "tudo certo" if falhas == 0 else f"{falhas} verificacao(oes) falharam")
    sys.exit(1 if falhas else 0)

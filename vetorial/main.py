"""
Serviço de ARMAZENAMENTO VETORIAL (busca por similaridade).
(Responsável: Gustavo — 4º microsserviço exigido pelo edital)

  POST /indexar  {id, texto, metadados}  -> guarda o VETOR (não guarda o texto!)
  POST /buscar   {texto, k}              -> ids mais parecidos (similaridade cosseno)
  GET  /saude

Embedding: "hashing trick" determinístico (sem modelo externo, 100% offline):
cada palavra vira um índice por hash e o vetor é normalizado. Como o modelo de IA
NÃO pontua, o foco é a arquitetura (serviço independente + persistência + TTL).

LGPD / minimização: só o vetor + metadados mínimos (id e sentimento) são guardados,
nunca o texto original, e cada vetor expira em VETORIAL_TTL_S (padrão 24h).

Variáveis de ambiente:
  VETORIAL_DIM (128)  VETORIAL_TTL_S (86400)  VETORIAL_MAX_ITENS (2000)
  VETORIAL_ARQUIVO    caminho do snapshot em disco (vazio = só memória)
"""
import hashlib
import json
import os
import re
import threading
import time
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

import telemetria

DIM = int(os.getenv("VETORIAL_DIM", "128"))
TTL_S = int(os.getenv("VETORIAL_TTL_S", "86400"))
MAX_ITENS = int(os.getenv("VETORIAL_MAX_ITENS", "2000"))
ARQUIVO = os.getenv("VETORIAL_ARQUIVO", "")
INTERVALO_SNAPSHOT_S = 10


def embedding(texto: str) -> np.ndarray:
    vetor = np.zeros(DIM, dtype=np.float32)
    for palavra in re.findall(r"\w+", texto.lower()):
        h = int(hashlib.md5(palavra.encode()).hexdigest(), 16)
        vetor[h % DIM] += 1.0 if (h >> 64) % 2 == 0 else -1.0
    norma = np.linalg.norm(vetor)
    return vetor / norma if norma > 0 else vetor


class Armazem:
    """Guarda {id: (vetor, metadados, expira_em)}. Thread-safe."""

    def __init__(self):
        self._itens = {}
        self._trava = threading.Lock()
        self._sujo = False

    def indexar(self, id_: str, vetor: np.ndarray, metadados: dict, agora=None):
        agora = agora if agora is not None else time.time()
        with self._trava:
            self._purgar(agora)
            if id_ not in self._itens and len(self._itens) >= MAX_ITENS:
                mais_antigo = min(self._itens, key=lambda k: self._itens[k][2])
                del self._itens[mais_antigo]
            self._itens[id_] = (vetor, metadados, agora + TTL_S)
            self._sujo = True

    def buscar(self, vetor: np.ndarray, k: int, agora=None):
        agora = agora if agora is not None else time.time()
        with self._trava:
            self._purgar(agora)
            pontuados = [(float(np.dot(vetor, v)), id_, meta)
                         for id_, (v, meta, _) in self._itens.items()]
        pontuados.sort(key=lambda t: t[0], reverse=True)
        return [{"id": i, "similaridade": round(s, 4), "metadados": m}
                for s, i, m in pontuados[:k]]

    def tamanho(self) -> int:
        with self._trava:
            return len(self._itens)

    def _purgar(self, agora):
        for k in [k for k, (_, _, exp) in self._itens.items() if exp <= agora]:
            del self._itens[k]
            self._sujo = True

    # ---- persistência simples em disco (snapshot) ----
    def salvar(self, caminho: str):
        with self._trava:
            if not self._sujo:
                return
            dados = {k: {"v": v.tolist(), "m": m, "exp": e}
                     for k, (v, m, e) in self._itens.items()}
            self._sujo = False
        tmp = caminho + ".tmp"
        with open(tmp, "w") as f:
            json.dump(dados, f)
        os.replace(tmp, caminho)   # troca atômica

    def carregar(self, caminho: str):
        if not caminho or not os.path.exists(caminho):
            return
        with open(caminho) as f:
            dados = json.load(f)
        agora = time.time()
        with self._trava:
            for k, d in dados.items():
                if d["exp"] > agora:
                    self._itens[k] = (np.array(d["v"], dtype=np.float32), d["m"], d["exp"])


armazem = Armazem()


def _loop_snapshot(parar: threading.Event):
    while not parar.wait(INTERVALO_SNAPSHOT_S):
        try:
            armazem.salvar(ARQUIVO)
        except OSError as e:
            print(f"[vetorial] falha ao salvar snapshot: {e}")


@asynccontextmanager
async def ciclo_de_vida(_app):
    parar = threading.Event()
    if ARQUIVO:
        armazem.carregar(ARQUIVO)
        threading.Thread(target=_loop_snapshot, args=(parar,), daemon=True).start()
    print(f"[vetorial] pronto (dim={DIM}, ttl={TTL_S}s, itens={armazem.tamanho()})")
    yield
    parar.set()
    if ARQUIVO:
        armazem.salvar(ARQUIVO)


app = FastAPI(title="Armazenamento vetorial - C3.A2", lifespan=ciclo_de_vida)
telemetria.configurar("vetorial", app)


class PedidoIndexar(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    texto: str = Field(min_length=1, max_length=2000)
    metadados: dict = Field(default_factory=dict)


class PedidoBuscar(BaseModel):
    texto: str = Field(min_length=1, max_length=2000)
    k: int = Field(default=3, ge=1, le=20)


@app.middleware("http")
async def registrar(request: Request, call_next):
    inicio = time.time()
    resposta = await call_next(request)
    print(f"[vetorial] {request.method} {request.url.path} "
          f"-> {resposta.status_code} ({(time.time() - inicio) * 1000:.1f}ms)")
    return resposta


@app.get("/saude")
def saude():
    return {"status": "ok", "itens": armazem.tamanho(), "dim": DIM}


@app.post("/indexar", status_code=201)
def indexar(p: PedidoIndexar):
    # O texto é usado só para calcular o vetor e é descartado em seguida.
    armazem.indexar(p.id, embedding(p.texto), p.metadados)
    return {"id": p.id, "indexado": True}


@app.post("/buscar")
def buscar(p: PedidoBuscar):
    return {"resultados": armazem.buscar(embedding(p.texto), p.k)}

"""Testes de integração do gateway com os serviços internos simulados."""
import os
os.environ.update(USUARIOS="ana:segredo1", JWT_SEGREDO="segredo-de-teste")

import pytest
import requests
from fastapi.testclient import TestClient

import app as gw
import ratelimit
import resiliencia
from ratelimit import LimitadorJanela


class Resp:
    def __init__(self, code, corpo):
        self.status_code, self._c = code, corpo

    def json(self):
        return self._c


@pytest.fixture()
def cliente(monkeypatch):
    ratelimit.limitador_usuarios = LimitadorJanela(100, 60)
    ratelimit.limitador_login = LimitadorJanela(100, 60)
    gw.breaker_inferencia = resiliencia.CircuitBreaker("inferencia", falhas_limite=2, reset_s=30)
    monkeypatch.setattr(resiliencia.time, "sleep", lambda s: None)
    return TestClient(gw.app)


@pytest.fixture()
def cab(cliente):
    t = cliente.post("/login", json={"usuario": "ana", "senha": "segredo1"}).json()["access_token"]
    return {"Authorization": f"Bearer {t}"}


def test_saude_publica(cliente):
    assert cliente.get("/saude").json()["status"] == "ok"


@pytest.mark.parametrize("metodo,rota,corpo", [
    ("post", "/predict", {"texto": "x"}),
    ("get", "/resultado/00000000-0000-0000-0000-000000000000", None),
    ("post", "/predict-sync", {"texto": "x"}),
    ("post", "/similares", {"texto": "x"}),
])
def test_rotas_exigem_jwt(cliente, metodo, rota, corpo):
    r = getattr(cliente, metodo)(rota, **({"json": corpo} if corpo else {}))
    assert r.status_code == 401


def test_predict_roteia_e_devolve_202(cliente, cab, monkeypatch):
    monkeypatch.setattr(resiliencia.requests, "request",
                        lambda m, u, **k: Resp(202, {"id": "abc", "status": "processando"}))
    r = cliente.post("/predict", json={"texto": "adorei"}, headers=cab)
    assert r.status_code == 202 and r.json()["id"] == "abc"


def test_resultado_404_repassado(cliente, cab, monkeypatch):
    monkeypatch.setattr(resiliencia.requests, "request",
                        lambda m, u, **k: Resp(404, {"detail": "nao encontrado"}))
    r = cliente.get("/resultado/00000000-0000-0000-0000-000000000000", headers=cab)
    assert r.status_code == 404


def test_id_invalido_rejeitado(cliente, cab):
    assert cliente.get("/resultado/../../admin", headers=cab).status_code in (404, 422)
    assert cliente.get("/resultado/abc", headers=cab).status_code == 422


def test_servico_fora_do_ar_503_e_circuito_abre(cliente, cab, monkeypatch):
    def cai(*a, **k):
        raise requests.ConnectionError("fora")
    monkeypatch.setattr(resiliencia.requests, "request", cai)
    r = cliente.post("/predict", json={"texto": "x"}, headers=cab)
    assert r.status_code == 503
    assert cliente.get("/saude").json()["circuitos"]["inferencia"] == "aberto"
    r2 = cliente.post("/predict", json={"texto": "x"}, headers=cab)
    assert r2.status_code == 503 and "Retry-After" in r2.headers


def test_texto_vazio_422(cliente, cab):
    assert cliente.post("/predict", json={"texto": ""}, headers=cab).status_code == 422

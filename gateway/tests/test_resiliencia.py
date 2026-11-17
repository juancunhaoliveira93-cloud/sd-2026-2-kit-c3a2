import pytest
import requests

import resiliencia
from resiliencia import CircuitBreaker, ServicoIndisponivel, chamar


class Resp:
    def __init__(self, code=200):
        self.status_code = code


def _patch(monkeypatch, respostas):
    """respostas: lista de Resp ou Exception, consumida em ordem."""
    chamadas = []

    def falso(metodo, url, timeout=None, **kw):
        chamadas.append(timeout)
        item = respostas.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
    monkeypatch.setattr(resiliencia.requests, "request", falso)
    return chamadas


def test_sucesso_direto_usa_timeout(monkeypatch):
    chamadas = _patch(monkeypatch, [Resp(200)])
    r = chamar("GET", "http://x", CircuitBreaker("t"), dormir=lambda s: None)
    assert r.status_code == 200
    assert chamadas[0] == (resiliencia.TIMEOUT_CONEXAO_S, resiliencia.TIMEOUT_LEITURA_S)


def test_retenta_ate_dar_certo_com_espera_progressiva(monkeypatch):
    _patch(monkeypatch, [requests.ConnectionError(), Resp(503), Resp(200)])
    esperas = []
    r = chamar("GET", "http://x", CircuitBreaker("t", falhas_limite=10),
               tentativas=3, espera_base=1.0, dormir=esperas.append)
    assert r.status_code == 200
    assert len(esperas) == 2
    assert 1.0 <= esperas[0] <= 1.2 and 2.0 <= esperas[1] <= 2.4   # 1s, 2s (+jitter)


def test_esgota_tentativas_levanta_servico_indisponivel(monkeypatch):
    _patch(monkeypatch, [requests.Timeout()] * 3)
    with pytest.raises(ServicoIndisponivel):
        chamar("GET", "http://x", CircuitBreaker("t", falhas_limite=10),
               tentativas=3, dormir=lambda s: None)


def test_4xx_nao_e_falha_nem_retenta(monkeypatch):
    chamadas = _patch(monkeypatch, [Resp(404)])
    b = CircuitBreaker("t")
    assert chamar("GET", "http://x", b, dormir=lambda s: None).status_code == 404
    assert len(chamadas) == 1 and b.estado == "fechado"


def test_circuit_breaker_abre_meio_abre_e_fecha():
    t = [0.0]
    b = CircuitBreaker("t", falhas_limite=3, reset_s=10, relogio=lambda: t[0])
    for _ in range(3):
        assert b.permitir()
        b.registrar_falha()
    assert b.estado == "aberto" and not b.permitir()
    t[0] = 11
    assert b.estado == "meio_aberto"
    assert b.permitir() and not b.permitir()      # só UMA chamada de teste
    b.registrar_sucesso()
    assert b.estado == "fechado" and b.permitir()


def test_meio_aberto_falha_reabre():
    t = [0.0]
    b = CircuitBreaker("t", falhas_limite=1, reset_s=5, relogio=lambda: t[0])
    b.registrar_falha()
    t[0] = 6
    assert b.permitir()
    b.registrar_falha()
    assert b.estado == "aberto"


def test_circuito_aberto_falha_rapido_sem_chamar(monkeypatch):
    chamadas = _patch(monkeypatch, [])
    b = CircuitBreaker("t", falhas_limite=1)
    b.registrar_falha()
    with pytest.raises(ServicoIndisponivel) as e:
        chamar("GET", "http://x", b, dormir=lambda s: None)
    assert chamadas == [] and e.value.retry_after >= 1

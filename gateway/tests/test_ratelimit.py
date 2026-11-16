import os
os.environ["USUARIOS"] = "ana:segredo1"
os.environ["JWT_SEGREDO"] = "segredo-de-teste"

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import auth
import ratelimit
from ratelimit import LimitadorJanela


def test_janela_bloqueia_e_libera_com_o_tempo():
    t = [0.0]
    lim = LimitadorJanela(limite=3, janela_s=60, relogio=lambda: t[0])
    assert all(lim.verificar("a")[0] for _ in range(3))
    ok, espera = lim.verificar("a")
    assert not ok and 0 < espera <= 60
    assert lim.verificar("b")[0]          # outro cliente não é afetado
    t[0] = 61
    assert lim.verificar("a")[0]          # passou a janela


def test_limpar_inativos():
    t = [0.0]
    lim = LimitadorJanela(2, 10, relogio=lambda: t[0])
    lim.verificar("a")
    t[0] = 20
    lim.limpar_inativos()
    assert "a" not in lim._eventos


def test_rota_devolve_429_com_retry_after():
    ratelimit.limitador_usuarios = LimitadorJanela(2, 60)
    app = FastAPI()

    @app.post("/login", dependencies=[Depends(ratelimit.limitar_login)])
    def login(c: auth.Credenciais):
        return auth.emitir_token(c.usuario, c.senha)

    @app.get("/x")
    def x(u: str = Depends(ratelimit.limitar_cliente)):
        return {"u": u}

    c = TestClient(app)
    token = c.post("/login", json={"usuario": "ana", "senha": "segredo1"}).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    assert c.get("/x", headers=h).status_code == 200
    assert c.get("/x", headers=h).status_code == 200
    r = c.get("/x", headers=h)
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    # sem token continua 401 (e não consome cota)
    assert c.get("/x").status_code == 401


def test_login_limitado_por_ip():
    ratelimit.limitador_login = LimitadorJanela(3, 60)
    app = FastAPI()

    @app.post("/login", dependencies=[Depends(ratelimit.limitar_login)])
    def login(c: auth.Credenciais):
        return auth.emitir_token(c.usuario, c.senha)

    c = TestClient(app)
    codigos = [c.post("/login", json={"usuario": "ana", "senha": "errada"}).status_code for _ in range(4)]
    assert codigos == [401, 401, 401, 429]

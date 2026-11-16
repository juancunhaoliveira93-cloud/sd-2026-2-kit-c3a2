import os
os.environ["USUARIOS"] = "ana:segredo1,bruno:segredo2"
os.environ["JWT_SEGREDO"] = "segredo-de-teste"

import time
import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import auth

app = FastAPI()


@app.post("/login")
def login(c: auth.Credenciais):
    return auth.emitir_token(c.usuario, c.senha)


@app.get("/protegida")
def protegida(usuario: str = Depends(auth.exigir_token)):
    return {"usuario": usuario}


client = TestClient(app)


def _login(usuario="ana", senha="segredo1"):
    return client.post("/login", json={"usuario": usuario, "senha": senha})


def test_login_correto_devolve_token():
    r = _login()
    assert r.status_code == 200
    assert r.json()["token_type"] == "bearer"
    assert r.json()["access_token"]


@pytest.mark.parametrize("usuario,senha", [("ana", "errada"), ("fantasma", "x"), ("ana", "segredo2")])
def test_login_invalido_401(usuario, senha):
    assert _login(usuario, senha).status_code == 401


def test_rota_sem_token_401():
    r = client.get("/protegida")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


def test_rota_com_token_valido():
    token = _login().json()["access_token"]
    r = client.get("/protegida", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json() == {"usuario": "ana"}


def test_token_adulterado_401():
    r = client.get("/protegida", headers={"Authorization": "Bearer abc.def.ghi"})
    assert r.status_code == 401


def test_token_assinado_com_outro_segredo_401():
    falso = jwt.encode({"sub": "ana", "exp": int(time.time()) + 60}, "outro", algorithm="HS256")
    assert client.get("/protegida", headers={"Authorization": f"Bearer {falso}"}).status_code == 401


def test_token_expirado_401():
    velho = jwt.encode({"sub": "ana", "exp": int(time.time()) - 10}, "segredo-de-teste", algorithm="HS256")
    r = client.get("/protegida", headers={"Authorization": f"Bearer {velho}"})
    assert r.status_code == 401 and "expirado" in r.json()["detail"]

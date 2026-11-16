"""
Autenticação por JWT no gateway.  (Responsável: Carine — TAREFA 1 do edital)

Fluxo:
  1. POST /login  {usuario, senha}  ->  {access_token, token_type, expires_in}
  2. Demais rotas exigem  Authorization: Bearer <token>  (sem token válido -> 401)

Toda a configuração vem de variáveis de ambiente (nada fixo no código):
  JWT_SEGREDO          chave de assinatura (HS256). TROQUE em produção.
  JWT_EXPIRA_MINUTOS   validade do token (padrão 30)
  USUARIOS             lista "usuario:senha,usuario2:senha2"
"""
import hmac
import os
import time

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

ALGORITMO = "HS256"
SEGREDO_PADRAO = "troque-este-segredo"

JWT_SEGREDO = os.getenv("JWT_SEGREDO", SEGREDO_PADRAO)
JWT_EXPIRA_MINUTOS = int(os.getenv("JWT_EXPIRA_MINUTOS", "30"))

if JWT_SEGREDO == SEGREDO_PADRAO:
    print("[auth] AVISO: usando JWT_SEGREDO padrao. Defina um segredo proprio em producao.")

_esquema = HTTPBearer(auto_error=False)  # auto_error=False: nós devolvemos 401 (e não 403)


class Credenciais(BaseModel):
    usuario: str = Field(min_length=1, max_length=64)
    senha: str = Field(min_length=1, max_length=128)


def _carregar_usuarios() -> dict:
    """Lê USUARIOS='ana:senha1,bruno:senha2' a cada chamada (facilita testes)."""
    bruto = os.getenv("USUARIOS", "demo:demo123")
    usuarios = {}
    for par in bruto.split(","):
        if ":" in par:
            nome, senha = par.split(":", 1)
            usuarios[nome.strip()] = senha.strip()
    return usuarios


def credenciais_validas(usuario: str, senha: str) -> bool:
    """Compara em tempo constante (evita ataque de temporização)."""
    esperada = _carregar_usuarios().get(usuario)
    # Sempre executa a comparação, mesmo para usuário inexistente.
    return hmac.compare_digest((esperada or "\0").encode(), senha.encode()) and esperada is not None


def criar_token(usuario: str) -> str:
    agora = int(time.time())
    carga = {"sub": usuario, "iat": agora, "exp": agora + JWT_EXPIRA_MINUTOS * 60}
    return jwt.encode(carga, JWT_SEGREDO, algorithm=ALGORITMO)


def emitir_token(usuario: str, senha: str) -> dict:
    """Usada pela rota /login. Levanta 401 se usuário/senha estiverem errados."""
    if not credenciais_validas(usuario, senha):
        raise HTTPException(status_code=401, detail="usuario ou senha invalidos")
    return {
        "access_token": criar_token(usuario),
        "token_type": "bearer",
        "expires_in": JWT_EXPIRA_MINUTOS * 60,
    }


def exigir_token(
    credenciais: HTTPAuthorizationCredentials = Depends(_esquema),
) -> str:
    """Dependência do FastAPI: devolve o usuário (claim 'sub') ou levanta 401."""
    cabecalho = {"WWW-Authenticate": "Bearer"}
    if credenciais is None:
        raise HTTPException(status_code=401, detail="token ausente", headers=cabecalho)
    try:
        carga = jwt.decode(
            credenciais.credentials,
            JWT_SEGREDO,
            algorithms=[ALGORITMO],
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="token expirado", headers=cabecalho)
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="token invalido", headers=cabecalho)
    return carga["sub"]

"""
Rate limit por cliente.  (Responsável: Carine — TAREFA 2 do edital)

Janela deslizante em memória: guarda os instantes das últimas requisições de
cada cliente e recusa (HTTP 429 + Retry-After) quando passa do limite no último minuto.

  - Rotas autenticadas: o "cliente" é o usuário do JWT.
  - /login: o "cliente" é o IP (limite mais baixo, contra força bruta).

Variáveis de ambiente:
  RATE_LIMIT_POR_MINUTO   requisições/min por usuário (padrão 30)
  RATE_LIMIT_LOGIN        tentativas de login/min por IP (padrão 10)
  CONFIAR_PROXY           "true" se o gateway está atrás de proxy/HTTPS (Caddy, Render...)
                          e o IP real vem em X-Forwarded-For

Limitação conhecida (documentar no relatório de trade-offs): o contador fica na
memória de CADA instância do gateway. Com N réplicas o limite efetivo vira N x limite.
Para limite global seria preciso um contador compartilhado (ex.: Redis).
"""
import os
import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request

from auth import exigir_token


class LimitadorJanela:
    def __init__(self, limite: int, janela_s: float = 60.0, relogio=time.monotonic):
        self.limite = limite
        self.janela_s = janela_s
        self._relogio = relogio
        self._eventos = defaultdict(deque)
        self._trava = threading.Lock()

    def verificar(self, chave: str):
        """Devolve (permitido, segundos_para_tentar_de_novo)."""
        agora = self._relogio()
        with self._trava:
            fila = self._eventos[chave]
            while fila and agora - fila[0] >= self.janela_s:
                fila.popleft()
            if len(fila) >= self.limite:
                espera = self.janela_s - (agora - fila[0])
                return False, max(espera, 0.0)
            fila.append(agora)
            return True, 0.0

    def limpar_inativos(self):
        """Remove clientes sem eventos recentes (evita crescimento da memória)."""
        agora = self._relogio()
        with self._trava:
            for chave in [k for k, f in self._eventos.items()
                          if not f or agora - f[-1] >= self.janela_s]:
                del self._eventos[chave]


limitador_usuarios = LimitadorJanela(int(os.getenv("RATE_LIMIT_POR_MINUTO", "30")))
limitador_login = LimitadorJanela(int(os.getenv("RATE_LIMIT_LOGIN", "10")))


def _recusar(espera: float):
    segundos = int(espera) + 1
    raise HTTPException(
        status_code=429,
        detail="limite de requisicoes excedido; tente novamente em instantes",
        headers={"Retry-After": str(segundos)},
    )


def ip_do_cliente(request: Request) -> str:
    if os.getenv("CONFIAR_PROXY", "false").lower() == "true":
        encaminhado = request.headers.get("x-forwarded-for")
        if encaminhado:
            return encaminhado.split(",")[0].strip()
    return request.client.host if request.client else "desconhecido"


def limitar_cliente(usuario: str = Depends(exigir_token)) -> str:
    """Dependência: exige JWT válido e aplica o limite por usuário. Devolve o usuário."""
    permitido, espera = limitador_usuarios.verificar(usuario)
    if not permitido:
        _recusar(espera)
    return usuario


def limitar_login(request: Request) -> None:
    """Dependência para /login: limite por IP."""
    permitido, espera = limitador_login.verificar(ip_do_cliente(request))
    if not permitido:
        _recusar(espera)

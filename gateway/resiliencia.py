"""
Resiliência nas chamadas do gateway aos serviços internos.
(Responsável: Gustavo — TAREFA 6 do edital)

Três mecanismos combinados:
  1. TEMPO-LIMITE  : nenhuma chamada espera para sempre (timeout de conexão e de leitura).
  2. RETENTATIVA   : falhas transitórias são repetidas com espera progressiva
                     (backoff exponencial + jitter: 0,3s, 0,6s, 1,2s ...).
  3. CIRCUIT BREAKER: depois de N falhas seguidas o circuito ABRE e as chamadas
                     falham na hora (sem sobrecarregar o serviço doente) por um tempo;
                     depois passa a MEIO-ABERTO e deixa UMA chamada de teste passar.

Variáveis de ambiente:
  TIMEOUT_CONEXAO_S (1.5)   TIMEOUT_LEITURA_S (5)
  RETRY_TENTATIVAS (3)      RETRY_ESPERA_BASE_S (0.3)
  CB_FALHAS_LIMITE (5)      CB_RESET_S (15)

Observação (at-least-once): repetir um POST que o servidor chegou a processar pode
duplicar a tarefa na fila. É aceitável aqui porque a inferência é idempotente.
"""
import os
import random
import threading
import time

import requests

TIMEOUT_CONEXAO_S = float(os.getenv("TIMEOUT_CONEXAO_S", "1.5"))
TIMEOUT_LEITURA_S = float(os.getenv("TIMEOUT_LEITURA_S", "5"))
RETRY_TENTATIVAS = int(os.getenv("RETRY_TENTATIVAS", "3"))
RETRY_ESPERA_BASE_S = float(os.getenv("RETRY_ESPERA_BASE_S", "0.3"))
CB_FALHAS_LIMITE = int(os.getenv("CB_FALHAS_LIMITE", "5"))
CB_RESET_S = float(os.getenv("CB_RESET_S", "15"))

STATUS_TRANSITORIOS = {502, 503, 504}


class ServicoIndisponivel(Exception):
    """Serviço fora do ar, lento demais ou com circuito aberto."""

    def __init__(self, detalhe: str, retry_after: int | None = None):
        super().__init__(detalhe)
        self.detalhe = detalhe
        self.retry_after = retry_after


class CircuitBreaker:
    FECHADO, ABERTO, MEIO_ABERTO = "fechado", "aberto", "meio_aberto"

    def __init__(self, nome: str, falhas_limite: int = CB_FALHAS_LIMITE,
                 reset_s: float = CB_RESET_S, relogio=time.monotonic):
        self.nome = nome
        self.falhas_limite = falhas_limite
        self.reset_s = reset_s
        self._relogio = relogio
        self._trava = threading.Lock()
        self._estado = self.FECHADO
        self._falhas = 0
        self._aberto_em = 0.0
        self._teste_em_andamento = False

    @property
    def estado(self) -> str:
        with self._trava:
            return self._estado_atual()

    def _estado_atual(self) -> str:
        if self._estado == self.ABERTO and self._relogio() - self._aberto_em >= self.reset_s:
            self._estado = self.MEIO_ABERTO
            self._teste_em_andamento = False
        return self._estado

    def permitir(self) -> bool:
        """True se a chamada pode ir adiante."""
        with self._trava:
            estado = self._estado_atual()
            if estado == self.FECHADO:
                return True
            if estado == self.MEIO_ABERTO and not self._teste_em_andamento:
                self._teste_em_andamento = True   # só UMA chamada de teste
                return True
            return False

    def segundos_para_tentar(self) -> int:
        with self._trava:
            restante = self.reset_s - (self._relogio() - self._aberto_em)
            return max(int(restante) + 1, 1)

    def registrar_sucesso(self):
        with self._trava:
            self._estado = self.FECHADO
            self._falhas = 0
            self._teste_em_andamento = False

    def registrar_falha(self):
        with self._trava:
            self._falhas += 1
            if self._estado == self.MEIO_ABERTO or self._falhas >= self.falhas_limite:
                self._estado = self.ABERTO
                self._aberto_em = self._relogio()
                self._teste_em_andamento = False


def chamar(metodo: str, url: str, breaker: CircuitBreaker, *,
           tentativas: int | None = None, espera_base: float | None = None,
           timeout=None, dormir=time.sleep, **kwargs) -> requests.Response:
    """
    Faz a requisição HTTP com timeout + retentativa + circuit breaker.
    Respostas 4xx (erro do cliente) NÃO são falha do serviço: voltam direto.
    Levanta ServicoIndisponivel quando esgota as tentativas ou o circuito está aberto.
    """
    tentativas = tentativas if tentativas is not None else RETRY_TENTATIVAS
    espera_base = espera_base if espera_base is not None else RETRY_ESPERA_BASE_S
    timeout = timeout or (TIMEOUT_CONEXAO_S, TIMEOUT_LEITURA_S)
    ultimo_erro = "erro desconhecido"

    for tentativa in range(tentativas):
        if not breaker.permitir():
            raise ServicoIndisponivel(
                f"circuito aberto para '{breaker.nome}'", breaker.segundos_para_tentar())
        try:
            resposta = requests.request(metodo, url, timeout=timeout, **kwargs)
            if resposta.status_code in STATUS_TRANSITORIOS or resposta.status_code >= 500:
                raise requests.HTTPError(f"HTTP {resposta.status_code}", response=resposta)
            breaker.registrar_sucesso()
            return resposta
        except requests.RequestException as erro:
            breaker.registrar_falha()
            ultimo_erro = f"{type(erro).__name__}: {erro}"
            print(f"[resiliencia] {breaker.nome}: tentativa {tentativa + 1}/{tentativas} "
                  f"falhou ({type(erro).__name__}); circuito={breaker.estado}")
            if tentativa < tentativas - 1:
                espera = espera_base * (2 ** tentativa)
                dormir(espera + random.uniform(0, espera * 0.2))   # jitter

    raise ServicoIndisponivel(
        f"'{breaker.nome}' indisponivel apos {tentativas} tentativas ({ultimo_erro})",
        breaker.segundos_para_tentar() if breaker.estado == CircuitBreaker.ABERTO else None)

"""
Interface gRPC do servico de inferencia.

PRE-REQUISITO: gerar os stubs antes de rodar (veja scripts/gerar_stubs).

Metodos: Prever e PreverLote.
Cada chamada gera um log (metodo, tamanho, status, tempo) SEM o conteudo do texto,
e os erros voltam com codigos gRPC explicitos:
  INVALID_ARGUMENT (texto vazio/grande demais, lote vazio/grande demais) e INTERNAL (falha do modelo).

Rodar:  python -m app.servidor_grpc
"""
import time
from concurrent import futures

import grpc

from app.modelo import carregar_modelo

try:
    import inferencia_pb2
    import inferencia_pb2_grpc
except ImportError:  # pragma: no cover
    raise SystemExit(
        "Stubs nao encontrados. Rode antes:\n"
        "  python -m grpc_tools.protoc -I proto --python_out=. "
        "--grpc_python_out=. proto/inferencia.proto"
    )


TEXTO_MAX = 2000
LOTE_MAX = 100


def _registrar(metodo: str, tamanho: int, status: str, inicio: float) -> None:
    """Log da chamada: nunca inclui o texto (LGPD)."""
    print(f"[grpc] {metodo} tamanho={tamanho} status={status} "
          f"({(time.time() - inicio) * 1000:.1f}ms)")


def _validar_texto(texto: str):
    if not texto or not texto.strip():
        return "texto vazio"
    if len(texto) > TEXTO_MAX:
        return f"texto maior que {TEXTO_MAX} caracteres"
    return None


class ServicoInferencia(inferencia_pb2_grpc.InferenciaServicer):

    def __init__(self):
        print("[grpc] carregando modelo...")
        self.modelo = carregar_modelo()
        print("[grpc] modelo pronto")

    def Prever(self, request, context):
        inicio = time.time()
        erro = _validar_texto(request.texto)
        if erro:
            _registrar("Prever", len(request.texto), "INVALID_ARGUMENT", inicio)
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, erro)
        try:
            r = self.modelo.prever(request.texto)
        except Exception as e:  # noqa: BLE001
            print(f"[grpc] ERRO no modelo: {type(e).__name__}")
            _registrar("Prever", len(request.texto), "INTERNAL", inicio)
            context.abort(grpc.StatusCode.INTERNAL, "falha ao executar o modelo")
        _registrar("Prever", len(request.texto), "OK", inicio)
        return inferencia_pb2.RespostaPrever(
            texto=r["texto"], sentimento=r["sentimento"], confianca=r["confianca"]
        )

    def PreverLote(self, request, context):
        inicio = time.time()
        textos = list(request.textos)
        if not textos:
            _registrar("PreverLote", 0, "INVALID_ARGUMENT", inicio)
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "lote vazio")
        if len(textos) > LOTE_MAX:
            _registrar("PreverLote", len(textos), "INVALID_ARGUMENT", inicio)
            context.abort(grpc.StatusCode.INVALID_ARGUMENT,
                          f"lote maior que {LOTE_MAX} textos")
        for texto in textos:
            erro = _validar_texto(texto)
            if erro:
                _registrar("PreverLote", len(textos), "INVALID_ARGUMENT", inicio)
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, f"item invalido no lote: {erro}")

        resultados = []
        try:
            for texto in textos:
                r = self.modelo.prever(texto)
                resultados.append(inferencia_pb2.RespostaPrever(
                    texto=r["texto"], sentimento=r["sentimento"], confianca=r["confianca"]))
        except Exception as e:  # noqa: BLE001
            print(f"[grpc] ERRO no modelo: {type(e).__name__}")
            _registrar("PreverLote", len(textos), "INTERNAL", inicio)
            context.abort(grpc.StatusCode.INTERNAL, "falha ao executar o modelo")
        _registrar("PreverLote", len(textos), "OK", inicio)
        return inferencia_pb2.RespostaLote(resultados=resultados)


def servir(porta: int = 50051):
    servidor = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    inferencia_pb2_grpc.add_InferenciaServicer_to_server(
        ServicoInferencia(), servidor)
    servidor.add_insecure_port(f"[::]:{porta}")
    servidor.start()
    print(f"[grpc] escutando na porta {porta}")
    servidor.wait_for_termination()


if __name__ == "__main__":
    servir()

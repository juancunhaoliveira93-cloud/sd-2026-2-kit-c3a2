import numpy as np
from fastapi.testclient import TestClient

import main


def setup_function():
    main.armazem = main.Armazem()


def test_embedding_deterministico_e_normalizado():
    a, b = main.embedding("produto otimo"), main.embedding("produto otimo")
    assert np.allclose(a, b) and abs(np.linalg.norm(a) - 1) < 1e-5


def test_busca_devolve_mais_parecido_primeiro():
    c = TestClient(main.app)
    c.post("/indexar", json={"id": "1", "texto": "entrega rapida e atendimento excelente"})
    c.post("/indexar", json={"id": "2", "texto": "produto quebrou no primeiro dia"})
    r = c.post("/buscar", json={"texto": "atendimento excelente e entrega rapida", "k": 2}).json()
    assert r["resultados"][0]["id"] == "1"


def test_nao_guarda_o_texto():
    c = TestClient(main.app)
    c.post("/indexar", json={"id": "1", "texto": "meu cpf e 123", "metadados": {"sentimento": "positivo"}})
    vetor, meta, _ = main.armazem._itens["1"]
    assert "cpf" not in str(meta) and isinstance(vetor, np.ndarray)


def test_ttl_expira():
    arm = main.Armazem()
    arm.indexar("1", main.embedding("a"), {}, agora=1000)
    assert arm.tamanho() == 1
    assert arm.buscar(main.embedding("a"), 3, agora=1000 + main.TTL_S + 1) == []


def test_limite_maximo_remove_o_mais_antigo(monkeypatch):
    monkeypatch.setattr(main, "MAX_ITENS", 2)
    arm = main.Armazem()
    for i, t in enumerate(["a", "b", "c"]):
        arm.indexar(t, main.embedding(t), {}, agora=1000 + i)
    assert arm.tamanho() == 2 and "a" not in arm._itens


def test_snapshot_em_disco(tmp_path):
    caminho = str(tmp_path / "v.json")
    arm = main.Armazem()
    arm.indexar("1", main.embedding("ola mundo"), {"s": "x"})
    arm.salvar(caminho)
    novo = main.Armazem()
    novo.carregar(caminho)
    assert novo.tamanho() == 1

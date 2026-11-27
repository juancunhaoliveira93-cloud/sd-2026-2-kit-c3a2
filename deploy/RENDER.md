# Deploy no Render (usado na entrega)

> URL pública: https://sd-2026-2-kit-c3a2-w7zb.onrender.com · documentação interativa: `/docs`

## Como está montado

O plano gratuito do Render só aceita **web service**: não há worker em segundo plano, nem rede privada
entre serviços, e o serviço dorme após 15 min sem tráfego. Por isso o deploy usa **uma única imagem**
(`Dockerfile.render`) que roda a plataforma inteira em um container:

```
internet ──HTTPS (Render)──▶ gateway :$PORT ──127.0.0.1──▶ inferencia :8001 ──▶ Redis :6379 ◀── worker
                                          └────127.0.0.1──▶ vetorial  :8002 ◀───────────────────┘
```

- Só o **gateway** escuta na porta pública. Inferência, vetorial e Redis escutam apenas em `127.0.0.1`
  (não dá para chamá-los de fora, então JWT e rate limit não podem ser contornados).
- Os mesmos 5 componentes do `docker-compose.yml` continuam separados em código e processos; o compose segue
  sendo a forma de rodar como microsserviços independentes (local ou VM). Ver trade-offs em `docs/TRADEOFFS.md`.
- Vantagem de rodar junto: com tráfego no gateway, o worker e o Redis também estão acordados
  (um worker em serviço separado dormiria no free tier e as tarefas ficariam paradas).
- Uso de memória medido com tudo rodando e sob tráfego: ~390 MB dos 512 MB do plano gratuito.

## Configuração no painel do Render (Settings do serviço)

| Campo | Valor |
|---|---|
| Runtime | Docker |
| Root Directory | *(vazio — raiz do repositório)* |
| Dockerfile Path | `./Dockerfile.render` |
| Docker Build Context Directory | `.` |
| Health Check Path | `/saude` |
| Branch / Auto-Deploy | `main` / ligado (cada `git push` publica) |

### Variáveis de ambiente (Environment)

| Variável | Valor | Observação |
|---|---|---|
| `JWT_SEGREDO` | texto aleatório longo | gere com `openssl rand -hex 32`. **Obrigatória**: o serviço recusa subir com o valor padrão |
| `USUARIOS` | `avaliador:SENHA-FORTE` | formato `usuario:senha` (vários separados por vírgula). **Obrigatória**; não pode conter `demo:demo123` |
| `JWT_EXPIRA_MINUTOS` | `30` | opcional |
| `RATE_LIMIT_POR_MINUTO` | `30` | opcional (padrão). Só aumente temporariamente para medir latência |

Nunca coloque a senha de produção no repositório (ele é público): ela vive só no painel do Render
e é informada ao professor no campo de entrega.

## Testar a URL pública

```bash
BASE_URL=https://sd-2026-2-kit-c3a2-w7zb.onrender.com API_USUARIO=avaliador API_SENHA=SENHA-FORTE python3 scripts/smoke_test.py
```

Dica: o serviço dorme após 15 min. Abra `/docs` no navegador antes e espere carregar (pode levar ~50 s);
depois rode o teste. Esperado: `RESULTADO: tudo certo`.

## Problemas comuns

| Sintoma | Causa provável |
|---|---|
| Deploy "Exited" logo após subir, log com `ERRO: defina JWT_SEGREDO` | falta configurar as variáveis de ambiente acima |
| `Out of memory` no log | plano gratuito (512 MB) estourou; faça *Manual Deploy → Clear build cache & deploy* e, se persistir, suba de plano |
| `/saude` ok mas `/predict` com `503` | algum processo interno caiu: veja os logs (`[start]`, `[inferencia]`, `[worker]`) |
| Primeira chamada muito lenta ou `timeout` | serviço estava dormindo; repita |
| `404 {"detail":"Not Found"}` em `/` | normal: o gateway não tem rota na raiz; use `/docs` ou `/saude` |

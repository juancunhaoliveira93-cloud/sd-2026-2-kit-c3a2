# Relatório de trade-offs: CAP, custo e latência

> Responsável: Lucas

## 1. CAP

Em partição de rede, escolhemos **disponibilidade (AP)** nos caminhos de escrita/leitura de tarefas e aceitamos **consistência eventual**:

| Componente | Escolha | Justificativa e consequência |
|---|---|---|
| Fila + resultados (Redis, instância única) | **CP na prática** (um único nó: se cai, a fila para) | Sem réplica não há inconsistência, mas há ponto único de falha. Com Redis Sentinel/Cluster viraria AP com perda possível de escritas recentes |
| Fluxo assíncrono (`202` + consulta) | **AP / consistência eventual** | O cliente recebe `202` na hora; o resultado aparece depois. Consultar cedo devolve `na_fila`/`processando` |
| Armazenamento vetorial | **AP** | Se estiver fora do ar, o worker segue sem indexar (degradação graciosa); o índice pode ficar defasado |
| Gateway (circuit breaker) | **A** com falha rápida | Serviço doente → `503` imediato em vez de travar o cliente |
| Entrega da fila | **At-least-once** | Retentativas podem duplicar uma tarefa; é aceitável porque a inferência é idempotente |

## 2. Latência

Medição local de referência (`python scripts/medir_latencia.py`, 30 amostras, tudo em um host):

| Operação | p50 (ms) | p95 (ms) | máx (ms) |
|---|---|---|---|
| `/predict-sync` | 5,5 | 11,5 | 20,4 |
| `/predict` (até o 202) | 6,8 | 10,5 | 11,0 |
| Fim a fim assíncrono | 13,6 | 19,4 | 74,1 |

Medição na **URL pública** (Render free tier, `scripts/medir_latencia.py`, 5 amostras, feita a partir do Brasil com o serviço já acordado):

| Operação | p50 (ms) | p95 (ms) | máx (ms) |
|---|---|---|---|
| `/predict-sync` | 511,6 | 737,1 | 737,1 |
| `/predict` (até o 202) | 328,0 | 405,5 | 405,5 |
| Fim a fim assíncrono | 814,1 | 1026,9 | 1026,9 |

> Com só 5 amostras, p95 e máximo coincidem: os números mostram a ordem de grandeza, não uma estatística robusta.
> Comparada à medição local, a latência pública é cerca de duas ordens de grandeza maior. O modelo continua levando poucos
> milissegundos; o que domina é a rede (cada requisição HTTPS ao servidor do Render custa centenas de ms) e, após inatividade,
> o *cold start* do plano gratuito (o serviço dorme após 15 min e a primeira chamada pode levar ~50 s). O fim a fim assíncrono
> (~0,8 s) soma o envio da tarefa e as consultas ao `/resultado` até ficar pronta.

Trade-offs: o caminho assíncrono é mais lento fim a fim (+ fila + worker) mas **responde rápido ao cliente**
e absorve picos; o síncrono é mais simples e rápido para cargas leves, porém trava o cliente se o modelo demorar.
Timeouts curtos (1,5 s conexão / 5 s leitura) e retentativas com backoff limitam a pior latência a poucos segundos
(≈ 3 tentativas + esperas de 0,3 s e 0,6 s) — depois disso o circuito abre e a falha passa a ser instantânea.

## 3. Custo

| Decisão | Economiza | Custo/limite |
|---|---|---|
| Tudo em um único container no Render free (`Dockerfile.render`) | Dinheiro (R$ 0) e o worker não dorme sozinho | Os 5 processos dividem 512 MB e uma CPU e falham juntos; sem alta disponibilidade; serviço dorme após 15 min |
| Redis único, sem persistência | Simplicidade | Fila em memória: reiniciar o Redis perde tarefas pendentes |
| Modelo leve (scikit-learn) no worker | CPU/GPU | Sem LLM; sofisticação do modelo não pontua |
| Embedding por hash (sem modelo externo) | Chamadas de API pagas | Similaridade lexical, não semântica |
| Jaeger em memória | Armazenamento | Traces somem ao reiniciar |
| Rate limit em memória do gateway | Não precisa de Redis compartilhado | Com N réplicas o limite efetivo é N× |

Free tier: o Render só oferece instância gratuita para *web service* (worker em segundo plano é pago, não há rede
privada entre serviços e o serviço dorme após 15 min). Por isso o deploy público roda a plataforma inteira em **um container**
(`Dockerfile.render`): só o gateway é público e os demais componentes escutam em `127.0.0.1`. Troca consciente: perdemos o
isolamento e a escala independente de cada serviço na nuvem, mas ganhamos um worker que funciona no plano gratuito.
Os microsserviços independentes continuam no `docker-compose.yml` e na opção de VM (`deploy/INSTRUCOES.md`).

## 4. Como escalaria
`docker compose up --scale worker=N` já divide a carga (BLPOP entrega cada tarefa a um só worker). Próximos passos:
autoescalonamento por tamanho da fila, Redis gerenciado com réplica e rate limit compartilhado.

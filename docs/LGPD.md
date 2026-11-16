# Conformidade com a LGPD

> Responsável: Carine · Projeto acadêmico (C3.A2). Este documento descreve o que a plataforma
> realmente faz no código — cada prazo abaixo é configurável por variável de ambiente.

## 1. Quais dados são tratados, para quê e por quanto tempo

| Dado | Onde fica | Finalidade | Retenção |
|---|---|---|---|
| **Texto enviado** para análise (pode conter dado pessoal, pois é texto livre) | Redis (fila e resultado) | Executar a inferência e devolver o resultado ao próprio solicitante | Resultado expira em **1 h** (`RESULTADO_TTL_S=3600`) |
| Texto de tarefas que **falharam** (DLQ) | Redis (`dlq:<id>`) | Diagnóstico de falhas | Expira em **24 h** (`DLQ_TTL_S=86400`) |
| **Vetor** (representação numérica) + id + sentimento | Serviço vetorial | Busca por similaridade | Expira em **24 h** (`VETORIAL_TTL_S`). O texto original **não** é guardado |
| **Usuário** (login) | Variável de ambiente `USUARIOS` e claim `sub` do JWT | Autenticar e aplicar limite por cliente | Token vale **30 min** (`JWT_EXPIRA_MINUTOS`) |
| **Endereço IP** | Memória do gateway | Limitar tentativas de login (rate limit) | **60 s** (janela deslizante), nunca gravado em disco |
| **Logs** | Saída padrão dos containers | Operação e depuração | Somente método, rota, status, tamanho e tempo. **Nunca** o texto, o token ou a senha |
| **Traces** (Jaeger) | Memória do Jaeger | Observabilidade | Somente rotas, ids de tarefa e tempos. Sem conteúdo do usuário; some ao reiniciar |

## 2. Princípios aplicados no código

- **Minimização:** o vetorial guarda só o vetor; logs e traces não carregam o texto; o texto tem limite de 2000 caracteres.
- **Limitação de retenção:** tudo que contém conteúdo do usuário tem prazo de expiração automático (TTL).
- **Segurança:** HTTPS na borda, JWT com expiração, rate limit, senha comparada em tempo constante, serviços internos sem porta pública.
- **Transparência:** esta tabela e o README informam dados, finalidade e prazo.

## 3. Direitos do titular

- **Eliminação:** os dados são eliminados automaticamente nos prazos acima; para eliminação imediata, o administrador remove as chaves do Redis (`DEL resultado:<id>`) ou reinicia o serviço vetorial.
- **Acesso/correção:** o titular só consegue consultar o resultado de uma tarefa pelo `id` recebido.

## 4. Limitações assumidas (honestidade técnica)

- O usuário do exemplo (`demo`) e as senhas em variável de ambiente servem só para demonstração; em produção usar hash de senha e um provedor de identidade.
- Não há endpoint de "apagar meus dados"; a retenção curta (TTL) é a mitigação adotada.
- Nenhum dado pessoal real deve ser enviado ao ambiente de demonstração.

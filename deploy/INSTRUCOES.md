# Deploy em nuvem (free tier) com HTTPS

> Responsável: Victor

## Por que não Render/Railway puro?
No Render, o free tier é **só para web service** (worker em segundo plano e private service são pagos;
o web service gratuito dorme após 15 min). Como nossa arquitetura precisa de gateway + inferência + worker +
vetorial + Redis, a opção mais fiel ao edital é **uma VM gratuita rodando o `docker compose`**, com
**Caddy** fazendo o HTTPS. *(Confira as condições vigentes do free tier do provedor escolhido antes de começar.)*

## Opção A (recomendada): VM free tier + docker compose + Caddy

1. **Crie uma VM Linux** em um provedor com camada gratuita (ex.: Oracle Cloud *Always Free* ou Google Cloud
   *e2-micro*). Anote o **IP público**.
2. **Libere as portas 80 e 443** no firewall/security group do provedor. **Não** abra 8000, 16686 nem 6379.
3. **Domínio gratuito com HTTPS:** use `sslip.io`, que resolve o IP automaticamente. Para o IP `203.0.113.10`:
   `203-0-113-10.sslip.io`. (Alternativa: DuckDNS.)
4. **Instale Docker** na VM (`curl -fsSL https://get.docker.com | sh`) e clone o repositório:
   ```bash
   git clone https://github.com/juancunhaoliveira93-cloud/sd-2026-2-kit-c3a2.git plataforma
   cd plataforma
   cp .env.example .env
   ```
5. **Edite o `.env`** com valores de produção:
   ```
   DOMINIO=203-0-113-10.sslip.io
   JWT_SEGREDO=<gere com: openssl rand -hex 32>
   USUARIOS=admin:<senha-forte>
   CONFIAR_PROXY=true
   ```
6. **Suba:**
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
   ```
7. **Teste a URL pública:**
   ```bash
   BASE_URL=https://203-0-113-10.sslip.io API_USUARIO=admin API_SENHA=<senha-forte> python scripts/smoke_test.py
   ```
8. **Anote a URL pública no README** (seção "Deploy").

### Solução de problemas
- Certificado não emitido: confira se as portas 80/443 estão abertas e se `DOMINIO` está correto (`docker compose logs caddy`).
- Pouca RAM: a build pode falhar; crie *swap* (`sudo fallocate -l 2G /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile`).

## Opção B (plano B): Render com tudo como web service
Só se não houver VM: publicar cada serviço como *web service* gratuito (com URLs públicas entre si), usar o
*Key Value* gratuito do Render como Redis e o worker como web service com thread consumidora.
Perde-se a rede privada e o serviço dorme após 15 min — documente essas limitações no relatório.

## CI/CD (extensão opcional)
`.github/workflows/ci.yml` roda testes + sobe o compose + smoke test a cada commit. O job `deploy` só executa se
os segredos `DEPLOY_HOST`, `DEPLOY_USER` e `DEPLOY_SSH_KEY` estiverem configurados no GitHub (Settings → Secrets).

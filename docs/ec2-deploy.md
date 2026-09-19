# Query Mind EC2 deploy (own machine)

Query Mind owns this box. ServeEasy runs on a **different** EC2 and talks to this host over HTTP.

| | Query Mind (this project) | ServeEasy |
|---|---|---|
| Public URL | `http://chatapp.clustorflow.com` | `http://easyserve.clustorflow.com` |
| DNS A record | this EC2 public IP | ServeEasy public IP |
| Remote dir | `/opt/app` | `/opt/serveeasy` (other machine) |
| Nginx | `querymind-nginx` publishes host `:80` | `serveeasy-nginx` on the other host |
| Containers | `chat-llm`, `querymind-nginx` | not on this instance |
| Docker network | `querymind_net` | — |

GitHub secret `EC2_HOST` in **this** repo must be the Query Mind instance only.

## Traffic

```
Browser / ServeEasy API  -->  chatapp.clustorflow.com:80  -->  querymind-nginx  -->  chat-llm:8000

Query Mind MCP client  -->  http://easyserve.clustorflow.com/mcp
```

ServeEasy stores `QUERYMIND_URL=http://chatapp.clustorflow.com`. The Query Mind org `mcp_server_url` must be the public ServeEasy MCP URL, not a Docker hostname.

## GitHub secrets

- `EC2_HOST` — Query Mind public IP
- `EC2_SSH_PRIVATE_KEY`
- `ECR_REGISTRY`, `AWS_REGION`
- `GEMINI_API_KEY`
- `DJANGO_SECRET_KEY` — required. Deploy fails closed without it and writes `DJANGO_DEBUG=false`
- `APP_MODE` — optional, default `both`

Workflow **Deploy** (`08-deploy.yaml`) uploads `docker-compose.deployment.yml` and `nginx.conf` to `/opt/app`, writes `.env`, and starts `chat-llm` + `querymind-nginx`.

## DNS and security groups

| Type | Host | Value |
|------|------|--------|
| A | `chatapp` | this EC2 public IP |
| A | `easyserve` | ServeEasy EC2 public IP |

Inbound TCP **22** and **80**. Allow TCP **80 from the ServeEasy security group** as well as from users; assistant chat is server-to-server.

## Cutover from the old shared EC2

Typical path: keep Query Mind on the current box, move ServeEasy to a new box.

1. Move ServeEasy first (see ServeEasy `docs/ec2-deploy.md`). Point `easyserve` DNS at the new IP.
2. On this box: `docker rm -f nginx edge-nginx` (the deploy workflow does this).
3. Stop leftover ServeEasy on this box if it is still running:
   `cd /opt/serveeasy && docker compose -p serveeasy -f docker-compose.deployment.yml down`
4. Dispatch Query Mind **Deploy**. Confirm `querymind-nginx` is publishing `:80`.
5. Confirm `curl -sS http://chatapp.clustorflow.com/api/v1/health`.
6. In the ServeEasy org on this host, set MCP URL to `http://easyserve.clustorflow.com/mcp`.

Do not recreate `public_web` or start `edge-nginx`.

## TLS / who may use HTTP

`http://chatapp.clustorflow.com` is a **private pilot** until TLS terminates in front of `querymind-nginx`. API keys and forwarded restaurant JWTs travel in cleartext on port 80.

Production uses **SQLite** (`SQLITE_PATH=/app/data/db.sqlite3`). There are no Celery/Redis workers. Local org `llm_backend=local` talks to host Ollama; it does not silently fall back to Gemini.

## Health

- `chat-llm` → `http://127.0.0.1:8000/api/v1/health`
- Public → `http://chatapp.clustorflow.com/api/v1/health`

## Seed (after first boot)

```bash
cd /opt/app
docker exec -it chat-llm python manage.py seed_example_data \
  --mcp-url http://easyserve.clustorflow.com/mcp
```

Put the printed key in ServeEasy GitHub secret `QUERYMIND_API_KEY` and redeploy ServeEasy.

# QueryMind

QueryMind is the **MCP client** and SQL chat product. ServeEasy is a separate restaurant SaaS and MCP **server**. Do not put restaurant JWTs in QueryMind settings — only the MCP server URL.

## Run locally

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py seed_example_data
uv run python manage.py runserver
```

Optional local LLM: Ollama on the **host** (`http://localhost:11434`). Docker/EC2 `localhost` is that host, not a compose service. Set `OLLAMA_BASE_URL` if Ollama is elsewhere. Org backend `local` does **not** fall back to Gemini.

```bash
ollama pull qwen2.5:3b
```

## Tests

```bash
uv run python manage.py test chat.tests connections.tests
```

## Environment

| Variable | Purpose |
|---|---|
| `DJANGO_SECRET_KEY` | Required in production (`APP_ENV=production`) and whenever `DEBUG` is false |
| `DJANGO_DEBUG` / `DEBUG` | Production deploy writes `false`. Never inferred from an insecure key in production |
| `APP_ENV` | `production` fail-closes missing/insecure secrets |
| `APP_MODE` | `chat`, `api`, or `both` |
| `DJANGO_ALLOWED_HOSTS` | Explicit hosts when DEBUG is false |
| `GEMINI_API_KEY` | Online LLM |
| `OLLAMA_BASE_URL` | Default `http://localhost:11434` |
| `SQLITE_PATH` | Production compose uses `/app/data/db.sqlite3` (SQLite volume, not the local Postgres vars) |

GitHub deploy secret **`DJANGO_SECRET_KEY`** is required. See [docs/ec2-deploy.md](docs/ec2-deploy.md).

## Docs (sign in, API-enabled org)

- API keys: http://127.0.0.1:8000/developers/
- MCP client: http://127.0.0.1:8000/developers/mcp/

## Architecture notes

- ServeEasy staff chat calls QueryMind `POST /api/v1/messages/` with `x-api-key` and `X-MCP-Authorization` (restaurant JWT).
- QueryMind lists/calls tools on ServeEasy `/mcp`. Restaurant RBAC is the JWT on ServeEasy, not a QueryMind allowlist. ServeEasy production must be **ASGI** (Gunicorn + UvicornWorker); `runserver` is WSGI JSON-RPC only.
- Django `/admin/` is QueryMind-branded **staff admin** for superusers (orgs, memberships, MCP URLs, API keys). Organization admins use Dashboard and Team in the product.
- Writes never go through SQL against the restaurant database.
- There are **no** Celery/Redis workers. Production nginx is HTTP `:80` until TLS is terminated in front — go-live gate, not done in this repo.
- `vercel.json` is not a QueryMind deploy path.

Production URL: `http://chatapp.clustorflow.com`. ServeEasy is a different EC2.

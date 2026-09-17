# QueryMind

Ask a question in English, get a result from a connected database — or a refusal if the SQL is unsafe.

**Status:** personal product. The LangGraph safety pipeline is most complete on `LangGraph_with_onprimise_and_api`. Some agent files on `main` are still stubs.

---

## What it does

QueryMind does **not** copy client business rows into its own tables. It stores users, workspaces, connection metadata, schema cache, and query history. Client data is read at query time, under constraints.

```text
Question
  → Schema (inspect, allow-list)
  → Generate SQL
  → Validate (parse, filter, fail-closed)
  → Execute (read-only, timed)  or  Refuse
```

---

## What I built

- LangGraph workflow: plan, ground against schema, generate SQL, validate, then execute / repair / refuse
- SQL safety: **SELECT-only**, no `SELECT *`, table/column allow-lists, one statement, **read-only transactions**, statement timeout, row cap
- Django + PostgreSQL product app (users, connections, history)
- Docker, Nginx, GitHub Actions, and Terraform on the LangGraph work

MCP is in the dependency set and on a dedicated branch. The path that actually runs is the validator and executor, not an unrestricted model calling the database.

**One-pager:** [querymind.pdf](docs/querymind.pdf)

---

## Stack

| Area | Tools |
| --- | --- |
| App | Django, Django REST Framework |
| Agent | LangGraph |
| SQL safety | sqlglot, allow-lists, read-only tx |
| Data | PostgreSQL |
| Packaging | Docker, Nginx, GitHub Actions, Terraform |

---

## Run

See the Django project in this repo. Prefer the `LangGraph_with_onprimise_and_api` branch if you want the implemented graph, not stubs.

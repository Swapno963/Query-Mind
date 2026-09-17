# QueryMind

Natural-language-to-SQL: LangGraph plans, grounds against schema, generates SQL, then validates or refuses. SELECT-only, no `SELECT *`, allow-lists, read-only transactions, timeouts. Django + PostgreSQL. Built so the model cannot freely hit the database.

**One-pager:** [querymind.pdf](docs/querymind.pdf)

---

## What it is

QueryMind lets a user ask a question in English and get an answer from a connected database. It does **not** dump client business data into its own tables. It stores users, workspaces, connection metadata, schema cache, and query history. Client rows are read at query time, under constraints.

```text
Question
  → Schema (inspect, allow-list)
  → Generate SQL
  → Validate (parse, filter, fail-closed)
  → Execute (read-only, timed)  or  Refuse
```

The QueryMind database holds the product itself. An optional client database is queried through a read-only path: allowed tables and columns, max rows, statement timeout.

---

## Safety model

Implemented checks before anything hits a client database:

- **SELECT-only** SQL, parsed with sqlglot (PostgreSQL dialect)
- **No `SELECT *`**
- Table and column **allow-lists**; unauthorized identifiers fail closed
- One statement at a time
- **Read-only transaction** (`SET TRANSACTION READ ONLY`)
- **Statement timeout**
- Row cap on streamed results
- Repair/retry with a cap; otherwise refuse

The model proposes SQL. The validator and executor decide whether it runs.

---

## Agent workflow

The LangGraph path (see `agent/`):

1. Plan the question
2. Ground against discovered / allow-listed schema
3. Generate SQL
4. Validate
5. Execute, repair, or refuse
6. Format the result

Failed execution goes through error analysis and limited retries. Connection failures and policy violations are refused rather than retried forever.

MCP appears as a dependency and as an optional tool path. The default safety path is schema grounding plus SQL validation, not unrestricted tool calling.

---

## Stack

| Area | Tools |
| --- | --- |
| App | Django, Django REST Framework |
| Agent | LangGraph |
| SQL safety | sqlglot, allow-lists, read-only tx |
| Data | PostgreSQL |
| Packaging | Docker, Nginx, GitHub Actions, Terraform (LangGraph work) |

---

## Status

The LangGraph safety pipeline is most complete on `LangGraph_with_onprimise_and_api`. Some agent files on `main` are still stubs; read that branch for the implemented graph.

This repository is the public engineering record for QueryMind, not a claim that every branch is production-ready.

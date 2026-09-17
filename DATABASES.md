# Database engines

QueryMind executes **read-only SELECT** queries against a customer database after allow-list validation. Engines do not behave identically.

## Supported engines

| Engine | Connection | Schema discovery | sqlglot dialect | EXPLAIN JSON | Read-only session |
|---|---|---|---|---|---|
| PostgreSQL | `psycopg` | `information_schema` + `pg_catalog` comments | `postgres` | Yes | `SET TRANSACTION READ ONLY` + `statement_timeout` |
| MySQL / MariaDB | `pymysql` | `information_schema` for current schema | `mysql` | `EXPLAIN FORMAT=JSON` | `START TRANSACTION READ ONLY` (timeout best-effort) |
| Oracle | `oracledb` (thin) | `USER_TABLES` / `USER_TAB_COLUMNS` | `oracle` | Not implemented | `SET TRANSACTION READ ONLY` (must be first statement) |
| SQL Server | `pymssql` | `INFORMATION_SCHEMA` | `tsql` | Not implemented | `SET LOCK_TIMEOUT` only |

PostgreSQL remains the most complete path: privilege checks for superuser/owner, confirmed read-only roles, and Django connection pooling via `django.db.backends.postgresql`.

MySQL, Oracle, and SQL Server use native drivers for discovery and execution. They are **not** registered as Django `DATABASES` aliases except PostgreSQL.

## Limitations

- **Oracle** connects with `service_name` = the “database name” field. SID connections are not a separate UI option. Thick mode / Instant Client is not required for thin mode.
- **SQL Server** table names are stored without schema qualification. Two tables with the same name in different schemas can collide in the allow-list.
- **EXPLAIN** is skipped for Oracle and SQL Server. The critic still runs AST checks.
- **Read-only role detection** (`is_readonly_role`) is PostgreSQL-only. Other engines show “Connected” unless the login is rejected (MySQL `root@`, SQL Server `sysadmin`).
- **MySQL `MAX_EXECUTION_TIME`** may require privileges; QueryMind ignores failures and still enforces `max_rows`.
- **Chunked / server-side cursors** are PostgreSQL-specific. Other engines stream with `fetchmany`.
- Driver packages must be installed (`pymysql`, `oracledb`, `pymssql`). Missing drivers return a connection error, not a silent fallback to PostgreSQL.
- Generated SQL uses the engine dialect. PostgreSQL-only functions (for example `ILIKE`, `TIMESTAMPTZ`) may fail on other engines; repair uses the engine language name.

## Credentials

Workspace passwords are stored encrypted. API and UI responses never include the password. Connection errors are mapped to generic messages; raw driver text is kept as internal `detail` on discovery only for the connecting admin.

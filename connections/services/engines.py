from __future__ import annotations

from typing import Any

ENGINE_POSTGRES = "postgres"
ENGINE_MYSQL = "mysql"
ENGINE_ORACLE = "oracle"
ENGINE_MSSQL = "mssql"

ENGINE_CHOICES = [
    (ENGINE_POSTGRES, "PostgreSQL"),
    (ENGINE_MYSQL, "MySQL"),
    (ENGINE_ORACLE, "Oracle"),
    (ENGINE_MSSQL, "Microsoft SQL Server"),
]

SQLGLOT_DIALECT = {
    ENGINE_POSTGRES: "postgres",
    ENGINE_MYSQL: "mysql",
    ENGINE_ORACLE: "oracle",
    ENGINE_MSSQL: "tsql",
}

DEFAULT_PORTS = {
    ENGINE_POSTGRES: 5432,
    ENGINE_MYSQL: 3306,
    ENGINE_ORACLE: 1521,
    ENGINE_MSSQL: 1433,
}

DJANGO_ENGINES = {
    ENGINE_POSTGRES: "django.db.backends.postgresql",
    ENGINE_MYSQL: "django.db.backends.mysql",
    ENGINE_ORACLE: "django.db.backends.oracle",
    ENGINE_MSSQL: "mssql",
}

DISPLAY_NAMES = {
    ENGINE_POSTGRES: "PostgreSQL",
    ENGINE_MYSQL: "MySQL",
    ENGINE_ORACLE: "Oracle",
    ENGINE_MSSQL: "Microsoft SQL Server",
}

SUPPORTED_ENGINES = tuple(SQLGLOT_DIALECT.keys())


def normalize_engine(value: str | None) -> str:
    raw = (value or ENGINE_POSTGRES).strip().lower()
    aliases = {
        "postgresql": ENGINE_POSTGRES,
        "postgres": ENGINE_POSTGRES,
        "pg": ENGINE_POSTGRES,
        "mysql": ENGINE_MYSQL,
        "mariadb": ENGINE_MYSQL,
        "oracle": ENGINE_ORACLE,
        "mssql": ENGINE_MSSQL,
        "sqlserver": ENGINE_MSSQL,
        "sql server": ENGINE_MSSQL,
        "microsoft sql server": ENGINE_MSSQL,
    }
    engine = aliases.get(raw, raw)
    if engine not in SQLGLOT_DIALECT:
        raise ValueError(f"Unsupported database engine: {value}")
    return engine


def sqlglot_dialect(engine: str | None) -> str:
    return SQLGLOT_DIALECT[normalize_engine(engine)]


def display_name(engine: str | None) -> str:
    try:
        return DISPLAY_NAMES[normalize_engine(engine)]
    except ValueError:
        return DISPLAY_NAMES[ENGINE_POSTGRES]


def default_port(engine: str | None) -> int:
    try:
        return DEFAULT_PORTS[normalize_engine(engine)]
    except ValueError:
        return DEFAULT_PORTS[ENGINE_POSTGRES]


def django_engine(engine: str | None) -> str:
    return DJANGO_ENGINES[normalize_engine(engine)]


def catalog_header(engine: str | None) -> str:
    return f"DATABASE: {display_name(engine)}"


def sql_language_name(engine: str | None) -> str:
    names = {
        ENGINE_POSTGRES: "PostgreSQL",
        ENGINE_MYSQL: "MySQL",
        ENGINE_ORACLE: "Oracle",
        ENGINE_MSSQL: "Microsoft SQL Server (T-SQL)",
    }
    try:
        return names[normalize_engine(engine)]
    except ValueError:
        return names[ENGINE_POSTGRES]

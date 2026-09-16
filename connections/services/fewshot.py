from __future__ import annotations

import re
from typing import Any

from connections.models import VerifiedQueryExample


_TOKEN = re.compile(r"[a-z0-9_]+")


def tokenize(text: str) -> set[str]:
    return {token for token in _TOKEN.findall((text or "").lower()) if len(token) > 1}


def retrieve_examples(
    *,
    workspace_id: int | None,
    question: str,
    allowed_tables: list[str],
    limit: int = 3,
) -> list[dict[str, Any]]:
    allowed = {str(name).lower() for name in allowed_tables or [] if name}
    q_tokens = tokenize(question)
    queryset = VerifiedQueryExample.objects.all()
    if workspace_id:
        queryset = queryset.filter(workspace_id=workspace_id)
    scored: list[tuple[float, VerifiedQueryExample]] = []
    for example in queryset[:200]:
        linked = {str(name).lower() for name in (example.linked_tables or []) if name}
        if linked - allowed:
            continue
        overlap = len(q_tokens & tokenize(example.question))
        if overlap <= 0:
            continue
        scored.append((float(overlap), example))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "question": item.question,
            "sql": item.sql,
            "linked_tables": item.linked_tables,
        }
        for _, item in scored[:limit]
    ]


def record_success(
    *,
    workspace_id: int | None,
    question: str,
    sql: str,
    linked_tables: list[str],
) -> None:
    question = (question or "").strip()
    sql = (sql or "").strip()
    if not question or not sql:
        return
    exists = VerifiedQueryExample.objects.filter(
        workspace_id=workspace_id,
        question=question,
        sql=sql,
    ).exists()
    if exists:
        return
    VerifiedQueryExample.objects.create(
        workspace_id=workspace_id,
        question=question,
        sql=sql,
        linked_tables=list(linked_tables or []),
    )

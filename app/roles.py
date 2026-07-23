from __future__ import annotations

import re

ROLE_TAG_BY_DISPLAY_NAME = {
    "김가현": "FE",
    "유승주": "FE",
    "김세민": "Infra",
    "이정헌": "AI",
    "박민용": "BE",
    "홍석호": "BE",
}
VALID_ROLE_TAGS = frozenset(ROLE_TAG_BY_DISPLAY_NAME.values())
_ROLE_PREFIX = re.compile(r"^\s*\[(?:FE|BE|Infra|AI)\]\s*", re.IGNORECASE)


def role_tag_for(display_name: str) -> str | None:
    return ROLE_TAG_BY_DISPLAY_NAME.get(display_name.strip())


def validate_role_tag(role_tag: str) -> str:
    normalized = role_tag.strip()
    if normalized not in VALID_ROLE_TAGS:
        raise ValueError("invalid role tag")
    return normalized


def ticket_summary(summary: str, role_tag: str) -> str:
    role = validate_role_tag(role_tag)
    body = summary.strip()
    while _ROLE_PREFIX.match(body):
        body = _ROLE_PREFIX.sub("", body, count=1).strip()
    if not body:
        raise ValueError("ticket summary is empty")
    prefix = f"[{role}] "
    return prefix + body[: 255 - len(prefix)].rstrip()


def ticket_description(description: str | None) -> str | None:
    if not description or not description.strip():
        return None
    return f"## 작업 내용\n{description.strip()}"

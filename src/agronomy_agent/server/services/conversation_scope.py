"""Stable conversation identities, independent of a model or field snapshot."""
from __future__ import annotations

from typing import Any


class ConversationScopeError(ValueError):
    """A request would move an existing conversation to a different scope."""


def _value(context: dict[str, Any], key: str) -> str:
    extra = context.get("extra")
    fallback = extra.get(key) if isinstance(extra, dict) else None
    return str(context.get(key) or fallback or "").strip()


def identity(context: dict[str, Any]) -> tuple[str, str]:
    inner = context.get("field_context")
    inner = inner if isinstance(inner, dict) else {}
    field_id = _value(context, "field_context_id")
    inner_id = _value(inner, "field_context_id")
    if field_id and inner_id and field_id != inner_id:
        raise ConversationScopeError("The conversation cannot bind two different fields.")
    field_id = field_id or inner_id
    key = _value(context, "field_conversation_key") or _value(inner, "field_conversation_key")
    if field_id:
        base = f"field:{field_id}"
        if key and key != base and not key.startswith(base + ":chat:"):
            raise ConversationScopeError("The conversation key does not match its field.")
        return base, key
    if key.startswith("field:"):
        raise ConversationScopeError("A field conversation requires a saved field identifier.")
    if key:
        base = key.split(":chat:", 1)[0]
        if base != "general" and not base.startswith("sample:"):
            raise ConversationScopeError("Unknown conversation scope.")
        return base, key
    return "", ""


def bind_conversation_context(
    stored: dict[str, Any] | None,
    incoming: dict[str, Any] | None,
    *,
    has_turns: bool,
) -> dict[str, Any]:
    """Hydrate omitted identity; never rebind a declared or used conversation.

    Legacy empty sessions may adopt a field on their first request. Once used,
    an unbound legacy session is general. Snapshot values remain subject to the
    field authorization boundary, which runs after this identity check.
    """
    previous = dict(stored or {})
    supplied = dict(incoming or {})
    old_base, old_key = identity(previous)
    new_base, new_key = identity(supplied)
    locked_base = old_base or ("general" if has_turns else "")
    if locked_base and new_base and locked_base != new_base:
        raise ConversationScopeError("Start a new chat to change the conversation's field or general scope.")
    if old_key and new_key and old_key != new_key:
        raise ConversationScopeError("Start a new chat to change the conversation identity.")
    merged = {**previous, **supplied}
    # Reload saved field facts through authorization, not a stale prior snapshot.
    if "field_context" not in supplied:
        merged.pop("field_context", None)
    base = locked_base or new_base or "general"
    key = old_key or new_key or base
    merged["field_conversation_key"] = key
    if base.startswith("field:"):
        merged["field_context_id"] = base.removeprefix("field:")
    # The model receives history only from the server-owned bounded query.
    for name in ("conversation_history", "chat_history", "history", "messages"):
        merged.pop(name, None)
    return merged

"""Stable conversation identities, independent of a model or field snapshot."""
from __future__ import annotations

from typing import Any


class ConversationScopeError(ValueError):
    """A request would move an existing conversation to a different scope."""


def _identity_values(context: dict[str, Any], key: str) -> set[str]:
    """Read every supported representation; conflicting aliases are not fallback."""
    extra = context.get("extra")
    outer = [context, extra] if isinstance(extra, dict) else [context]
    records = list(outer)
    for record in outer:
        inner = record.get("field_context")
        if isinstance(inner, dict):
            records.append(inner)
            if isinstance(inner.get("extra"), dict):
                records.append(inner["extra"])
    values = set()
    for record in records:
        value = record.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise ConversationScopeError("Conversation identity values must be text.")
        if value.strip():
            values.add(value.strip())
    return values


def identity(context: dict[str, Any]) -> tuple[str, str]:
    field_ids = _identity_values(context, "field_context_id")
    keys = _identity_values(context, "field_conversation_key")
    if len(field_ids) > 1 or len(keys) > 1:
        raise ConversationScopeError("The conversation contains conflicting identity aliases.")
    field_id = next(iter(field_ids), "")
    key = next(iter(keys), "")
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

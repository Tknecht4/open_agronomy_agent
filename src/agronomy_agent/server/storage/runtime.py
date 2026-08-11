from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agronomy_agent.field_events import (
    FIELD_EVENT_TYPES,
    field_event_integrity_sha256,
    field_event_sync_export,
    validate_field_event_fast_forward,
    verify_field_event_chain,
)
from agronomy_agent.field_measurements import validate_field_event_payload
from agronomy_agent.server.settings import ServerSettings
from agronomy_agent.server.services.field_context_quality import evaluate_field_context_quality
from agronomy_agent.server.services.privacy_boundary import minimized_export_trace_payload
from agronomy_agent.server.storage.db import TraceStore, _local_text_embedding
from agronomy_agent.server.storage.postgres_migrations import psycopg_connect, verify_postgres_schema


class PostgresRuntimeStore:
    """Schema-verified Postgres runtime boundary.

    The SQLite TraceStore still owns the broad local-dev method surface. This
    class makes the hosted Postgres switch explicit: startup verifies the target
    schema and implemented methods use Postgres, while unported methods fail
    loudly instead of falling back to SQLite.
    """

    backend = "postgres"
    storage_label = "postgres-runtime"

    def __init__(
        self,
        database_url: str,
        *,
        connect: Callable[..., Any] | None = None,
        verify_schema: Callable[[Any], list[str]] = verify_postgres_schema,
    ) -> None:
        if not database_url.strip():
            raise ValueError("database_url is required for Postgres runtime storage")
        self.database_url = database_url
        self._connect = connect or psycopg_connect()
        self.verified_objects = self._verify_schema(verify_schema)

    def _verify_schema(self, verify_schema: Callable[[Any], list[str]]) -> list[str]:
        try:
            with self._connect(self.database_url) as connection:
                with connection.cursor() as cursor:
                    return list(verify_schema(cursor))
        except Exception as exc:
            raise RuntimeError(f"Postgres runtime storage unavailable: {exc}") from exc

    def create_corpus_audit(self, audit_id: str, config_path: str, corpus_hash: str, corpus_count: int) -> str:
        try:
            with self._connect(self.database_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO corpus_audits(id, config_path, corpus_hash, corpus_count, updated_at)
                        VALUES (%s, %s, %s, %s, now())
                        ON CONFLICT (id) DO UPDATE SET
                          config_path = EXCLUDED.config_path,
                          corpus_hash = EXCLUDED.corpus_hash,
                          corpus_count = EXCLUDED.corpus_count,
                          updated_at = now()
                        """,
                        (audit_id, config_path, corpus_hash, corpus_count),
                    )
            return audit_id
        except Exception as exc:
            raise RuntimeError(f"Postgres corpus audit persistence failed: {exc}") from exc

    @staticmethod
    def _new_uuid() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def _to_json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, default=str)

    @staticmethod
    def _from_json(value: Any, fallback: Any) -> Any:
        if value is None:
            return fallback
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return fallback
        return fallback

    @staticmethod
    def _from_array(value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                inner = stripped[1:-1]
                if not inner:
                    return []
                return [item.strip().strip('"') for item in inner.split(",")]
            try:
                loaded = json.loads(stripped)
            except json.JSONDecodeError:
                return [stripped] if stripped else []
            return loaded if isinstance(loaded, list) else []
        return []

    @staticmethod
    def _role(value: Any) -> str:
        return str(getattr(value, "value", value))

    @staticmethod
    def _row_dict(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        if isinstance(row, dict):
            return row
        if hasattr(row, "_asdict"):
            return dict(row._asdict())
        return dict(row)

    def _cursor(self, connection: Any) -> Any:
        try:
            from psycopg.rows import dict_row  # type: ignore[import-not-found]

            return connection.cursor(row_factory=dict_row)
        except (ImportError, TypeError):
            return connection.cursor()

    def _execute_fetchone(self, query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute(query, params)
                return self._row_dict(cursor.fetchone())

    def _execute_fetchall(self, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute(query, params)
                return [self._row_dict(row) or {} for row in cursor.fetchall()]

    def _insert_audit_event(
        self,
        cursor: Any,
        *,
        event_type: str,
        actor_user_id: str,
        organization_id: str | None,
        workspace_id: str | None = None,
        target_type: str,
        target_id: str,
        payload: dict[str, Any],
    ) -> None:
        cursor.execute(
            """
            INSERT INTO audit_events(
              organization_id, workspace_id, actor_user_id, event_type,
              target_type, target_id, payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (organization_id, workspace_id, actor_user_id, event_type, target_type, target_id, self._to_json(payload)),
        )

    def _normalize_user(self, raw: dict[str, Any]) -> dict[str, Any]:
        training_candidate_allowed = bool(raw.get("training_candidate_allowed")) or str(raw.get("training_consent_default") or "").lower() == "yes"
        account_consent = {
            "schema_version": "phase6.account_consent.v1",
            "trace_storage_enabled": bool(raw.get("trace_storage_enabled", True)),
            "feedback_use_allowed": bool(raw.get("feedback_use_allowed", False)),
            "training_candidate_allowed": training_candidate_allowed,
            "public_anonymized_examples_allowed": bool(raw.get("public_anonymized_examples_allowed", False)),
            "product_updates_allowed": bool(raw.get("product_updates_allowed", False)),
            "retention_preference": raw.get("retention_preference") or "default",
            "updated_at": raw.get("consent_updated_at"),
        }
        return {
            "id": str(raw["id"]),
            "email": raw["email"],
            "display_name": raw["display_name"],
            "auth_provider_subject": raw.get("auth_provider_subject"),
            "status": raw["status"],
            "role_label": raw.get("role_label"),
            "region_hint": raw.get("region_hint"),
            "units_preference": raw.get("units_preference"),
            "privacy_mode": raw.get("privacy_mode"),
            "training_consent_default": raw.get("training_consent_default"),
            "account_consent": account_consent,
            "created_at": raw.get("created_at"),
            "updated_at": raw.get("updated_at"),
            "last_login_at": raw.get("last_login_at"),
        }

    def upsert_phase4_user(self, *, email: str, display_name: str | None = None) -> dict[str, Any]:
        normalized_email = email.strip().lower()
        if not normalized_email:
            raise ValueError("email is required")
        row = self._execute_fetchone(
            """
            INSERT INTO users(email, display_name, auth_provider_subject, last_login_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (email) DO UPDATE SET
              display_name = COALESCE(EXCLUDED.display_name, users.display_name),
              updated_at = now(),
              last_login_at = now()
            RETURNING *
            """,
            (normalized_email, display_name or normalized_email.split("@")[0], f"local_dev:{normalized_email}"),
        )
        return self._normalize_user(row or {})

    def get_phase4_user(self, user_id: str) -> dict[str, Any] | None:
        row = self._execute_fetchone("SELECT * FROM users WHERE id = %s", (user_id,))
        return self._normalize_user(row) if row else None

    def get_phase4_user_by_email(self, email: str) -> dict[str, Any] | None:
        row = self._execute_fetchone("SELECT * FROM users WHERE email = %s", (email.strip().lower(),))
        return self._normalize_user(row) if row else None

    def get_phase6_account_consent(self, user_id: str) -> dict[str, Any] | None:
        user = self.get_phase4_user(user_id)
        return dict(user["account_consent"]) if user else None

    def update_phase6_account_consent(
        self,
        *,
        user_id: str,
        actor_user_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        user = self.get_phase4_user(user_id)
        if not user or user.get("status") != "active":
            return None
        allowed = {
            "trace_storage_enabled",
            "feedback_use_allowed",
            "training_candidate_allowed",
            "public_anonymized_examples_allowed",
            "product_updates_allowed",
            "retention_preference",
        }
        updates = {key: value for key, value in payload.items() if key in allowed}
        if not updates:
            return dict(user["account_consent"])
        assignments: list[str] = []
        values: list[Any] = []
        changes: dict[str, dict[str, Any]] = {}
        current = dict(user["account_consent"])
        for key, value in updates.items():
            next_value = bool(value) if (key.endswith("_allowed") or key == "trace_storage_enabled") else value
            if current.get(key) == next_value:
                continue
            assignments.append(f"{key} = %s")
            values.append(next_value)
            changes[key] = {"from": current.get(key), "to": next_value}
        if "training_candidate_allowed" in changes:
            assignments.append("training_consent_default = %s")
            values.append("yes" if bool(updates["training_candidate_allowed"]) else "no")
        if not assignments:
            return dict(user["account_consent"])
        assignments.extend(["consent_updated_at = now()", "updated_at = now()"])
        values.append(user_id)
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute(
                    f"UPDATE users SET {', '.join(assignments)} WHERE id = %s",
                    tuple(values),
                )
                self._insert_audit_event(
                    cursor,
                    event_type="account.consent_updated",
                    actor_user_id=actor_user_id,
                    organization_id=None,
                    workspace_id=None,
                    target_type="user",
                    target_id=user_id,
                    payload={"changes": changes, "reauthenticated": True},
                )
        updated = self.get_phase4_user(user_id)
        return dict(updated["account_consent"]) if updated else None

    def create_phase6_password_signup(
        self,
        *,
        email: str,
        display_name: str | None,
        password_hash: str,
        token_hash: str,
        expires_at: str,
    ) -> dict[str, Any]:
        normalized_email = email.strip().lower()
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute("SELECT * FROM users WHERE email = %s", (normalized_email,))
                row = self._row_dict(cursor.fetchone())
                if row:
                    user = self._normalize_user(row)
                    created = False
                    if user["status"] == "pending_verification":
                        cursor.execute(
                            """
                            UPDATE users
                            SET display_name = %s, updated_at = now()
                            WHERE id = %s
                            RETURNING *
                            """,
                            (display_name or user["display_name"], user["id"]),
                        )
                        user = self._normalize_user(self._row_dict(cursor.fetchone()) or row)
                        cursor.execute(
                            """
                            INSERT INTO password_credentials(user_id, email, password_hash)
                            VALUES (%s, %s, %s)
                            ON CONFLICT(user_id) DO UPDATE SET
                              password_hash = EXCLUDED.password_hash,
                              updated_at = now()
                            """,
                            (user["id"], normalized_email, password_hash),
                        )
                        self._create_phase6_auth_token_row(
                            cursor,
                            user_id=user["id"],
                            email=normalized_email,
                            purpose="email_verification",
                            token_hash=token_hash,
                            expires_at=expires_at,
                        )
                        token_created = True
                    else:
                        token_created = False
                else:
                    cursor.execute(
                        """
                        INSERT INTO users(email, display_name, auth_provider, auth_provider_subject, status)
                        VALUES (%s, %s, 'password', %s, 'pending_verification')
                        RETURNING *
                        """,
                        (normalized_email, display_name or normalized_email.split("@")[0], f"password:{normalized_email}"),
                    )
                    user = self._normalize_user(self._row_dict(cursor.fetchone()) or {})
                    cursor.execute(
                        """
                        INSERT INTO password_credentials(user_id, email, password_hash)
                        VALUES (%s, %s, %s)
                        """,
                        (user["id"], normalized_email, password_hash),
                    )
                    self._create_phase6_auth_token_row(
                        cursor,
                        user_id=user["id"],
                        email=normalized_email,
                        purpose="email_verification",
                        token_hash=token_hash,
                        expires_at=expires_at,
                    )
                    created = True
                    token_created = True
        return {"user": user, "created": created, "verification_token_created": token_created}

    def get_phase6_password_credential(self, email: str) -> dict[str, Any] | None:
        row = self._execute_fetchone(
            """
            SELECT c.*, u.status, u.display_name
            FROM password_credentials c
            JOIN users u ON u.id = c.user_id
            WHERE c.email = %s
            """,
            (email.strip().lower(),),
        )
        if not row:
            return None
        out = dict(row)
        out["user_id"] = str(out["user_id"])
        return out

    def verify_phase6_email_token(self, *, token_hash: str) -> dict[str, Any] | None:
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                token = self._consume_phase6_auth_token_row(cursor, purpose="email_verification", token_hash=token_hash)
                if not token:
                    return None
                cursor.execute(
                    """
                    UPDATE password_credentials
                    SET email_verified_at = now(), updated_at = now()
                    WHERE user_id = %s
                    """,
                    (token["user_id"],),
                )
                cursor.execute(
                    "UPDATE users SET status = 'active', updated_at = now() WHERE id = %s RETURNING *",
                    (token["user_id"],),
                )
                row = self._row_dict(cursor.fetchone())
        return self._normalize_user(row) if row else None

    def create_phase6_password_reset_token(self, *, email: str, token_hash: str, expires_at: str) -> bool:
        credential = self.get_phase6_password_credential(email)
        if not credential or credential.get("status") != "active" or not credential.get("email_verified_at"):
            return False
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                self._create_phase6_auth_token_row(
                    cursor,
                    user_id=credential["user_id"],
                    email=credential["email"],
                    purpose="password_reset",
                    token_hash=token_hash,
                    expires_at=expires_at,
                )
        return True

    def reset_phase6_password(self, *, token_hash: str, password_hash: str) -> dict[str, Any] | None:
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                token = self._consume_phase6_auth_token_row(cursor, purpose="password_reset", token_hash=token_hash)
                if not token:
                    return None
                cursor.execute(
                    """
                    UPDATE password_credentials
                    SET password_hash = %s, updated_at = now()
                    WHERE user_id = %s
                    """,
                    (password_hash, token["user_id"]),
                )
                cursor.execute("UPDATE users SET updated_at = now() WHERE id = %s RETURNING *", (token["user_id"],))
                row = self._row_dict(cursor.fetchone())
        return self._normalize_user(row) if row else None

    def _create_phase6_auth_token_row(
        self,
        cursor: Any,
        *,
        user_id: str,
        email: str,
        purpose: str,
        token_hash: str,
        expires_at: str,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO auth_tokens(user_id, email, purpose, token_hash, expires_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_id, email, purpose, token_hash, expires_at),
        )

    def _consume_phase6_auth_token_row(self, cursor: Any, *, purpose: str, token_hash: str) -> dict[str, Any] | None:
        cursor.execute(
            """
            UPDATE auth_tokens
            SET consumed_at = now()
            WHERE id = (
              SELECT id
              FROM auth_tokens
              WHERE purpose = %s AND token_hash = %s AND consumed_at IS NULL AND expires_at > now()
              ORDER BY created_at DESC
              LIMIT 1
            )
            RETURNING *
            """,
            (purpose, token_hash),
        )
        row = self._row_dict(cursor.fetchone())
        if row:
            row["user_id"] = str(row["user_id"])
        return row

    def upsert_phase6_auth_session(
        self,
        *,
        session_id: str,
        user_id: str,
        auth_subject: str,
        email: str,
        display_name: str,
        issued_at: str,
        expires_at: str,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        user_agent_hash = hashlib.sha256(user_agent.encode("utf-8")).hexdigest() if user_agent else None
        row = self._execute_fetchone(
            """
            INSERT INTO auth_sessions(
              id, user_id, auth_subject, email, display_name, issued_at,
              expires_at, last_seen_at, user_agent_hash
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, now(), %s)
            ON CONFLICT (id) DO UPDATE SET last_seen_at = EXCLUDED.last_seen_at
            RETURNING *
            """,
            (session_id, user_id, auth_subject, email, display_name, issued_at, expires_at, user_agent_hash),
        )
        return self._normalize_auth_session(row or {})

    def get_phase6_auth_session(self, session_id: str) -> dict[str, Any] | None:
        row = self._execute_fetchone("SELECT * FROM auth_sessions WHERE id = %s", (session_id,))
        return self._normalize_auth_session(row) if row else None

    def touch_phase6_auth_session(self, session_id: str) -> None:
        self._execute_fetchone("UPDATE auth_sessions SET last_seen_at = now() WHERE id = %s RETURNING id", (session_id,))

    def list_phase6_auth_sessions(self, user_id: str) -> list[dict[str, Any]]:
        rows = self._execute_fetchall(
            """
            SELECT *
            FROM auth_sessions
            WHERE user_id = %s
            ORDER BY last_seen_at DESC, issued_at DESC
            """,
            (user_id,),
        )
        return [self._normalize_auth_session(row) for row in rows]

    def revoke_phase6_auth_sessions(self, *, user_id: str, revoked_by_user_id: str) -> dict[str, Any]:
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute(
                    """
                    UPDATE auth_sessions
                    SET revoked_at = now()
                    WHERE user_id = %s AND revoked_at IS NULL
                    RETURNING *
                    """,
                    (user_id,),
                )
                sessions = [self._normalize_auth_session(self._row_dict(row) or {}) for row in cursor.fetchall()]
                revoked_at = sessions[0]["revoked_at"] if sessions else None
                for session in sessions:
                    self._insert_audit_event(
                        cursor,
                        event_type="auth.sessions_revoked",
                        actor_user_id=revoked_by_user_id,
                        organization_id=None,
                        target_type="auth_session",
                        target_id=session["id"],
                        payload={"user_id": user_id, "revoked_all": True},
                    )
        return {"revoked_at": revoked_at, "revoked_count": len(sessions), "sessions": sessions}

    def revoke_phase6_auth_session(self, *, session_id: str, revoked_by_user_id: str) -> dict[str, Any]:
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute(
                    """
                    UPDATE auth_sessions
                    SET revoked_at = now()
                    WHERE id = %s AND revoked_at IS NULL
                    RETURNING *
                    """,
                    (session_id,),
                )
                row = self._row_dict(cursor.fetchone())
                if not row:
                    return {"revoked_at": None, "revoked_count": 0, "session": None}
                session = self._normalize_auth_session(row)
                self._insert_audit_event(
                    cursor,
                    event_type="auth.session_revoked",
                    actor_user_id=revoked_by_user_id,
                    organization_id=None,
                    target_type="auth_session",
                    target_id=session["id"],
                    payload={"user_id": session["user_id"], "revoked_all": False},
                )
        return {"revoked_at": session["revoked_at"], "revoked_count": 1, "session": session}

    def _normalize_auth_session(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(raw["id"]),
            "user_id": str(raw["user_id"]),
            "auth_subject": raw["auth_subject"],
            "email": raw["email"],
            "display_name": raw["display_name"],
            "issued_at": raw["issued_at"],
            "expires_at": raw["expires_at"],
            "last_seen_at": raw["last_seen_at"],
            "revoked_at": raw.get("revoked_at"),
            "user_agent_hash": raw.get("user_agent_hash"),
        }

    def _normalize_organization(self, raw: dict[str, Any]) -> dict[str, Any]:
        out = {
            "id": str(raw["id"]),
            "name": raw["name"],
            "slug": raw["slug"],
            "plan": raw["plan"],
            "created_by_user_id": str(raw["created_by_user_id"]) if raw.get("created_by_user_id") is not None else None,
            "metadata": self._from_json(raw.get("metadata"), {}),
            "created_at": raw.get("created_at"),
            "updated_at": raw.get("updated_at"),
            "deleted_at": raw.get("deleted_at"),
        }
        if "role" in raw:
            out["role"] = self._role(raw["role"])
        if "membership_status" in raw:
            out["membership_status"] = raw["membership_status"]
        return out

    def create_phase4_organization(
        self,
        *,
        name: str,
        slug: str,
        plan: str,
        created_by_user_id: str,
    ) -> dict[str, Any]:
        organization_id = self._new_uuid()
        membership_id = self._new_uuid()
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute(
                    """
                    INSERT INTO organizations(id, name, slug, plan, created_by_user_id, metadata)
                    VALUES (%s, %s, %s, %s, %s, '{}'::jsonb)
                    RETURNING *
                    """,
                    (organization_id, name, slug, plan, created_by_user_id),
                )
                organization = self._row_dict(cursor.fetchone()) or {}
                cursor.execute(
                    """
                    INSERT INTO memberships(id, organization_id, user_id, role, status)
                    VALUES (%s, %s, %s, %s, 'active')
                    """,
                    (membership_id, organization_id, created_by_user_id, "owner"),
                )
                self._insert_audit_event(
                    cursor,
                    event_type="organization.created",
                    actor_user_id=created_by_user_id,
                    organization_id=organization_id,
                    target_type="organization",
                    target_id=organization_id,
                    payload={"name": name, "slug": slug},
                )
        normalized = self._normalize_organization(organization)
        normalized["role"] = "owner"
        normalized["membership_status"] = "active"
        return normalized

    def list_phase4_organizations_for_user(self, user_id: str) -> list[dict[str, Any]]:
        rows = self._execute_fetchall(
            """
            SELECT o.*, m.role, m.status AS membership_status
            FROM organizations o
            JOIN memberships m ON m.organization_id = o.id
            WHERE m.user_id = %s AND m.status = 'active' AND o.deleted_at IS NULL
            ORDER BY o.created_at ASC
            """,
            (user_id,),
        )
        return [self._normalize_organization(row) for row in rows]

    def get_phase4_organization(self, organization_id: str) -> dict[str, Any] | None:
        row = self._execute_fetchone("SELECT * FROM organizations WHERE id = %s AND deleted_at IS NULL", (organization_id,))
        return self._normalize_organization(row) if row else None

    def phase4_user_can_access_org(self, user_id: str, organization_id: str) -> bool:
        row = self._execute_fetchone(
            """
            SELECT 1 AS allowed
            FROM memberships
            WHERE user_id = %s AND organization_id = %s AND status = 'active'
            """,
            (user_id, organization_id),
        )
        return bool(row)

    def _normalize_membership(self, raw: dict[str, Any]) -> dict[str, Any]:
        out = {
            "id": str(raw["id"]),
            "organization_id": str(raw["organization_id"]),
            "user_id": str(raw["user_id"]),
            "role": self._role(raw["role"]),
            "status": raw["status"],
            "created_at": raw.get("created_at"),
        }
        if "email" in raw:
            out["email"] = raw["email"]
        if "display_name" in raw:
            out["display_name"] = raw["display_name"]
        return out

    def get_phase4_membership(self, *, user_id: str, organization_id: str) -> dict[str, Any] | None:
        row = self._execute_fetchone(
            """
            SELECT *
            FROM memberships
            WHERE user_id = %s AND organization_id = %s AND status = 'active'
            """,
            (user_id, organization_id),
        )
        return self._normalize_membership(row) if row else None

    def list_phase4_memberships(self, organization_id: str) -> list[dict[str, Any]]:
        rows = self._execute_fetchall(
            """
            SELECT m.*, u.email, u.display_name
            FROM memberships m
            JOIN users u ON u.id = m.user_id
            WHERE m.organization_id = %s AND m.status = 'active'
            ORDER BY m.created_at ASC
            """,
            (organization_id,),
        )
        return [self._normalize_membership(row) for row in rows]

    def upsert_phase4_membership(
        self,
        *,
        organization_id: str,
        user_id: str,
        role: str,
        actor_user_id: str,
    ) -> dict[str, Any]:
        membership_id = self._new_uuid()
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute(
                    """
                    INSERT INTO memberships(id, organization_id, user_id, role, status)
                    VALUES (%s, %s, %s, %s, 'active')
                    ON CONFLICT (organization_id, user_id) DO UPDATE SET
                      role = EXCLUDED.role,
                      status = 'active'
                    RETURNING *
                    """,
                    (membership_id, organization_id, user_id, role),
                )
                membership = self._row_dict(cursor.fetchone()) or {}
                self._insert_audit_event(
                    cursor,
                    event_type="membership.upserted",
                    actor_user_id=actor_user_id,
                    organization_id=organization_id,
                    target_type="membership",
                    target_id=str(membership.get("id") or membership_id),
                    payload={"user_id": user_id, "role": role},
                )
        return self._normalize_membership(membership)

    def _normalize_workspace(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(raw["id"]),
            "organization_id": str(raw["organization_id"]),
            "name": raw["name"],
            "created_by_user_id": str(raw["created_by_user_id"]) if raw.get("created_by_user_id") is not None else None,
            "settings": self._from_json(raw.get("settings"), {}),
            "created_at": raw.get("created_at"),
            "updated_at": raw.get("updated_at"),
            "deleted_at": raw.get("deleted_at"),
        }

    def create_phase4_workspace(
        self,
        *,
        organization_id: str,
        name: str,
        created_by_user_id: str,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        workspace_id = self._new_uuid()
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute(
                    """
                    INSERT INTO workspaces(id, organization_id, name, created_by_user_id, settings)
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    RETURNING *
                    """,
                    (workspace_id, organization_id, name, created_by_user_id, self._to_json(settings or {})),
                )
                workspace = self._row_dict(cursor.fetchone()) or {}
                self._insert_audit_event(
                    cursor,
                    event_type="workspace.created",
                    actor_user_id=created_by_user_id,
                    organization_id=organization_id,
                    workspace_id=workspace_id,
                    target_type="workspace",
                    target_id=workspace_id,
                    payload={"name": name},
                )
        return self._normalize_workspace(workspace)

    def list_phase4_workspaces_for_user(self, user_id: str, organization_id: str | None = None) -> list[dict[str, Any]]:
        params: tuple[Any, ...]
        org_filter = ""
        if organization_id:
            org_filter = "AND w.organization_id = %s"
            params = (user_id, organization_id)
        else:
            params = (user_id,)
        rows = self._execute_fetchall(
            f"""
            SELECT w.*
            FROM workspaces w
            JOIN memberships m ON m.organization_id = w.organization_id
            WHERE m.user_id = %s AND m.status = 'active' AND w.deleted_at IS NULL {org_filter}
            ORDER BY w.created_at ASC
            """,
            params,
        )
        return [self._normalize_workspace(row) for row in rows]

    def get_phase4_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        row = self._execute_fetchone("SELECT * FROM workspaces WHERE id = %s AND deleted_at IS NULL", (workspace_id,))
        return self._normalize_workspace(row) if row else None

    def delete_phase4_workspace(self, *, workspace_id: str, deleted_by_user_id: str) -> dict[str, Any] | None:
        workspace = self.get_phase4_workspace(workspace_id)
        if not workspace:
            return None
        usage = self.phase4_workspace_usage(workspace_id)
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute(
                    """
                    UPDATE workspaces
                    SET deleted_at = now(), updated_at = now()
                    WHERE id = %s AND deleted_at IS NULL
                    RETURNING *
                    """,
                    (workspace_id,),
                )
                deleted = self._row_dict(cursor.fetchone())
                cursor.execute("UPDATE field_contexts SET deleted_at = now(), updated_at = now() WHERE workspace_id = %s AND deleted_at IS NULL", (workspace_id,))
                cursor.execute(
                    """
                    UPDATE threads
                    SET deleted_at = now(), status = 'deleted', training_eligible = false, updated_at = now()
                    WHERE workspace_id = %s AND deleted_at IS NULL
                    """,
                    (workspace_id,),
                )
                cursor.execute("UPDATE attachments SET deleted_at = now(), parse_status = 'deleted' WHERE workspace_id = %s AND deleted_at IS NULL", (workspace_id,))
                cursor.execute("UPDATE data_sources SET deleted_at = now(), updated_at = now() WHERE workspace_id = %s AND deleted_at IS NULL", (workspace_id,))
                cursor.execute("UPDATE document_chunks SET deleted_at = now() WHERE workspace_id = %s AND deleted_at IS NULL", (workspace_id,))
                cursor.execute("UPDATE embeddings SET deleted_at = now() WHERE workspace_id = %s AND deleted_at IS NULL", (workspace_id,))
                self._insert_audit_event(
                    cursor,
                    event_type="workspace.deleted",
                    actor_user_id=deleted_by_user_id,
                    organization_id=workspace["organization_id"],
                    workspace_id=workspace_id,
                    target_type="workspace",
                    target_id=workspace_id,
                    payload={
                        "name": workspace["name"],
                        "soft_deleted": True,
                        "thread_count": usage["thread_count"],
                        "attachment_count": usage["attachment_count"],
                        "data_source_count": usage["data_source_count"],
                        "retention_policy": "soft_delete_then_purge_policy",
                    },
                )
        if not deleted:
            return None
        normalized = self._normalize_workspace(deleted)
        normalized["deletion_summary"] = {
            "soft_deleted": True,
            "thread_count": usage["thread_count"],
            "attachment_count": usage["attachment_count"],
            "data_source_count": usage["data_source_count"],
            "retention_policy": "soft_delete_then_purge_policy",
        }
        return normalized

    def phase4_user_can_access_workspace(self, user_id: str, workspace_id: str) -> bool:
        row = self._execute_fetchone(
            """
            SELECT 1 AS allowed
            FROM workspaces w
            JOIN memberships m ON m.organization_id = w.organization_id
            WHERE w.id = %s AND m.user_id = %s AND m.status = 'active' AND w.deleted_at IS NULL
            """,
            (workspace_id, user_id),
        )
        return bool(row)

    def delete_phase6_account(self, *, user_id: str, deleted_by_user_id: str) -> dict[str, Any] | None:
        user = self.get_phase4_user(user_id)
        if not user or user.get("status") != "active":
            return None
        organizations = self.list_phase4_organizations_for_user(user_id)
        workspaces = self.list_phase4_workspaces_for_user(user_id)
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute("UPDATE users SET status = 'deleted', updated_at = now() WHERE id = %s", (user_id,))
                cursor.execute("UPDATE memberships SET status = 'inactive' WHERE user_id = %s AND status = 'active'", (user_id,))
                for workspace in workspaces:
                    self._insert_audit_event(
                        cursor,
                        event_type="account.deleted",
                        actor_user_id=deleted_by_user_id,
                        organization_id=workspace["organization_id"],
                        workspace_id=workspace["id"],
                        target_type="user",
                        target_id=user_id,
                        payload={
                            "email_hash": hashlib.sha256(str(user["email"]).encode("utf-8")).hexdigest(),
                            "memberships_inactivated": True,
                            "export_acknowledgement_required": True,
                        },
                    )
        deleted = self.get_phase4_user(user_id) or dict(user)
        return {
            "schema_version": "phase6.account_delete.v1",
            "deleted_at": deleted.get("updated_at"),
            "user": deleted,
            "organization_count": len(organizations),
            "workspace_count": len(workspaces),
            "memberships_inactivated": True,
            "reauth_method": "current_identity_email_confirmation",
            "export_acknowledged": True,
        }

    def phase4_workspace_usage(self, workspace_id: str) -> dict[str, int]:
        row = self._execute_fetchone(
            """
            SELECT
              (SELECT COUNT(*) FROM threads WHERE workspace_id = %s AND deleted_at IS NULL) AS thread_count,
              (SELECT COUNT(*) FROM messages WHERE workspace_id = %s) AS message_count,
              (SELECT COUNT(*) FROM attachments WHERE workspace_id = %s AND deleted_at IS NULL) AS attachment_count,
              (SELECT COALESCE(SUM(size_bytes), 0) FROM attachments WHERE workspace_id = %s AND deleted_at IS NULL) AS attachment_bytes,
              (SELECT COUNT(*) FROM data_sources WHERE workspace_id = %s AND deleted_at IS NULL) AS data_source_count,
              (SELECT COUNT(*) FROM eval_runs WHERE workspace_id = %s AND deleted_at IS NULL) AS eval_run_count,
              (SELECT COUNT(*) FROM exports WHERE workspace_id = %s) AS export_count
            """,
            (workspace_id, workspace_id, workspace_id, workspace_id, workspace_id, workspace_id, workspace_id),
        ) or {}
        return {
            "thread_count": int(row.get("thread_count") or 0),
            "message_count": int(row.get("message_count") or 0),
            "attachment_count": int(row.get("attachment_count") or 0),
            "attachment_bytes": int(row.get("attachment_bytes") or 0),
            "data_source_count": int(row.get("data_source_count") or 0),
            "eval_run_count": int(row.get("eval_run_count") or 0),
            "export_count": int(row.get("export_count") or 0),
        }

    def _normalize_field_context(self, raw: dict[str, Any]) -> dict[str, Any]:
        normalized = {
            "id": str(raw["id"]),
            "organization_id": str(raw["organization_id"]),
            "workspace_id": str(raw["workspace_id"]),
            "created_by_user_id": str(raw["created_by_user_id"]) if raw.get("created_by_user_id") is not None else None,
            "display_name": raw["display_name"],
            "region_text": raw["region_text"],
            "country": raw.get("country"),
            "province_state": raw.get("province_state"),
            "county_rm": raw.get("county_rm"),
            "generalized_geohash": raw.get("generalized_geohash"),
            "crop_current": raw.get("crop_current"),
            "crop_year": raw.get("crop_year"),
            "soil_series_or_texture": raw.get("soil_series_or_texture"),
            "drainage_class": raw.get("drainage_class"),
            "irrigation_status": raw.get("irrigation_status"),
            "soil_test_summary": raw.get("soil_test_summary"),
            "crop_rotation_notes": raw.get("crop_rotation_notes"),
            "management_notes": raw.get("management_notes"),
            "known_constraints": self._from_array(raw.get("known_constraints")),
            "sensitivity": raw.get("sensitivity", "medium"),
            "metadata": self._from_json(raw.get("metadata"), {}),
            "created_at": raw.get("created_at"),
            "updated_at": raw.get("updated_at"),
            "deleted_at": raw.get("deleted_at"),
        }
        normalized["quality_meter"] = evaluate_field_context_quality(normalized)
        return normalized

    def create_phase4_field_context(self, *, workspace: dict[str, Any], created_by_user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        field_context_id = self._new_uuid()
        row = self._execute_fetchone(
            """
            INSERT INTO field_contexts(
              id, organization_id, workspace_id, created_by_user_id, display_name, region_text,
              country, province_state, county_rm, crop_current, crop_year, soil_series_or_texture,
              drainage_class, irrigation_status, soil_test_summary, crop_rotation_notes, management_notes,
              known_constraints, sensitivity, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING *
            """,
            (
                field_context_id,
                workspace["organization_id"],
                workspace["id"],
                created_by_user_id,
                payload["display_name"],
                payload["region_text"],
                payload.get("country"),
                payload.get("province_state"),
                payload.get("county_rm"),
                payload.get("crop_current"),
                payload.get("crop_year"),
                payload.get("soil_series_or_texture"),
                payload.get("drainage_class"),
                payload.get("irrigation_status"),
                payload.get("soil_test_summary"),
                payload.get("crop_rotation_notes"),
                payload.get("management_notes"),
                payload.get("known_constraints", []),
                payload.get("sensitivity", "medium"),
                self._to_json(payload.get("metadata", {})),
            ),
        )
        return self._normalize_field_context(row or {})

    def list_phase4_field_contexts(self, workspace_id: str) -> list[dict[str, Any]]:
        rows = self._execute_fetchall(
            """
            SELECT *
            FROM field_contexts
            WHERE workspace_id = %s AND deleted_at IS NULL
            ORDER BY created_at DESC
            """,
            (workspace_id,),
        )
        return [self._normalize_field_context(row) for row in rows]

    def get_phase4_field_context(self, field_context_id: str) -> dict[str, Any] | None:
        row = self._execute_fetchone(
            "SELECT * FROM field_contexts WHERE id = %s AND deleted_at IS NULL",
            (field_context_id,),
        )
        return self._normalize_field_context(row) if row else None

    def update_phase4_field_context(
        self,
        *,
        field_context_id: str,
        actor_user_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        current = self.get_phase4_field_context(field_context_id)
        if not current:
            return None
        allowed_fields = {
            "display_name",
            "region_text",
            "country",
            "province_state",
            "county_rm",
            "crop_current",
            "crop_year",
            "soil_series_or_texture",
            "drainage_class",
            "irrigation_status",
            "soil_test_summary",
            "crop_rotation_notes",
            "management_notes",
            "known_constraints",
            "sensitivity",
            "metadata",
        }
        updates = {key: value for key, value in payload.items() if key in allowed_fields}
        if not updates:
            return current
        assignments = [f"{key} = %s::jsonb" if key == "metadata" else f"{key} = %s" for key in updates]
        params = [self._to_json(value) if key == "metadata" else value for key, value in updates.items()]
        params.append(field_context_id)
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute(
                    f"""
                    UPDATE field_contexts
                    SET {", ".join(assignments)}, updated_at = now()
                    WHERE id = %s AND deleted_at IS NULL
                    RETURNING *
                    """,
                    tuple(params),
                )
                updated = self._row_dict(cursor.fetchone())
                self._insert_audit_event(
                    cursor,
                    event_type="field_context.updated",
                    actor_user_id=actor_user_id,
                    organization_id=current["organization_id"],
                    workspace_id=current["workspace_id"],
                    target_type="field_context",
                    target_id=field_context_id,
                    payload={"updated_fields": sorted(updates)},
                )
        return self._normalize_field_context(updated) if updated else None

    def delete_phase4_field_context(self, *, field_context_id: str, deleted_by_user_id: str) -> dict[str, Any] | None:
        current = self.get_phase4_field_context(field_context_id)
        if not current:
            return None
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute(
                    """
                    UPDATE field_contexts
                    SET deleted_at = now(), updated_at = now()
                    WHERE id = %s AND deleted_at IS NULL
                    RETURNING *
                    """,
                    (field_context_id,),
                )
                deleted = self._row_dict(cursor.fetchone())
                self._insert_audit_event(
                    cursor,
                    event_type="field_context.deleted",
                    actor_user_id=deleted_by_user_id,
                    organization_id=current["organization_id"],
                    workspace_id=current["workspace_id"],
                    target_type="field_context",
                    target_id=field_context_id,
                    payload={"display_name": current["display_name"], "region_text": current["region_text"]},
                )
        return self._normalize_field_context(deleted) if deleted else None

    def _normalize_field_event(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "open_agronomy_agent.field_event.v1",
            "id": str(raw["id"]),
            "organization_id": str(raw["organization_id"]),
            "workspace_id": str(raw["workspace_id"]),
            "field_context_id": str(raw["field_context_id"]),
            "recorded_by_user_id": (
                str(raw["recorded_by_user_id"]) if raw.get("recorded_by_user_id") is not None else None
            ),
            "event_type": raw["event_type"],
            "occurred_at": raw.get("occurred_at").isoformat()
            if isinstance(raw.get("occurred_at"), datetime)
            else str(raw.get("occurred_at")),
            "payload": self._from_json(raw.get("payload"), {}),
            "provenance": self._from_json(raw.get("provenance"), {}),
            "corrects_event_id": str(raw["corrects_event_id"]) if raw.get("corrects_event_id") else None,
            "previous_event_sha256": raw.get("previous_event_sha256"),
            "integrity_sha256": raw["integrity_sha256"],
            "recorded_at": raw.get("recorded_at").isoformat()
            if isinstance(raw.get("recorded_at"), datetime)
            else str(raw.get("recorded_at")),
        }

    def append_phase4_field_event(
        self,
        *,
        field_context: dict[str, Any],
        recorded_by_user_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        event_type = str(payload.get("event_type") or "")
        corrects_event_id = str(payload["corrects_event_id"]) if payload.get("corrects_event_id") else None
        if event_type not in FIELD_EVENT_TYPES:
            raise ValueError(f"unsupported field event type: {event_type}")
        if (event_type == "correction") != bool(corrects_event_id):
            raise ValueError("correction events must identify exactly one corrected field event")
        validate_field_event_payload(payload.get("payload"))

        event_id = self._new_uuid()
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute(
                    "SELECT id FROM field_contexts WHERE id = %s AND deleted_at IS NULL FOR UPDATE",
                    (field_context["id"],),
                )
                if cursor.fetchone() is None:
                    raise ValueError("field context does not exist")
                recorded_at = datetime.now(timezone.utc).isoformat()
                occurred_at = str(payload.get("occurred_at") or recorded_at)
                cursor.execute(
                    """
                    SELECT integrity_sha256
                    FROM field_events
                    WHERE field_context_id = %s
                    ORDER BY recorded_at DESC, id DESC
                    LIMIT 1
                    """,
                    (field_context["id"],),
                )
                previous = self._row_dict(cursor.fetchone())
                if corrects_event_id:
                    cursor.execute(
                        """
                        SELECT id
                        FROM field_events
                        WHERE id = %s AND field_context_id = %s
                        """,
                        (corrects_event_id, field_context["id"]),
                    )
                    if cursor.fetchone() is None:
                        raise ValueError("corrected field event does not exist in this field")
                event = {
                    "id": event_id,
                    "organization_id": field_context["organization_id"],
                    "workspace_id": field_context["workspace_id"],
                    "field_context_id": field_context["id"],
                    "recorded_by_user_id": recorded_by_user_id,
                    "event_type": event_type,
                    "occurred_at": occurred_at,
                    "payload": dict(payload.get("payload") or {}),
                    "provenance": dict(payload.get("provenance") or {}),
                    "corrects_event_id": corrects_event_id,
                    "previous_event_sha256": previous.get("integrity_sha256") if previous else None,
                    "recorded_at": recorded_at,
                }
                event["integrity_sha256"] = field_event_integrity_sha256(event)
                cursor.execute(
                    """
                    INSERT INTO field_events(
                      id, organization_id, workspace_id, field_context_id, recorded_by_user_id,
                      event_type, occurred_at, payload, provenance, corrects_event_id,
                      previous_event_sha256, integrity_sha256, recorded_at
                    )
                    VALUES (
                      %s, %s, %s, %s, %s, %s, %s::timestamptz, %s::jsonb, %s::jsonb, %s,
                      %s, %s, %s::timestamptz
                    )
                    RETURNING *
                    """,
                    (
                        event["id"],
                        event["organization_id"],
                        event["workspace_id"],
                        event["field_context_id"],
                        event["recorded_by_user_id"],
                        event["event_type"],
                        event["occurred_at"],
                        self._to_json(event["payload"]),
                        self._to_json(event["provenance"]),
                        event["corrects_event_id"],
                        event["previous_event_sha256"],
                        event["integrity_sha256"],
                        event["recorded_at"],
                    ),
                )
                inserted = self._row_dict(cursor.fetchone())
                self._insert_audit_event(
                    cursor,
                    event_type="field_event.appended",
                    actor_user_id=recorded_by_user_id,
                    organization_id=field_context["organization_id"],
                    workspace_id=field_context["workspace_id"],
                    target_type="field_event",
                    target_id=event_id,
                    payload={
                        "field_context_id": field_context["id"],
                        "field_event_type": event_type,
                        "integrity_sha256": event["integrity_sha256"],
                        "corrects_event_id": corrects_event_id,
                    },
                )
        return self._normalize_field_event(inserted or event)

    def get_phase4_field_event(self, event_id: str) -> dict[str, Any] | None:
        row = self._execute_fetchone("SELECT * FROM field_events WHERE id = %s", (event_id,))
        return self._normalize_field_event(row) if row else None

    def list_phase4_field_events(self, field_context_id: str) -> list[dict[str, Any]]:
        rows = self._execute_fetchall(
            """
            SELECT *
            FROM field_events
            WHERE field_context_id = %s
            ORDER BY recorded_at, id
            """,
            (field_context_id,),
        )
        return [self._normalize_field_event(row) for row in rows]

    def verify_phase4_field_event_chain(self, field_context_id: str) -> dict[str, Any]:
        return verify_field_event_chain(self.list_phase4_field_events(field_context_id))

    def export_phase4_field_event_sync(
        self,
        field_context_id: str,
        *,
        after_sha256: str | None = None,
    ) -> dict[str, Any]:
        return field_event_sync_export(
            self.list_phase4_field_events(field_context_id),
            field_context_id=field_context_id,
            after_sha256=after_sha256,
        )

    def import_phase4_field_event_sync(
        self,
        *,
        field_context: dict[str, Any],
        syncing_user_id: str,
        source_device_id: str,
        base_head_sha256: str | None,
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        for event in events:
            validate_field_event_payload(event.get("payload"))
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute(
                    "SELECT id FROM field_contexts WHERE id = %s AND deleted_at IS NULL FOR UPDATE",
                    (field_context["id"],),
                )
                if cursor.fetchone() is None:
                    raise ValueError("field context does not exist")
                cursor.execute(
                    """
                    SELECT *
                    FROM field_events
                    WHERE field_context_id = %s
                    ORDER BY recorded_at, id
                    """,
                    (field_context["id"],),
                )
                local = [
                    self._normalize_field_event(self._row_dict(row) or {})
                    for row in cursor.fetchall()
                ]
                validation = validate_field_event_fast_forward(
                    local_events=local,
                    incoming_events=events,
                    field_context=field_context,
                    syncing_user_id=syncing_user_id,
                    base_head_sha256=base_head_sha256,
                )
                if validation["status"] == "already_applied":
                    return {
                        "schema_version": "open_agronomy_agent.field_event_sync_result.v1",
                        "status": "already_applied",
                        "field_context_id": field_context["id"],
                        "source_device_id": source_device_id,
                        "imported_event_count": 0,
                        "chain": verify_field_event_chain(local),
                        "boundary": (
                            "Idempotent fast-forward retry; no event was duplicated. source_device_id is "
                            "an operator-supplied label, not device attestation."
                        ),
                    }
                for event in validation["events"]:
                    cursor.execute(
                        """
                        INSERT INTO field_events(
                          id, organization_id, workspace_id, field_context_id, recorded_by_user_id,
                          event_type, occurred_at, payload, provenance, corrects_event_id,
                          previous_event_sha256, integrity_sha256, recorded_at
                        )
                        VALUES (
                          %s, %s, %s, %s, %s, %s, %s::timestamptz, %s::jsonb, %s::jsonb, %s,
                          %s, %s, %s::timestamptz
                        )
                        """,
                        (
                            event["id"],
                            event["organization_id"],
                            event["workspace_id"],
                            event["field_context_id"],
                            event["recorded_by_user_id"],
                            event["event_type"],
                            event["occurred_at"],
                            self._to_json(event["payload"]),
                            self._to_json(event["provenance"]),
                            event.get("corrects_event_id"),
                            event.get("previous_event_sha256"),
                            event["integrity_sha256"],
                            event["recorded_at"],
                        ),
                    )
                self._insert_audit_event(
                    cursor,
                    event_type="field_event.sync_imported",
                    actor_user_id=syncing_user_id,
                    organization_id=field_context["organization_id"],
                    workspace_id=field_context["workspace_id"],
                    target_type="field_context",
                    target_id=field_context["id"],
                    payload={
                        "source_device_id": source_device_id,
                        "base_head_sha256": base_head_sha256,
                        "result_head_sha256": validation["result_head_sha256"],
                        "imported_event_count": validation["event_count"],
                        "accepted_full_prefix": validation["accepted_full_prefix"],
                    },
                )
                combined = [*local, *validation["events"]]
        return {
            "schema_version": "open_agronomy_agent.field_event_sync_result.v1",
            "status": "imported",
            "field_context_id": field_context["id"],
            "source_device_id": source_device_id,
            "imported_event_count": validation["event_count"],
            "accepted_full_prefix": validation["accepted_full_prefix"],
            "chain": verify_field_event_chain(combined),
            "boundary": (
                "Imported as one atomic fast-forward batch. source_device_id is an operator-supplied label, "
                "not device attestation; divergent branches require human reconciliation."
            ),
        }

    def _normalize_thread(self, raw: dict[str, Any], *, include_messages: bool) -> dict[str, Any]:
        out = {
            "id": str(raw["id"]),
            "organization_id": str(raw["organization_id"]),
            "workspace_id": str(raw["workspace_id"]),
            "created_by_user_id": str(raw["created_by_user_id"]) if raw.get("created_by_user_id") is not None else None,
            "field_context_id": str(raw["field_context_id"]) if raw.get("field_context_id") is not None else None,
            "title": raw["title"],
            "mode": self._role(raw["mode"]),
            "task_family": raw.get("task_family"),
            "risk_level": raw.get("risk_level"),
            "model_profile_id": raw.get("model_profile_id"),
            "rag_config_id": raw.get("rag_config_id"),
            "trace_capture_level": self._role(raw.get("trace_capture_level", raw.get("trace_capture"))),
            "training_eligible": bool(raw.get("training_eligible")),
            "redaction_status": self._role(raw.get("redaction_status", "not_required")),
            "visibility": self._role(raw.get("visibility", "workspace")),
            "status": raw.get("status", "active"),
            "metadata": self._from_json(raw.get("metadata"), {}),
            "created_at": raw.get("created_at"),
            "updated_at": raw.get("updated_at"),
            "deleted_at": raw.get("deleted_at"),
        }
        if include_messages:
            out["messages"] = []
        return out

    def create_phase4_thread(
        self,
        *,
        workspace: dict[str, Any],
        created_by_user_id: str,
        title: str,
        mode: str,
        trace_capture_level: str,
        field_context_id: str | None = None,
        model_profile_id: str | None = None,
        rag_config_id: str | None = None,
        training_eligible: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        thread_id = self._new_uuid()
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute(
                    """
                    INSERT INTO threads(
                      id, organization_id, workspace_id, created_by_user_id, field_context_id,
                      title, mode, model_profile_id, rag_config_id, trace_capture,
                      training_eligible, metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    RETURNING *, trace_capture AS trace_capture_level
                    """,
                    (
                        thread_id,
                        workspace["organization_id"],
                        workspace["id"],
                        created_by_user_id,
                        field_context_id,
                        title,
                        mode,
                        model_profile_id,
                        rag_config_id,
                        trace_capture_level,
                        bool(training_eligible),
                        self._to_json(metadata or {}),
                    ),
                )
                thread = self._row_dict(cursor.fetchone()) or {}
                self._insert_audit_event(
                    cursor,
                    event_type="thread.created",
                    actor_user_id=created_by_user_id,
                    organization_id=workspace["organization_id"],
                    workspace_id=workspace["id"],
                    target_type="thread",
                    target_id=thread_id,
                    payload={"title": title, "mode": mode},
                )
        return self._normalize_thread(thread, include_messages=True)

    def list_phase4_threads(self, workspace_id: str) -> list[dict[str, Any]]:
        rows = self._execute_fetchall(
            """
            SELECT *, trace_capture AS trace_capture_level
            FROM threads
            WHERE workspace_id = %s AND deleted_at IS NULL
            ORDER BY updated_at DESC
            """,
            (workspace_id,),
        )
        return [self._normalize_thread(row, include_messages=False) for row in rows]

    def get_phase4_thread(self, thread_id: str) -> dict[str, Any] | None:
        row = self._execute_fetchone(
            """
            SELECT *, trace_capture AS trace_capture_level
            FROM threads
            WHERE id = %s AND deleted_at IS NULL
            """,
            (thread_id,),
        )
        if not row:
            return None
        thread = self._normalize_thread(row, include_messages=True)
        thread["messages"] = self.list_phase4_messages(thread_id)
        return thread

    def update_phase4_thread_metadata(
        self,
        thread_id: str,
        *,
        metadata: dict[str, Any] | None = None,
        task_family: str | None = None,
        risk_level: str | None = None,
    ) -> dict[str, Any] | None:
        updates: list[str] = ["updated_at = now()"]
        values: list[Any] = []
        if metadata is not None:
            updates.append("metadata = %s::jsonb")
            values.append(self._to_json(metadata))
        if task_family is not None:
            updates.append("task_family = %s")
            values.append(task_family)
        if risk_level is not None:
            updates.append("risk_level = %s")
            values.append(risk_level)
        if len(updates) == 1:
            return self.get_phase4_thread(thread_id)
        values.append(thread_id)
        row = self._execute_fetchone(
            f"""
            UPDATE threads
            SET {", ".join(updates)}
            WHERE id = %s AND deleted_at IS NULL
            RETURNING *, trace_capture AS trace_capture_level
            """,
            tuple(values),
        )
        if not row:
            return None
        thread = self._normalize_thread(row, include_messages=True)
        thread["messages"] = self.list_phase4_messages(thread_id)
        return thread

    def update_phase4_thread_consent(
        self,
        *,
        thread_id: str,
        actor_user_id: str,
        trace_capture_level: str | None = None,
        training_eligible: bool | None = None,
        redaction_status: str | None = None,
    ) -> dict[str, Any] | None:
        existing = self.get_phase4_thread(thread_id)
        if not existing:
            return None
        updates: list[str] = ["updated_at = now()"]
        values: list[Any] = []
        changes: dict[str, dict[str, Any]] = {}
        if trace_capture_level is not None and trace_capture_level != existing["trace_capture_level"]:
            updates.append("trace_capture = %s")
            values.append(trace_capture_level)
            changes["trace_capture_level"] = {"from": existing["trace_capture_level"], "to": trace_capture_level}
        if training_eligible is not None and bool(training_eligible) != bool(existing["training_eligible"]):
            updates.append("training_eligible = %s")
            values.append(bool(training_eligible))
            changes["training_eligible"] = {"from": bool(existing["training_eligible"]), "to": bool(training_eligible)}
        if redaction_status is not None and redaction_status != existing["redaction_status"]:
            updates.append("redaction_status = %s")
            values.append(redaction_status)
            changes["redaction_status"] = {"from": existing["redaction_status"], "to": redaction_status}
        if not changes:
            return existing
        values.append(thread_id)
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute(
                    f"""
                    UPDATE threads
                    SET {", ".join(updates)}
                    WHERE id = %s AND deleted_at IS NULL
                    RETURNING *, trace_capture AS trace_capture_level
                    """,
                    tuple(values),
                )
                row = self._row_dict(cursor.fetchone())
                self._insert_audit_event(
                    cursor,
                    event_type="training_consent.updated",
                    actor_user_id=actor_user_id,
                    organization_id=existing["organization_id"],
                    workspace_id=existing["workspace_id"],
                    target_type="thread",
                    target_id=thread_id,
                    payload={"changes": changes},
                )
        if not row:
            return None
        thread = self._normalize_thread(row, include_messages=True)
        thread["messages"] = self.list_phase4_messages(thread_id)
        return thread

    def delete_phase4_thread(self, *, thread_id: str, deleted_by_user_id: str) -> dict[str, Any] | None:
        existing = self.get_phase4_thread(thread_id)
        if not existing:
            return None
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute(
                    """
                    UPDATE threads
                    SET deleted_at = now(), status = 'deleted', training_eligible = false, updated_at = now()
                    WHERE id = %s AND deleted_at IS NULL
                    RETURNING *, trace_capture AS trace_capture_level
                    """,
                    (thread_id,),
                )
                row = self._row_dict(cursor.fetchone())
                if not row:
                    return None
                self._insert_audit_event(
                    cursor,
                    event_type="thread.deleted",
                    actor_user_id=deleted_by_user_id,
                    organization_id=existing["organization_id"],
                    workspace_id=existing["workspace_id"],
                    target_type="thread",
                    target_id=thread_id,
                    payload={"message_count": len(existing.get("messages", [])), "training_eligible": False},
                )
        deleted = self._normalize_thread(row, include_messages=True)
        deleted["messages"] = existing.get("messages", [])
        return deleted

    def phase4_user_can_access_thread(self, user_id: str, thread_id: str) -> bool:
        row = self._execute_fetchone(
            """
            SELECT 1 AS allowed
            FROM threads t
            JOIN memberships m ON m.organization_id = t.organization_id
            WHERE t.id = %s AND m.user_id = %s AND m.status = 'active' AND t.deleted_at IS NULL
            """,
            (thread_id, user_id),
        )
        return bool(row)

    def _normalize_message(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(raw["id"]),
            "organization_id": str(raw["organization_id"]),
            "workspace_id": str(raw["workspace_id"]),
            "thread_id": str(raw["thread_id"]),
            "actor": raw["actor"],
            "content": raw["content"],
            "content_hash": raw.get("content_hash"),
            "sequence_no": int(raw["sequence_no"]),
            "metadata": self._from_json(raw.get("metadata"), {}),
            "created_at": raw.get("created_at"),
        }

    def create_phase4_message(
        self,
        *,
        thread: dict[str, Any],
        actor: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        message_id = self._new_uuid()
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute("SELECT COALESCE(MAX(sequence_no), 0) AS max_sequence FROM messages WHERE thread_id = %s", (thread["id"],))
                row = self._row_dict(cursor.fetchone()) or {}
                sequence_no = int(row.get("max_sequence", 0)) + 1
                cursor.execute(
                    """
                    INSERT INTO messages(
                      id, organization_id, workspace_id, thread_id, actor, content,
                      content_hash, sequence_no, metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    RETURNING *
                    """,
                    (
                        message_id,
                        thread["organization_id"],
                        thread["workspace_id"],
                        thread["id"],
                        actor,
                        content,
                        str(uuid.uuid5(uuid.NAMESPACE_URL, content)),
                        sequence_no,
                        self._to_json(metadata or {}),
                    ),
                )
                message = self._row_dict(cursor.fetchone()) or {}
                cursor.execute("UPDATE threads SET updated_at = now() WHERE id = %s", (thread["id"],))
        return self._normalize_message(message)

    def get_phase4_message(self, message_id: str) -> dict[str, Any] | None:
        row = self._execute_fetchone("SELECT * FROM messages WHERE id = %s", (message_id,))
        return self._normalize_message(row) if row else None

    def list_phase4_messages(self, thread_id: str) -> list[dict[str, Any]]:
        rows = self._execute_fetchall(
            "SELECT * FROM messages WHERE thread_id = %s ORDER BY sequence_no ASC",
            (thread_id,),
        )
        return [self._normalize_message(row) for row in rows]

    def _normalize_trace_event(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "event_id": str(raw["id"]),
            "organization_id": str(raw["organization_id"]),
            "workspace_id": str(raw["workspace_id"]),
            "thread_id": str(raw["thread_id"]),
            "message_id": str(raw["message_id"]) if raw.get("message_id") is not None else None,
            "event_type": raw["event_type"],
            "actor": raw.get("actor"),
            "payload": self._from_json(raw.get("payload"), {}),
            "hashes": {
                "prompt_hash": raw.get("prompt_hash"),
                "output_hash": raw.get("output_hash"),
                "source_hash": raw.get("source_hash"),
            },
            "elapsed_ms": raw.get("elapsed_ms"),
            "created_at": raw.get("created_at"),
        }

    def append_phase4_trace_event(
        self,
        *,
        thread: dict[str, Any],
        event_type: str,
        payload: dict[str, Any],
        actor: str | None = "system",
        message_id: str | None = None,
        prompt_hash: str | None = None,
        output_hash: str | None = None,
        source_hash: str | None = None,
        elapsed_ms: int | None = None,
    ) -> dict[str, Any]:
        event_id = self._new_uuid()
        row = self._execute_fetchone(
            """
            INSERT INTO trace_events(
              id, organization_id, workspace_id, thread_id, message_id, event_type, actor,
              payload, prompt_hash, output_hash, source_hash, elapsed_ms
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                event_id,
                thread["organization_id"],
                thread["workspace_id"],
                thread["id"],
                message_id,
                event_type,
                actor,
                self._to_json(payload),
                prompt_hash,
                output_hash,
                source_hash,
                elapsed_ms,
            ),
        )
        return self._normalize_trace_event(row or {})

    def get_phase4_trace_event(self, event_id: str) -> dict[str, Any] | None:
        row = self._execute_fetchone("SELECT * FROM trace_events WHERE id = %s", (event_id,))
        return self._normalize_trace_event(row) if row else None

    def list_phase4_trace_events(self, thread_id: str) -> list[dict[str, Any]]:
        rows = self._execute_fetchall(
            "SELECT * FROM trace_events WHERE thread_id = %s ORDER BY created_at ASC",
            (thread_id,),
        )
        return [self._normalize_trace_event(row) for row in rows]

    def create_phase5_trace_spans(self, spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not spans:
            return []
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                for span in spans:
                    cursor.execute(
                        """
                        INSERT INTO agent_trace_spans(
                          trace_id, thread_id, turn_id, span_id, parent_span_id, stage,
                          start_ns, end_ns, duration_ms, status, error_type,
                          error_message_redacted, input_size, output_size,
                          token_estimate_in, token_estimate_out, cache_status,
                          component_version, metadata
                        )
                        VALUES (
                          %s::uuid, %s::uuid, %s::uuid, %s, %s, %s,
                          %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
                        )
                        """,
                        (
                            span["trace_id"],
                            span.get("thread_id"),
                            span.get("turn_id"),
                            span["span_id"],
                            span.get("parent_span_id"),
                            span["stage"],
                            int(span["start_ns"]),
                            int(span["end_ns"]),
                            float(span["duration_ms"]),
                            span["status"],
                            span.get("error_type"),
                            span.get("error_message_redacted"),
                            span.get("input_size"),
                            span.get("output_size"),
                            span.get("token_estimate_in"),
                            span.get("token_estimate_out"),
                            span.get("cache_status"),
                            span.get("component_version"),
                            self._to_json(span.get("metadata") or {}),
                        ),
                    )
        return self.list_phase5_trace_spans(str(spans[0]["trace_id"]))

    def create_phase5_turn_metrics(self, metrics: dict[str, Any]) -> dict[str, Any]:
        row = self._execute_fetchone(
            """
            INSERT INTO agent_turn_metrics(
              trace_id, thread_id, turn_id, user_id, workspace_id,
              route_question_type, risk_level, namespaces, required_tools,
              rag_config_version, corpus_bundle_version, prompt_template_version,
              context_packer_version, model_id, quantization, max_tokens,
              temperature, top_p, top_k, total_latency_ms,
              time_to_first_token_ms, decode_tokens_per_sec, prompt_tokens_est,
              completion_tokens_est, context_tokens_est, retrieval_doc_count,
              top_doc_score, source_diversity, required_support_rate,
              tool_notes_count, tool_precision_proxy, tool_recall_proxy,
              answer_word_count, leak_check_passed, risk_banner_present,
              missing_data_present, quality_flags, user_feedback_score,
              human_review_status, reflection_status
            )
            VALUES (
              %s::uuid, %s::uuid, %s::uuid, %s::uuid, %s::uuid,
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
              %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (trace_id) DO UPDATE SET
              max_tokens = EXCLUDED.max_tokens,
              temperature = EXCLUDED.temperature,
              top_p = EXCLUDED.top_p,
              top_k = EXCLUDED.top_k,
              total_latency_ms = EXCLUDED.total_latency_ms,
              time_to_first_token_ms = EXCLUDED.time_to_first_token_ms,
              decode_tokens_per_sec = EXCLUDED.decode_tokens_per_sec,
              prompt_tokens_est = EXCLUDED.prompt_tokens_est,
              completion_tokens_est = EXCLUDED.completion_tokens_est,
              context_tokens_est = EXCLUDED.context_tokens_est,
              retrieval_doc_count = EXCLUDED.retrieval_doc_count,
              top_doc_score = EXCLUDED.top_doc_score,
              source_diversity = EXCLUDED.source_diversity,
              required_support_rate = EXCLUDED.required_support_rate,
              tool_notes_count = EXCLUDED.tool_notes_count,
              tool_precision_proxy = EXCLUDED.tool_precision_proxy,
              tool_recall_proxy = EXCLUDED.tool_recall_proxy,
              answer_word_count = EXCLUDED.answer_word_count,
              leak_check_passed = EXCLUDED.leak_check_passed,
              risk_banner_present = EXCLUDED.risk_banner_present,
              missing_data_present = EXCLUDED.missing_data_present,
              quality_flags = EXCLUDED.quality_flags,
              user_feedback_score = EXCLUDED.user_feedback_score,
              human_review_status = EXCLUDED.human_review_status,
              reflection_status = EXCLUDED.reflection_status
            RETURNING *
            """,
            (
                metrics["trace_id"],
                metrics["thread_id"],
                metrics["turn_id"],
                metrics.get("user_id"),
                metrics.get("workspace_id"),
                metrics.get("route_question_type"),
                metrics.get("risk_level"),
                metrics.get("namespaces") or [],
                metrics.get("required_tools") or [],
                metrics.get("rag_config_version"),
                metrics.get("corpus_bundle_version"),
                metrics.get("prompt_template_version"),
                metrics.get("context_packer_version"),
                metrics["model_id"],
                metrics.get("quantization"),
                int(metrics.get("max_tokens") or 0),
                float(metrics.get("temperature") if metrics.get("temperature") is not None else 0.0),
                float(metrics.get("top_p") if metrics.get("top_p") is not None else 0.9),
                int(metrics.get("top_k") or 0),
                float(metrics["total_latency_ms"]),
                metrics.get("time_to_first_token_ms"),
                metrics.get("decode_tokens_per_sec"),
                metrics.get("prompt_tokens_est"),
                metrics.get("completion_tokens_est"),
                metrics.get("context_tokens_est"),
                int(metrics.get("retrieval_doc_count") or 0),
                metrics.get("top_doc_score"),
                int(metrics.get("source_diversity") or 0),
                metrics.get("required_support_rate"),
                int(metrics.get("tool_notes_count") or 0),
                metrics.get("tool_precision_proxy"),
                metrics.get("tool_recall_proxy"),
                int(metrics.get("answer_word_count") or 0),
                bool(metrics.get("leak_check_passed")),
                bool(metrics.get("risk_banner_present")),
                bool(metrics.get("missing_data_present")),
                metrics.get("quality_flags") or [],
                metrics.get("user_feedback_score"),
                metrics.get("human_review_status") or "unreviewed",
                metrics.get("reflection_status") or "not_created",
            ),
        )
        return self._normalize_phase5_turn_metrics(row or {})

    def create_phase5_prompt_leak_events(
        self,
        *,
        trace_id: str,
        thread_id: str | None,
        turn_id: str | None,
        findings: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not findings:
            return []
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                for finding in findings:
                    cursor.execute(
                        """
                        INSERT INTO prompt_leak_events(
                          trace_id, thread_id, turn_id, leak_class, matched_text_hash,
                          severity, reviewer_status
                        )
                        VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s)
                        """,
                        (
                            trace_id,
                            thread_id,
                            turn_id,
                            finding["leak_class"],
                            finding["matched_text_hash"],
                            finding["severity"],
                            finding.get("reviewer_status", "unreviewed"),
                        ),
                    )
        return self.list_phase5_prompt_leak_events(trace_id)

    def list_phase5_trace_spans(self, trace_id: str) -> list[dict[str, Any]]:
        rows = self._execute_fetchall(
            "SELECT * FROM agent_trace_spans WHERE trace_id = %s::uuid ORDER BY start_ns ASC, id ASC",
            (trace_id,),
        )
        return [self._normalize_phase5_trace_span(row) for row in rows]

    def get_phase5_turn_metrics(self, trace_id: str) -> dict[str, Any] | None:
        row = self._execute_fetchone("SELECT * FROM agent_turn_metrics WHERE trace_id = %s::uuid", (trace_id,))
        return self._normalize_phase5_turn_metrics(row) if row else None

    def list_phase5_turn_metrics(self, workspace_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
        rows = self._execute_fetchall(
            "SELECT * FROM agent_turn_metrics WHERE workspace_id = %s::uuid ORDER BY created_at DESC LIMIT %s",
            (workspace_id, max(1, min(int(limit), 5000))),
        )
        return [self._normalize_phase5_turn_metrics(row) for row in rows]

    def update_phase5_turn_feedback(
        self,
        *,
        turn_id: str,
        user_feedback_score: float | None,
        human_review_status: str = "feedback_received",
    ) -> dict[str, Any] | None:
        row = self._execute_fetchone(
            """
            UPDATE agent_turn_metrics
            SET user_feedback_score = %s, human_review_status = %s
            WHERE turn_id = %s::uuid
            RETURNING *
            """,
            (user_feedback_score, human_review_status, turn_id),
        )
        return self._normalize_phase5_turn_metrics(row) if row else None

    def list_phase5_prompt_leak_events(self, trace_id: str) -> list[dict[str, Any]]:
        rows = self._execute_fetchall(
            "SELECT * FROM prompt_leak_events WHERE trace_id = %s::uuid ORDER BY created_at ASC, id ASC",
            (trace_id,),
        )
        return [self._normalize_phase5_prompt_leak_event(row) for row in rows]

    def get_phase5_admin_trace(self, trace_id: str) -> dict[str, Any] | None:
        metrics = self.get_phase5_turn_metrics(trace_id)
        if not metrics:
            return None
        return {
            "trace_id": trace_id,
            "metrics": metrics,
            "spans": self.list_phase5_trace_spans(trace_id),
            "prompt_leak_events": self.list_phase5_prompt_leak_events(trace_id),
        }

    def _normalize_phase5_trace_span(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "trace_id": str(raw["trace_id"]),
            "thread_id": str(raw["thread_id"]) if raw.get("thread_id") is not None else None,
            "turn_id": str(raw["turn_id"]) if raw.get("turn_id") is not None else None,
            "span_id": raw["span_id"],
            "parent_span_id": raw.get("parent_span_id"),
            "stage": raw["stage"],
            "start_ns": int(raw["start_ns"]),
            "end_ns": int(raw["end_ns"]),
            "duration_ms": float(raw["duration_ms"]),
            "status": raw["status"],
            "error_type": raw.get("error_type"),
            "error_message_redacted": raw.get("error_message_redacted"),
            "input_size": raw.get("input_size"),
            "output_size": raw.get("output_size"),
            "token_estimate_in": raw.get("token_estimate_in"),
            "token_estimate_out": raw.get("token_estimate_out"),
            "cache_status": raw.get("cache_status"),
            "component_version": raw.get("component_version"),
            "metadata": self._from_json(raw.get("metadata"), {}),
            "created_at": raw.get("created_at"),
        }

    def _normalize_phase5_turn_metrics(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "trace_id": str(raw["trace_id"]),
            "thread_id": str(raw["thread_id"]),
            "turn_id": str(raw["turn_id"]),
            "user_id": str(raw["user_id"]) if raw.get("user_id") is not None else None,
            "workspace_id": str(raw["workspace_id"]) if raw.get("workspace_id") is not None else None,
            "route_question_type": raw.get("route_question_type"),
            "risk_level": raw.get("risk_level"),
            "namespaces": [str(item) for item in self._from_array(raw.get("namespaces"))],
            "required_tools": [str(item) for item in self._from_array(raw.get("required_tools"))],
            "rag_config_version": raw.get("rag_config_version"),
            "corpus_bundle_version": raw.get("corpus_bundle_version"),
            "prompt_template_version": raw.get("prompt_template_version"),
            "context_packer_version": raw.get("context_packer_version"),
            "model_id": raw["model_id"],
            "quantization": raw.get("quantization"),
            "max_tokens": int(raw.get("max_tokens") or 0),
            "temperature": float(raw.get("temperature") if raw.get("temperature") is not None else 0.0),
            "top_p": float(raw.get("top_p") if raw.get("top_p") is not None else 0.9),
            "top_k": int(raw.get("top_k") or 0),
            "total_latency_ms": float(raw["total_latency_ms"]),
            "time_to_first_token_ms": raw.get("time_to_first_token_ms"),
            "decode_tokens_per_sec": raw.get("decode_tokens_per_sec"),
            "prompt_tokens_est": raw.get("prompt_tokens_est"),
            "completion_tokens_est": raw.get("completion_tokens_est"),
            "context_tokens_est": raw.get("context_tokens_est"),
            "retrieval_doc_count": int(raw.get("retrieval_doc_count") or 0),
            "top_doc_score": raw.get("top_doc_score"),
            "source_diversity": int(raw.get("source_diversity") or 0),
            "required_support_rate": raw.get("required_support_rate"),
            "tool_notes_count": int(raw.get("tool_notes_count") or 0),
            "tool_precision_proxy": raw.get("tool_precision_proxy"),
            "tool_recall_proxy": raw.get("tool_recall_proxy"),
            "answer_word_count": int(raw.get("answer_word_count") or 0),
            "leak_check_passed": bool(raw.get("leak_check_passed")),
            "risk_banner_present": bool(raw.get("risk_banner_present")),
            "missing_data_present": bool(raw.get("missing_data_present")),
            "quality_flags": [str(item) for item in self._from_array(raw.get("quality_flags"))],
            "user_feedback_score": raw.get("user_feedback_score"),
            "human_review_status": raw.get("human_review_status") or "unreviewed",
            "reflection_status": raw.get("reflection_status") or "not_created",
            "created_at": raw.get("created_at"),
        }

    def _normalize_phase5_prompt_leak_event(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": raw["id"],
            "trace_id": str(raw["trace_id"]),
            "thread_id": str(raw["thread_id"]) if raw.get("thread_id") is not None else None,
            "turn_id": str(raw["turn_id"]) if raw.get("turn_id") is not None else None,
            "leak_class": raw["leak_class"],
            "matched_text_hash": raw["matched_text_hash"],
            "severity": raw["severity"],
            "reviewer_status": raw.get("reviewer_status", "unreviewed"),
            "created_at": raw.get("created_at"),
        }

    def create_phase5_optimization_candidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        candidate_id = str(payload.get("candidate_id") or self._new_uuid())
        row = self._execute_fetchone(
            """
            INSERT INTO optimization_candidates(
              candidate_id, workspace_id, created_by_user_id, candidate_type,
              parent_version, candidate_version, generated_from_trace_ids,
              reflection_summary, patch, eval_summary, rollback_plan, pareto_status,
              promoted_at
            )
            VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s::uuid[], %s, %s::jsonb, %s::jsonb, %s, %s, %s)
            RETURNING *
            """,
            (
                candidate_id,
                payload.get("workspace_id"),
                payload.get("created_by_user_id"),
                payload["candidate_type"],
                payload.get("parent_version"),
                payload["candidate_version"],
                payload.get("generated_from_trace_ids") or [],
                payload.get("reflection_summary"),
                self._to_json(payload.get("patch") or {}),
                self._to_json(payload.get("eval_summary") or {}),
                payload.get("rollback_plan"),
                payload.get("pareto_status", "pending"),
                payload.get("promoted_at"),
            ),
        )
        return self._normalize_phase5_optimization_candidate(row or {})

    def get_phase5_optimization_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        row = self._execute_fetchone("SELECT * FROM optimization_candidates WHERE candidate_id = %s::uuid", (candidate_id,))
        return self._normalize_phase5_optimization_candidate(row) if row else None

    def list_phase5_optimization_candidates(self, workspace_id: str, *, pareto_status: str | None = None) -> list[dict[str, Any]]:
        if pareto_status:
            rows = self._execute_fetchall(
                "SELECT * FROM optimization_candidates WHERE workspace_id = %s::uuid AND pareto_status = %s ORDER BY created_at DESC",
                (workspace_id, pareto_status),
            )
        else:
            rows = self._execute_fetchall(
                "SELECT * FROM optimization_candidates WHERE workspace_id = %s::uuid ORDER BY created_at DESC",
                (workspace_id,),
            )
        return [self._normalize_phase5_optimization_candidate(row) for row in rows]

    def update_phase5_optimization_candidate_status(
        self,
        candidate_id: str,
        *,
        pareto_status: str,
        promoted_at: str | None = None,
        eval_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        row = self._execute_fetchone(
            """
            UPDATE optimization_candidates
            SET pareto_status = %s,
                promoted_at = %s,
                eval_summary = COALESCE(%s::jsonb, eval_summary)
            WHERE candidate_id = %s::uuid
            RETURNING *
            """,
            (pareto_status, promoted_at, self._to_json(eval_summary) if eval_summary is not None else None, candidate_id),
        )
        return self._normalize_phase5_optimization_candidate(row) if row else None

    def create_phase5_training_candidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        candidate_id = str(payload.get("id") or self._new_uuid())
        row = self._execute_fetchone(
            """
            INSERT INTO phase5_training_candidates(
              id, workspace_id, thread_id, trace_id, reviewer_user_id, review_status,
              consent_scope, redaction_status, repair_layer, failure_class, messages,
              labels, dataset_card, reviewed_at, exported_at
            )
            VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s)
            ON CONFLICT (trace_id) DO UPDATE SET
              reviewer_user_id = EXCLUDED.reviewer_user_id,
              review_status = EXCLUDED.review_status,
              consent_scope = EXCLUDED.consent_scope,
              redaction_status = EXCLUDED.redaction_status,
              repair_layer = EXCLUDED.repair_layer,
              failure_class = EXCLUDED.failure_class,
              messages = EXCLUDED.messages,
              labels = EXCLUDED.labels,
              dataset_card = EXCLUDED.dataset_card,
              reviewed_at = EXCLUDED.reviewed_at,
              exported_at = EXCLUDED.exported_at
            RETURNING *
            """,
            (
                candidate_id,
                payload["workspace_id"],
                payload["thread_id"],
                payload["trace_id"],
                payload.get("reviewer_user_id"),
                payload.get("review_status", "pending"),
                payload["consent_scope"],
                payload.get("redaction_status", "redacted"),
                payload.get("repair_layer"),
                payload.get("failure_class"),
                self._to_json(payload.get("messages") or []),
                self._to_json(payload.get("labels") or {}),
                self._to_json(payload.get("dataset_card") or {}),
                payload.get("reviewed_at"),
                payload.get("exported_at"),
            ),
        )
        return self._normalize_phase5_training_candidate(row or {})

    def get_phase5_training_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        row = self._execute_fetchone("SELECT * FROM phase5_training_candidates WHERE id = %s::uuid", (candidate_id,))
        return self._normalize_phase5_training_candidate(row) if row else None

    def list_phase5_training_candidates(self, workspace_id: str, *, review_status: str | None = None) -> list[dict[str, Any]]:
        if review_status:
            rows = self._execute_fetchall(
                "SELECT * FROM phase5_training_candidates WHERE workspace_id = %s::uuid AND review_status = %s ORDER BY created_at DESC",
                (workspace_id, review_status),
            )
        else:
            rows = self._execute_fetchall(
                "SELECT * FROM phase5_training_candidates WHERE workspace_id = %s::uuid ORDER BY created_at DESC",
                (workspace_id,),
            )
        return [self._normalize_phase5_training_candidate(row) for row in rows]

    def update_phase5_training_candidate_review(
        self,
        candidate_id: str,
        *,
        review_status: str,
        reviewer_user_id: str,
        labels: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        current = self.get_phase5_training_candidate(candidate_id)
        if not current:
            return None
        merged = {**current.get("labels", {}), **(labels or {})}
        row = self._execute_fetchone(
            """
            UPDATE phase5_training_candidates
            SET review_status = %s, reviewer_user_id = %s::uuid, labels = %s::jsonb, reviewed_at = now()
            WHERE id = %s::uuid
            RETURNING *
            """,
            (review_status, reviewer_user_id, self._to_json(merged), candidate_id),
        )
        return self._normalize_phase5_training_candidate(row) if row else None

    def mark_phase5_training_candidates_exported(self, candidate_ids: list[str]) -> None:
        if not candidate_ids:
            return
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute("UPDATE phase5_training_candidates SET exported_at = now() WHERE id = ANY(%s::uuid[])", (candidate_ids,))

    def upsert_phase5_adapter_registry(self, payload: dict[str, Any]) -> dict[str, Any]:
        row_id = str(payload.get("id") or self._new_uuid())
        row = self._execute_fetchone(
            """
            INSERT INTO phase5_adapter_registry(
              id, workspace_id, adapter_id, base_model_id, method, status,
              artifact_uri, eval_summary, rollback_plan
            )
            VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s::jsonb, %s)
            ON CONFLICT (adapter_id) DO UPDATE SET
              workspace_id = EXCLUDED.workspace_id,
              base_model_id = EXCLUDED.base_model_id,
              method = EXCLUDED.method,
              status = EXCLUDED.status,
              artifact_uri = EXCLUDED.artifact_uri,
              eval_summary = EXCLUDED.eval_summary,
              rollback_plan = EXCLUDED.rollback_plan,
              updated_at = now()
            RETURNING *
            """,
            (
                row_id,
                payload.get("workspace_id"),
                payload["adapter_id"],
                payload["base_model_id"],
                payload["method"],
                payload.get("status", "planned"),
                payload.get("artifact_uri"),
                self._to_json(payload.get("eval_summary") or {}),
                payload["rollback_plan"],
            ),
        )
        return self._normalize_phase5_adapter_registry(row or {})

    def get_phase5_adapter_registry(self, adapter_id: str) -> dict[str, Any] | None:
        row = self._execute_fetchone("SELECT * FROM phase5_adapter_registry WHERE adapter_id = %s", (adapter_id,))
        return self._normalize_phase5_adapter_registry(row) if row else None

    def list_phase5_adapter_registry(self, workspace_id: str | None = None) -> list[dict[str, Any]]:
        if workspace_id:
            rows = self._execute_fetchall(
                "SELECT * FROM phase5_adapter_registry WHERE workspace_id = %s::uuid OR workspace_id IS NULL ORDER BY updated_at DESC",
                (workspace_id,),
            )
        else:
            rows = self._execute_fetchall("SELECT * FROM phase5_adapter_registry ORDER BY updated_at DESC", ())
        return [self._normalize_phase5_adapter_registry(row) for row in rows]

    def upsert_phase5_model_registry(self, payload: dict[str, Any]) -> dict[str, Any]:
        row_id = str(payload.get("id") or self._new_uuid())
        row = self._execute_fetchone(
            """
            INSERT INTO phase5_model_registry(
              id, workspace_id, model_id, quantization, context_window,
              hardware_profile, license, latency_profile, eval_profile,
              release_status, notes
            )
            VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
            ON CONFLICT (workspace_id, model_id) DO UPDATE SET
              quantization = EXCLUDED.quantization,
              context_window = EXCLUDED.context_window,
              hardware_profile = EXCLUDED.hardware_profile,
              license = EXCLUDED.license,
              latency_profile = EXCLUDED.latency_profile,
              eval_profile = EXCLUDED.eval_profile,
              release_status = EXCLUDED.release_status,
              notes = EXCLUDED.notes,
              updated_at = now()
            RETURNING *
            """,
            (
                row_id,
                payload["workspace_id"],
                payload["model_id"],
                payload["quantization"],
                int(payload["context_window"]),
                payload["hardware_profile"],
                payload["license"],
                self._to_json(payload.get("latency_profile") or {}),
                self._to_json(payload.get("eval_profile") or {}),
                payload.get("release_status", "candidate"),
                payload.get("notes"),
            ),
        )
        return self._normalize_phase5_model_registry(row or {})

    def get_phase5_model_registry(self, workspace_id: str, model_id: str) -> dict[str, Any] | None:
        row = self._execute_fetchone(
            "SELECT * FROM phase5_model_registry WHERE workspace_id = %s::uuid AND model_id = %s",
            (workspace_id, model_id),
        )
        return self._normalize_phase5_model_registry(row) if row else None

    def list_phase5_model_registry(self, workspace_id: str, *, release_status: str | None = None) -> list[dict[str, Any]]:
        if release_status:
            rows = self._execute_fetchall(
                "SELECT * FROM phase5_model_registry WHERE workspace_id = %s::uuid AND release_status = %s ORDER BY updated_at DESC",
                (workspace_id, release_status),
            )
        else:
            rows = self._execute_fetchall(
                "SELECT * FROM phase5_model_registry WHERE workspace_id = %s::uuid ORDER BY updated_at DESC",
                (workspace_id,),
            )
        return [self._normalize_phase5_model_registry(row) for row in rows]

    def _normalize_phase5_optimization_candidate(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "candidate_id": str(raw["candidate_id"]),
            "workspace_id": str(raw["workspace_id"]) if raw.get("workspace_id") is not None else None,
            "created_by_user_id": str(raw["created_by_user_id"]) if raw.get("created_by_user_id") is not None else None,
            "candidate_type": raw["candidate_type"],
            "parent_version": raw.get("parent_version"),
            "candidate_version": raw["candidate_version"],
            "generated_from_trace_ids": [str(item) for item in self._from_array(raw.get("generated_from_trace_ids"))],
            "reflection_summary": raw.get("reflection_summary"),
            "patch": self._from_json(raw.get("patch"), {}),
            "eval_summary": self._from_json(raw.get("eval_summary"), {}),
            "rollback_plan": raw.get("rollback_plan"),
            "pareto_status": raw.get("pareto_status"),
            "promoted_at": raw.get("promoted_at"),
            "created_at": raw.get("created_at"),
        }

    def _normalize_phase5_training_candidate(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(raw["id"]),
            "workspace_id": str(raw["workspace_id"]),
            "thread_id": str(raw["thread_id"]),
            "trace_id": str(raw["trace_id"]),
            "reviewer_user_id": str(raw["reviewer_user_id"]) if raw.get("reviewer_user_id") is not None else None,
            "review_status": raw["review_status"],
            "consent_scope": raw["consent_scope"],
            "redaction_status": raw["redaction_status"],
            "repair_layer": raw.get("repair_layer"),
            "failure_class": raw.get("failure_class"),
            "messages": self._from_json(raw.get("messages"), []),
            "labels": self._from_json(raw.get("labels"), {}),
            "dataset_card": self._from_json(raw.get("dataset_card"), {}),
            "created_at": raw.get("created_at"),
            "reviewed_at": raw.get("reviewed_at"),
            "exported_at": raw.get("exported_at"),
        }

    def _normalize_phase5_adapter_registry(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(raw["id"]),
            "workspace_id": str(raw["workspace_id"]) if raw.get("workspace_id") is not None else None,
            "adapter_id": raw["adapter_id"],
            "base_model_id": raw["base_model_id"],
            "method": raw["method"],
            "status": raw["status"],
            "artifact_uri": raw.get("artifact_uri"),
            "eval_summary": self._from_json(raw.get("eval_summary"), {}),
            "rollback_plan": raw["rollback_plan"],
            "created_at": raw.get("created_at"),
            "updated_at": raw.get("updated_at"),
        }

    def _normalize_phase5_model_registry(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(raw["id"]),
            "workspace_id": str(raw["workspace_id"]),
            "model_id": raw["model_id"],
            "quantization": raw["quantization"],
            "context_window": int(raw["context_window"]),
            "hardware_profile": raw["hardware_profile"],
            "license": raw["license"],
            "latency_profile": self._from_json(raw.get("latency_profile"), {}),
            "eval_profile": self._from_json(raw.get("eval_profile"), {}),
            "release_status": raw["release_status"],
            "notes": raw.get("notes"),
            "created_at": raw.get("created_at"),
            "updated_at": raw.get("updated_at"),
        }

    def _normalize_feedback(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(raw["id"]),
            "organization_id": str(raw["organization_id"]),
            "workspace_id": str(raw["workspace_id"]),
            "thread_id": str(raw["thread_id"]),
            "message_id": str(raw["message_id"]) if raw.get("message_id") is not None else None,
            "created_by_user_id": str(raw["created_by_user_id"]) if raw.get("created_by_user_id") is not None else None,
            "rating": raw["rating"],
            "failure_tags": self._from_array(raw.get("failure_tags")),
            "human_correction": raw.get("human_correction"),
            "ideal_answer": raw.get("ideal_answer"),
            "training_consent": bool(raw.get("training_consent")),
            "metadata": self._from_json(raw.get("metadata"), {}),
            "created_at": raw.get("created_at"),
        }

    def create_phase4_feedback(
        self,
        *,
        thread: dict[str, Any],
        message_id: str,
        created_by_user_id: str,
        rating: str,
        failure_tags: list[str],
        human_correction: str | None = None,
        ideal_answer: str | None = None,
        training_consent: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        feedback_id = self._new_uuid()
        row = self._execute_fetchone(
            """
            INSERT INTO feedback_events(
              id, organization_id, workspace_id, thread_id, message_id, created_by_user_id,
              rating, failure_tags, human_correction, ideal_answer, training_consent, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING *
            """,
            (
                feedback_id,
                thread["organization_id"],
                thread["workspace_id"],
                thread["id"],
                message_id,
                created_by_user_id,
                rating,
                failure_tags,
                human_correction,
                ideal_answer,
                bool(training_consent),
                self._to_json(metadata or {}),
            ),
        )
        feedback = self._normalize_feedback(row or {})
        self.append_phase4_trace_event(
            thread=thread,
            event_type="user_feedback",
            actor="user",
            message_id=message_id,
            payload=feedback,
        )
        return feedback

    def get_phase4_feedback(self, feedback_id: str) -> dict[str, Any] | None:
        row = self._execute_fetchone("SELECT * FROM feedback_events WHERE id = %s", (feedback_id,))
        return self._normalize_feedback(row) if row else None

    def list_phase4_feedback_for_thread(self, thread_id: str) -> list[dict[str, Any]]:
        rows = self._execute_fetchall(
            "SELECT * FROM feedback_events WHERE thread_id = %s ORDER BY created_at ASC",
            (thread_id,),
        )
        return [self._normalize_feedback(row) for row in rows]

    def _normalize_reflection(self, raw: dict[str, Any]) -> dict[str, Any]:
        thread_id = str(raw["thread_id"]) if raw.get("thread_id") is not None else None
        return {
            "memory_id": str(raw["id"]),
            "id": str(raw["id"]),
            "schema_version": "phase4.reflection_memory.v1",
            "organization_id": str(raw["organization_id"]),
            "workspace_id": str(raw["workspace_id"]) if raw.get("workspace_id") is not None else None,
            "thread_id": thread_id,
            "target_component": raw["target_component"],
            "lesson": raw["lesson"],
            "candidate_rule": raw.get("candidate_rule"),
            "source_thread_ids": [thread_id] if thread_id else [],
            "evidence": self._from_json(raw.get("evidence"), {}),
            "status": raw["status"],
            "scope": "workspace",
            "created_by_user_id": str(raw["created_by_user_id"]) if raw.get("created_by_user_id") is not None else None,
            "reviewed_by_user_id": str(raw["reviewed_by_user_id"]) if raw.get("reviewed_by_user_id") is not None else None,
            "created_at": raw.get("created_at"),
            "reviewed_at": raw.get("reviewed_at"),
        }

    def create_phase4_reflection_candidate(
        self,
        *,
        thread: dict[str, Any],
        created_by_user_id: str,
        target_component: str,
        lesson: str,
        candidate_rule: str | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        reflection_id = self._new_uuid()
        row = self._execute_fetchone(
            """
            INSERT INTO reflection_candidates(
              id, organization_id, workspace_id, thread_id, target_component, lesson,
              candidate_rule, evidence, status, created_by_user_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, 'candidate', %s)
            RETURNING *
            """,
            (
                reflection_id,
                thread["organization_id"],
                thread["workspace_id"],
                thread["id"],
                target_component,
                lesson,
                candidate_rule,
                self._to_json(evidence or {}),
                created_by_user_id,
            ),
        )
        reflection = self._normalize_reflection(row or {})
        self.append_phase4_trace_event(
            thread=thread,
            event_type="reflection_candidate",
            actor="system",
            payload=reflection,
        )
        return reflection

    def get_phase4_reflection(self, reflection_id: str) -> dict[str, Any] | None:
        row = self._execute_fetchone("SELECT * FROM reflection_candidates WHERE id = %s", (reflection_id,))
        return self._normalize_reflection(row) if row else None

    def update_phase4_reflection_status(self, *, reflection_id: str, reviewed_by_user_id: str, status: str) -> dict[str, Any] | None:
        existing = self.get_phase4_reflection(reflection_id)
        if not existing:
            return None
        row = self._execute_fetchone(
            """
            UPDATE reflection_candidates
            SET status = %s, reviewed_by_user_id = %s, reviewed_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (status, reviewed_by_user_id, reflection_id),
        )
        updated = self._normalize_reflection(row) if row else None
        thread = self.get_phase4_thread(existing["thread_id"]) if existing.get("thread_id") else None
        if thread and updated:
            self.append_phase4_trace_event(
                thread=thread,
                event_type="reflection_review",
                actor="reviewer",
                payload=updated,
            )
        return updated

    def _normalize_eval_candidate(self, raw: dict[str, Any]) -> dict[str, Any]:
        payload = self._from_json(raw.get("candidate_payload", raw.get("payload")), {})
        return {
            "id": str(raw["id"]),
            "organization_id": str(raw["organization_id"]),
            "workspace_id": str(raw["workspace_id"]),
            "thread_id": str(raw["thread_id"]) if raw.get("thread_id") is not None else None,
            "message_id": str(raw["message_id"]) if raw.get("message_id") is not None else None,
            "candidate_type": payload.get("candidate_type", raw.get("candidate_type", "eval_row")),
            "target_component": payload.get("target_component", raw.get("target_component", "eval")),
            "payload": payload,
            "review_status": raw["review_status"],
            "created_by_user_id": str(raw["created_by_user_id"]) if raw.get("created_by_user_id") is not None else None,
            "reviewed_by_user_id": str(raw["reviewed_by_user_id"]) if raw.get("reviewed_by_user_id") is not None else None,
            "created_at": raw.get("created_at"),
            "reviewed_at": raw.get("reviewed_at"),
        }

    def create_phase4_eval_candidate(self, *, thread: dict[str, Any], created_by_user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        candidate_id = self._new_uuid()
        prompt = str(payload.get("question") or payload.get("prompt") or payload.get("message") or "")
        feedback = payload.get("feedback") if isinstance(payload.get("feedback"), dict) else {}
        expected_behavior = payload.get("ideal_answer") or feedback.get("ideal_answer") or payload.get("answer")
        row = self._execute_fetchone(
            """
            INSERT INTO eval_candidates(
              id, organization_id, workspace_id, created_by_user_id, thread_id, message_id,
              feedback_event_id, prompt, expected_behavior, candidate_payload, review_status,
              visibility, sensitivity, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, 'pending', 'workspace', 'medium', '{}'::jsonb)
            RETURNING *
            """,
            (
                candidate_id,
                thread["organization_id"],
                thread["workspace_id"],
                created_by_user_id,
                thread["id"],
                payload.get("message_id"),
                feedback.get("id"),
                prompt,
                expected_behavior,
                self._to_json(payload),
            ),
        )
        candidate = self._normalize_eval_candidate(row or {})
        self.append_phase4_trace_event(thread=thread, event_type="eval_candidate", actor="system", payload=candidate)
        return candidate

    def get_phase4_eval_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        row = self._execute_fetchone("SELECT * FROM eval_candidates WHERE id = %s AND deleted_at IS NULL", (candidate_id,))
        return self._normalize_eval_candidate(row) if row else None

    def list_phase4_eval_candidates(self, workspace_id: str, *, review_status: str | None = None) -> list[dict[str, Any]]:
        params: tuple[Any, ...]
        status_filter = ""
        if review_status:
            status_filter = "AND review_status = %s"
            params = (workspace_id, review_status)
        else:
            params = (workspace_id,)
        rows = self._execute_fetchall(
            f"""
            SELECT *
            FROM eval_candidates
            WHERE workspace_id = %s AND deleted_at IS NULL {status_filter}
            ORDER BY created_at DESC
            """,
            params,
        )
        return [self._normalize_eval_candidate(row) for row in rows]

    def update_phase4_eval_candidate_status(
        self,
        *,
        candidate_id: str,
        reviewed_by_user_id: str,
        review_status: str,
    ) -> dict[str, Any] | None:
        existing = self.get_phase4_eval_candidate(candidate_id)
        if not existing:
            return None
        row = self._execute_fetchone(
            """
            UPDATE eval_candidates
            SET review_status = %s, reviewed_by_user_id = %s, reviewed_at = now(), updated_at = now()
            WHERE id = %s AND deleted_at IS NULL
            RETURNING *
            """,
            (review_status, reviewed_by_user_id, candidate_id),
        )
        updated = self._normalize_eval_candidate(row) if row else None
        thread = self.get_phase4_thread(existing["thread_id"]) if existing.get("thread_id") else None
        if thread and updated:
            self.append_phase4_trace_event(thread=thread, event_type="eval_candidate", actor="reviewer", payload=updated)
        return updated

    def _normalize_eval_run(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(raw["id"]),
            "organization_id": str(raw["organization_id"]),
            "workspace_id": str(raw["workspace_id"]),
            "created_by_user_id": str(raw["created_by_user_id"]) if raw.get("created_by_user_id") is not None else None,
            "name": raw.get("name", raw.get("suite_name")),
            "status": raw["status"],
            "candidate_ids": [str(item) for item in self._from_array(raw.get("candidate_ids"))],
            "metrics": self._from_json(raw.get("metrics"), {}),
            "gates": self._from_json(raw.get("gates"), {}),
            "metadata": self._from_json(raw.get("metadata"), {}),
            "created_at": raw.get("created_at"),
            "started_at": raw.get("started_at"),
            "finished_at": raw.get("finished_at"),
        }

    def create_phase4_eval_run(
        self,
        *,
        workspace: dict[str, Any],
        created_by_user_id: str,
        name: str,
        candidate_ids: list[str],
        metrics: dict[str, Any] | None = None,
        gates: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        status: str = "completed",
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> dict[str, Any]:
        run_id = self._new_uuid()
        row = self._execute_fetchone(
            """
            INSERT INTO eval_runs(
              id, organization_id, workspace_id, created_by_user_id, status, suite_name,
              candidate_ids, metrics, gates, metadata, started_at, finished_at
            )
            VALUES (
              %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb,
              COALESCE(%s::timestamptz, CASE WHEN %s = 'completed' THEN now() ELSE NULL END),
              COALESCE(%s::timestamptz, CASE WHEN %s = 'completed' THEN now() ELSE NULL END)
            )
            RETURNING *, suite_name AS name
            """,
            (
                run_id,
                workspace["organization_id"],
                workspace["id"],
                created_by_user_id,
                status,
                name,
                candidate_ids,
                self._to_json(metrics or {}),
                self._to_json(gates or {}),
                self._to_json(metadata or {}),
                started_at,
                status,
                finished_at,
                status,
            ),
        )
        return self._normalize_eval_run(row or {})

    def get_phase4_eval_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._execute_fetchone("SELECT *, suite_name AS name FROM eval_runs WHERE id = %s AND deleted_at IS NULL", (run_id,))
        return self._normalize_eval_run(row) if row else None

    def list_phase4_eval_runs(self, workspace_id: str) -> list[dict[str, Any]]:
        rows = self._execute_fetchall(
            """
            SELECT *, suite_name AS name
            FROM eval_runs
            WHERE workspace_id = %s AND deleted_at IS NULL
            ORDER BY created_at DESC
            """,
            (workspace_id,),
        )
        return [self._normalize_eval_run(row) for row in rows]

    def list_phase4_queued_eval_runs(self, *, limit: int) -> list[dict[str, Any]]:
        if limit <= 0:
            raise ValueError("limit must be > 0")
        rows = self._execute_fetchall(
            """
            SELECT *, suite_name AS name
            FROM eval_runs
            WHERE status = 'queued' AND deleted_at IS NULL
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (limit,),
        )
        return [self._normalize_eval_run(row) for row in rows]

    def update_phase4_eval_run(
        self,
        *,
        run_id: str,
        status: str,
        metrics: dict[str, Any] | None = None,
        gates: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> dict[str, Any] | None:
        existing = self.get_phase4_eval_run(run_id)
        if not existing:
            return None
        next_metadata = dict(existing.get("metadata") or {})
        if metadata:
            next_metadata.update(metadata)
        row = self._execute_fetchone(
            """
            UPDATE eval_runs
            SET status = %s,
                metrics = %s::jsonb,
                gates = %s::jsonb,
                metadata = %s::jsonb,
                started_at = COALESCE(%s::timestamptz, started_at),
                finished_at = COALESCE(%s::timestamptz, finished_at),
                updated_at = now()
            WHERE id = %s AND deleted_at IS NULL
            RETURNING *, suite_name AS name
            """,
            (
                status,
                self._to_json(existing.get("metrics", {}) if metrics is None else metrics),
                self._to_json(existing.get("gates", {}) if gates is None else gates),
                self._to_json(next_metadata),
                started_at,
                finished_at,
                run_id,
            ),
        )
        return self._normalize_eval_run(row) if row else None

    def _normalize_attachment(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(raw["id"]),
            "organization_id": str(raw["organization_id"]),
            "workspace_id": str(raw["workspace_id"]),
            "thread_id": str(raw["thread_id"]) if raw.get("thread_id") is not None else None,
            "message_id": str(raw["message_id"]) if raw.get("message_id") is not None else None,
            "created_by_user_id": str(raw["created_by_user_id"]) if raw.get("created_by_user_id") is not None else None,
            "filename": raw["filename"],
            "content_type": raw["content_type"],
            "storage_uri": raw["storage_uri"],
            "size_bytes": int(raw["size_bytes"]),
            "sha256": raw["sha256"],
            "modality": self._role(raw["modality"]),
            "sensitivity": raw["sensitivity"],
            "parse_status": raw["parse_status"],
            "metadata": self._from_json(raw.get("metadata"), {}),
            "created_at": raw.get("created_at"),
            "deleted_at": raw.get("deleted_at"),
        }

    def _attachment_metadata_and_chunks(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str, list[str]]:
        text_content = str(payload.get("text_content") or "")
        chunks = [text_content[index : index + 1200] for index in range(0, len(text_content), 1200)] if text_content.strip() else []
        metadata = {
            "retention_policy": payload.get("retention_policy", "delete_on_request"),
            "scan_status": "passed_local_stub",
            "parse_method": (
                "image_metadata_stub"
                if str(payload.get("content_type", "")).startswith("image/")
                else "local_pdf_text_stub"
                if payload.get("content_type") == "application/pdf"
                else "plain_text"
            ),
            "chunk_count": len(chunks),
            "embedding_status": "metadata_only_local_stub",
            "private_rag_scope": "workspace",
        }
        metadata.update(payload.get("metadata") or {})
        if str(payload.get("content_type", "")).startswith("image/"):
            parse_status = "image_staged"
        elif payload.get("content_type") == "application/pdf":
            parse_status = "private_indexed" if chunks else "parse_blocked"
        else:
            parse_status = "private_indexed"
        return metadata, parse_status, chunks

    def create_phase4_attachment(
        self,
        *,
        workspace: dict[str, Any],
        created_by_user_id: str,
        payload: dict[str, Any],
        storage_uri: str,
        size_bytes: int,
        sha256: str,
    ) -> dict[str, Any]:
        attachment_id = str(payload.get("id") or self._new_uuid())
        metadata, parse_status, chunks = self._attachment_metadata_and_chunks(payload)
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute(
                    """
                    INSERT INTO attachments(
                      id, organization_id, workspace_id, thread_id, message_id, created_by_user_id,
                      filename, content_type, storage_uri, size_bytes, sha256, modality, sensitivity,
                      parse_status, metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    RETURNING *
                    """,
                    (
                        attachment_id,
                        workspace["organization_id"],
                        workspace["id"],
                        payload.get("thread_id"),
                        payload.get("message_id"),
                        created_by_user_id,
                        payload["filename"],
                        payload["content_type"],
                        storage_uri,
                        size_bytes,
                        sha256,
                        payload.get("modality", "text"),
                        payload.get("sensitivity", "medium"),
                        parse_status,
                        self._to_json(metadata),
                    ),
                )
                attachment = self._row_dict(cursor.fetchone()) or {}
                for index, chunk_text in enumerate(chunks):
                    chunk_id = self._new_uuid()
                    cursor.execute(
                        """
                        INSERT INTO document_chunks(
                          id, organization_id, workspace_id, attachment_id, source_doc_id,
                          chunk_index, title, text_content, license_state, training_eligible,
                          visibility, metadata
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'private', %s::jsonb)
                        """,
                        (
                            chunk_id,
                            workspace["organization_id"],
                            workspace["id"],
                            attachment_id,
                            attachment_id,
                            index,
                            payload["filename"],
                            chunk_text,
                            "user_workspace_private",
                            False,
                            self._to_json({"text_len": len(chunk_text), "local_index_stub": True}),
                        ),
                    )
                    embedding_vector = _local_text_embedding(chunk_text)
                    cursor.execute(
                        """
                        INSERT INTO embeddings(
                          id, organization_id, workspace_id, chunk_id, attachment_id,
                          source_kind, source_id, modality, encoder_name, encoder_version,
                          dimensions, embedding, license_state, training_eligible, metadata
                        )
                        VALUES (%s, %s, %s, %s, %s, 'user_upload', %s, %s, 'local-hash-bow', 'v1', %s, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            self._new_uuid(),
                            workspace["organization_id"],
                            workspace["id"],
                            chunk_id,
                            attachment_id,
                            attachment_id,
                            payload.get("modality", "text"),
                            len(embedding_vector),
                            embedding_vector,
                            "user_workspace_private",
                            False,
                            self._to_json({"chunk_index": index, "embedding_status": "computed_local_hash_bow"}),
                        ),
                    )
                image_fingerprint = (metadata.get("image") or {}).get("fingerprint") or {}
                if image_fingerprint:
                    cursor.execute(
                        """
                        INSERT INTO embeddings(
                          id, organization_id, workspace_id, chunk_id, attachment_id,
                          source_kind, source_id, modality, encoder_name, encoder_version,
                          dimensions, embedding, license_state, training_eligible, metadata
                        )
                        VALUES (%s, %s, %s, NULL, %s, 'user_upload', %s, %s, 'local-image-fingerprint-stub', 'v0', %s, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            self._new_uuid(),
                            workspace["organization_id"],
                            workspace["id"],
                            attachment_id,
                            attachment_id,
                            payload.get("modality", "image"),
                            int(image_fingerprint.get("dimensions") or 0),
                            image_fingerprint.get("vector") or [],
                            "user_workspace_private",
                            False,
                            self._to_json(
                                {
                                    "embedding_status": "metadata_only_local_stub",
                                    "fingerprint_hash": image_fingerprint.get("hash"),
                                    "algorithm": image_fingerprint.get("algorithm"),
                                    "filters": metadata.get("filters", {}),
                                },
                            ),
                        ),
                    )
                self._insert_audit_event(
                    cursor,
                    event_type="attachment.created",
                    actor_user_id=created_by_user_id,
                    organization_id=workspace["organization_id"],
                    workspace_id=workspace["id"],
                    target_type="attachment",
                    target_id=attachment_id,
                    payload={"filename": payload["filename"], "size_bytes": size_bytes, "chunk_count": len(chunks)},
                )
        return self._normalize_attachment(attachment)

    def list_phase4_attachments(self, workspace_id: str, *, include_deleted: bool = False) -> list[dict[str, Any]]:
        deleted_filter = "" if include_deleted else "AND deleted_at IS NULL"
        rows = self._execute_fetchall(
            f"""
            SELECT *
            FROM attachments
            WHERE workspace_id = %s {deleted_filter}
            ORDER BY created_at DESC
            """,
            (workspace_id,),
        )
        return [self._normalize_attachment(row) for row in rows]

    def get_phase4_attachment(self, attachment_id: str, *, include_deleted: bool = False) -> dict[str, Any] | None:
        deleted_filter = "" if include_deleted else "AND deleted_at IS NULL"
        row = self._execute_fetchone(f"SELECT * FROM attachments WHERE id = %s {deleted_filter}", (attachment_id,))
        return self._normalize_attachment(row) if row else None

    def delete_phase4_attachment(self, *, attachment_id: str, deleted_by_user_id: str) -> dict[str, Any] | None:
        attachment = self.get_phase4_attachment(attachment_id)
        if not attachment:
            return None
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute("UPDATE attachments SET deleted_at = now(), parse_status = 'deleted' WHERE id = %s RETURNING *", (attachment_id,))
                deleted = self._row_dict(cursor.fetchone())
                cursor.execute("UPDATE document_chunks SET deleted_at = now() WHERE attachment_id = %s", (attachment_id,))
                cursor.execute("UPDATE embeddings SET deleted_at = now() WHERE attachment_id = %s", (attachment_id,))
                self._insert_audit_event(
                    cursor,
                    event_type="attachment.deleted",
                    actor_user_id=deleted_by_user_id,
                    organization_id=attachment["organization_id"],
                    workspace_id=attachment["workspace_id"],
                    target_type="attachment",
                    target_id=attachment_id,
                    payload={"filename": attachment["filename"], "derived_chunks_tombstoned": True, "derived_embeddings_tombstoned": True},
                )
        return self._normalize_attachment(deleted) if deleted else None

    def _normalize_document_chunk(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(raw["id"]),
            "organization_id": str(raw["organization_id"]) if raw.get("organization_id") is not None else None,
            "workspace_id": str(raw["workspace_id"]) if raw.get("workspace_id") is not None else None,
            "data_source_id": str(raw["data_source_id"]) if raw.get("data_source_id") is not None else None,
            "attachment_id": str(raw["attachment_id"]) if raw.get("attachment_id") is not None else None,
            "source_doc_id": raw.get("source_doc_id"),
            "chunk_index": int(raw["chunk_index"]),
            "title": raw.get("title"),
            "text_content": raw["text_content"],
            "source_url": raw.get("source_url"),
            "license_state": raw["license_state"],
            "training_eligible": bool(raw.get("training_eligible")),
            "visibility": self._role(raw.get("visibility", "private")),
            "metadata": self._from_json(raw.get("metadata"), {}),
            "created_at": raw.get("created_at"),
            "deleted_at": raw.get("deleted_at"),
        }

    def _normalize_embedding(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(raw["id"]),
            "organization_id": str(raw["organization_id"]) if raw.get("organization_id") is not None else None,
            "workspace_id": str(raw["workspace_id"]) if raw.get("workspace_id") is not None else None,
            "chunk_id": str(raw["chunk_id"]) if raw.get("chunk_id") is not None else None,
            "attachment_id": str(raw["attachment_id"]) if raw.get("attachment_id") is not None else None,
            "source_kind": raw["source_kind"],
            "source_id": raw["source_id"],
            "modality": self._role(raw["modality"]),
            "encoder_name": raw["encoder_name"],
            "encoder_version": raw["encoder_version"],
            "dimensions": raw["dimensions"],
            "vector": self._from_array(raw.get("vector", raw.get("embedding"))),
            "license_state": raw["license_state"],
            "training_eligible": bool(raw.get("training_eligible")),
            "metadata": self._from_json(raw.get("metadata"), {}),
            "created_at": raw.get("created_at"),
            "deleted_at": raw.get("deleted_at"),
            "filename": raw.get("filename"),
            "content_type": raw.get("content_type"),
            "attachment_metadata": self._from_json(raw.get("attachment_metadata"), {}),
        }

    def _normalize_data_source(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(raw["id"]),
            "organization_id": str(raw["organization_id"]),
            "workspace_id": str(raw["workspace_id"]),
            "source_id": raw["source_id"],
            "title": raw["title"],
            "publisher": raw.get("publisher"),
            "canonical_url": raw.get("canonical_url"),
            "license_state": raw["license_state"],
            "rag_eligible": bool(raw.get("rag_eligible")),
            "sft_eligible": bool(raw.get("sft_eligible")),
            "visibility": self._role(raw.get("visibility", "private")),
            "source_kind": raw["source_kind"],
            "crops": self._from_array(raw.get("crops")),
            "regions": self._from_array(raw.get("regions")),
            "buckets": self._from_array(raw.get("buckets")),
            "metadata": self._from_json(raw.get("metadata"), {}),
            "created_at": raw.get("created_at"),
            "updated_at": raw.get("updated_at"),
            "deleted_at": raw.get("deleted_at"),
        }

    def create_phase4_data_source(self, *, workspace: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        data_source_id = str(payload.get("id") or self._new_uuid())
        metadata = {
            **(payload.get("metadata") or {}),
            **{key: payload[key] for key in ["source_path", "text_content"] if payload.get(key) is not None},
        }
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute(
                    """
                    INSERT INTO data_sources(
                      id, organization_id, workspace_id, source_id, title, publisher, canonical_url,
                      license_state, rag_eligible, sft_eligible, visibility, source_kind, crops, regions,
                      buckets, metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    RETURNING *
                    """,
                    (
                        data_source_id,
                        workspace["organization_id"],
                        workspace["id"],
                        payload["source_id"],
                        payload["title"],
                        payload.get("publisher"),
                        payload.get("canonical_url"),
                        payload.get("license_state", "unknown"),
                        bool(payload.get("rag_eligible", False)),
                        bool(payload.get("sft_eligible", False)),
                        payload.get("visibility", "workspace"),
                        payload["source_kind"],
                        payload.get("crops", []),
                        payload.get("regions", []),
                        payload.get("buckets", []),
                        self._to_json(metadata),
                    ),
                )
                data_source = self._row_dict(cursor.fetchone()) or {}
        return self._normalize_data_source(data_source)

    def list_phase4_data_sources(self, workspace_id: str) -> list[dict[str, Any]]:
        rows = self._execute_fetchall(
            """
            SELECT *
            FROM data_sources
            WHERE workspace_id = %s AND deleted_at IS NULL
            ORDER BY created_at DESC
            """,
            (workspace_id,),
        )
        return [self._normalize_data_source(row) for row in rows]

    def get_phase4_data_source(self, data_source_id: str) -> dict[str, Any] | None:
        row = self._execute_fetchone("SELECT * FROM data_sources WHERE id = %s AND deleted_at IS NULL", (data_source_id,))
        return self._normalize_data_source(row) if row else None

    def update_phase4_data_source(
        self,
        *,
        data_source_id: str,
        actor_user_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        current = self.get_phase4_data_source(data_source_id)
        if not current:
            return None
        allowed_fields = {
            "title",
            "publisher",
            "canonical_url",
            "license_state",
            "rag_eligible",
            "sft_eligible",
            "source_kind",
            "crops",
            "regions",
            "buckets",
            "metadata",
            "source_path",
            "text_content",
        }
        updates = {key: value for key, value in payload.items() if key in allowed_fields}
        if not updates:
            return current
        metadata_updates = dict(current.get("metadata") or {})
        if "metadata" in updates:
            metadata_updates.update(updates.pop("metadata") or {})
        for key in ["source_path", "text_content"]:
            if key in updates:
                metadata_updates[key] = updates.pop(key)
        if metadata_updates != (current.get("metadata") or {}):
            updates["metadata"] = metadata_updates
        if not updates:
            return current
        assignments = [f"{key} = %s::jsonb" if key == "metadata" else f"{key} = %s" for key in updates]
        params = [self._to_json(value) if key == "metadata" else value for key, value in updates.items()]
        params.append(data_source_id)
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute(
                    f"""
                    UPDATE data_sources
                    SET {", ".join(assignments)}, updated_at = now()
                    WHERE id = %s AND deleted_at IS NULL
                    RETURNING *
                    """,
                    tuple(params),
                )
                updated = self._row_dict(cursor.fetchone())
                self._insert_audit_event(
                    cursor,
                    event_type="data_source.updated",
                    actor_user_id=actor_user_id,
                    organization_id=current["organization_id"],
                    workspace_id=current["workspace_id"],
                    target_type="data_source",
                    target_id=data_source_id,
                    payload={"updated_fields": sorted(updates)},
                )
        return self._normalize_data_source(updated) if updated else None

    def delete_phase4_data_source(self, *, data_source_id: str, deleted_by_user_id: str) -> dict[str, Any] | None:
        current = self.get_phase4_data_source(data_source_id)
        if not current:
            return None
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute(
                    """
                    UPDATE data_sources
                    SET deleted_at = now(), updated_at = now()
                    WHERE id = %s AND deleted_at IS NULL
                    RETURNING *
                    """,
                    (data_source_id,),
                )
                deleted = self._row_dict(cursor.fetchone())
                cursor.execute(
                    """
                    UPDATE source_documents
                    SET deleted_at = now(), updated_at = now()
                    WHERE data_source_id = %s AND deleted_at IS NULL
                    """,
                    (data_source_id,),
                )
                cursor.execute(
                    """
                    UPDATE document_chunks
                    SET deleted_at = now()
                    WHERE data_source_id = %s AND deleted_at IS NULL
                    """,
                    (data_source_id,),
                )
                cursor.execute(
                    """
                    UPDATE embeddings
                    SET deleted_at = now()
                    WHERE source_kind = 'data_source' AND source_id = %s AND deleted_at IS NULL
                    """,
                    (data_source_id,),
                )
                self._insert_audit_event(
                    cursor,
                    event_type="data_source.deleted",
                    actor_user_id=deleted_by_user_id,
                    organization_id=current["organization_id"],
                    workspace_id=current["workspace_id"],
                    target_type="data_source",
                    target_id=data_source_id,
                    payload={"source_id": current["source_id"], "title": current["title"]},
                )
        return self._normalize_data_source(deleted) if deleted else None

    def _normalize_ingest_job(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(raw["id"]),
            "organization_id": str(raw["organization_id"]),
            "workspace_id": str(raw["workspace_id"]),
            "data_source_id": str(raw["data_source_id"]) if raw.get("data_source_id") is not None else None,
            "attachment_id": str(raw["attachment_id"]) if raw.get("attachment_id") is not None else None,
            "job_type": raw["job_type"],
            "status": raw["status"],
            "queue_name": raw["queue_name"],
            "error_message": raw.get("error_message"),
            "result": self._from_json(raw.get("result"), {}),
            "created_by_user_id": str(raw["created_by_user_id"]) if raw.get("created_by_user_id") is not None else None,
            "created_at": raw.get("created_at"),
            "started_at": raw.get("started_at"),
            "finished_at": raw.get("finished_at"),
        }

    def create_phase4_ingest_job(self, *, data_source: dict[str, Any], created_by_user_id: str) -> dict[str, Any]:
        job_id = self._new_uuid()
        row = self._execute_fetchone(
            """
            INSERT INTO ingest_jobs(
              id, organization_id, workspace_id, data_source_id, job_type, status, queue_name,
              result, created_by_user_id
            )
            VALUES (%s, %s, %s, %s, 'data_source_ingest', 'queued', 'ingest', %s::jsonb, %s)
            RETURNING *
            """,
            (
                job_id,
                data_source["organization_id"],
                data_source["workspace_id"],
                data_source["id"],
                self._to_json({"queued": True, "phase": "phase4_postgres"}),
                created_by_user_id,
            ),
        )
        return self._normalize_ingest_job(row or {})

    def get_phase4_ingest_job(self, job_id: str) -> dict[str, Any] | None:
        row = self._execute_fetchone("SELECT * FROM ingest_jobs WHERE id = %s", (job_id,))
        return self._normalize_ingest_job(row) if row else None

    def list_phase4_ingest_jobs(self, workspace_id: str) -> list[dict[str, Any]]:
        rows = self._execute_fetchall(
            """
            SELECT *
            FROM ingest_jobs
            WHERE workspace_id = %s
            ORDER BY created_at DESC
            """,
            (workspace_id,),
        )
        return [self._normalize_ingest_job(row) for row in rows]

    def list_phase4_queued_ingest_jobs(self, *, limit: int = 10) -> list[dict[str, Any]]:
        if limit <= 0:
            raise ValueError("limit must be > 0")
        rows = self._execute_fetchall(
            """
            SELECT *
            FROM ingest_jobs
            WHERE status = 'queued'
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (limit,),
        )
        return [self._normalize_ingest_job(row) for row in rows]

    def update_phase4_ingest_job(
        self,
        *,
        job_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        error_message: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> dict[str, Any]:
        current = self.get_phase4_ingest_job(job_id)
        if not current:
            return {}
        row = self._execute_fetchone(
            """
            UPDATE ingest_jobs
            SET status = %s,
                result = %s::jsonb,
                error_message = %s,
                started_at = COALESCE(%s::timestamptz, started_at),
                finished_at = COALESCE(%s::timestamptz, finished_at)
            WHERE id = %s
            RETURNING *
            """,
            (
                status,
                self._to_json(current.get("result", {}) if result is None else result),
                error_message,
                started_at,
                finished_at,
                job_id,
            ),
        )
        return self._normalize_ingest_job(row or {})

    def replace_phase4_data_source_chunks(self, *, data_source: dict[str, Any], chunks: list[dict[str, Any]]) -> int:
        source_doc_id = data_source["source_id"]
        content_hash = hashlib.sha256("\n".join(str(chunk.get("text_content", "")) for chunk in chunks).encode("utf-8")).hexdigest()
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute(
                    """
                    UPDATE document_chunks
                    SET deleted_at = now()
                    WHERE data_source_id = %s AND deleted_at IS NULL
                    """,
                    (data_source["id"],),
                )
                cursor.execute(
                    """
                    UPDATE embeddings
                    SET deleted_at = now()
                    WHERE source_kind = 'data_source' AND source_id = %s AND deleted_at IS NULL
                    """,
                    (data_source["id"],),
                )
                source_document_uuid = self._new_uuid()
                cursor.execute(
                    """
                    INSERT INTO source_documents(
                      id, organization_id, workspace_id, data_source_id, source_doc_id, title,
                      canonical_url, content_hash, license_state, training_eligible, visibility, metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (data_source_id, source_doc_id) DO UPDATE SET
                      title = EXCLUDED.title,
                      canonical_url = EXCLUDED.canonical_url,
                      content_hash = EXCLUDED.content_hash,
                      license_state = EXCLUDED.license_state,
                      training_eligible = EXCLUDED.training_eligible,
                      visibility = EXCLUDED.visibility,
                      metadata = EXCLUDED.metadata,
                      updated_at = now(),
                      deleted_at = NULL
                    RETURNING id
                    """,
                    (
                        source_document_uuid,
                        data_source["organization_id"],
                        data_source["workspace_id"],
                        data_source["id"],
                        source_doc_id,
                        data_source["title"],
                        data_source.get("canonical_url"),
                        content_hash,
                        data_source["license_state"],
                        bool(data_source.get("sft_eligible")),
                        data_source.get("visibility", "workspace"),
                        self._to_json({"local_ingest_worker": True, "chunk_count": len(chunks)}),
                    ),
                )
                source_document = self._row_dict(cursor.fetchone()) or {"id": source_document_uuid}
                for index, chunk in enumerate(chunks):
                    text_content = str(chunk["text_content"])
                    chunk_id = self._new_uuid()
                    cursor.execute(
                        """
                        INSERT INTO document_chunks(
                          id, organization_id, workspace_id, data_source_id, source_document_id,
                          source_doc_id, chunk_index, title, text_content, source_url, license_state,
                          training_eligible, visibility, metadata
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            chunk_id,
                            data_source["organization_id"],
                            data_source["workspace_id"],
                            data_source["id"],
                            source_document["id"],
                            source_doc_id,
                            index,
                            data_source["title"],
                            text_content,
                            data_source.get("canonical_url"),
                            data_source["license_state"],
                            bool(data_source.get("sft_eligible")),
                            data_source.get("visibility", "workspace"),
                            self._to_json(
                                {
                                    "text_len": len(text_content),
                                    "local_ingest_worker": True,
                                    **(chunk.get("metadata") or {}),
                                },
                            ),
                        ),
                    )
                    embedding_vector = _local_text_embedding(text_content)
                    cursor.execute(
                        """
                        INSERT INTO embeddings(
                          id, organization_id, workspace_id, chunk_id, attachment_id,
                          source_kind, source_id, modality, encoder_name, encoder_version,
                          dimensions, embedding, license_state, training_eligible, visibility, metadata
                        )
                        VALUES (%s, %s, %s, %s, NULL, 'data_source', %s, 'text', 'local-hash-bow', 'v1', %s, %s, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            self._new_uuid(),
                            data_source["organization_id"],
                            data_source["workspace_id"],
                            chunk_id,
                            data_source["id"],
                            len(embedding_vector),
                            embedding_vector,
                            data_source["license_state"],
                            bool(data_source.get("sft_eligible")),
                            data_source.get("visibility", "workspace"),
                            self._to_json({"chunk_index": index, "embedding_status": "computed_local_hash_bow"}),
                        ),
                    )
        return len(chunks)

    def count_phase4_document_chunks_by_source(self, workspace_id: str) -> dict[str, int]:
        rows = self._execute_fetchall(
            """
            SELECT data_source_id, COUNT(*) AS chunk_count
            FROM document_chunks
            WHERE workspace_id = %s AND data_source_id IS NOT NULL AND deleted_at IS NULL
            GROUP BY data_source_id
            """,
            (workspace_id,),
        )
        return {str(row["data_source_id"]): int(row["chunk_count"]) for row in rows}

    def _normalize_knowledge_source(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(raw["id"]),
            "workspace_id": str(raw["workspace_id"]) if raw.get("workspace_id") is not None else None,
            "source_id": raw["source_id"],
            "title": raw["title"],
            "owner": raw["owner"],
            "visibility": raw["visibility"],
            "license_status": raw["license_status"],
            "canonical_url": raw.get("canonical_url"),
            "artifact_path": raw.get("artifact_path"),
            "checksum_sha256": raw.get("checksum_sha256"),
            "source_kind": raw.get("source_kind"),
            "rag_eligible": bool(raw.get("rag_eligible")),
            "sft_eligible": bool(raw.get("sft_eligible")),
            "metadata": self._from_json(raw.get("metadata_json"), {}),
            "created_at": raw.get("created_at"),
            "updated_at": raw.get("updated_at"),
        }

    def create_knowledge_source(self, payload: dict[str, Any]) -> dict[str, Any]:
        workspace_id = payload.get("workspace_id")
        if not workspace_id:
            raise ValueError("workspace_id is required for Postgres knowledge sources")
        source_id = str(payload.get("source_id") or "").strip()
        if not source_id:
            raise ValueError("source_id is required for Postgres knowledge sources")
        row_id = str(payload.get("id") or self._new_uuid())
        row = self._execute_fetchone(
            """
            INSERT INTO knowledge_sources(
              id, organization_id, workspace_id, source_id, title, owner, visibility,
              license_status, canonical_url, artifact_path, checksum_sha256, source_kind,
              rag_eligible, sft_eligible, metadata_json
            )
            SELECT
              %s, w.organization_id, w.id, %s, %s, %s, %s,
              %s, %s, %s, %s, %s, %s, %s, %s::jsonb
            FROM workspaces w
            WHERE w.id = %s
            ON CONFLICT (workspace_id, source_id) DO UPDATE SET
              title = EXCLUDED.title,
              owner = EXCLUDED.owner,
              visibility = EXCLUDED.visibility,
              license_status = EXCLUDED.license_status,
              canonical_url = EXCLUDED.canonical_url,
              artifact_path = EXCLUDED.artifact_path,
              checksum_sha256 = EXCLUDED.checksum_sha256,
              source_kind = EXCLUDED.source_kind,
              rag_eligible = EXCLUDED.rag_eligible,
              sft_eligible = EXCLUDED.sft_eligible,
              metadata_json = EXCLUDED.metadata_json,
              updated_at = now()
            RETURNING *
            """,
            (
                row_id,
                source_id,
                payload["title"],
                payload.get("owner", "unknown"),
                payload.get("visibility", "public"),
                payload.get("license_status", "review_required"),
                payload.get("canonical_url"),
                payload.get("artifact_path"),
                payload.get("checksum_sha256"),
                payload.get("source_kind"),
                bool(payload.get("rag_eligible", True)),
                bool(payload.get("sft_eligible", False)),
                self._to_json(payload.get("metadata") or {}),
                workspace_id,
            ),
        )
        if not row:
            raise ValueError(f"workspace not found for knowledge source: {workspace_id}")
        return self._normalize_knowledge_source(row)

    def get_knowledge_source(self, workspace_id: str | None, source_id: str) -> dict[str, Any] | None:
        if workspace_id is None:
            return None
        row = self._execute_fetchone(
            "SELECT * FROM knowledge_sources WHERE workspace_id = %s AND source_id = %s",
            (workspace_id, source_id),
        )
        return self._normalize_knowledge_source(row) if row else None

    def _normalize_knowledge_ingest_job(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(raw["id"]),
            "source_id": raw["source_id"],
            "status": raw["status"],
            "runtime": raw["runtime"],
            "reader": raw["reader"],
            "chunking_strategy": raw["chunking_strategy"],
            "embedder_profile": raw["embedder_profile"],
            "knowledge_base": raw["knowledge_base"],
            "contents_table": raw["contents_table"],
            "vector_table": raw["vector_table"],
            "chunk_count": raw.get("chunk_count"),
            "duplicate_of_source_id": raw.get("duplicate_of_source_id"),
            "error_message": raw.get("error_message"),
            "started_at": raw.get("started_at"),
            "finished_at": raw.get("finished_at"),
            "created_at": raw.get("created_at"),
            "updated_at": raw.get("updated_at"),
        }

    def create_knowledge_ingest_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        source_id = str(payload.get("source_id") or "").strip()
        if not source_id:
            raise ValueError("source_id is required for Postgres knowledge ingest jobs")
        row_id = str(payload.get("id") or self._new_uuid())
        row = self._execute_fetchone(
            """
            INSERT INTO knowledge_ingest_jobs(
              id, organization_id, workspace_id, source_id, status, runtime, reader,
              chunking_strategy, embedder_profile, knowledge_base, contents_table,
              vector_table, chunk_count, duplicate_of_source_id, error_message,
              started_at, finished_at
            )
            SELECT
              %s, ks.organization_id, ks.workspace_id, %s, %s, %s, %s,
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            FROM knowledge_sources ks
            WHERE ks.source_id = %s
            ORDER BY ks.updated_at DESC
            LIMIT 1
            RETURNING *
            """,
            (
                row_id,
                source_id,
                payload.get("status", "queued"),
                payload.get("runtime", "agno_knowledge"),
                payload["reader"],
                payload["chunking_strategy"],
                payload["embedder_profile"],
                payload["knowledge_base"],
                payload["contents_table"],
                payload["vector_table"],
                int(payload.get("chunk_count", 0)),
                payload.get("duplicate_of_source_id"),
                payload.get("error_message"),
                payload.get("started_at"),
                payload.get("finished_at"),
                source_id,
            ),
        )
        if not row:
            raise ValueError(f"knowledge source not found for ingest job: {source_id}")
        return self._normalize_knowledge_ingest_job(row)

    def create_knowledge_source_version(self, payload: dict[str, Any]) -> dict[str, Any]:
        row_id = str(payload.get("id") or self._new_uuid())
        row = self._execute_fetchone(
            """
            INSERT INTO knowledge_source_versions(
              id, organization_id, workspace_id, source_id, checksum_sha256,
              canonical_url, artifact_path, status, metadata_json
            )
            SELECT
              %s, ks.organization_id, ks.workspace_id, %s, %s, %s, %s, %s, %s::jsonb
            FROM knowledge_sources ks
            WHERE ks.source_id = %s
            ORDER BY ks.updated_at DESC
            LIMIT 1
            RETURNING *
            """,
            (
                row_id,
                payload["source_id"],
                payload["checksum_sha256"],
                payload.get("canonical_url"),
                payload.get("artifact_path"),
                payload["status"],
                self._to_json(payload.get("metadata") or {}),
                payload["source_id"],
            ),
        )
        if not row:
            raise ValueError(f"knowledge source not found for source version: {payload['source_id']}")
        return self._normalize_knowledge_source_version(row)

    def list_knowledge_source_versions(self, source_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._execute_fetchall(
            """
            SELECT *
            FROM knowledge_source_versions
            WHERE source_id = %s
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            (source_id, max(1, min(int(limit), 500))),
        )
        return [self._normalize_knowledge_source_version(row) for row in rows]

    def create_knowledge_chunk_review(self, payload: dict[str, Any]) -> dict[str, Any]:
        row_id = str(payload.get("id") or self._new_uuid())
        row = self._execute_fetchone(
            """
            INSERT INTO knowledge_chunk_reviews(
              id, organization_id, workspace_id, source_id, chunk_id,
              reviewer_status, rejection_reasons, evidence_coordinates
            )
            SELECT
              %s, ks.organization_id, ks.workspace_id, %s, %s, %s, %s::jsonb, %s::jsonb
            FROM knowledge_sources ks
            WHERE ks.source_id = %s
            ORDER BY ks.updated_at DESC
            LIMIT 1
            RETURNING *
            """,
            (
                row_id,
                payload["source_id"],
                payload["chunk_id"],
                payload.get("reviewer_status", "pending"),
                self._to_json(payload.get("rejection_reasons") or []),
                self._to_json(payload.get("evidence_coordinates") or {}),
                payload["source_id"],
            ),
        )
        if not row:
            raise ValueError(f"knowledge source not found for chunk review: {payload['source_id']}")
        return self._normalize_knowledge_chunk_review(row)

    def list_knowledge_chunk_reviews(self, source_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._execute_fetchall(
            """
            SELECT *
            FROM knowledge_chunk_reviews
            WHERE source_id = %s
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            (source_id, max(1, min(int(limit), 500))),
        )
        return [self._normalize_knowledge_chunk_review(row) for row in rows]

    def _normalize_knowledge_source_version(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(raw["id"]),
            "source_id": raw["source_id"],
            "checksum_sha256": raw["checksum_sha256"],
            "canonical_url": raw.get("canonical_url"),
            "artifact_path": raw.get("artifact_path"),
            "status": raw["status"],
            "metadata": self._from_json(raw.get("metadata_json"), {}),
            "created_at": raw.get("created_at"),
        }

    def _normalize_knowledge_chunk_review(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(raw["id"]),
            "source_id": raw["source_id"],
            "chunk_id": raw["chunk_id"],
            "reviewer_status": raw["reviewer_status"],
            "rejection_reasons": self._from_json(raw.get("rejection_reasons"), []),
            "evidence_coordinates": self._from_json(raw.get("evidence_coordinates"), {}),
            "created_at": raw.get("created_at"),
            "updated_at": raw.get("updated_at"),
        }

    def _normalize_export(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(raw["id"]),
            "organization_id": str(raw["organization_id"]),
            "workspace_id": str(raw["workspace_id"]),
            "thread_id": str(raw["thread_id"]) if raw.get("thread_id") is not None else None,
            "created_by_user_id": str(raw["created_by_user_id"]) if raw.get("created_by_user_id") is not None else None,
            "export_type": raw["export_type"],
            "storage_uri": raw["storage_uri"],
            "redaction_status": self._role(raw["redaction_status"]),
            "sha256": raw.get("sha256"),
            "metadata": self._from_json(raw.get("metadata"), {}),
            "created_at": raw.get("created_at"),
        }

    def create_phase4_export(
        self,
        *,
        thread: dict[str, Any],
        created_by_user_id: str,
        export_type: str,
        storage_uri: str,
        redaction_status: str,
        sha256: str | None,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        export_id = self._new_uuid()
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute(
                    """
                    INSERT INTO exports(
                      id, organization_id, workspace_id, thread_id, created_by_user_id, export_type,
                      storage_uri, redaction_status, sha256, metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    RETURNING *
                    """,
                    (
                        export_id,
                        thread["organization_id"],
                        thread["workspace_id"],
                        thread["id"],
                        created_by_user_id,
                        export_type,
                        storage_uri,
                        redaction_status,
                        sha256,
                        self._to_json(metadata),
                    ),
                )
                export = self._row_dict(cursor.fetchone()) or {}
                self._insert_audit_event(
                    cursor,
                    event_type="export.created",
                    actor_user_id=created_by_user_id,
                    organization_id=thread["organization_id"],
                    workspace_id=thread["workspace_id"],
                    target_type="export",
                    target_id=export_id,
                    payload={"thread_id": thread["id"], "export_type": export_type, "redaction_status": redaction_status, "sha256": sha256},
                )
        normalized = self._normalize_export(export)
        self.append_phase4_trace_event(
            thread=thread,
            event_type="export_event",
            actor="system",
            payload=minimized_export_trace_payload(normalized),
        )
        return normalized

    def list_phase4_exports(
        self,
        *,
        workspace_id: str,
        thread_id: str | None = None,
        export_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(limit, 500))
        filters = []
        params: list[Any] = [workspace_id]
        if thread_id:
            filters.append("thread_id = %s")
            params.append(thread_id)
        if export_type:
            filters.append("export_type = %s")
            params.append(export_type)
        where_extra = " AND " + " AND ".join(filters) if filters else ""
        rows = self._execute_fetchall(
            f"""
            SELECT *
            FROM exports
            WHERE workspace_id = %s {where_extra}
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            (*params, bounded_limit),
        )
        return [self._normalize_export(row) for row in rows]

    def get_phase4_export(self, export_id: str) -> dict[str, Any] | None:
        row = self._execute_fetchone("SELECT * FROM exports WHERE id = %s", (export_id,))
        return self._normalize_export(row) if row else None

    def _normalize_export_job(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(raw["id"]),
            "organization_id": str(raw["organization_id"]),
            "workspace_id": str(raw["workspace_id"]),
            "thread_id": str(raw["thread_id"]) if raw.get("thread_id") is not None else None,
            "created_by_user_id": str(raw["created_by_user_id"]) if raw.get("created_by_user_id") is not None else None,
            "export_type": raw["export_type"],
            "redaction_status": self._role(raw["redaction_status"]),
            "status": raw["status"],
            "queue_name": raw["queue_name"],
            "export_id": str(raw["export_id"]) if raw.get("export_id") is not None else None,
            "error_message": raw.get("error_message"),
            "result": self._from_json(raw.get("result"), {}),
            "created_at": raw.get("created_at"),
            "started_at": raw.get("started_at"),
            "finished_at": raw.get("finished_at"),
        }

    def create_phase4_export_job(
        self,
        *,
        thread: dict[str, Any],
        created_by_user_id: str,
        export_type: str,
        redaction_status: str,
        queue_name: str = "exports",
    ) -> dict[str, Any]:
        job_id = self._new_uuid()
        row = self._execute_fetchone(
            """
            INSERT INTO export_jobs(
              id, organization_id, workspace_id, thread_id, created_by_user_id,
              export_type, redaction_status, status, queue_name, result
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'queued', %s, '{}'::jsonb)
            RETURNING *
            """,
            (job_id, thread["organization_id"], thread["workspace_id"], thread["id"], created_by_user_id, export_type, redaction_status, queue_name),
        )
        return self._normalize_export_job(row or {})

    def get_phase4_export_job(self, job_id: str) -> dict[str, Any] | None:
        row = self._execute_fetchone("SELECT * FROM export_jobs WHERE id = %s", (job_id,))
        return self._normalize_export_job(row) if row else None

    def list_phase4_queued_export_jobs(self, *, limit: int) -> list[dict[str, Any]]:
        if limit <= 0:
            raise ValueError("limit must be > 0")
        rows = self._execute_fetchall(
            """
            SELECT *
            FROM export_jobs
            WHERE status = 'queued'
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (limit,),
        )
        return [self._normalize_export_job(row) for row in rows]

    def list_phase4_export_jobs(
        self,
        *,
        workspace_id: str,
        thread_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(limit, 500))
        filters = "WHERE workspace_id = %s"
        params: list[Any] = [workspace_id]
        if thread_id:
            filters += " AND thread_id = %s"
            params.append(thread_id)
        if status:
            filters += " AND status = %s"
            params.append(status)
        rows = self._execute_fetchall(
            f"""
            SELECT *
            FROM export_jobs
            {filters}
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (*params, bounded_limit),
        )
        return [self._normalize_export_job(row) for row in rows]

    def update_phase4_export_job(
        self,
        *,
        job_id: str,
        status: str,
        export_id: str | None = None,
        result: dict[str, Any] | None = None,
        error_message: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> dict[str, Any] | None:
        job = self.get_phase4_export_job(job_id)
        if not job:
            return None
        row = self._execute_fetchone(
            """
            UPDATE export_jobs
            SET status = %s,
                export_id = COALESCE(%s, export_id),
                result = %s::jsonb,
                error_message = %s,
                started_at = COALESCE(%s::timestamptz, started_at),
                finished_at = COALESCE(%s::timestamptz, finished_at)
            WHERE id = %s
            RETURNING *
            """,
            (status, export_id, self._to_json(job.get("result", {}) if result is None else result), error_message, started_at, finished_at, job_id),
        )
        return self._normalize_export_job(row) if row else None

    def _normalize_embedding_job(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(raw["id"]),
            "organization_id": str(raw["organization_id"]),
            "workspace_id": str(raw["workspace_id"]),
            "attachment_id": str(raw["attachment_id"]) if raw.get("attachment_id") is not None else None,
            "created_by_user_id": str(raw["created_by_user_id"]) if raw.get("created_by_user_id") is not None else None,
            "job_type": raw["job_type"],
            "status": raw["status"],
            "queue_name": raw["queue_name"],
            "error_message": raw.get("error_message"),
            "result": self._from_json(raw.get("result"), {}),
            "created_at": raw.get("created_at"),
            "started_at": raw.get("started_at"),
            "finished_at": raw.get("finished_at"),
        }

    def create_phase4_embedding_job(self, *, attachment: dict[str, Any], created_by_user_id: str, queue_name: str = "embedding") -> dict[str, Any]:
        job_id = self._new_uuid()
        row = self._execute_fetchone(
            """
            INSERT INTO embedding_jobs(
              id, organization_id, workspace_id, attachment_id, created_by_user_id,
              job_type, status, queue_name, result
            )
            VALUES (%s, %s, %s, %s, %s, 'attachment_embedding_reindex', 'queued', %s, '{}'::jsonb)
            RETURNING *
            """,
            (job_id, attachment["organization_id"], attachment["workspace_id"], attachment["id"], created_by_user_id, queue_name),
        )
        return self._normalize_embedding_job(row or {})

    def get_phase4_embedding_job(self, job_id: str) -> dict[str, Any] | None:
        row = self._execute_fetchone("SELECT * FROM embedding_jobs WHERE id = %s", (job_id,))
        return self._normalize_embedding_job(row) if row else None

    def list_phase4_queued_embedding_jobs(self, *, limit: int) -> list[dict[str, Any]]:
        if limit <= 0:
            raise ValueError("limit must be > 0")
        rows = self._execute_fetchall(
            """
            SELECT *
            FROM embedding_jobs
            WHERE status = 'queued'
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (limit,),
        )
        return [self._normalize_embedding_job(row) for row in rows]

    def update_phase4_embedding_job(
        self,
        *,
        job_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        error_message: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> dict[str, Any] | None:
        job = self.get_phase4_embedding_job(job_id)
        if not job:
            return None
        row = self._execute_fetchone(
            """
            UPDATE embedding_jobs
            SET status = %s,
                result = %s::jsonb,
                error_message = %s,
                started_at = COALESCE(%s::timestamptz, started_at),
                finished_at = COALESCE(%s::timestamptz, finished_at)
            WHERE id = %s
            RETURNING *
            """,
            (status, self._to_json(job.get("result", {}) if result is None else result), error_message, started_at, finished_at, job_id),
        )
        return self._normalize_embedding_job(row) if row else None

    def replace_phase4_attachment_embeddings(self, attachment_id: str, *, worker_name: str = "local_worker") -> dict[str, Any]:
        attachment = self.get_phase4_attachment(attachment_id)
        if not attachment:
            raise ValueError(f"attachment not found: {attachment_id}")
        metadata = dict(attachment.get("metadata") or {})
        text_count = 0
        image_count = 0
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute("UPDATE embeddings SET deleted_at = now() WHERE attachment_id = %s AND deleted_at IS NULL", (attachment_id,))
                cursor.execute(
                    """
                    SELECT *
                    FROM document_chunks
                    WHERE attachment_id = %s AND deleted_at IS NULL
                    ORDER BY chunk_index ASC
                    """,
                    (attachment_id,),
                )
                for raw_chunk in cursor.fetchall():
                    chunk = self._row_dict(raw_chunk) or {}
                    embedding_vector = _local_text_embedding(chunk["text_content"])
                    cursor.execute(
                        """
                        INSERT INTO embeddings(
                          id, organization_id, workspace_id, chunk_id, attachment_id,
                          source_kind, source_id, modality, encoder_name, encoder_version,
                          dimensions, embedding, license_state, training_eligible, metadata
                        )
                        VALUES (%s, %s, %s, %s, %s, 'user_upload', %s, 'text', 'local-hash-bow', 'v1', %s, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            self._new_uuid(),
                            attachment["organization_id"],
                            attachment["workspace_id"],
                            chunk["id"],
                            attachment_id,
                            attachment_id,
                            len(embedding_vector),
                            embedding_vector,
                            "user_workspace_private",
                            False,
                            self._to_json({"chunk_index": chunk.get("chunk_index"), "embedding_status": "computed_local_hash_bow", "worker": worker_name}),
                        ),
                    )
                    text_count += 1
                image_fingerprint = (metadata.get("image") or {}).get("fingerprint") or {}
                if image_fingerprint.get("vector"):
                    vector = image_fingerprint.get("vector") or []
                    cursor.execute(
                        """
                        INSERT INTO embeddings(
                          id, organization_id, workspace_id, chunk_id, attachment_id,
                          source_kind, source_id, modality, encoder_name, encoder_version,
                          dimensions, embedding, license_state, training_eligible, metadata
                        )
                        VALUES (%s, %s, %s, NULL, %s, 'user_upload', %s, %s, 'local-image-fingerprint-stub', 'v0', %s, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            self._new_uuid(),
                            attachment["organization_id"],
                            attachment["workspace_id"],
                            attachment_id,
                            attachment_id,
                            attachment.get("modality", "image"),
                            int(image_fingerprint.get("dimensions") or len(vector)),
                            vector,
                            "user_workspace_private",
                            False,
                            self._to_json(
                                {
                                    "embedding_status": "metadata_only_local_stub",
                                    "fingerprint_hash": image_fingerprint.get("hash"),
                                    "algorithm": image_fingerprint.get("algorithm"),
                                    "filters": metadata.get("filters", {}),
                                    "worker": worker_name,
                                },
                            ),
                        ),
                    )
                    image_count += 1
                metadata.update(
                    {
                        "embedding_status": "computed_worker_reindex",
                        "embedding_worker": worker_name,
                        "embedding_text_count": text_count,
                        "embedding_image_count": image_count,
                    },
                )
                cursor.execute("UPDATE attachments SET metadata = %s::jsonb WHERE id = %s", (self._to_json(metadata), attachment_id))
        return {"attachment_id": attachment_id, "text_embedding_count": text_count, "image_embedding_count": image_count, "worker": worker_name}

    def _normalize_image_job(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(raw["id"]),
            "organization_id": str(raw["organization_id"]),
            "workspace_id": str(raw["workspace_id"]),
            "thread_id": str(raw["thread_id"]) if raw.get("thread_id") is not None else None,
            "created_by_user_id": str(raw["created_by_user_id"]) if raw.get("created_by_user_id") is not None else None,
            "question": raw["question"],
            "crop": raw.get("crop"),
            "region": raw.get("region"),
            "attachment_ids": [str(value) for value in self._from_array(raw.get("attachment_ids"))],
            "status": raw["status"],
            "queue_name": raw["queue_name"],
            "error_message": raw.get("error_message"),
            "result": self._from_json(raw.get("result"), {}),
            "created_at": raw.get("created_at"),
            "started_at": raw.get("started_at"),
            "finished_at": raw.get("finished_at"),
        }

    def create_phase4_image_job(
        self,
        *,
        workspace: dict[str, Any],
        created_by_user_id: str,
        question: str,
        attachment_ids: list[str],
        thread_id: str | None = None,
        crop: str | None = None,
        region: str | None = None,
        queue_name: str = "image",
    ) -> dict[str, Any]:
        job_id = self._new_uuid()
        row = self._execute_fetchone(
            """
            INSERT INTO image_jobs(
              id, organization_id, workspace_id, thread_id, created_by_user_id,
              question, crop, region, attachment_ids, status, queue_name, result
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'queued', %s, '{}'::jsonb)
            RETURNING *
            """,
            (job_id, workspace["organization_id"], workspace["id"], thread_id, created_by_user_id, question, crop, region, attachment_ids, queue_name),
        )
        return self._normalize_image_job(row or {})

    def get_phase4_image_job(self, job_id: str) -> dict[str, Any] | None:
        row = self._execute_fetchone("SELECT * FROM image_jobs WHERE id = %s", (job_id,))
        return self._normalize_image_job(row) if row else None

    def list_phase4_queued_image_jobs(self, *, limit: int) -> list[dict[str, Any]]:
        if limit <= 0:
            raise ValueError("limit must be > 0")
        rows = self._execute_fetchall(
            """
            SELECT *
            FROM image_jobs
            WHERE status = 'queued'
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (limit,),
        )
        return [self._normalize_image_job(row) for row in rows]

    def update_phase4_image_job(
        self,
        *,
        job_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        error_message: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> dict[str, Any] | None:
        job = self.get_phase4_image_job(job_id)
        if not job:
            return None
        row = self._execute_fetchone(
            """
            UPDATE image_jobs
            SET status = %s,
                result = %s::jsonb,
                error_message = %s,
                started_at = COALESCE(%s::timestamptz, started_at),
                finished_at = COALESCE(%s::timestamptz, finished_at)
            WHERE id = %s
            RETURNING *
            """,
            (status, self._to_json(job.get("result", {}) if result is None else result), error_message, started_at, finished_at, job_id),
        )
        return self._normalize_image_job(row) if row else None

    def _normalize_change_proposal(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(raw["id"]),
            "organization_id": str(raw["organization_id"]),
            "workspace_id": str(raw["workspace_id"]),
            "created_by_user_id": str(raw["created_by_user_id"]) if raw.get("created_by_user_id") is not None else None,
            "title": raw["title"],
            "target_component": raw["target_component"],
            "proposal_type": raw["proposal_type"],
            "summary": raw["summary"],
            "rationale": raw.get("rationale"),
            "linked_reflection_id": str(raw["linked_reflection_id"]) if raw.get("linked_reflection_id") is not None else None,
            "linked_eval_run_id": str(raw["linked_eval_run_id"]) if raw.get("linked_eval_run_id") is not None else None,
            "review_status": raw["review_status"],
            "gates": self._from_json(raw.get("gates"), {}),
            "metadata": self._from_json(raw.get("metadata"), {}),
            "created_at": raw.get("created_at"),
            "reviewed_by_user_id": str(raw["reviewed_by_user_id"]) if raw.get("reviewed_by_user_id") is not None else None,
            "reviewed_at": raw.get("reviewed_at"),
        }

    def create_phase4_change_proposal(
        self,
        *,
        workspace: dict[str, Any],
        created_by_user_id: str,
        payload: dict[str, Any],
        gates: dict[str, Any],
    ) -> dict[str, Any]:
        proposal_id = self._new_uuid()
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute(
                    """
                    INSERT INTO change_proposals(
                      id, organization_id, workspace_id, created_by_user_id, title, target_component,
                      proposal_type, summary, rationale, linked_reflection_id, linked_eval_run_id,
                      review_status, gates, metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'candidate', %s::jsonb, %s::jsonb)
                    RETURNING *
                    """,
                    (
                        proposal_id,
                        workspace["organization_id"],
                        workspace["id"],
                        created_by_user_id,
                        payload["title"],
                        payload["target_component"],
                        payload["proposal_type"],
                        payload["summary"],
                        payload.get("rationale"),
                        payload.get("linked_reflection_id"),
                        payload.get("linked_eval_run_id"),
                        self._to_json(gates),
                        self._to_json(payload.get("metadata") or {}),
                    ),
                )
                proposal = self._row_dict(cursor.fetchone()) or {}
                self._insert_audit_event(
                    cursor,
                    event_type="change_proposal.created",
                    actor_user_id=created_by_user_id,
                    organization_id=workspace["organization_id"],
                    workspace_id=workspace["id"],
                    target_type="change_proposal",
                    target_id=proposal_id,
                    payload={
                        "title": payload["title"],
                        "target_component": payload["target_component"],
                        "proposal_type": payload["proposal_type"],
                        "linked_eval_run_id": payload.get("linked_eval_run_id"),
                        "promotion_allowed": bool(gates.get("promotion_allowed")),
                    },
                )
        return self._normalize_change_proposal(proposal)

    def get_phase4_change_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        row = self._execute_fetchone("SELECT * FROM change_proposals WHERE id = %s AND deleted_at IS NULL", (proposal_id,))
        return self._normalize_change_proposal(row) if row else None

    def list_phase4_change_proposals(self, workspace_id: str, *, review_status: str | None = None) -> list[dict[str, Any]]:
        status_filter = "AND review_status = %s" if review_status else ""
        params: tuple[Any, ...] = (workspace_id, review_status) if review_status else (workspace_id,)
        rows = self._execute_fetchall(
            f"""
            SELECT *
            FROM change_proposals
            WHERE workspace_id = %s AND deleted_at IS NULL {status_filter}
            ORDER BY created_at DESC, id DESC
            """,
            params,
        )
        return [self._normalize_change_proposal(row) for row in rows]

    def update_phase4_change_proposal_status(
        self,
        *,
        proposal_id: str,
        reviewed_by_user_id: str,
        review_status: str,
        notes: str | None = None,
    ) -> dict[str, Any] | None:
        proposal = self.get_phase4_change_proposal(proposal_id)
        if not proposal:
            return None
        metadata = dict(proposal.get("metadata") or {})
        if notes:
            metadata["review_notes"] = notes
        with self._connect(self.database_url) as connection:
            with self._cursor(connection) as cursor:
                cursor.execute(
                    """
                    UPDATE change_proposals
                    SET review_status = %s,
                        reviewed_by_user_id = %s,
                        reviewed_at = now(),
                        metadata = %s::jsonb,
                        updated_at = now()
                    WHERE id = %s AND deleted_at IS NULL
                    RETURNING *
                    """,
                    (review_status, reviewed_by_user_id, self._to_json(metadata), proposal_id),
                )
                updated = self._row_dict(cursor.fetchone())
                self._insert_audit_event(
                    cursor,
                    event_type="change_proposal.reviewed",
                    actor_user_id=reviewed_by_user_id,
                    organization_id=proposal["organization_id"],
                    workspace_id=proposal["workspace_id"],
                    target_type="change_proposal",
                    target_id=proposal_id,
                    payload={
                        "review_status": review_status,
                        "previous_review_status": proposal["review_status"],
                        "promotion_allowed": bool(proposal.get("gates", {}).get("promotion_allowed")),
                        "notes": notes,
                    },
                )
        return self._normalize_change_proposal(updated) if updated else None

    def _normalize_audit_event(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(raw["id"]),
            "organization_id": str(raw["organization_id"]) if raw.get("organization_id") is not None else None,
            "workspace_id": str(raw["workspace_id"]) if raw.get("workspace_id") is not None else None,
            "actor_user_id": str(raw["actor_user_id"]) if raw.get("actor_user_id") is not None else None,
            "event_type": raw["event_type"],
            "target_type": raw.get("target_type"),
            "target_id": str(raw["target_id"]) if raw.get("target_id") is not None else None,
            "payload": self._from_json(raw.get("payload"), {}),
            "created_at": raw.get("created_at"),
        }

    def list_phase4_audit_events(
        self,
        *,
        workspace_id: str,
        limit: int = 100,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(limit, 500))
        event_filter = "AND event_type = %s" if event_type else ""
        params: tuple[Any, ...] = (workspace_id, event_type, bounded_limit) if event_type else (workspace_id, bounded_limit)
        rows = self._execute_fetchall(
            f"""
            SELECT *
            FROM audit_events
            WHERE workspace_id = %s {event_filter}
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            params,
        )
        return [self._normalize_audit_event(row) for row in rows]

    def list_phase4_attachment_chunks(self, attachment_id: str) -> list[dict[str, Any]]:
        rows = self._execute_fetchall(
            """
            SELECT *
            FROM document_chunks
            WHERE attachment_id = %s AND deleted_at IS NULL
            ORDER BY chunk_index ASC
            """,
            (attachment_id,),
        )
        return [self._normalize_document_chunk(row) for row in rows]

    def list_phase4_attachment_chunks_with_embeddings(self, attachment_id: str) -> list[dict[str, Any]]:
        rows = self._execute_fetchall(
            """
            SELECT c.*, e.embedding AS embedding_vector, e.encoder_name, e.encoder_version,
                   e.dimensions AS embedding_dimensions, e.metadata AS embedding_metadata
            FROM document_chunks c
            LEFT JOIN embeddings e ON e.chunk_id = c.id AND e.deleted_at IS NULL
            WHERE c.attachment_id = %s AND c.deleted_at IS NULL
            ORDER BY c.chunk_index ASC
            """,
            (attachment_id,),
        )
        chunks: list[dict[str, Any]] = []
        for row in rows:
            chunk = self._normalize_document_chunk(row)
            chunk["embedding"] = {
                "vector": self._from_array(row.get("embedding_vector")),
                "encoder_name": row.get("encoder_name"),
                "encoder_version": row.get("encoder_version"),
                "dimensions": row.get("embedding_dimensions"),
                "metadata": self._from_json(row.get("embedding_metadata"), {}),
            }
            chunks.append(chunk)
        return chunks

    def list_phase4_data_source_chunks_with_embeddings(self, workspace_id: str) -> list[dict[str, Any]]:
        rows = self._execute_fetchall(
            """
            SELECT c.*, e.embedding AS embedding_vector, e.encoder_name, e.encoder_version,
                   e.dimensions AS embedding_dimensions, e.metadata AS embedding_metadata,
                   s.source_id AS registered_source_id, s.publisher, s.source_kind,
                   s.crops, s.regions, s.buckets, s.rag_eligible,
                   s.metadata AS data_source_metadata
            FROM document_chunks c
            JOIN data_sources s
              ON s.id = c.data_source_id AND s.deleted_at IS NULL
            LEFT JOIN embeddings e
              ON e.chunk_id = c.id AND e.deleted_at IS NULL
            WHERE c.workspace_id = %s
              AND c.data_source_id IS NOT NULL
              AND c.deleted_at IS NULL
              AND s.rag_eligible = TRUE
            ORDER BY s.updated_at DESC, c.chunk_index ASC
            """,
            (workspace_id,),
        )
        chunks: list[dict[str, Any]] = []
        for row in rows:
            chunk = self._normalize_document_chunk(row)
            chunk["embedding"] = {
                "vector": self._from_array(row.get("embedding_vector")),
                "encoder_name": row.get("encoder_name"),
                "encoder_version": row.get("encoder_version"),
                "dimensions": row.get("embedding_dimensions"),
                "metadata": self._from_json(row.get("embedding_metadata"), {}),
            }
            chunk["data_source"] = {
                "source_id": row.get("registered_source_id"),
                "publisher": row.get("publisher"),
                "source_kind": row.get("source_kind"),
                "crops": self._from_json(row.get("crops"), []),
                "regions": self._from_json(row.get("regions"), []),
                "buckets": self._from_json(row.get("buckets"), []),
                "rag_eligible": bool(row.get("rag_eligible")),
                "metadata": self._from_json(row.get("data_source_metadata"), {}),
            }
            chunks.append(chunk)
        return chunks

    def list_phase4_image_embeddings(self, workspace_id: str) -> list[dict[str, Any]]:
        rows = self._execute_fetchall(
            """
            SELECT e.*, e.embedding AS vector, a.filename, a.content_type, a.metadata AS attachment_metadata
            FROM embeddings e
            JOIN attachments a ON a.id = e.attachment_id
            WHERE e.workspace_id = %s
              AND e.deleted_at IS NULL
              AND a.deleted_at IS NULL
              AND e.modality IN ('image', 'multimodal')
            ORDER BY e.created_at DESC
            """,
            (workspace_id,),
        )
        return [self._normalize_embedding(row) for row in rows]

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        def _unimplemented(*args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError(
                f"Postgres runtime store method '{name}' is not implemented yet; "
                "SQLite fallback is disabled when AGRONOMY_AGENT_DB_BACKEND=postgres."
            )

        return _unimplemented


def build_trace_store(settings: ServerSettings) -> TraceStore | PostgresRuntimeStore:
    if settings.database_backend == "sqlite":
        return TraceStore(settings.db_path)
    if settings.database_backend == "postgres":
        return PostgresRuntimeStore(str(settings.database_url or ""))
    raise ValueError(f"Unsupported database backend: {settings.database_backend}")


def storage_label_for(store: Any) -> str:
    return str(getattr(store, "storage_label", "sqlite-local-dev"))


def storage_db_path_for(store: Any, default: Path) -> str | None:
    if getattr(store, "backend", "sqlite") == "postgres":
        return None
    return str(getattr(store, "db_path", default))

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def build_workspace_client(
    workspace_config: dict[str, Any],
    *,
    secret_resolver: Callable[[str, str], str] | None = None,
    workspace_client_class: Any = None,
) -> Any | None:
    """Build an SDK client without storing credentials in migration YAML."""
    if workspace_client_class is None:
        try:
            from databricks.sdk import WorkspaceClient
        except ImportError:
            return None
        workspace_client_class = WorkspaceClient

    forbidden = {"token", "access_token", "password", "client_secret"}
    found = forbidden.intersection(workspace_config.keys())
    auth = workspace_config.get("auth", {})
    if isinstance(auth, dict):
        found.update(forbidden.intersection(auth.keys()))
    if found:
        raise ValueError(
            "Credentials must not be stored directly in migration configuration; "
            f"remove: {', '.join(sorted(found))}"
        )

    auth = workspace_config.get("auth", {})
    if isinstance(auth, str):
        auth = {"type": auth}
    auth_type = str(auth.get("type", "DEFAULT")).upper()
    host = workspace_config.get("host")

    if auth_type == "DEFAULT":
        kwargs = {"host": host} if host else {}
        return workspace_client_class(**kwargs)

    if auth_type == "PROFILE":
        profile = auth.get("profile")
        if not profile:
            raise ValueError("PROFILE authentication requires auth.profile")
        kwargs = {"profile": profile}
        if host:
            kwargs["host"] = host
        return workspace_client_class(**kwargs)

    if auth_type == "TOKEN_SECRET":
        secret_scope = auth.get("secret_scope")
        secret_key = auth.get("secret_key")
        if not secret_scope or not secret_key:
            raise ValueError(
                "TOKEN_SECRET authentication requires auth.secret_scope and auth.secret_key"
            )
        if not host:
            raise ValueError("TOKEN_SECRET authentication requires workspace.host")
        if secret_resolver is None:
            raise ValueError(
                "TOKEN_SECRET authentication requires a Databricks secret resolver"
            )
        token = secret_resolver(secret_scope, secret_key)
        if not token:
            raise ValueError(
                f"Databricks secret {secret_scope}/{secret_key} is empty"
            )
        return workspace_client_class(host=host, token=token)

    raise ValueError(
        f"Unsupported workspace authentication type: {auth_type}. "
        "Supported types are DEFAULT, PROFILE, and TOKEN_SECRET."
    )

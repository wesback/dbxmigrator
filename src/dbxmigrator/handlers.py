from __future__ import annotations

from typing import Any, Iterable
import re

from .models import (
    Artifact,
    ArtifactIdentity,
    ArtifactMigrationStatus,
    ArtifactType,
    Dependency,
    DependencyResolution,
    ReadinessStatus,
)
from .registry import ArtifactHandler
from .registry import ArtifactHandlerRegistry


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "as_dict"):
        try:
            return value.as_dict()
        except TypeError:
            pass
    if hasattr(value, "__dict__"):
        return {
            key: val
            for key, val in vars(value).items()
            if not key.startswith("_")
        }
    return {"value": str(value)}


def _sdk_context(context: Any) -> Any:
    return context.source_client if hasattr(context, "source_client") else context


class NotebookHandler(ArtifactHandler):
    artifact_types = (ArtifactType.NOTEBOOK,)
    provider = "Databricks Workspace API"

    def discover(self, context: Any) -> Iterable[Artifact]:
        payload = _dict_source(context, "notebooks")
        if payload is not None:
            for item in payload:
                yield self._from_payload(item)
            return
        client = _sdk_context(context)
        workspace = getattr(client, "workspace", None)
        if workspace is None:
            return
        pending = ["/"]
        seen = set()
        while pending:
            directory = pending.pop()
            if directory in seen:
                continue
            seen.add(directory)
            for item in workspace.list(directory):
                as_dict = _as_dict(item)
                object_type = getattr(item, "object_type", as_dict.get("object_type"))
                path = getattr(item, "path", as_dict.get("path"))
                if object_type and str(object_type).upper().endswith("DIRECTORY"):
                    pending.append(path)
                elif object_type and str(object_type).upper().endswith("NOTEBOOK"):
                    yield self._from_payload(as_dict)
                elif str(path or "").endswith(".py") or str(path or "").endswith(".sql"):
                    yield self._from_payload(as_dict)

    def _from_payload(self, item: Any) -> Artifact:
        payload = _as_dict(item)
        path = payload.get("path") or payload.get("name") or payload.get("source_id")
        return Artifact(
            identity=ArtifactIdentity(
                key=f"NOTEBOOK:{path}",
                artifact_type=ArtifactType.NOTEBOOK,
                source_id=str(payload.get("object_id", payload.get("id", ""))) or None,
                name=path,
                parent=str(path).rsplit("/", 1)[0] if "/" in str(path) else "/",
            ),
            source_definition=payload,
            migration_strategy="EXPORT_IMPORT",
            validation_strategy="VERIFY_NOTEBOOK_CONTENT",
            migration_provider=self.provider,
            readiness_status=ReadinessStatus.UNKNOWN,
        )

    def analyze_dependencies(self, context: Any, artifact: Artifact) -> Artifact:
        source_text = str(artifact.source_definition.get("content", ""))
        if not source_text and artifact.source_definition.get("path"):
            client = getattr(context, "source_client", context)
            workspace = getattr(client, "workspace", None)
            if workspace is not None and hasattr(workspace, "export"):
                try:
                    exported = workspace.export(
                        path=artifact.identity.name,
                        format="SOURCE",
                    )
                    source_text = str(getattr(exported, "content", "") or "")
                except Exception:
                    source_text = ""
            if source_text:
                artifact.source_definition["content"] = source_text

        references: set[str] = set()
        patterns = (
            r"(?<![\w])(?:spark\.(?:sql|table)|table)\(\s*[\"']([^\"']+)[\"']",
            r"\b(?:FROM|JOIN|INSERT\s+INTO|MERGE\s+INTO)\s+([A-Za-z_][\w.]*\.[A-Za-z_][\w.]*)",
        )
        for pattern in patterns:
            references.update(re.findall(pattern, source_text, flags=re.IGNORECASE))

        artifact.dependencies = [
            Dependency(
                target_key=f"HIVE_TABLE:{reference}",
                dependency_type="HIVE_TABLE",
                reference=reference,
                resolution=DependencyResolution.UNRESOLVED,
            )
            for reference in sorted(references)
            if not reference.startswith(("http://", "https://"))
        ]
        return artifact

    def migrate(self, context: Any, artifact: Artifact) -> dict[str, Any]:
        client = getattr(context, "target_client", context)
        workspace = getattr(client, "workspace", None)
        if workspace is None:
            raise NotImplementedError("No target Databricks Workspace API client configured")
        content = artifact.source_definition.get("content")
        language = artifact.source_definition.get("language") or "PYTHON"
        path = artifact.identity.name
        workspace.import_(path=path, format="SOURCE", language=language, content=content, overwrite=False)
        return {"target_path": path}


class JobHandler(ArtifactHandler):
    artifact_types = (ArtifactType.JOB,)
    provider = "Databricks SDK"

    def discover(self, context: Any) -> Iterable[Artifact]:
        payload = _dict_source(context, "jobs")
        if payload is not None:
            for item in payload:
                yield self._from_payload(item)
            return
        client = _sdk_context(context)
        jobs = getattr(client, "jobs", None)
        if jobs is None:
            return
        for item in jobs.list():
            yield self._from_payload(_as_dict(item))

    def _from_payload(self, item: dict[str, Any]) -> Artifact:
        settings = item.get("settings", item)
        job_id = item.get("job_id", item.get("id"))
        name = settings.get("name", item.get("name", job_id))
        return Artifact(
            identity=ArtifactIdentity(
                key=f"JOB:{job_id}",
                artifact_type=ArtifactType.JOB,
                source_id=str(job_id) if job_id is not None else None,
                name=str(name),
            ),
            source_definition=item,
            migration_strategy="CREATE_JOB_WITH_TARGET_IDS",
            validation_strategy="VERIFY_JOB_DEFINITION",
            migration_provider=self.provider,
        )


class GenericInventoryHandler(ArtifactHandler):
    def __init__(
        self,
        artifact_type: ArtifactType,
        keys: tuple[str, ...],
        strategy: str,
        provider: str = "Databricks SDK",
    ) -> None:
        self.artifact_types = (artifact_type,)
        self._keys = keys
        self._strategy = strategy
        self.provider = provider

    def discover(self, context: Any) -> Iterable[Artifact]:
        for key in self._keys:
            payload = _dict_source(context, key)
            if payload is not None:
                for item in payload:
                    yield self._from_payload(item, key)
                return
        client = _sdk_context(context)
        service_name = self._keys[0]
        service = getattr(client, service_name, None)
        if service is None:
            return
        if hasattr(service, "list"):
            for item in service.list():
                yield self._from_payload(_as_dict(item), service_name)

    def _from_payload(self, item: Any, collection: str) -> Artifact:
        payload = _as_dict(item)
        identifier = (
            payload.get("id")
            or payload.get("object_id")
            or payload.get("name")
            or payload.get("path")
            or payload.get("policy_id")
        )
        name = payload.get("name") or payload.get("path") or str(identifier)
        return Artifact(
            identity=ArtifactIdentity(
                key=f"{self.artifact_types[0].value}:{identifier}",
                artifact_type=self.artifact_types[0],
                source_id=str(identifier) if identifier is not None else None,
                name=str(name),
            ),
            source_definition=payload,
            migration_strategy=self._strategy,
            validation_strategy="VERIFY_TARGET_ARTIFACT",
            migration_provider=self.provider,
        )


def _dict_source(context: Any, key: str) -> Any | None:
    if isinstance(context, dict):
        value = context.get(key)
        if isinstance(value, list):
            return value
        inventory = context.get("inventory")
        if isinstance(inventory, dict):
            value = inventory.get(key)
            if isinstance(value, list):
                return value
        return None
    inventory = getattr(context, "inventory", None)
    if isinstance(inventory, dict):
        value = inventory.get(key)
        return value if isinstance(value, list) else None
    return None


def default_registry() -> ArtifactHandlerRegistry:
    registry = ArtifactHandlerRegistry()
    registry.register_many(
        NotebookHandler(),
        JobHandler(),
        GenericInventoryHandler(
            ArtifactType.CLUSTER_POLICY,
            ("cluster_policies", "policies"),
            "CREATE_CLUSTER_POLICY",
        ),
        GenericInventoryHandler(
            ArtifactType.POOL,
            ("pools", "instance_pools"),
            "CREATE_INSTANCE_POOL",
        ),
        GenericInventoryHandler(
            ArtifactType.CLUSTER,
            ("clusters",),
            "CREATE_CLUSTER_OR_SKIP_EPHEMERAL",
        ),
        GenericInventoryHandler(
            ArtifactType.WAREHOUSE,
            ("warehouses", "sql_warehouses"),
            "CREATE_SQL_WAREHOUSE",
        ),
        GenericInventoryHandler(
            ArtifactType.DASHBOARD,
            ("dashboards",),
            "EXPORT_IMPORT",
        ),
        GenericInventoryHandler(
            ArtifactType.QUERY,
            ("queries",),
            "EXPORT_IMPORT",
        ),
        GenericInventoryHandler(
            ArtifactType.SECRET_SCOPE,
            ("secret_scopes",),
            "MANUAL_SECRET_RESEED",
        ),
        GenericInventoryHandler(
            ArtifactType.PIPELINE,
            ("pipelines", "dlt_pipelines"),
            "IMPORT_DLT_PIPELINE",
        ),
        GenericInventoryHandler(
            ArtifactType.FILE,
            ("files", "workspace_files"),
            "EXPORT_IMPORT",
        ),
        GenericInventoryHandler(
            ArtifactType.GIT_FOLDER,
            ("git_folders", "repos"),
            "RECREATE_REPO_PERMISSION",
        ),
        GenericInventoryHandler(
            ArtifactType.ALERT,
            ("alerts",),
            "EXPORT_IMPORT",
        ),
        GenericInventoryHandler(
            ArtifactType.MLFLOW,
            ("mlflow_experiments", "experiments"),
            "EXPORT_MLFLOW_METADATA_AND_MODELS",
        ),
        GenericInventoryHandler(
            ArtifactType.SERVING,
            ("serving_endpoints", "serving_resources"),
            "RECREATE_SERVING_ENDPOINT",
        ),
        GenericInventoryHandler(
            ArtifactType.HIVE_DATABASE,
            ("hive_databases",),
            "UC_ASSESS_OR_REGISTER_OR_MIGRATE",
            provider="SQL / UCX / Databricks SDK",
        ),
        GenericInventoryHandler(
            ArtifactType.HIVE_TABLE,
            ("hive_tables",),
            "UC_ASSESS_OR_REGISTER_OR_MIGRATE",
            provider="SQL / UCX / Databricks SDK",
        ),
        GenericInventoryHandler(
            ArtifactType.DBFS,
            ("dbfs", "dbfs_dependencies"),
            "STORAGE_COPY",
            provider="Storage Copy",
        ),
        GenericInventoryHandler(
            ArtifactType.VOLUME,
            ("volumes",),
            "STORAGE_COPY_AND_RECREATE_VOLUME",
            provider="Storage Copy",
        ),
        GenericInventoryHandler(
            ArtifactType.LEGACY_MOUNT,
            ("legacy_mounts", "mounts"),
            "ASSESS_AND_REMAP_STORAGE_DEPENDENCY",
            provider="Databricks SDK / Manual",
        ),
        GenericInventoryHandler(
            ArtifactType.CHECKPOINT,
            ("checkpoints", "streaming_checkpoints"),
            "STORAGE_COPY_WITH_STREAM_STATE_VALIDATION",
            provider="Storage Copy",
        ),
        GenericInventoryHandler(
            ArtifactType.APPLICATION_STATE,
            ("application_state",),
            "EXPORT_IMPORT_OR_MANUAL",
            provider="Manual / Export Import",
        ),
        GenericInventoryHandler(
            ArtifactType.PERMISSION,
            ("permissions",),
            "IDENTITY_MAPPED_PERMISSION_IMPORT",
            provider="Databricks SDK",
        ),
    )
    return registry

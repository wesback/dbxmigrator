from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Iterable

from .models import (
    Artifact,
    ArtifactMigrationStatus,
    ArtifactType,
    DependencyResolution,
    MigrationDisposition,
    ReadinessStatus,
)
from .registry import ArtifactHandlerRegistry


SYSTEM_ARTIFACT_TYPES = {
    ArtifactType.RUN,
    ArtifactType.QUERY_HISTORY,
    ArtifactType.AI_PLAYGROUND,
}

SYSTEM_PATH_MARKERS = (
    "/databricks/",
    "/databricks-demos/",
    "/databricks_",
    "/shared/databricks ",
    "/shared/databricks_",
    "/shared/databricks/",
    "/shared/ubuntu/",
    "/shared/sample",
    "/shared/samples",
    "/workspace/shared/databricks ",
    "/workspace/shared/databricks_",
)

SYSTEM_NAME_MARKERS = (
    "databricks sample",
    "databricks-sample",
    "databricks_sample",
    "sample notebook",
    "__databricks",
    "system.",
)


def is_system_managed_artifact(artifact: Artifact) -> bool:
    if artifact.artifact_type in SYSTEM_ARTIFACT_TYPES:
        return True

    payload = artifact.source_definition
    for flag in ("is_sample", "sample", "system_managed", "is_system"):
        if payload.get(flag) is True:
            return True

    name = str(
        payload.get("name")
        or payload.get("path")
        or payload.get("full_name")
        or artifact.identity.name
        or ""
    ).lower()
    path = str(payload.get("path") or artifact.identity.parent or "").lower()
    catalog_name = str(
        payload.get("catalog_name")
        or payload.get("catalog")
        or ""
    ).lower()
    schema_name = str(
        payload.get("schema_name")
        or payload.get("schema")
        or ""
    ).lower()
    full_name = str(payload.get("full_name") or "").lower()

    if artifact.artifact_type == ArtifactType.CATALOG:
        if name in {"system", "samples", "hive_metastore"}:
            return True

    if catalog_name in {"system", "samples"}:
        return True
    if schema_name in {"information_schema", "system"}:
        return True
    if full_name.startswith(("system.", "samples.", "information_schema.")):
        return True

    if artifact.artifact_type == ArtifactType.SERVING:
        if name.startswith("system_") or name.startswith("databricks-"):
            return True
        if payload.get("creator") in {"databricks", "Databricks"}:
            return True

    return (
        any(marker in path for marker in SYSTEM_PATH_MARKERS)
        or any(marker in name for marker in SYSTEM_NAME_MARKERS)
    )


class MigrationPlanner:
    def __init__(self, registry: ArtifactHandlerRegistry) -> None:
        self.registry = registry

    def build_inventory(self, context: Any) -> list[Artifact]:
        artifacts = self.registry.discover(context)
        artifacts_by_key = {artifact.key: artifact for artifact in artifacts}

        for artifact in artifacts:
            handler = self.registry.get(artifact.artifact_type)
            handler.analyze_dependencies(context, artifact)

        return list(artifacts_by_key.values())

    def build_dependency_graph(
        self, artifacts: Iterable[Artifact]
    ) -> list[dict[str, Any]]:
        edges: list[dict[str, Any]] = []
        for artifact in artifacts:
            for dependency in artifact.dependencies:
                edges.append(
                    {
                        "source": artifact.key,
                        "target": dependency.target_key,
                        "dependency_type": dependency.dependency_type,
                        "reference": dependency.reference,
                        "resolution": dependency.resolution.value,
                    }
                )
        return edges

    def classify(
        self,
        context: Any,
        artifacts: Iterable[Artifact],
        configuration: dict[str, Any],
    ) -> list[Artifact]:
        include = {
            value.upper()
            for value in configuration.get("migration", {}).get(
                "include_artifact_types", []
            )
        }
        exclude = {
            value.upper()
            for value in configuration.get("migration", {}).get(
                "exclude_artifact_types", []
            )
        }
        uc_mode = configuration.get("migration", {}).get(
            "unity_catalog", {}
        ).get("mode", "NONE").upper()
        migration = configuration.get("migration", {})
        workspace_artifacts = bool(migration.get("workspace_artifacts", True))
        data_enabled = bool(migration.get("data", {}).get("enabled", True))
        assessment_only = bool(migration.get("assessment_only", False))
        data_types = {
            ArtifactType.DBFS,
            ArtifactType.VOLUME,
            ArtifactType.CHECKPOINT,
            ArtifactType.APPLICATION_STATE,
        }
        governance_types = {
            ArtifactType.HIVE_DATABASE,
            ArtifactType.HIVE_TABLE,
            ArtifactType.STORAGE_CREDENTIAL,
            ArtifactType.EXTERNAL_LOCATION,
            ArtifactType.LEGACY_MOUNT,
        }

        classified: list[Artifact] = []
        for artifact in artifacts:
            artifact_type = artifact.artifact_type.value
            if artifact.artifact_type in data_types:
                artifact.metadata["dimension"] = "DATA"
            elif artifact.artifact_type in governance_types:
                artifact.metadata["dimension"] = "GOVERNANCE"
            else:
                artifact.metadata["dimension"] = "WORKSPACE"

            if is_system_managed_artifact(artifact):
                artifact.metadata["system_managed"] = True
                artifact.disposition = MigrationDisposition.SKIP_BY_POLICY
                artifact.migration_status = ArtifactMigrationStatus.SKIPPED
                artifact.readiness_status = ReadinessStatus.NOT_APPLICABLE
                artifact.warnings.append(
                    "System-managed or sample artifact; migration is excluded by policy"
                )
                classified.append(artifact)
                continue
            if artifact_type in exclude or (include and artifact_type not in include):
                artifact.disposition = MigrationDisposition.SKIP_BY_POLICY
                artifact.migration_status = ArtifactMigrationStatus.SKIPPED
                artifact.readiness_status = ReadinessStatus.NOT_APPLICABLE
                classified.append(artifact)
                continue
            if assessment_only:
                artifact.metadata["assessment_only"] = True
                artifact.metadata["target_required"] = False
                artifact.disposition = (
                    MigrationDisposition.MANUAL_REQUIRED
                    if artifact.artifact_type in governance_types
                    else MigrationDisposition.MIGRATE_AUTOMATICALLY
                )
                artifact.migration_status = ArtifactMigrationStatus.PLANNED
                artifact.readiness_status = ReadinessStatus.WARNING
                artifact.warnings.append(
                    "Assessment-only mode: target configuration is not required and no migration or UC mutation has been planned for execution"
                )
                handler = self.registry.get(artifact.artifact_type)
                handler.plan(context, artifact)
                classified.append(artifact)
                continue
            if artifact.artifact_type in data_types and not data_enabled:
                artifact.disposition = MigrationDisposition.SKIP_BY_POLICY
                artifact.migration_status = ArtifactMigrationStatus.SKIPPED
                artifact.readiness_status = ReadinessStatus.NOT_APPLICABLE
                classified.append(artifact)
                continue
            if artifact.metadata["dimension"] == "WORKSPACE" and not workspace_artifacts:
                artifact.disposition = MigrationDisposition.SKIP_BY_POLICY
                artifact.migration_status = ArtifactMigrationStatus.SKIPPED
                artifact.readiness_status = ReadinessStatus.NOT_APPLICABLE
                classified.append(artifact)
                continue

            if artifact.artifact_type in {
                ArtifactType.HIVE_DATABASE,
                ArtifactType.HIVE_TABLE,
                ArtifactType.STORAGE_CREDENTIAL,
                ArtifactType.EXTERNAL_LOCATION,
                ArtifactType.LEGACY_MOUNT,
            } and uc_mode == "NONE":
                artifact.metadata["dimension"] = "GOVERNANCE"
                artifact.metadata["uc_mode"] = "NONE"
                artifact.metadata["no_automatic_uc_change"] = True
                if artifact.artifact_type in {
                    ArtifactType.HIVE_DATABASE,
                    ArtifactType.HIVE_TABLE,
                }:
                    artifact.disposition = MigrationDisposition.BLOCKED_DEPENDENCY
                    artifact.migration_status = ArtifactMigrationStatus.BLOCKED
                    artifact.readiness_status = ReadinessStatus.BLOCKED
                    artifact.blockers.append(
                        "Legacy Hive dependency is unresolved in target; UC migration is disabled"
                    )
                else:
                    artifact.disposition = MigrationDisposition.SKIP_BY_POLICY
                    artifact.migration_status = ArtifactMigrationStatus.SKIPPED
                    artifact.readiness_status = ReadinessStatus.NOT_APPLICABLE

            elif artifact.artifact_type in {
                ArtifactType.HIVE_DATABASE,
                ArtifactType.HIVE_TABLE,
            } and uc_mode in {"ASSESS", "REGISTER", "MIGRATE"}:
                artifact.metadata["dimension"] = "GOVERNANCE"
                artifact.metadata["uc_mode"] = uc_mode
                artifact.disposition = (
                    MigrationDisposition.REGISTER_UC
                    if uc_mode == "REGISTER"
                    else MigrationDisposition.MIGRATE_AUTOMATICALLY
                    if uc_mode == "MIGRATE"
                    else MigrationDisposition.MIGRATE_AUTOMATICALLY
                )
                if uc_mode == "ASSESS":
                    artifact.disposition = MigrationDisposition.MANUAL_REQUIRED
                    artifact.migration_status = ArtifactMigrationStatus.PLANNED
                    artifact.readiness_status = ReadinessStatus.WARNING
                else:
                    artifact.migration_status = ArtifactMigrationStatus.PLANNED
                    artifact.readiness_status = ReadinessStatus.UNKNOWN

            handler = self.registry.get(artifact.artifact_type)
            handler.plan(context, artifact)

            if artifact.blockers and not artifact.disposition:
                artifact.disposition = MigrationDisposition.BLOCKED_DEPENDENCY
                artifact.migration_status = ArtifactMigrationStatus.BLOCKED
                artifact.readiness_status = ReadinessStatus.BLOCKED
            elif artifact.disposition is None:
                artifact.disposition = MigrationDisposition.MIGRATE_AUTOMATICALLY
                artifact.migration_status = ArtifactMigrationStatus.PLANNED
                if artifact.readiness_status == ReadinessStatus.UNKNOWN:
                    unresolved = [
                        dependency
                        for dependency in artifact.dependencies
                        if dependency.resolution
                        == DependencyResolution.UNRESOLVED
                    ]
                    artifact.readiness_status = (
                        ReadinessStatus.BLOCKED if unresolved else ReadinessStatus.READY
                    )
                    if unresolved:
                        for dependency in unresolved:
                            artifact.blockers.append(
                                f"Unresolved dependency: {dependency.reference}"
                            )
            classified.append(artifact)

        return classified

    def topological_artifacts(
        self, artifacts: Iterable[Artifact]
    ) -> list[Artifact]:
        artifacts_by_key = {artifact.key: artifact for artifact in artifacts}
        indegree = {key: 0 for key in artifacts_by_key}
        outgoing: dict[str, list[str]] = defaultdict(list)
        for artifact in artifacts_by_key.values():
            for dependency in artifact.dependencies:
                if dependency.target_key in artifacts_by_key:
                    outgoing[dependency.target_key].append(artifact.key)
                    indegree[artifact.key] += 1

        queue = deque(key for key, degree in indegree.items() if degree == 0)
        ordered: list[Artifact] = []
        while queue:
            key = queue.popleft()
            ordered.append(artifacts_by_key[key])
            for dependent in outgoing[key]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    queue.append(dependent)
        for key, degree in indegree.items():
            if degree > 0:
                ordered.append(artifacts_by_key[key])
        return ordered

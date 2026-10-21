from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Iterable, Optional


class ArtifactMigrationStatus(str, Enum):
    MIGRATED = "MIGRATED"
    PLANNED = "PLANNED"
    SKIPPED = "SKIPPED"
    BLOCKED = "BLOCKED"
    UNSUPPORTED = "UNSUPPORTED"
    MANUAL_REQUIRED = "MANUAL_REQUIRED"


class ReadinessStatus(str, Enum):
    READY = "READY"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class MigrationDisposition(str, Enum):
    MIGRATE_AUTOMATICALLY = "MIGRATE_AUTOMATICALLY"
    MIGRATE_WITH_TRANSFORMATION = "MIGRATE_WITH_TRANSFORMATION"
    MIGRATE_DATA_ONLY = "MIGRATE_DATA_ONLY"
    REGISTER_UC = "REGISTER_UC"
    SKIP_BY_POLICY = "SKIP_BY_POLICY"
    BLOCKED_DEPENDENCY = "BLOCKED_DEPENDENCY"
    MANUAL_REQUIRED = "MANUAL_REQUIRED"
    UNSUPPORTED = "UNSUPPORTED"


class ArtifactType(str, Enum):
    NOTEBOOK = "NOTEBOOK"
    FILE = "FILE"
    GIT_FOLDER = "GIT_FOLDER"
    JOB = "JOB"
    PIPELINE = "PIPELINE"
    CLUSTER = "CLUSTER"
    CLUSTER_POLICY = "CLUSTER_POLICY"
    POOL = "POOL"
    WAREHOUSE = "SQL_WAREHOUSE"
    QUERY = "QUERY"
    DASHBOARD = "DASHBOARD"
    ALERT = "ALERT"
    MLFLOW = "MLFLOW"
    SERVING = "SERVING"
    PERMISSION = "PERMISSION"
    SECRET_SCOPE = "SECRET_SCOPE"
    WORKSPACE_CONFIG = "WORKSPACE_CONFIG"
    HIVE_DATABASE = "HIVE_DATABASE"
    HIVE_TABLE = "HIVE_TABLE"
    DBFS = "DBFS"
    VOLUME = "VOLUME"
    STORAGE_CREDENTIAL = "STORAGE_CREDENTIAL"
    EXTERNAL_LOCATION = "EXTERNAL_LOCATION"
    LEGACY_MOUNT = "LEGACY_MOUNT"
    CHECKPOINT = "CHECKPOINT"
    APPLICATION_STATE = "APPLICATION_STATE"
    UNKNOWN = "UNKNOWN"


class DependencyResolution(str, Enum):
    UNRESOLVED = "UNRESOLVED"
    HMS = "HMS"
    UC = "UC"
    OTHER = "OTHER"
    RESOLVED = "RESOLVED"
    NOT_REQUIRED = "NOT_REQUIRED"


@dataclass(frozen=True)
class ArtifactIdentity:
    key: str
    artifact_type: ArtifactType
    source_id: Optional[str] = None
    name: Optional[str] = None
    parent: Optional[str] = None


@dataclass
class Dependency:
    target_key: str
    dependency_type: str
    reference: str
    resolution: DependencyResolution = DependencyResolution.UNRESOLVED
    resolution_target: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_key": self.target_key,
            "dependency_type": self.dependency_type,
            "reference": self.reference,
            "resolution": self.resolution.value,
            "resolution_target": self.resolution_target,
            "details": self.details,
        }


@dataclass
class Artifact:
    identity: ArtifactIdentity
    source_definition: dict[str, Any] = field(default_factory=dict)
    dependencies: list[Dependency] = field(default_factory=list)
    migration_strategy: Optional[str] = None
    migration_status: ArtifactMigrationStatus = ArtifactMigrationStatus.PLANNED
    validation_strategy: Optional[str] = None
    readiness_status: ReadinessStatus = ReadinessStatus.UNKNOWN
    migration_provider: Optional[str] = None
    disposition: Optional[MigrationDisposition] = None
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return self.identity.key

    @property
    def artifact_type(self) -> ArtifactType:
        return self.identity.artifact_type

    def source_hash(self) -> str:
        payload = json.dumps(
            {
                "identity": asdict(self.identity),
                "source_definition": self.source_definition,
            },
            sort_keys=True,
            default=str,
        )
        return sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": {
                "key": self.identity.key,
                "type": self.identity.artifact_type.value,
                "source_id": self.identity.source_id,
                "name": self.identity.name,
                "parent": self.identity.parent,
            },
            "source_definition": self.source_definition,
            "dependencies": [dependency.to_dict() for dependency in self.dependencies],
            "migration_strategy": self.migration_strategy,
            "migration_status": self.migration_status.value,
            "validation_strategy": self.validation_strategy,
            "readiness_status": self.readiness_status.value,
            "migration_provider": self.migration_provider,
            "disposition": self.disposition.value if self.disposition else None,
            "blockers": self.blockers,
            "warnings": self.warnings,
            "metadata": self.metadata,
            "source_hash": self.source_hash(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Artifact":
        identity_payload = payload["identity"]
        dependencies = [
            Dependency(
                target_key=item["target_key"],
                dependency_type=item["dependency_type"],
                reference=item["reference"],
                resolution=DependencyResolution(item.get("resolution", "UNRESOLVED")),
                resolution_target=item.get("resolution_target"),
                details=item.get("details", {}),
            )
            for item in payload.get("dependencies", [])
        ]
        return cls(
            identity=ArtifactIdentity(
                key=identity_payload["key"],
                artifact_type=ArtifactType(identity_payload["type"]),
                source_id=identity_payload.get("source_id"),
                name=identity_payload.get("name"),
                parent=identity_payload.get("parent"),
            ),
            source_definition=payload.get("source_definition", {}),
            dependencies=dependencies,
            migration_strategy=payload.get("migration_strategy"),
            migration_status=ArtifactMigrationStatus(
                payload.get("migration_status", "PLANNED")
            ),
            validation_strategy=payload.get("validation_strategy"),
            readiness_status=ReadinessStatus(payload.get("readiness_status", "UNKNOWN")),
            migration_provider=payload.get("migration_provider"),
            disposition=(
                MigrationDisposition(payload["disposition"])
                if payload.get("disposition")
                else None
            ),
            blockers=payload.get("blockers", []),
            warnings=payload.get("warnings", []),
            metadata=payload.get("metadata", {}),
        )


@dataclass
class MigrationPlan:
    migration_plan_id: str
    artifacts: list[Artifact] = field(default_factory=list)
    dependency_edges: list[dict[str, Any]] = field(default_factory=list)
    configuration: dict[str, Any] = field(default_factory=dict)
    lifecycle_state: str = "DISCOVERED"
    approved_at: Optional[str] = None
    approved_by: Optional[str] = None
    created_at: Optional[str] = None
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "migration_plan_id": self.migration_plan_id,
            "lifecycle_state": self.lifecycle_state,
            "created_at": self.created_at,
            "approved_at": self.approved_at,
            "approved_by": self.approved_by,
            "configuration": self.configuration,
            "dependency_edges": self.dependency_edges,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "blockers": self.blockers,
            "warnings": self.warnings,
        }

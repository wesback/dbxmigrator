from __future__ import annotations

from abc import ABC
from typing import Any, Iterable, Protocol

from .models import Artifact, ArtifactType
from .models import ReadinessStatus


class ArtifactHandler(ABC):
    """Extension interface for workspace, data, and governance artifacts."""

    artifact_types: tuple[ArtifactType, ...] = ()
    provider: str = "Databricks REST API"

    def discover(self, context: Any) -> Iterable[Artifact]:
        return []

    def export(self, context: Any, artifact: Artifact) -> dict[str, Any]:
        return artifact.source_definition

    def plan(self, context: Any, artifact: Artifact) -> Artifact:
        if artifact.disposition is None:
            artifact.disposition = artifact.metadata.get("default_disposition")
        if not artifact.migration_strategy:
            artifact.migration_strategy = "EXPORT_IMPORT"
        if not artifact.validation_strategy:
            artifact.validation_strategy = "VERIFY_TARGET_ARTIFACT"
        return artifact

    def migrate(self, context: Any, artifact: Artifact) -> dict[str, Any]:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement migration"
        )

    def validate_migration(self, context: Any, artifact: Artifact) -> bool:
        return True

    def analyze_dependencies(self, context: Any, artifact: Artifact) -> Artifact:
        return artifact

    def validate_readiness(self, context: Any, artifact: Artifact) -> bool:
        return (
            not artifact.blockers
            and artifact.readiness_status != ReadinessStatus.BLOCKED
        )


class ArtifactHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[ArtifactType, ArtifactHandler] = {}
        self._fallback = ArtifactHandler()

    def register(self, handler: ArtifactHandler) -> None:
        for artifact_type in handler.artifact_types:
            self._handlers[artifact_type] = handler

    def register_many(self, *handlers: ArtifactHandler) -> None:
        for handler in handlers:
            self.register(handler)

    def get(self, artifact_type: ArtifactType) -> ArtifactHandler:
        return self._handlers.get(artifact_type, self._fallback)

    def discover(self, context: Any) -> list[Artifact]:
        result: list[Artifact] = []
        seen: set[int] = set()
        for handler in [*dict.fromkeys(self._handlers.values())]:
            if id(handler) in seen:
                continue
            seen.add(id(handler))
            result.extend(handler.discover(context))

        unique: dict[str, Artifact] = {}
        for artifact in result:
            if artifact.key not in unique:
                unique[artifact.key] = artifact
        return list(unique.values())

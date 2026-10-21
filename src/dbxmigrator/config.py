from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Iterable


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError(
            "PyYAML is required to load YAML configuration; "
            "install the databricks extra or pass a JSON configuration."
        ) from exc
    with path.open("r", encoding="utf-8") as handle:
        result = yaml.safe_load(handle) or {}
    if not isinstance(result, dict):
        raise ValueError("Migration configuration must be a mapping")
    return result


@dataclass
class MigrationConfig:
    scope: str = "ALL"
    workspace_artifacts: bool = True
    data_enabled: bool = True
    unity_catalog_mode: str = "NONE"
    assessment_only: bool = False
    conflict_strategy: str = "FAIL"
    dry_run: bool = True
    source_workspace: dict[str, Any] = field(default_factory=dict)
    target_workspace: dict[str, Any] = field(default_factory=dict)
    include_artifact_types: list[str] = field(default_factory=list)
    exclude_artifact_types: list[str] = field(default_factory=list)
    storage: dict[str, Any] = field(default_factory=dict)
    uc: dict[str, Any] = field(default_factory=dict)
    policy: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MigrationConfig":
        migration = payload.get("migration", payload)
        data = migration.get("data", {})
        uc = migration.get("unity_catalog", {})
        source = payload.get("source") or {}
        target = payload.get("target") or {}
        uc_mode = str(
            uc.get("mode", "NONE") if isinstance(uc, dict) else uc
        ).upper()
        if "assessment_only" in migration:
            assessment_only = bool(migration["assessment_only"])
        else:
            assessment_only = uc_mode == "ASSESS" and not target
        if isinstance(data, dict):
            data_enabled = bool(data.get("enabled", True))
        else:
            data_enabled = bool(data)
        return cls(
            scope=str(migration.get("scope", "ALL")).upper(),
            workspace_artifacts=bool(migration.get("workspace_artifacts", True)),
            data_enabled=data_enabled,
            unity_catalog_mode=uc_mode,
            assessment_only=assessment_only,
            conflict_strategy=str(migration.get("conflict_strategy", "FAIL")).upper(),
            dry_run=bool(migration.get("dry_run", True)),
            source_workspace=source if isinstance(source, dict) else {},
            target_workspace=target if isinstance(target, dict) else {},
            include_artifact_types=[
                str(item).upper()
                for item in migration.get("include_artifact_types", [])
            ],
            exclude_artifact_types=[
                str(item).upper()
                for item in migration.get("exclude_artifact_types", [])
            ],
            storage=migration.get("storage", {}),
            uc=uc if isinstance(uc, dict) else {},
            policy=migration.get("policy", {}),
        )

    @classmethod
    def load(cls, source: str | Path | dict[str, Any]) -> "MigrationConfig":
        if isinstance(source, dict):
            return cls.from_dict(source)
        path = Path(source)
        if path.suffix.lower() in {".yaml", ".yml"}:
            payload = _load_yaml(path)
        else:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        return cls.from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "migration": {
                "scope": self.scope,
                "workspace_artifacts": self.workspace_artifacts,
                "data": {"enabled": self.data_enabled},
                "unity_catalog": {"mode": self.unity_catalog_mode},
                "assessment_only": self.assessment_only,
                "conflict_strategy": self.conflict_strategy,
                "dry_run": self.dry_run,
                "include_artifact_types": self.include_artifact_types,
                "exclude_artifact_types": self.exclude_artifact_types,
                "storage": self.storage,
                "uc": self.uc,
                "policy": self.policy,
            },
            "source": self.source_workspace,
            "target": self.target_workspace,
        }

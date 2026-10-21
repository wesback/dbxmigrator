from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from .models import Artifact, MigrationPlan


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MigrationStore:
    def __init__(self, root: str | Path | None = None) -> None:
        if root is None:
            root = "/Workspace/Shared/dbxmigrator/plans"

        requested_root = self.normalize_root(root)
        candidates = [requested_root]
        if str(requested_root).startswith("/dbfs/"):
            relative = str(requested_root)[len("/dbfs/") :]
            candidates.insert(
                0,
                Path("/Workspace/Shared/dbxmigrator") / relative,
            )

        candidates.extend([
            Path("/Workspace/Shared/dbxmigrator/plans"),
            Path("/tmp/dbxmigrator-plans"),
        ])

        selected = None
        last_error = None
        seen = set()
        for candidate in candidates:
            candidate = Path(candidate)
            if str(candidate) in seen:
                continue
            seen.add(str(candidate))
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                probe = candidate / ".write-test"
                with probe.open("w", encoding="utf-8") as handle:
                    handle.write("ok")
                probe.unlink()
                selected = candidate
                break
            except (OSError, PermissionError) as exc:
                last_error = exc

        if selected is None:
            raise RuntimeError(
                "No migration plan store location is writable. "
                f"Configured root: {requested_root}. "
                f"Last filesystem error: {last_error}"
            )

        self.requested_root = requested_root
        self.root = selected
        self.fallback_used = selected != requested_root

    @staticmethod
    def normalize_root(root: str | Path) -> Path:
        value = str(root)
        if value.startswith("dbfs:/"):
            relative = value[len("dbfs:/") :].lstrip("/")
            if relative:
                return Path("/Workspace/Shared/dbxmigrator") / relative
            return Path("/Workspace/Shared/dbxmigrator/plans")
        if value.startswith("/dbfs/"):
            relative = value[len("/dbfs/") :].lstrip("/")
            if relative:
                return Path("/Workspace/Shared/dbxmigrator") / relative
            return Path("/Workspace/Shared/dbxmigrator/plans")
        return Path(value)

    def create_plan(self, configuration: dict[str, Any]) -> MigrationPlan:
        plan_id = str(uuid4())
        plan = MigrationPlan(
            migration_plan_id=plan_id,
            lifecycle_state="DISCOVERED",
            created_at=utc_now(),
            configuration=configuration,
        )
        self.save_plan(plan)
        return plan

    def plan_path(self, migration_plan_id: str) -> Path:
        return self.root / migration_plan_id / "migration_plan.json"

    def save_plan(self, plan: MigrationPlan) -> Path:
        plan_path = self.plan_path(plan.migration_plan_id)
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        with plan_path.open("w", encoding="utf-8") as handle:
            json.dump(plan.to_dict(), handle, indent=2, sort_keys=True)
        return plan_path

    def load_plan(self, migration_plan_id: str) -> MigrationPlan:
        plan_path = self.plan_path(migration_plan_id)
        with plan_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return MigrationPlan(
            migration_plan_id=payload["migration_plan_id"],
            artifacts=[
                Artifact.from_dict(item) for item in payload.get("artifacts", [])
            ],
            dependency_edges=payload.get("dependency_edges", []),
            configuration=payload.get("configuration", {}),
            lifecycle_state=payload.get("lifecycle_state", "DISCOVERED"),
            approved_at=payload.get("approved_at"),
            approved_by=payload.get("approved_by"),
            created_at=payload.get("created_at"),
            blockers=payload.get("blockers", []),
            warnings=payload.get("warnings", []),
        )

    def append_event(self, migration_plan_id: str, event: dict[str, Any]) -> Path:
        ledger_path = self.root / migration_plan_id / "events.jsonl"
        event = dict(event)
        event.setdefault("timestamp", utc_now())
        with ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
        return ledger_path

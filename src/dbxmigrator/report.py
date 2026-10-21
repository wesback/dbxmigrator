from __future__ import annotations

from typing import Any, Iterable


def render_summary_table(report: dict[str, Any], limit: int | None = None) -> str:
    rows = report["artifacts"]
    if limit is not None:
        rows = rows[:limit]
    lines = [
        "ARTIFACT MIGRATION READINESS",
        "ARTIFACT | MIGRATION | READINESS | DISPOSITION | TYPE",
        "-" * 100,
    ]
    for artifact in rows:
        identity = artifact["identity"]
        name = identity.get("name") or identity["key"]
        lines.append(
            f"{name} | {artifact['migration_status']} | "
            f"{artifact['readiness_status']} | "
            f"{artifact['disposition'] or '-'} | {identity['type']}"
        )
    lines.extend([
        "",
        f"MIGRATION PLAN ID: {report['migration_plan_id']}",
        f"LIFECYCLE STATE: {report['lifecycle_state']}",
        "NO CHANGES HAVE BEEN MADE."
        if report["configuration"]["migration"]["dry_run"]
        else "MUTATING LIFECYCLE HAS BEEN REQUESTED.",
    ])
    return "\n".join(lines)

from dbxmigrator.models import (
    Artifact,
    ArtifactIdentity,
    ArtifactType,
    Dependency,
    DependencyResolution,
)


def test_artifact_identity_and_dependency_are_serializable():
    artifact = Artifact(
        identity=ArtifactIdentity(
            key="NOTEBOOK:/Shared/test",
            artifact_type=ArtifactType.NOTEBOOK,
            name="/Shared/test",
        ),
        dependencies=[
            Dependency(
                target_key="HIVE_TABLE:raw.customer",
                dependency_type="HIVE_TABLE",
                reference="raw.customer",
                resolution=DependencyResolution.UNRESOLVED,
            )
        ],
    )

    payload = artifact.to_dict()
    restored = Artifact.from_dict(payload)

    assert restored.key == artifact.key
    assert restored.dependencies[0].reference == "raw.customer"
    assert restored.dependencies[0].resolution == DependencyResolution.UNRESOLVED

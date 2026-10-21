import pytest

from dbxmigrator.auth import build_workspace_client


class FakeWorkspaceClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_default_auth_builds_sdk_client_for_source():
    client = build_workspace_client(
        {
            "host": "https://adb-SOURCE.azuredatabricks.net",
            "auth": {"type": "DEFAULT"},
        },
        workspace_client_class=FakeWorkspaceClient,
    )

    assert client.kwargs["host"] == "https://adb-SOURCE.azuredatabricks.net"


def test_profile_auth_builds_sdk_client_for_target():
    client = build_workspace_client(
        {
            "host": "https://adb-TARGET.azuredatabricks.net",
            "auth": {"type": "PROFILE", "profile": "target-workspace"},
        },
        workspace_client_class=FakeWorkspaceClient,
    )

    assert client.kwargs == {
        "profile": "target-workspace",
        "host": "https://adb-TARGET.azuredatabricks.net",
    }


def test_token_secret_resolves_target_token_without_exposing_it():
    resolved = {}

    def resolver(scope, key):
        resolved["scope"] = scope
        resolved["key"] = key
        return "resolved-token"

    client = build_workspace_client(
        {
            "host": "https://adb-TARGET.azuredatabricks.net",
            "auth": {
                "type": "TOKEN_SECRET",
                "secret_scope": "dbxmigrator",
                "secret_key": "target-token",
            },
        },
        secret_resolver=resolver,
        workspace_client_class=FakeWorkspaceClient,
    )

    assert client.kwargs["token"] == "resolved-token"
    assert resolved == {
        "scope": "dbxmigrator",
        "key": "target-token",
    }


@pytest.mark.parametrize("credential", ["token", "access_token", "password", "client_secret"])
def test_direct_credentials_are_rejected(credential):
    with pytest.raises(ValueError, match="[Cc]redentials"):
        build_workspace_client(
            {credential: "must-not-be-used"},
            workspace_client_class=FakeWorkspaceClient,
        )

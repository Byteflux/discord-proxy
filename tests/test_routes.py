import pytest

from discord_proxy.rest.routes import classify


@pytest.mark.parametrize(
    "path, template, ids",
    [
        (
            "/api/v9/channels/123456789012345678/messages/987654321098765432",
            "/channels/{channel_id}/messages/{message_id}",
            {"channel_id": "123456789012345678", "message_id": "987654321098765432"},
        ),
        (
            "/api/v10/channels/123456789012345678/messages",
            "/channels/{channel_id}/messages",
            {"channel_id": "123456789012345678"},
        ),
        (
            "/api/v9/guilds/111111111111111111/members/222222222222222222",
            "/guilds/{guild_id}/members/{user_id}",
            {"guild_id": "111111111111111111", "user_id": "222222222222222222"},
        ),
        (
            "/api/v9/users/@me/guilds",
            "/users/@me/guilds",
            {},
        ),
        (
            "/api/v9/users/333333333333333333",
            "/users/{user_id}",
            {"user_id": "333333333333333333"},
        ),
        (
            "/api/v9/channels/123456789012345678/messages/987654321098765432/ack",
            "/channels/{channel_id}/messages/{message_id}/ack",
            {"channel_id": "123456789012345678", "message_id": "987654321098765432"},
        ),
        (
            "/api/v9/channels/123456789012345678/summaries",
            "/channels/{channel_id}/summaries",
            {"channel_id": "123456789012345678"},
        ),
        (
            "/api/v9/channels/123456789012345678/threads/search",
            "/channels/{channel_id}/threads/search",
            {"channel_id": "123456789012345678"},
        ),
        (
            "/api/v9/guilds/111111111111111111/members/@me",
            "/guilds/{guild_id}/members/{user_id}",
            {"guild_id": "111111111111111111", "user_id": "@me"},
        ),
        (
            "/api/v9/guilds/111111111111111111/roles/member-counts",
            "/guilds/{guild_id}/roles/member-counts",
            {"guild_id": "111111111111111111"},
        ),
        (
            "/api/v9/guilds/111111111111111111/onboarding",
            "/guilds/{guild_id}/onboarding",
            {"guild_id": "111111111111111111"},
        ),
        (
            "/api/v9/users/@me/billing/subscriptions/444444444444444444/preview",
            "/users/@me/billing/subscriptions/{subscription_id}/preview",
            {"subscription_id": "444444444444444444"},
        ),
        (
            "/api/v9/users/@me/applications/555555555555555555/entitlements",
            "/users/@me/applications/{application_id}/entitlements",
            {"application_id": "555555555555555555"},
        ),
        (
            "/api/v9/users/@me/settings-proto/1",
            "/users/@me/settings-proto/{version}",
            {"version": "1"},
        ),
        (
            "/api/v10/users/@me/harvest",
            "/users/@me/harvest",
            {},
        ),
        (
            "/api/v9/users/333333333333333333/profile",
            "/users/{user_id}/profile",
            {"user_id": "333333333333333333"},
        ),
        (
            "/api/v9/store/published-listings/skus/666666666666666666/subscription-plans",
            "/store/published-listings/skus/{sku_id}/subscription-plans",
            {"sku_id": "666666666666666666"},
        ),
        (
            "/api/v9/quests/@me",
            "/quests/@me",
            {},
        ),
        (
            "/api/v9/quests/@me/claimed",
            "/quests/@me/claimed",
            {},
        ),
        (
            "/api/v9/science",
            "/science",
            {},
        ),
        (
            "/api/v9/metrics/v2",
            "/metrics/v2",
            {},
        ),
    ],
)
def test_classify_known_routes(path: str, template: str, ids: dict[str, str]) -> None:
    match = classify(path)
    assert match is not None
    assert match.template == template
    assert match.ids == ids
    assert match.classified is True


@pytest.mark.parametrize(
    "path, expected_template",
    [
        (
            "/api/v9/users/@me/settings",
            "/users/@me/settings",
        ),
        (
            "/api/v9/guilds/123456789012345678/bans",
            "/guilds/{id}/bans",
        ),
        (
            "/api/v9/guilds/123456789012345678/roles",
            "/guilds/{id}/roles",
        ),
        (
            "/api/v9/channels/123456789012345678/pins/987654321098765432",
            "/channels/{id}/pins/{id}",
        ),
        (
            "/api/v10/gateway",
            "/gateway",
        ),
    ],
)
def test_classify_unclassified_routes(path: str, expected_template: str) -> None:
    match = classify(path)
    assert match is not None
    assert match.template == expected_template
    assert match.ids == {}
    assert match.classified is False


def test_classify_non_api_path_returns_none() -> None:
    assert classify("/assets/foo.js") is None
    assert classify("/login") is None


def test_classify_non_versioned_api_returns_none() -> None:
    # /api/ without version prefix should not match the versioned pattern
    assert classify("/api/channels/123456789012345678/messages") is None


def test_snowflake_not_templated_in_short_ids() -> None:
    # IDs shorter than 17 digits stay literal (not snowflakes)
    match = classify("/api/v9/some/12345/path")
    assert match is not None
    assert match.template == "/some/12345/path"
    assert match.classified is False

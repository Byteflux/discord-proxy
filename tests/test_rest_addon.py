import json
from typing import Any

from mitmproxy.test import tflow, tutils

from discord_proxy.nats_client import NatsPublisher
from discord_proxy.rest.addon import RestAddon


class _FakePublisher(NatsPublisher):
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any]]] = []

    def publish(self, subject: str, envelope: dict[str, Any]) -> None:
        self.published.append((subject, envelope))


def _make_flow(
    path: str,
    host: str = "discord.com",
    method: str = "GET",
    status: int = 200,
    body: dict[str, Any] | None = None,
) -> Any:
    flow = tflow.tflow()
    flow.request.host = host
    flow.request.path = path
    flow.request.method = method
    flow.response = tutils.tresp()
    flow.response.status_code = status
    flow.response.headers["content-type"] = "application/json"
    flow.response.content = json.dumps(body or {}).encode()
    return flow


def test_classified_route_publishes_to_discord_rest() -> None:
    pub = _FakePublisher()
    addon = RestAddon(pub)
    flow = _make_flow("/api/v9/channels/123456789012345678/messages")
    addon.request(flow)
    addon.response(flow)

    assert len(pub.published) == 1
    subject, envelope = pub.published[0]
    assert subject == "discord.rest.GET.channels.channel_id.messages"
    assert envelope["payload"]["classified"] is True
    assert envelope["payload"]["ids"] == {"channel_id": "123456789012345678"}


def test_unclassified_route_publishes_to_discord_rest_unclassified() -> None:
    pub = _FakePublisher()
    addon = RestAddon(pub)
    flow = _make_flow("/api/v9/users/@me/settings")
    addon.request(flow)
    addon.response(flow)

    assert len(pub.published) == 1
    subject, envelope = pub.published[0]
    assert subject == "discord.rest.unclassified.GET.users.@me.settings"
    assert envelope["payload"]["classified"] is False
    assert envelope["payload"]["ids"] == {}
    assert envelope["guild_id"] is None
    assert envelope["channel_id"] is None
    assert envelope["user_id"] is None


def test_non_api_path_not_published() -> None:
    pub = _FakePublisher()
    addon = RestAddon(pub)
    flow = _make_flow("/assets/bundle.js")
    addon.request(flow)
    addon.response(flow)
    assert len(pub.published) == 0


def test_body_ids_supplement_missing_envelope_ids() -> None:
    pub = _FakePublisher()
    addon = RestAddon(pub)
    flow = _make_flow(
        "/api/v9/users/@me/billing/subscriptions",
        body={"id": "991914835912695909", "user_id": "127637528961482753", "type": 1},
    )
    addon.request(flow)
    addon.response(flow)

    assert len(pub.published) == 1
    _, envelope = pub.published[0]
    assert envelope["user_id"] == "127637528961482753"
    assert envelope["guild_id"] is None
    assert envelope["channel_id"] is None


def test_body_ids_do_not_override_url_ids() -> None:
    pub = _FakePublisher()
    addon = RestAddon(pub)
    flow = _make_flow(
        "/api/v9/guilds/111111111111111111/onboarding-responses",
        method="PUT",
        body={"guild_id": "999999999999999999", "user_id": "127637528961482753"},
    )
    addon.request(flow)
    addon.response(flow)

    assert len(pub.published) == 1
    _, envelope = pub.published[0]
    assert envelope["guild_id"] == "111111111111111111"  # from URL, not body
    assert envelope["user_id"] == "127637528961482753"  # from body (not in URL)


def test_query_string_stripped_from_route_template() -> None:
    pub = _FakePublisher()
    addon = RestAddon(pub)
    flow = _make_flow("/api/v9/channels/123456789012345678/messages?limit=10")
    addon.request(flow)
    addon.response(flow)

    assert len(pub.published) == 1
    subject, envelope = pub.published[0]
    assert subject == "discord.rest.GET.channels.channel_id.messages"
    assert envelope["payload"]["classified"] is True
    assert envelope["payload"]["route_template"] == "/channels/{channel_id}/messages"
    assert envelope["payload"]["path"] == "/api/v9/channels/123456789012345678/messages"
    assert envelope["payload"]["query"] == "limit=10"


def test_query_string_on_unclassified_route() -> None:
    pub = _FakePublisher()
    addon = RestAddon(pub)
    flow = _make_flow("/api/v9/users/@me/settings?foo=bar&baz=qux")
    addon.request(flow)
    addon.response(flow)

    assert len(pub.published) == 1
    subject, envelope = pub.published[0]
    assert subject == "discord.rest.unclassified.GET.users.@me.settings"
    assert envelope["payload"]["route_template"] == "/users/@me/settings"
    assert envelope["payload"]["query"] == "foo=bar&baz=qux"


def test_non_discord_host_not_published() -> None:
    pub = _FakePublisher()
    addon = RestAddon(pub)
    flow = _make_flow("/api/v9/channels/123456789012345678/messages", host="example.com")
    addon.request(flow)
    addon.response(flow)
    assert len(pub.published) == 0

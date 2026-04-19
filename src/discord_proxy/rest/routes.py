import re
from typing import NamedTuple

# Each entry: (pattern, template, group-names-in-order)
_ROUTES: list[tuple[re.Pattern[str], str, list[str]]] = []


def _add(pattern: str, template: str, groups: list[str]) -> None:
    _ROUTES.append((re.compile(pattern), template, groups))


# Most-specific first.
_add(
    r"^/api/v\d+/channels/(\d+)/messages/(\d+)/reactions/([^/]+)/(\d+)$",
    "/channels/{channel_id}/messages/{message_id}/reactions/{emoji}/{user_id}",
    ["channel_id", "message_id", "emoji", "user_id"],
)
_add(
    r"^/api/v\d+/channels/(\d+)/messages/(\d+)/reactions/([^/]+)$",
    "/channels/{channel_id}/messages/{message_id}/reactions/{emoji}",
    ["channel_id", "message_id", "emoji"],
)
_add(
    r"^/api/v\d+/channels/(\d+)/messages/(\d+)/reactions$",
    "/channels/{channel_id}/messages/{message_id}/reactions",
    ["channel_id", "message_id"],
)
_add(
    r"^/api/v\d+/channels/(\d+)/messages/(\d+)$",
    "/channels/{channel_id}/messages/{message_id}",
    ["channel_id", "message_id"],
)
_add(
    r"^/api/v\d+/channels/(\d+)/messages$",
    "/channels/{channel_id}/messages",
    ["channel_id"],
)
_add(
    r"^/api/v\d+/channels/(\d+)/typing$",
    "/channels/{channel_id}/typing",
    ["channel_id"],
)
_add(
    r"^/api/v\d+/channels/(\d+)$",
    "/channels/{channel_id}",
    ["channel_id"],
)
_add(
    r"^/api/v\d+/guilds/(\d+)/members/(\d+)$",
    "/guilds/{guild_id}/members/{user_id}",
    ["guild_id", "user_id"],
)
_add(
    r"^/api/v\d+/guilds/(\d+)/members$",
    "/guilds/{guild_id}/members",
    ["guild_id"],
)
_add(
    r"^/api/v\d+/guilds/(\d+)/channels$",
    "/guilds/{guild_id}/channels",
    ["guild_id"],
)
_add(
    r"^/api/v\d+/guilds/(\d+)$",
    "/guilds/{guild_id}",
    ["guild_id"],
)
_add(
    r"^/api/v\d+/users/(\d+|@me)$",
    "/users/{user_id}",
    ["user_id"],
)


class RouteMatch(NamedTuple):
    template: str
    ids: dict[str, str]


def classify(path: str) -> RouteMatch | None:
    """Match a Discord REST API path to a route template.

    Returns None if the path is not a recognized Discord API path.
    """
    for pattern, template, groups in _ROUTES:
        m = pattern.match(path)
        if m:
            return RouteMatch(template, dict(zip(groups, m.groups(), strict=False)))
    return None

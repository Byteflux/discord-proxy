import re
from typing import NamedTuple

# Each entry: (pattern, template, group-names-in-order)
_ROUTES: list[tuple[re.Pattern[str], str, list[str]]] = []

_API_VERSION_RE = re.compile(r"^/api/v\d+")
_SNOWFLAKE_RE = re.compile(r"^\d{17,20}$")


def _add(pattern: str, template: str, groups: list[str]) -> None:
    _ROUTES.append((re.compile(pattern), template, groups))


def _generic_template(path: str) -> str | None:
    """Strip the /api/vN prefix and replace snowflake IDs with {id}."""
    m = _API_VERSION_RE.match(path)
    if not m:
        return None
    rest = path[m.end() :]
    segments = rest.split("/")
    return "/".join("{id}" if _SNOWFLAKE_RE.match(s) else s for s in segments)


# Most-specific first.

# Channels
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
    r"^/api/v\d+/channels/(\d+)/messages/(\d+)/ack$",
    "/channels/{channel_id}/messages/{message_id}/ack",
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
    r"^/api/v\d+/channels/(\d+)/threads/search$",
    "/channels/{channel_id}/threads/search",
    ["channel_id"],
)
_add(
    r"^/api/v\d+/channels/(\d+)/follower-stats$",
    "/channels/{channel_id}/follower-stats",
    ["channel_id"],
)
_add(
    r"^/api/v\d+/channels/(\d+)/post-data$",
    "/channels/{channel_id}/post-data",
    ["channel_id"],
)
_add(
    r"^/api/v\d+/channels/(\d+)/summaries$",
    "/channels/{channel_id}/summaries",
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

# Guilds
_add(
    r"^/api/v\d+/guilds/(\d+)/roles/member-counts$",
    "/guilds/{guild_id}/roles/member-counts",
    ["guild_id"],
)
_add(
    r"^/api/v\d+/guilds/(\d+)/members/(\d+|@me)$",
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
    r"^/api/v\d+/guilds/(\d+)/onboarding$",
    "/guilds/{guild_id}/onboarding",
    ["guild_id"],
)
_add(
    r"^/api/v\d+/guilds/(\d+)/onboarding-responses$",
    "/guilds/{guild_id}/onboarding-responses",
    ["guild_id"],
)
_add(
    r"^/api/v\d+/guilds/(\d+)/powerups$",
    "/guilds/{guild_id}/powerups",
    ["guild_id"],
)
_add(
    r"^/api/v\d+/guilds/(\d+)$",
    "/guilds/{guild_id}",
    ["guild_id"],
)

# Users (@me)
_add(
    r"^/api/v\d+/users/@me/billing/subscriptions/(\d+)/preview$",
    "/users/@me/billing/subscriptions/{subscription_id}/preview",
    ["subscription_id"],
)
_add(
    r"^/api/v\d+/users/@me/applications/(\d+)/entitlements$",
    "/users/@me/applications/{application_id}/entitlements",
    ["application_id"],
)
_add(
    r"^/api/v\d+/users/@me/guilds/premium/subscription-slots$",
    "/users/@me/guilds/premium/subscription-slots",
    [],
)
_add(
    r"^/api/v\d+/users/@me/video-filters/assets$",
    "/users/@me/video-filters/assets",
    [],
)
_add(
    r"^/api/v\d+/users/@me/billing/payment-sources$",
    "/users/@me/billing/payment-sources",
    [],
)
_add(
    r"^/api/v\d+/users/@me/billing/subscriptions$",
    "/users/@me/billing/subscriptions",
    [],
)
_add(
    r"^/api/v\d+/users/@me/settings-proto/(\d+)$",
    "/users/@me/settings-proto/{version}",
    ["version"],
)
_add(
    r"^/api/v\d+/users/@me/collectibles-purchases$",
    "/users/@me/collectibles-purchases",
    [],
)
_add(
    r"^/api/v\d+/users/@me/entitlements$",
    "/users/@me/entitlements",
    [],
)
_add(
    r"^/api/v\d+/users/@me/harvest$",
    "/users/@me/harvest",
    [],
)
_add(
    r"^/api/v\d+/users/@me/guilds$",
    "/users/@me/guilds",
    [],
)

# Users (by ID)
_add(
    r"^/api/v\d+/users/(\d+)/profile$",
    "/users/{user_id}/profile",
    ["user_id"],
)
_add(
    r"^/api/v\d+/users/(\d+)/application-identities$",
    "/users/{user_id}/application-identities",
    ["user_id"],
)
_add(
    r"^/api/v\d+/users/(\d+|@me)$",
    "/users/{user_id}",
    ["user_id"],
)

# Store
_add(
    r"^/api/v\d+/store/published-listings/skus/(\d+)/subscription-plans$",
    "/store/published-listings/skus/{sku_id}/subscription-plans",
    ["sku_id"],
)

# Quests
_add(
    r"^/api/v\d+/quests/@me/claimed$",
    "/quests/@me/claimed",
    [],
)
_add(
    r"^/api/v\d+/quests/@me$",
    "/quests/@me",
    [],
)

# Telemetry
_add(
    r"^/api/v\d+/metrics/v2$",
    "/metrics/v2",
    [],
)
_add(
    r"^/api/v\d+/science$",
    "/science",
    [],
)


class RouteMatch(NamedTuple):
    template: str
    ids: dict[str, str]
    classified: bool


def classify(path: str) -> RouteMatch | None:
    """Match a Discord REST API path to a route template.

    Returns a classified RouteMatch when the path matches a known route,
    an unclassified RouteMatch with a generic template for other /api/vN/ paths,
    or None for paths that are not Discord versioned API paths.
    """
    for pattern, template, groups in _ROUTES:
        m = pattern.match(path)
        if m:
            return RouteMatch(template, dict(zip(groups, m.groups(), strict=False)), True)
    generic = _generic_template(path)
    if generic is None:
        return None
    return RouteMatch(generic, {}, False)

import logging

from discord_proxy.config import from_file_and_env
from discord_proxy.gateway.addon import GatewayAddon
from discord_proxy.nats_client import NatsPublisher
from discord_proxy.rest.addon import RestAddon

cfg = from_file_and_env()
logging.basicConfig(level=cfg.log_level.upper())

_publisher = NatsPublisher()
_gateway = GatewayAddon(_publisher)
_rest = RestAddon(_publisher)


class _LifecycleAddon:
    async def running(self) -> None:
        await _publisher.connect(cfg.nats_url)
        logging.getLogger(__name__).info("Connected to NATS at %s", cfg.nats_url)

    async def done(self) -> None:
        await _publisher.close()


addons = [_LifecycleAddon(), _gateway, _rest]

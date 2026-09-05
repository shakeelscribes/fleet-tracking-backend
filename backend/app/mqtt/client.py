"""In-process asyncio MQTT subscriber (decision #5).

Runs as a background task started by the FastAPI lifespan. Never raises:
broker outages are logged and retried with backoff, bad messages are discarded
by the handler. Swap point: replace with a standalone worker container later -
the handler contract stays identical.
"""

import asyncio
import contextlib
import logging

from aiomqtt import Client, MqttError, TLSParameters

from app.core.config import settings
from app.db.session import async_session_factory
from app.mqtt.handler import handle_gps_message
from app.mqtt.payload import parse_payload, parse_topic

logger = logging.getLogger("app.mqtt.client")

RECONNECT_SECONDS = 5
SUBSCRIBE_QOS = 1  # decision: QoS 1 - at least once; handler dedups via latest-only upsert


def mqtt_client_kwargs() -> dict[str, object]:
    """Connection kwargs shared by the subscriber and the simulator.

    TLS (MQTT_TLS=true) is required by cloud brokers like HiveMQ Cloud (8883);
    TLSParameters() with defaults validates against system CAs, which covers
    HiveMQ's Let's Encrypt certificates."""
    kwargs: dict[str, object] = {}
    if settings.MQTT_TLS:
        kwargs["tls_params"] = TLSParameters()
    return kwargs


def _subscription_topic() -> str:
    return f"{settings.MQTT_TOPIC_PREFIX}/+/gps"


async def _process_message(topic: str, payload: bytes) -> None:
    """Parse + store one message; every failure mode ends in a log, not an exception."""
    vehicle_id = parse_topic(topic, prefix=settings.MQTT_TOPIC_PREFIX)
    if vehicle_id is None:
        logger.warning("Discarding message on unexpected topic: %s", topic)
        return
    message = parse_payload(payload)
    if message is None:
        return  # already logged by the parser
    if message.vehicle_id != vehicle_id:
        logger.warning(
            "Discarding GPS fix: topic vehicle_id=%s != payload vehicle_id=%s",
            vehicle_id,
            message.vehicle_id,
        )
        return
    async with async_session_factory() as session:
        await handle_gps_message(session, message)


async def _run_client() -> None:
    """One broker connection: subscribe and consume until the connection drops."""
    async with Client(
        settings.MQTT_HOST,
        port=settings.MQTT_PORT,
        username=settings.MQTT_USERNAME or None,
        password=settings.MQTT_PASSWORD or None,
        **mqtt_client_kwargs(),
    ) as client:
        logger.info(
            "MQTT connected to %s:%s, subscribing %r (QoS %s)",
            settings.MQTT_HOST,
            settings.MQTT_PORT,
            _subscription_topic(),
            SUBSCRIBE_QOS,
        )
        await client.subscribe(_subscription_topic(), qos=SUBSCRIBE_QOS)
        async for message in client.messages:
            topic = str(message.topic)
            payload = bytes(message.payload)
            try:
                await _process_message(topic, payload)
            except Exception:  # noqa: BLE001 - the loop must survive any bug
                logger.exception("Unhandled error while processing message on %s", topic)


async def mqtt_subscriber_task() -> None:
    """Reconnect loop; runs until cancelled. Logs broker outages, retries forever."""
    while True:
        try:
            await _run_client()
        except MqttError as exc:
            logger.warning(
                "MQTT connection lost (%s) - reconnecting in %ss", exc, RECONNECT_SECONDS
            )
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.sleep(RECONNECT_SECONDS)
        except asyncio.CancelledError:
            logger.info("MQTT subscriber stopped")
            raise

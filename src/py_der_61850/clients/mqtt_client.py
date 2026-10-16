import time

import paho.mqtt.client as mqtt
from loguru import logger


class MqttClient:

    def __init__(
        self,
        user: str,
        password: str | None,
        host: str,
        port: int,
        topics: list[str],
        client: mqtt.Client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2),  # type: ignore
    ):
        self.client = client
        self.user = user
        self.password = password
        self.host = host
        self.port = port
        self.topics = topics

    def _on_subscribe(self, client, userdata, mid, reason_code_list, properties):
        if reason_code_list[0].is_failure:
            logger.error(f"Broker rejected your subscription: {reason_code_list[0]}")
        else:
            logger.info(f"Broker granted QoS: {reason_code_list[0].value}")

    def _on_unsubscribe(self, client, userdata, mid, reason_code_list, properties):
        if len(reason_code_list) == 0 or not reason_code_list[0].is_failure:
            logger.debug("Unsubscribe succeeded (if SUBACK is received in MQTTv3, it means success)")
        else:
            logger.error(f"Broker responded with failure: {reason_code_list[0]}")
        self.client.disconnect()

    def _on_disconnect(self, client, userdata, flags, reason_code, properties, other=None):
        if reason_code != 0:
            logger.warning(f"Unexpected disconnection from broker (rc={reason_code})")
        else:
            logger.info("Disconnected from broker intentionally")

    def _on_connect_fail(self, client, userdata):
        logger.error("Failed to establish TCP connection to the broker (connect_fail)")

    def connect(self, on_connect=None, on_message=None):
        self.client.username_pw_set(self.user, self.password)
        if on_connect is not None:
            self.client.on_connect = on_connect
        if on_message is not None:
            self.client.on_message = on_message

        self.client.on_subscribe = self._on_subscribe
        self.client.on_unsubscribe = self._on_unsubscribe
        self.client.on_disconnect = self._on_disconnect
        self.client.on_connect_fail = self._on_connect_fail

        while True:
            try:
                self.client.connect(self.host, self.port, 60)
                self.client.loop_start()
                logger.info("Connected to MQTT broker")
                break
            except (ConnectionRefusedError, OSError) as e:
                logger.error(f"Connection failed: {e}. Retrying in 5 seconds...")
                time.sleep(5)

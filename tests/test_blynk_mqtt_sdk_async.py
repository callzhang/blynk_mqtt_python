#!/usr/bin/env python3
import asyncio
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path


class FakeMQTTClient:
    instances = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.callback = None
        self.published = []
        self.subscribed = []
        self.disconnected = False
        FakeMQTTClient.instances.append(self)

    def set_callback(self, callback):
        self.callback = callback

    def connect(self):
        return None

    def disconnect(self):
        self.disconnected = True
        return None

    def subscribe(self, topic, qos=0):
        self.subscribed.append((topic, qos))

    def publish(self, topic, payload, qos=0):
        self.published.append((topic, payload, qos))

    def check_msg(self):
        return None


class FakeMQTTException(Exception):
    pass


class FakeSSLContext:
    def __init__(self, protocol):
        self.protocol = protocol
        self.verify_mode = None

    def load_verify_locations(self, cafile):
        self.cafile = cafile


def load_sdk_with_micropython_fakes():
    root = Path(__file__).resolve().parents[1]
    sdk_path = root / "lib" / "blynk_mqtt_sdk_async.py"

    fake_micropython = types.ModuleType("micropython")
    fake_micropython.const = lambda value: value

    fake_machine = types.ModuleType("machine")
    fake_machine.reset = lambda: None

    fake_ssl = types.ModuleType("ssl")
    fake_ssl.PROTOCOL_TLS_CLIENT = object()
    fake_ssl.CERT_REQUIRED = object()
    fake_ssl.CERT_NONE = object()
    fake_ssl.SSLContext = FakeSSLContext

    fake_umqtt = types.ModuleType("umqtt")
    fake_umqtt_simple = types.ModuleType("umqtt.simple")
    fake_umqtt_simple.MQTTClient = FakeMQTTClient
    fake_umqtt_simple.MQTTException = FakeMQTTException

    originals = {
        name: sys.modules.get(name)
        for name in ("micropython", "machine", "uasyncio", "ssl", "umqtt", "umqtt.simple")
    }
    sys.modules["micropython"] = fake_micropython
    sys.modules["machine"] = fake_machine
    sys.modules["uasyncio"] = asyncio
    sys.modules["ssl"] = fake_ssl
    sys.modules["umqtt"] = fake_umqtt
    sys.modules["umqtt.simple"] = fake_umqtt_simple

    module_name = "blynk_mqtt_sdk_async_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, sdk_path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        for name, original in originals.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
    return module


class BlynkMQTTAsyncSDKTest(unittest.TestCase):
    def setUp(self):
        FakeMQTTClient.instances.clear()
        self.sdk = load_sdk_with_micropython_fakes()

    def test_default_authentication_matches_current_blynk_mqtt_api(self):
        client = self.sdk.BlynkMQTT("token", ssl=False, log_func=lambda message: None)
        client._running = True

        connected = asyncio.run(client._mqtt_connect())

        mqtt = FakeMQTTClient.instances[-1]
        self.assertTrue(connected)
        self.assertEqual(mqtt.args[1], "blynk.cloud")
        self.assertEqual(mqtt.kwargs["port"], 1883)
        self.assertEqual(mqtt.kwargs["user"], "device")
        self.assertEqual(mqtt.kwargs["password"], "token")
        self.assertEqual(mqtt.kwargs["keepalive"], 45)
        self.assertEqual(mqtt.args[0], "")

    def test_connect_subscribes_downlink_and_publishes_device_info(self):
        client = self.sdk.BlynkMQTT(
            "token",
            ssl=False,
            template_id="TMPL123",
            firmware_version="test-fw",
            log_func=lambda message: None,
        )
        client._running = True

        connected = asyncio.run(client._mqtt_connect())

        mqtt = FakeMQTTClient.instances[-1]
        self.assertTrue(connected)
        self.assertIn(("downlink/#", 0), mqtt.subscribed)
        info_messages = [item for item in mqtt.published if item[0] == "info/mcu"]
        self.assertEqual(len(info_messages), 1)
        payload = json.loads(info_messages[0][1])
        self.assertEqual(payload["tmpl"], "TMPL123")
        self.assertEqual(payload["type"], "TMPL123")
        self.assertEqual(payload["ver"], "test-fw")

    def test_datastream_publish_topics_match_current_blynk_mqtt_api(self):
        client = self.sdk.BlynkMQTT("token", ssl=False, log_func=lambda message: None)
        client._running = True
        asyncio.run(client._mqtt_connect())

        self.assertTrue(client.set_value("Temperature", 25.5))
        self.assertTrue(client.get_value("Temperature"))
        self.assertTrue(client.get_values(["Temperature", "Status"]))
        self.assertTrue(client.get_all_values())
        self.assertTrue(client.batch_set_values({"Temperature": 25.5, "Status": "ok"}))

        mqtt = FakeMQTTClient.instances[-1]
        self.assertIn(("ds/Temperature", "25.5", 0), mqtt.published)
        self.assertIn(("get/ds", "Temperature", 0), mqtt.published)
        self.assertIn(("get/ds", "Temperature,Status", 0), mqtt.published)
        self.assertIn(("get/ds/all", "", 0), mqtt.published)
        batch_payloads = [payload for topic, payload, qos in mqtt.published if topic == "batch_ds"]
        self.assertEqual(batch_payloads, ['{"Temperature": 25.5, "Status": "ok"}'])

    def test_redirect_uses_client_ssl_mode_port(self):
        client = self.sdk.BlynkMQTT("token", ssl=True, log_func=lambda message: None)

        client._handle_message("downlink/redirect", "mqtt://sgp1.blynk.cloud:1883")

        self.assertEqual(client._redirect_pending, ("sgp1.blynk.cloud", 8883))


if __name__ == "__main__":
    unittest.main()

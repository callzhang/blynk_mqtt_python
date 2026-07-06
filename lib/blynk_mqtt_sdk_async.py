# blynk_mqtt_sdk_async.py
# Description: An Async MicroPython library for Blynk using MQTT with enhanced reliability.
# This library provides a modern async/await-based interface for connecting MicroPython devices
# to the Blynk IoT platform using the MQTT protocol. It features automatic reconnection,
# redirect handling, SSL support, and comprehensive error handling.
#
# Key Features:
# - Asynchronous, non-blocking operations using async/await
# - Automatic server redirect handling (blynk.cloud -> regional servers)
# - SSL certificate validation with ISRG Root X1 certificate
# - NTP time synchronization for SSL connections
# - Automatic reconnection with connection statistics
# - Enhanced error handling with null safety
# - Data tracking for sent/received messages
# - Mock client for testing in regular Python environments
# - Compatible with official Blynk MQTT API
#
# Changelog:
# - v1.4.0: (Community Fix)
#   - Corrected redirect handling to ignore the port from the redirect URL. The client now
#     correctly uses port 8883 for secure connections or 1883 for non-secure, based on its
#     own SSL configuration, rather than the potentially misleading port in the redirect command.
#     This resolves the final connection issue after a redirect.
# - v1.3.0:
#   - Added specific error handling for invalid Auth Tokens and optional full SSL verification.
# - v1.2.0:
#   - Fixed `[Errno 9] EBADF` race condition during initial connect and redirect.

import time
import json
import gc
import sys

# Compatibility for MicroPython const and MQTT libs
try:
    from micropython import const
    import machine
    import uasyncio as asyncio
    from umqtt.simple import MQTTClient, MQTTException
    import ssl
    MQTT_CLIENT_TYPE = "umqtt"
except ImportError:
    import asyncio  # Fallback for standard Python
    import ssl  # Standard Python ssl module
    def const(expr): return expr
    class MockMachine:
        @staticmethod
        def reset(): print("Mock machine reset called")
    machine = MockMachine()
    # Mock MQTTException for non-MicroPython environments
    class MQTTException(Exception): pass
    from mock.mock_mqtt_client import MockMQTTClient as MQTTClient
    MQTT_CLIENT_TYPE = "mock"

class BlynkMQTT:
    """
    Async Blynk MQTT SDK for MicroPython with advanced features.

    A modern, asynchronous MQTT client for connecting to the Blynk IoT platform.
    Features automatic reconnection, redirect handling, SSL support, and comprehensive
    error handling suitable for production IoT applications.

    Key Features:
    - Async/await pattern for non-blocking operations
    - Automatic reconnection with exponential backoff
    - SSL/TLS support with certificate validation
    - Server redirect handling (blynk.cloud → regional servers)
    - NTP time synchronization for SSL connections
    - Remote reboot command support
    - Comprehensive error handling and logging
    - Data tracking for debugging
    - Mock client for testing
    """

    def __init__(self, auth_token, server="blynk.cloud", port=0,
                 template_id=None, client_id=None, ssl=True, ssl_ca=None,
                 log_func=None, keepalive=45,
                 firmware_version: str = "1.0.0"):
        """
        Initialize the Blynk MQTT client.
        :param auth_token: Your Blynk device authentication token.
        :param server: MQTT broker hostname (default: "blynk.cloud").
        :param port: MQTT broker port. If 0, defaults to 8883 for SSL, 1883 for non-SSL.
        :param template_id: Your Blynk template ID.
        :param client_id: Custom MQTT client ID (auto-generated if None).
        :param ssl: Enable SSL/TLS encryption (default: True).
        :param log_func: Custom logging function (default: print).
        :param keepalive: MQTT keepalive interval in seconds (default: 45).
        :param firmware_version: Firmware version for device info.
        """
        self.auth_token = auth_token
        self.server = server
        self.use_ssl = ssl
        self.ssl_ca = ssl_ca  # SSL CA certificate file path
        self.port = port or (8883 if self.use_ssl else 1883)
        self.template_id = template_id
        self.client_id = "" if client_id is None else client_id
        self.log = log_func or print
        self.keepalive = keepalive
        self.firmware_version = firmware_version

        self.connected = False
        self.mqtt = None
        self._handlers = {}
        self._running = False
        self.connection_count = 0
        self._redirect_pending = None

        self.username = "device"
        self.password = auth_token

        self.sdk_version = "v2.7.0"
        LOGO = fr"""
      ___  __          __
     / _ )/ /_ _____  / /__
    / _  / / // / _ \/  '_/
   /____/_/\_, /_//_/_/\_\ {self.sdk_version}
          /___/"""

        self.log(LOGO)

    @staticmethod
    def _parse_url(url):
        try:
            scheme, url = url.split("://", 1)
        except ValueError:
            scheme = None
        try:
            netloc, path = url.split("/", 1)
        except ValueError:
            netloc, path = url, ""
        try:
            hostname, port = netloc.split(":", 1)
            port = int(port)
        except:
            hostname = netloc
            port = 8883 if scheme == "mqtts" else 1883  # Default MQTT ports
        return scheme, hostname, port, path

    async def update_ntp_time(self):
        """Updates system time via NTP, required for SSL certificate validation."""
        if time.gmtime()[0] > 2023: return True
        try:
            self.log("Syncing time via NTP for SSL..."); import ntptime
            ntptime.settime()
            if time.gmtime()[0] > 2023:
                self.log(f"UTC Time synchronized: {time.gmtime()}"); return True
            return False
        except Exception as e:
            self.log(f"NTP sync failed: {e}"); return False

    def on(self, event: str, handler: callable = None) -> callable:
        def decorator(handler_func):
            self._handlers[event] = handler_func
            return handler_func
        return decorator

    def _handle_message(self, topic, msg=None):
        topic = topic.decode() if type(topic) is bytes else topic
        msg = msg.decode() if type(msg) is bytes else msg
        self.log(f"Message received: {topic} -> {msg}")

        if topic == "downlink/reboot":
            self.log("Reboot command received, rebooting...")
            if self.mqtt: self.mqtt.disconnect()
            machine.reset()
        elif topic == "downlink/ping":
            pass
        elif topic == "downlink/redirect":
            self.log(f"Redirect received: {msg}")
            try:
                scheme, new_server, _new_port, path = self._parse_url(msg)
                new_port = 8883 if self.use_ssl else 1883

                if (new_server, new_port) != (self.server, self.port):
                    self.log(f"Redirect requested to {new_server}:{new_port}. Disconnecting.")
                    self._redirect_pending = (new_server, new_port)
                    if self.mqtt: self.mqtt.disconnect()
            except Exception as e: self.log(f"Redirect handling failed: {e}")
        elif 'message' in self._handlers and self._handlers['message']:
            try:
                handler = self._handlers['message']
                if hasattr(handler, '__code__') and bool(handler.__code__.co_flags & 0x80):
                    task = asyncio.create_task(handler(topic, msg))
                    task.add_done_callback(lambda t: self.log(f"Message [{topic}] handler [{handler.__name__}] completed: {topic} -> {msg}"))
                else:
                    handler(topic, msg)
            except Exception as e: self.log(f"Error in message handler: {e}")

    async def _mqtt_connect(self) -> bool:
        for attempt in range(1, 4):
            if not self._running: return False
            try:
                if self.use_ssl and not await self.update_ntp_time():
                    self.log("NTP sync required for SSL, retrying..."); await asyncio.sleep(5); continue

                if self.mqtt:
                    try: self.mqtt.disconnect()
                    except: pass
                gc.collect()

                self.log(f"Attempt {attempt}/3: Connecting to {self.server}:{self.port}...")

                ssl_ctx = None
                if sys.platform in ("esp32", "rp2", "linux") and self.use_ssl:
                    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

                    # Load CA certificate if provided
                    if self.ssl_ca:
                        ssl_ctx.verify_mode = ssl.CERT_REQUIRED
                        ssl_ctx.load_verify_locations(cafile=self.ssl_ca)
                    else:
                        # For ESP32 without CA certificate, disable verification
                        ssl_ctx.verify_mode = ssl.CERT_NONE
                self.mqtt = MQTTClient(
                    self.client_id, self.server, port=self.port, user=self.username,
                    password=self.password, keepalive=self.keepalive, ssl=ssl_ctx
                )
                self.mqtt.set_callback(self._handle_message)
                self.log("Calling connect() on MQTTClient...")
                self.mqtt.connect()
                self.log("connect() returned, proceeding to subscribe.")

                try:
                    self.mqtt.subscribe("downlink/#", qos=0)
                except Exception as sub_e:
                    if self._redirect_pending:
                        self.log(f"Subscription interrupted by redirect: {sub_e}")
                        self.connected = False
                        self.mqtt = None
                        return False
                    self.log(f"Subscription failed: {sub_e}")
                    raise sub_e

                self.connected = True
                self.connection_count += 1
                self.log(f"Connected to {self.server}:{self.port} (Connection #{self.connection_count})")

                if self.template_id:
                    info = {
                        "type": self.template_id,
                        "tmpl": self.template_id,
                        "ver": self.firmware_version,
                        "rxbuff": 1024,
                    }
                    self.mqtt.publish("info/mcu", json.dumps(info), qos=0)

                if 'connect' in self._handlers:
                    handler = self._handlers['connect']
                    result = handler()
                    if hasattr(result, "send"):
                        asyncio.create_task(result)
                return True

            except MQTTException as e:
                if e.args[0] in (4, 5):
                    self.log(f"FATAL: Invalid BLYNK_AUTH_TOKEN. Halting. (Code: {e.args[0]})")
                    self._running = False
                    return False
                last_error = f"MQTT Error: {e}"
            except OSError as e:
                last_error = f"OS Error: {e}"

            self.log(f"Connection attempt {attempt} failed: {last_error}")
            if self._redirect_pending:
                self.log("Failure due to pending redirect. Exiting connect loop.")
                return False

            if attempt < 3: await asyncio.sleep(min(2 ** attempt, 10))

        self.log("Failed to connect after 3 attempts.")
        return False

    async def _mqtt_task(self):
        while self._running:
            if self._redirect_pending:
                self.server, self.port = self._redirect_pending
                self._redirect_pending = None
                self.connected = False
                if self.mqtt:
                    self.mqtt = None
                gc.collect()
                self.log(f"Redirect applied. New target: {self.server}:{self.port}")

            if not self.connected:
                await self._mqtt_connect()
                if not self._running:
                    self.log("Client has been halted due to a fatal error.")
                    break

            if self.connected and self.mqtt:
                try:
                    self.mqtt.check_msg()
                except OSError as e:
                    self.log(f"Connection lost: {e}. Resetting...")
                    self.connected = False; self.mqtt = None
                    if not self._redirect_pending and 'disconnect' in self._handlers:
                        try:
                            self._handlers['disconnect']()
                        except Exception as he:
                            self.log(f"Disconnect handler error: {he}")
                    await asyncio.sleep(2)

            # Small sleep to prevent busy-waiting
            await asyncio.sleep(0.1)

    def set_value(self, datastream_name: str, value):
        """Sets a value to a datastream.

        Args:
            datastream_name (str): The name of the datastream (e.g., "Salinity", "Temp")
            value: The value to send (will be converted to string)

        Returns:
            bool: True if message was queued for sending, False otherwise
        """
        if not self.connected or not self.mqtt: return False
        try:
            self.mqtt.publish(f"ds/{datastream_name}", str(value), qos=0)
            return True
        except Exception as e:
            self.log(f"Error in virtual_write: {e}"); return False

    def get_value(self, datastream_name):
        """Requests current value from the server for a specific datastream.

        Args:
            datastream_name (str): The datastream name (e.g., "Salinity", "V5", "Temp")

        Returns:
            bool: True if request was sent successfully, False otherwise
        """
        if not self.connected or not self.mqtt:
            return False

        try:
            self.mqtt.publish('get/ds', datastream_name, qos=0)
            self.log(f"Get value request sent for datastream {datastream_name}")
            return True

        except Exception as e:
            self.log(f"Get value request error for {datastream_name}: {e}")
        return False

    def get_values(self, datastream_names):
        """Requests current values from the server for specific datastreams."""
        if not self.connected or not self.mqtt:
            return False

        try:
            payload = ",".join(datastream_names)
            self.mqtt.publish('get/ds', payload, qos=0)
            self.log(f"Get values request sent for datastreams {payload}")
            return True
        except Exception as e:
            self.log(f"Get values request error for {datastream_names}: {e}")
        return False


    def batch_set_values(self, data_dict):
        """Sends a batch of Datastream values in a single message."""
        if not self.connected:
            self.log("Batch write failed: Not connected to server")
            return False

        if not self.mqtt:
            self.log("Batch write failed: MQTT client is None")
            return False

        try:
            # Debug the input data
            self.log(f"Batch input data: {data_dict}")

            # Ensure all values are JSON serializable
            clean_data = {}
            for key, value in data_dict.items():
                if isinstance(value, (int, float, str, bool)) or value is None:
                    clean_data[str(key)] = value
                else:
                    clean_data[str(key)] = str(value)

            self.log(f"Cleaned data: {clean_data}")
            payload = json.dumps(clean_data)

            self.mqtt.publish('batch_ds', payload, qos=0)
            self.log(f"Batch published: {payload}")

            return True
        except Exception as e:
            self.log(f"Batch publish error: {e}")
            return False


    def get_all_values(self):
        """Request current values for all configured datastreams.
        :return: True if sync request was sent successfully, False otherwise
        """
        if self.connected and self.mqtt:
            try:
                # Send sync request using the official Blynk MQTT API
                # Publish empty payload to request all current values
                self.mqtt.publish('get/ds/all', "", qos=0)
                self.log("Sync request sent for all datastreams")
                return True

            except Exception as e:
                self.log(f"Sync all request error: {e}")
        return False

    async def start(self) -> asyncio.Task:
        """Starts the Blynk client background task."""
        if not self._running:
            self._running = True
            self.log("Starting Blynk MQTT client...")
            return asyncio.create_task(self._mqtt_task())
        else:
            self.log("Blynk client is already running")
            return asyncio.create_task(asyncio.sleep(1))

    def stop(self):
        self._running = False
        if self.mqtt:
            try: self.mqtt.disconnect()
            except: pass
        self.connected = False
        self.log("Blynk MQTT client stopped.")

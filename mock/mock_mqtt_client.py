"""
Mock MQTT Client for Testing
Provides a mock implementation of MQTTClient for testing Blynk MQTT functionality
in environments where umqtt.simple is not available.
"""

class MockMQTTClient:
    """
    Mock MQTT Client that simulates umqtt.simple.MQTTClient behavior
    for testing purposes in standard Python environments.
    """

    def __init__(self, client_id="", server="localhost", port=1883, user=None, password=None, ssl=None, keepalive=60):
        self.client_id = client_id
        self.server = server
        self.port = port
        self.user = user
        self.password = password
        self.ssl = ssl
        self.keepalive = keepalive
        self.callback = None
        self.connected = False
        self.published = []
        self.subscribed = []
        print(f"Mock MQTT Client created: {server}:{port}")

    def set_callback(self, callback):
        """Set the message callback function"""
        self.callback = callback

    def connect(self):
        """Simulate MQTT connection"""
        print(f"Mock MQTT connecting to {self.server}:{self.port}")
        self.connected = True
        # Simulate redirect for testing
        if self.server == "blynk.cloud":
            print("Simulating redirect...")
            if self.callback:
                self.callback(b"downlink/redirect", b"mqtts://sgp1.blynk.cloud:8883/")

    def disconnect(self):
        """Simulate MQTT disconnection"""
        print("Mock MQTT disconnecting")
        self.connected = False

    def subscribe(self, topic, qos=0):
        """Simulate MQTT subscription"""
        self.subscribed.append((topic, qos))
        print(f"Mock MQTT subscribed to: {topic}")

    def publish(self, topic, payload, qos=0):
        """Simulate MQTT publish"""
        self.published.append((topic, payload, qos))
        print(f"Mock MQTT publish: {topic} -> {payload}")

    def check_msg(self):
        """Simulate checking for incoming messages"""
        # Simulate some incoming messages for testing
        if self.callback and self.connected:
            # Simulate datastream responses
            import random
            if random.random() < 0.1:  # 10% chance
                self.callback(b"downlink/ds/v0", b"25.5")

    def ping(self):
        """Simulate MQTT ping"""
        print("Mock MQTT ping")

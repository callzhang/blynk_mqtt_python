# blynk_mqtt_sdk.py
# Description: A MicroPython library for Blynk using MQTT.
# This library allows MicroPython devices to connect to the Blynk IoT platform
# using the MQTT protocol, enabling them to send data, receive commands,
# and interact with Blynk's features like notifications, events, and device management.
# Version: 0.2.1
# Author: Derek Zen (Based on Blynk MQTT API and blynk-library-python concepts)
# Changelog:
# - v0.2.1: Added comprehensive comments for public release.
# - v0.2.0: Added support for Device Info, Bridge, Location, Metadata,
#           Property Get, Automation, Device Log. Refined connect and callbacks.
# - v0.1.0: Initial version.

import ujson as json
try:
    from umqtt.simple import MQTTClient
except ImportError:
    # This is a common MicroPython MQTT library. If it's not found,
    # print a warning and define a dummy class so the rest of the
    # SDK can be imported/inspected, though it won't function.
    print("Warning: umqtt.simple module not found. Please install it for the library to function.")
    class MQTTClient:
        def __init__(self, *args, **kwargs): pass
        def set_callback(self, cb): pass
        def connect(self, clean_session=True): raise RuntimeError("umqtt.simple not installed")
        def disconnect(self): pass
        def subscribe(self, topic, qos=0): pass
        def publish(self, topic, msg, retain=False, qos=0): pass
        def wait_msg(self): pass
        def check_msg(self): pass
        def ping(self): pass

import time
import machine # For unique_id, if available, to generate a default MQTT client_id

# Default MQTT server details for Blynk Cloud
MQTT_SERVER = 'broker.blynk.cc' # Default Blynk MQTT broker hostname
MQTT_PORT_TCP = 1883           # Default MQTT port for unencrypted connections
MQTT_PORT_SSL = 8883           # Default MQTT port for SSL/TLS encrypted connections

# Blynk MQTT API topics structure.
# These are based on the official Blynk MQTT API documentation.
# The {auth_token} part of the topic is handled by the library user providing their token.
TOPIC_PREFIX = "blynk/v1/device/" # Base prefix for all device-specific topics

# --- Publish Topics (Device to Server) ---
TOPIC_DATA_STREAM = TOPIC_PREFIX + "data/stream"             # For publishing telemetry data (virtual pin values)
TOPIC_NOTIFICATIONS = TOPIC_PREFIX + "notifications"         # For sending push notifications to the app
TOPIC_PROPERTY_UPDATE = TOPIC_PREFIX + "property/update"     # For updating widget properties in the app
TOPIC_EVENT = TOPIC_PREFIX + "events"                        # For logging events to the device timeline
TOPIC_INFO_UPDATE = TOPIC_PREFIX + "info/update"             # For publishing static device information (board, firmware)
TOPIC_BRIDGE_REQUEST = TOPIC_PREFIX + "bridge/request"       # For sending bridge commands to other devices
TOPIC_LOCATION_UPDATE = TOPIC_PREFIX + "location/update"     # For publishing device GPS location
TOPIC_METADATA_UPDATE = TOPIC_PREFIX + "metadata/update"     # For publishing custom key-value metadata
TOPIC_AUTOMATION_TRIGGER = TOPIC_PREFIX + "automation/trigger" # For triggering Blynk automations
TOPIC_DEVICE_LOG = TOPIC_PREFIX + "log"                      # For sending internal device logs to Blynk (for debugging/monitoring)
TOPIC_OTA_UPDATE = TOPIC_PREFIX + "ota/update"               # For publishing status updates during a custom OTA process

# --- Subscribe Topics (Server to Device) ---
TOPIC_CONTROL = TOPIC_PREFIX + "control"                     # For receiving commands from the server/app (e.g., virtual pin writes)
TOPIC_INFO_GET = TOPIC_PREFIX + "info/get"                   # For server requests to get device information
TOPIC_PROPERTY_GET = TOPIC_PREFIX + "property/get"           # For server requests to get current widget property values
TOPIC_AUTOMATION_RESPONSE = TOPIC_PREFIX + "automation/response" # For receiving execution status of triggered automations
TOPIC_OTA_REQUEST = TOPIC_PREFIX + "ota/request"             # For receiving OTA commands from Blynk (for custom OTA implementations)


class BlynkMQTT:
    """
    BlynkMQTT class provides an interface to interact with the Blynk IoT platform
    using the MQTT protocol in a MicroPython environment.

    It handles connection, authentication, publishing data to virtual pins,
    receiving commands, and other Blynk-specific MQTT functionalities.
    """
    def __init__(self, auth_token, server=MQTT_SERVER, port=None,
                 client_id=None, user=None, password="", ssl=False, ssl_params=None,
                 log_func=None, keepalive=60,
                 board_type=None, fw_version=None, app_name=None):
        """
        Initialize the BlynkMQTT client.

        :param auth_token: Your unique Blynk device authentication token. This is mandatory.
        :param server: MQTT broker address. Defaults to Blynk's public cloud broker.
        :param port: MQTT broker port. Automatically set to 1883 (TCP) or 8883 (SSL) if None.
        :param client_id: MQTT client ID. A unique ID is generated using `machine.unique_id()`
                          or a random string if None or if `machine.unique_id()` is unavailable.
        :param user: MQTT username. Defaults to your `auth_token` as required by Blynk MQTT.
        :param password: MQTT password. Defaults to an empty string (Blynk MQTT allows this).
        :param ssl: Boolean, set to True to use SSL/TLS for a secure connection.
                    Requires firmware support for SSL and `umqtt.simple` compiled with SSL.
        :param ssl_params: Dictionary of SSL parameters (e.g., for certificates if using a private server
                           or specific SSL configurations). Passed directly to `umqtt.simple.MQTTClient`.
        :param log_func: Optional custom logging function (e.g., `print` or a more sophisticated logger).
                         It will be called with string arguments. Defaults to a no-op lambda.
        :param keepalive: MQTT keepalive interval in seconds. Defines the maximum period between
                          messages sent by the client. If no other messages are sent, a PINGREQ
                          will be sent. `umqtt.simple` handles this.
        :param board_type: Optional. String identifying the board type (e.g., "ESP32", "RP2040").
                           Used for the `info/update` topic.
        :param fw_version: Optional. String identifying the firmware version (e.g., "1.0.0").
                           Used for the `info/update` topic.
        :param app_name: Optional. String identifying the application name/version (e.g., "MyProject/1.2.3").
                         Used for the `info/update` topic.
        """
        if not auth_token:
            raise ValueError("Blynk authentication token ('auth_token') is required.")
        self.auth_token = auth_token
        self.server = server
        
        if port is None:
            self.port = MQTT_PORT_SSL if ssl else MQTT_PORT_TCP
        else:
            self.port = port
        
        if client_id is None:
            try:
                # Attempt to create a unique client_id using the MCU's unique ID
                client_id_hex = "".join(["{:02x}".format(b) for b in machine.unique_id()])
                client_id = "blynk_mp_" + client_id_hex
            except (ImportError, AttributeError, NameError, TypeError): # machine or unique_id might not be available/work
                # Fallback to a short random string for client_id if unique_id fails
                import urandom
                client_id = "blynk_mp_" + "".join([chr(ord('a') + urandom.getrandbits(5) % 26) for _ in range(8)])
        self.client_id = client_id

        # According to Blynk MQTT documentation, the username should be the auth_token.
        # The password can be empty or any string.
        self.user = user if user is not None else self.auth_token
        self.password = password

        self.ssl = ssl
        self.ssl_params = ssl_params if ssl_params is not None else {} # Ensure it's a dict for MQTTClient
        
        self.log = log_func if callable(log_func) else (lambda *args: None) # Default to a no-operation logger
        
        self.connected = False  # Tracks the MQTT connection state
        self._handlers = {}     # Dictionary to store user-defined event handlers (e.g., for V0, 'connect')
        self._last_activity_ms = time.ticks_ms() # Timestamp of the last MQTT send/receive activity

        # Store device information provided at initialization for automatic `info/update`
        self._device_info = {
            "board": board_type,
            "firmwareVersion": fw_version,
            "appName": app_name
        }

        # Initialize the underlying umqtt.simple.MQTTClient
        self.mqtt = MQTTClient(
            client_id=self.client_id,
            server=self.server,
            port=self.port,
            user=self.user,
            password=self.password,
            keepalive=keepalive,
            ssl=self.ssl,
            ssl_params=self.ssl_params
        )
        # Set the callback for incoming MQTT messages
        self.mqtt.set_callback(self._mqtt_message_callback)
        self.log("BlynkMQTT client initialized.")

    def _mqtt_message_callback(self, topic_bytes, msg_bytes):
        """
        Internal callback method invoked by `umqtt.simple` when an MQTT message is received
        on a subscribed topic.

        It decodes the topic and message, parses JSON payloads, and routes the message
        to the appropriate handler based on the topic.

        :param topic_bytes: Bytes, the topic on which the message was received.
        :param msg_bytes: Bytes, the payload of the received message.
        """
        topic_str = topic_bytes.decode('utf-8') # Topics are UTF-8
        msg_str = msg_bytes.decode('utf-8')   # Payloads are typically UTF-8 JSON strings
        self.log(f"MQTT RX: Topic='{topic_str}', Msg='{msg_str}'")
        self._last_activity_ms = time.ticks_ms() # Update activity timestamp

        try:
            # Most Blynk messages are JSON, but some (like info/get) might be empty.
            data = json.loads(msg_str) if msg_str else {}
        except ValueError: # Handles JSONDecodeError in MicroPython's ujson
            self.log(f"Error: Failed to decode JSON from topic '{topic_str}': {msg_str}")
            data = {} # Treat as an empty or invalid payload to prevent crashes

        # Route message based on topic
        if topic_str == TOPIC_CONTROL:
            # This topic delivers commands from the Blynk app/server, typically virtual pin writes.
            # Expected payload: {"pin": "v0", "value": "some_value"} or {"pin": "v1", "value": [val1, val2]}
            pin_str = data.get("pin")
            value = data.get("value") # Value can be string, number, list, etc.

            if pin_str and pin_str.lower().startswith("v"): # Check if it's a virtual pin
                handler_key = pin_str.upper()  # Normalize to "V0", "V1", etc. for handler lookup
                if handler_key in self._handlers:
                    try:
                        self._handlers[handler_key](value) # Call the registered handler
                    except Exception as e:
                        self.log(f"Error executing handler for {handler_key}: {e}")
                else:
                    self.log(f"Warning: No handler registered for incoming data on {handler_key}")
            else:
                self.log(f"Warning: Received unhandled control message structure or non-virtual pin: {data}")

        elif topic_str == TOPIC_INFO_GET:
            # Server is requesting device information.
            # Payload is usually empty.
            if 'info_get' in self._handlers: # Prioritize user-defined handler
                try:
                    self._handlers['info_get']()
                except Exception as e:
                    self.log(f"Error executing 'info_get' handler: {e}")
            else: # Default behavior: publish stored device info
                self.log("Received info/get request. Responding with stored device info.")
                self.publish_device_info() # Uses cached values

        elif topic_str == TOPIC_PROPERTY_GET:
            # Server is requesting the current value of a widget property.
            # Expected payload: {"pin": "v0", "property": "label"}
            pin_designator = data.get("pin")
            prop_name = data.get("property")
            if 'property_get' in self._handlers:
                try:
                    # User handler is responsible for publishing the property back using set_property()
                    self._handlers['property_get'](pin_designator, prop_name)
                except Exception as e:
                    self.log(f"Error executing 'property_get' handler for {pin_designator}.{prop_name}: {e}")
            else:
                self.log(f"Warning: Received property_get for {pin_designator}.{prop_name}, but no handler registered. "
                         "Use blynk.on('property_get', your_handler) to respond.")

        elif topic_str == TOPIC_AUTOMATION_RESPONSE:
            # Server sends status of a triggered automation.
            # Expected payload: {"automationId": 123, "status": "success", "message": "Optional details"}
            automation_id = data.get("automationId")
            status = data.get("status")
            message = data.get("message") # Optional field
            if 'automation_response' in self._handlers:
                try:
                    self._handlers['automation_response'](automation_id, status, message)
                except Exception as e:
                    self.log(f"Error executing 'automation_response' handler: {e}")
            else:
                self.log(f"Received automation_response for ID {automation_id}, status {status}. No handler registered.")
        
        elif topic_str == TOPIC_OTA_REQUEST:
            # Server sends a command to initiate a custom Over-The-Air update.
            # Payload structure depends on the custom OTA setup.
            # Example: {"command": "start", "url": "http://...", "version": "1.1.0"}
            if 'ota_request' in self._handlers:
                try:
                    self._handlers['ota_request'](data) # Pass the full data dictionary to the handler
                except Exception as e:
                    self.log(f"Error executing 'ota_request' handler: {e}")
            else:
                self.log(f"Received OTA request: {data}. No handler registered. This is for custom OTA implementations.")
        else:
            # Message on a subscribed topic that doesn't have specific handling logic here.
            self.log(f"Warning: Received message on an unhandled subscribed topic: {topic_str}")


    def connect(self, clean_session=True):
        """
        Connect to the MQTT broker and subscribe to essential Blynk topics.

        :param clean_session: MQTT clean session flag. If True, the broker discards any
                              previous session and subscriptions. If False, it attempts to
                              resume a previous session. `umqtt.simple` passes this to the broker.
        :return: True if connection and initial subscriptions are successful, False otherwise.
        """
        if self.connected:
            self.log("Already connected to MQTT.")
            return True
        
        self.log(f"Attempting to connect to MQTT broker: {self.server}:{self.port} as client '{self.client_id}'...")
        try:
            # Establish connection to the MQTT broker
            self.mqtt.connect(clean_session=clean_session)
            self.log("MQTT client connected to broker.")
            
            # Subscribe to topics for receiving data/commands from Blynk
            # Note: Topics must be encoded to bytes for umqtt.simple's subscribe method.
            
            # Essential for receiving widget commands, virtual pin writes from app/server
            self.mqtt.subscribe(TOPIC_CONTROL.encode('utf-8'))
            self.log(f"Subscribed to: {TOPIC_CONTROL}")
            
            # For server requests for device information
            self.mqtt.subscribe(TOPIC_INFO_GET.encode('utf-8'))
            self.log(f"Subscribed to: {TOPIC_INFO_GET}")

            # For server requests for widget property values
            self.mqtt.subscribe(TOPIC_PROPERTY_GET.encode('utf-8'))
            self.log(f"Subscribed to: {TOPIC_PROPERTY_GET}")

            # For receiving status updates about triggered automations
            self.mqtt.subscribe(TOPIC_AUTOMATION_RESPONSE.encode('utf-8'))
            self.log(f"Subscribed to: {TOPIC_AUTOMATION_RESPONSE}")

            # For receiving OTA commands (if custom OTA is implemented)
            self.mqtt.subscribe(TOPIC_OTA_REQUEST.encode('utf-8'))
            self.log(f"Subscribed to: {TOPIC_OTA_REQUEST}")
            
            self.connected = True # Update connection state
            self._last_activity_ms = time.ticks_ms()

            # Call user-defined 'connect' handler, if registered
            if 'connect' in self._handlers:
                try:
                    self._handlers['connect']()
                except Exception as e:
                    self.log(f"Error executing 'connect' handler: {e}")
            self.log("Successfully connected and subscribed to Blynk topics.")
            
            # After successful connection, publish initial device info if available
            if self._device_info.get("board") or self._device_info.get("firmwareVersion") or self._device_info.get("appName"):
                self.log("Publishing initial device info...")
                self.publish_device_info() # Uses cached values from __init__
            return True
            
        except OSError as e:  # OSError is common for network/socket issues in MicroPython
            self.log(f"Error: MQTT Connection failed (OSError): {e}")
        except Exception as e: # Catch any other unexpected errors during connection
            self.log(f"Error: MQTT Connection failed with unexpected error: {e}")
        
        # If connection failed
        self.connected = False
        # Call user-defined 'disconnect' handler on failed connect attempt, if registered
        if 'disconnect' in self._handlers:
            try:
                self._handlers['disconnect']()
            except Exception as e_handler:
                self.log(f"Error executing 'disconnect' handler during connect failure: {e_handler}")
        return False

    def disconnect(self):
        """
        Disconnect from the MQTT broker.
        Calls the user-defined 'disconnect' handler if registered.
        """
        if self.connected:
            try:
                self.mqtt.disconnect()
                self.log("Disconnected from MQTT broker.")
            except Exception as e:
                self.log(f"Error during MQTT disconnect: {e}")
            finally:
                self.connected = False # Ensure state is updated even if disconnect call fails
                # Call user-defined 'disconnect' handler
                if 'disconnect' in self._handlers:
                    try:
                        self._handlers['disconnect']()
                    except Exception as e_handler:
                        self.log(f"Error executing 'disconnect' handler: {e_handler}")
        else:
            self.log("Already disconnected. No action taken.")

    def on(self, event_name, func=None):
        """
        Register event handlers for various Blynk events.
        This method can be used as a decorator (`@blynk.on("V0")`) or as a direct call
        (`blynk.on("V0", my_handler_func)`).

        Supported event_name strings:
          - 'connect': Called when the MQTT connection to Blynk is successfully established.
          - 'disconnect': Called when the MQTT connection is lost or fails.
          - 'V<pin>': (e.g., 'V0', 'V12') Called when data is written to the specified
                       virtual pin from the Blynk app or server. The handler function
                       will receive the value(s) written to the pin.
          - 'info_get': Called when the Blynk server requests device information.
                        If no handler is registered, the SDK automatically responds with
                        information provided during `__init__` or `publish_device_info`.
                        A custom handler can be used for dynamic info.
          - 'property_get': Handler signature: `handler(pin_designator, property_name)`.
                            Called when the server requests a widget property's current value.
                            The handler should then use `blynk.set_property()` to send the
                            actual value back to the server.
          - 'automation_response': Handler signature: `handler(automation_id, status, message)`.
                                   Called with the execution status of a triggered automation.
          - 'ota_request': Handler signature: `handler(data_dict)`. Called when an OTA command
                           is received from Blynk (for custom OTA implementations). The `data_dict`
                           contains the OTA command details.

        :param event_name: String, the name of the event to handle.
        :param func: The function to be called when the event occurs. If None, this method
                     returns a decorator.
        :return: If `func` is None, returns a decorator. Otherwise, no return value.
        :raises ValueError: If `event_name` for a virtual pin is invalid (e.g., pin number out of range).
        """
        def decorator(f):
            # Normalize virtual pin event names to uppercase (e.g., "v0" -> "V0")
            event_key = event_name.upper() if event_name.lower().startswith('v') else event_name.lower()
            
            # Validate virtual pin numbers
            if event_key.startswith('V') and event_key[1:].isdigit():
                pin = int(event_key[1:])
                if not (0 <= pin <= 255): # Blynk virtual pins are typically 0-255
                    raise ValueError("Virtual pin number must be between 0 and 255 for 'on' event.")
            # Check against known event types for logging unrecognized ones
            elif event_key not in ['connect', 'disconnect', 'info_get', 'property_get', 
                                   'automation_response', 'ota_request']:
                self.log(f"Warning: Registering handler for potentially unknown event name '{event_name}'.")
            
            self._handlers[event_key] = f
            self.log(f"Registered handler for event: '{event_key}'")
            return f

        if func: # If used as blynk.on("event", my_func)
            return decorator(func)
        return decorator # If used as @blynk.on("event")

    def _publish(self, topic, payload_obj, qos=0, retain=False):
        """
        Internal helper method to publish an MQTT message with a JSON payload.
        Handles JSON serialization and MQTT publishing.

        :param topic: String, the MQTT topic to publish to.
        :param payload_obj: Python object (e.g., dict, list, string, number) to be
                            serialized to JSON and sent as the message payload.
        :param qos: Integer, MQTT Quality of Service level (0 or 1). `umqtt.simple`
                    typically supports QoS 0 and sometimes QoS 1 for publishing.
        :param retain: Boolean, MQTT retain flag. If True, the broker stores the message
                       and sends it to new subscribers.
        :return: True if publishing was successful, False otherwise.
        """
        if not self.connected:
            self.log(f"Error: Cannot publish to '{topic}'. Not connected to MQTT broker.")
            return False
        try:
            payload_str = json.dumps(payload_obj) # Serialize payload to JSON string
            self.log(f"MQTT TX: Topic='{topic}', Payload='{payload_str}', QoS={qos}, Retain={retain}")
            self.mqtt.publish(topic.encode('utf-8'), payload_str.encode('utf-8'), retain=retain, qos=qos)
            self._last_activity_ms = time.ticks_ms() # Update activity timestamp
            return True
        except OSError as e: # Handle network errors during publish
            self.log(f"Error: MQTT Publish to '{topic}' failed (OSError): {e}. Assuming disconnection.")
            self.disconnect() # A publish error often means the connection is lost
            return False
        except Exception as e: # Handle other errors (e.g., JSON serialization)
            self.log(f"Error: MQTT Publish to '{topic}' failed: {e}")
            return False

    def virtual_write(self, pin_number, *values):
        """
        Send data from the device to a Virtual Pin on the Blynk app/server.

        :param pin_number: Integer, the virtual pin number (0-255).
        :param values: One or more values to send to the pin.
                       If a single value is provided, it's sent directly.
                       If multiple values are provided, they are sent as a JSON array.
                       If no values are provided, `null` might be sent depending on JSON conversion.
        :return: True if the message was published successfully, False otherwise.
        :raises TypeError: If `pin_number` is not an integer.
        :raises ValueError: If `pin_number` is outside the valid range (0-255).
        """
        if not isinstance(pin_number, int):
            raise TypeError("Virtual pin number must be an integer.")
        if not (0 <= pin_number <= 255):
            raise ValueError("Virtual pin number must be between 0 and 255.")
        
        if not values: # No values provided
            # Blynk typically expects a value. Sending None (JSON null) or an empty string
            # might be options, or logging a warning.
            # For simplicity, if no values, we send a single None.
            self.log(f"Warning: virtual_write for V{pin_number} called with no values. Sending null.")
            value_to_send = None
        elif len(values) == 1:
            value_to_send = values[0] # Single value
        else:
            value_to_send = list(values) # Multiple values, send as a JSON array
        
        # The payload for data stream is a JSON object where keys are "v<pin>"
        # and values are the data for that pin.
        payload = {f"v{pin_number}": value_to_send}
        return self._publish(TOPIC_DATA_STREAM, payload)

    def notify(self, message):
        """
        Send a push notification to the Blynk app associated with this device's auth token.

        :param message: String, the message content of the notification.
        :return: True if the notification message was published successfully, False otherwise.
        """
        if not isinstance(message, str):
            message = str(message) # Ensure message is a string
        payload = {"body": message} # Payload format for notifications
        return self._publish(TOPIC_NOTIFICATIONS, payload)

    def set_property(self, pin_designator, property_name, value):
        """
        Set a property of a widget in the Blynk app (e.g., label, color, min/max values).

        :param pin_designator: String, identifies the pin associated with the widget
                               (e.g., "v0" for virtual pin 0, "d5" for digital pin 5).
        :param property_name: String, the name of the property to set (e.g., "label", "color", "min", "max").
                              Refer to Blynk documentation for available properties for each widget.
        :param value: The value to set for the property. Can be a string, number, or other JSON-compatible type.
        :return: True if the property update message was published successfully, False otherwise.
        :raises TypeError: If `pin_designator` or `property_name` are not strings.
        """
        if not isinstance(pin_designator, str):
            raise TypeError("Pin designator for set_property must be a string (e.g., 'v0', 'd5').")
        if not isinstance(property_name, str):
            raise TypeError("Property name for set_property must be a string.")
            
        payload = {"pin": pin_designator, "property": property_name, "value": value}
        return self._publish(TOPIC_PROPERTY_UPDATE, payload)

    def log_event(self, event_code, description=""):
        """
        Log an event to the Blynk device's timeline in the app or web dashboard.

        :param event_code: String, a code or name for the event (e.g., "device_rebooted", "sensor_alert").
        :param description: Optional string, a more detailed description of the event.
        :return: True if the event message was published successfully, False otherwise.
        """
        payload = {"name": str(event_code)} # Event code is mandatory
        if description: # Description is optional
            payload["description"] = str(description)
        return self._publish(TOPIC_EVENT, payload)

    def publish_device_info(self, board=None, fw_version=None, app_name=None):
        """
        Publish static device information to Blynk (e.g., board type, firmware version).
        This information can be viewed in the Blynk console.
        If parameters are provided, they update the SDK's internal cache of this info.
        If no parameters are provided, it publishes the currently cached info.

        :param board: Optional. String, the type of board (e.g., "ESP32", "RP2040").
        :param fw_version: Optional. String, the firmware version (e.g., "1.0.1").
        :param app_name: Optional. String, a name for the application/firmware (e.g., "MyProject/1.2.3").
        :return: True if the device info message was published successfully, False if no info to publish or error.
        """
        payload = {}
        # Update internal cache and build payload if new values are provided
        if board is not None: 
            payload["board"] = str(board)
            self._device_info["board"] = str(board) # Cache it
        elif self._device_info["board"] is not None: # Use cached if not provided in call
             payload["board"] = self._device_info["board"]

        if fw_version is not None:
            payload["firmwareVersion"] = str(fw_version)
            self._device_info["firmwareVersion"] = str(fw_version) # Cache it
        elif self._device_info["firmwareVersion"] is not None:
            payload["firmwareVersion"] = self._device_info["firmwareVersion"]

        if app_name is not None:
            payload["appName"] = str(app_name)
            self._device_info["appName"] = str(app_name) # Cache it
        elif self._device_info["appName"] is not None:
            payload["appName"] = self._device_info["appName"]
            
        if not payload: # If no board or firmware version info is available at all
            self.log("Warning: publish_device_info called, but no information (board, fw_version, appName) is available to send.")
            return False
            
        # According to docs, at least one field should be present.
        # Typically 'board' and 'firmwareVersion' are common.
        return self._publish(TOPIC_INFO_UPDATE, payload)

    def bridge_virtual_write(self, target_token, pin_designator, value):
        """
        Send a value to a virtual pin on another Blynk device using the Bridge feature.

        :param target_token: String, the authentication token of the target device.
        :param pin_designator: String, the virtual pin on the target device (e.g., "v0", "v12").
        :param value: The value to send to the target device's virtual pin.
        :return: True if the bridge request was published successfully, False otherwise.
        :raises TypeError: If `target_token` or `pin_designator` are not strings.
        """
        if not isinstance(target_token, str):
            raise TypeError("Target token for bridge_virtual_write must be a string.")
        if not isinstance(pin_designator, str) or not pin_designator.lower().startswith('v'):
            raise TypeError("Pin designator for bridge_virtual_write must be a virtual pin string (e.g., 'v0').")
            
        payload = {"targetToken": target_token, "pin": pin_designator, "value": value}
        return self._publish(TOPIC_BRIDGE_REQUEST, payload)

    def publish_location(self, lat, lon, alt=None, hdop=None):
        """
        Publish the device's geographical location (GPS coordinates) to Blynk.

        :param lat: Float or String, latitude of the device.
        :param lon: Float or String, longitude of the device.
        :param alt: Optional. Float or String, altitude in meters.
        :param hdop: Optional. Float or String, Horizontal Dilution of Precision (GPS accuracy measure).
        :return: True if the location message was published successfully, False otherwise.
        """
        payload = {"lat": lat, "lon": lon} # Latitude and Longitude are mandatory
        if alt is not None: payload["alt"] = alt
        if hdop is not None: payload["hdop"] = hdop
        return self._publish(TOPIC_LOCATION_UPDATE, payload)

    def publish_metadata(self, metadata_dict):
        """
        Publish custom metadata as a dictionary of key-value pairs to Blynk.
        This metadata can be viewed in the device details in the Blynk console.

        :param metadata_dict: Dictionary of metadata. Keys and values should be strings or numbers.
                              Example: `{"sensorModel": "DHT22", "serialNumber": "SN12345"}`
        :return: True if the metadata message was published successfully, False otherwise.
        :raises TypeError: If `metadata_dict` is not a dictionary.
        """
        if not isinstance(metadata_dict, dict):
            raise TypeError("Metadata for publish_metadata must be a dictionary.")
        return self._publish(TOPIC_METADATA_UPDATE, metadata_dict)

    def trigger_automation(self, automation_id, state=None, value=None):
        """
        Trigger a pre-configured Blynk automation by its ID.

        :param automation_id: Integer, the ID of the automation to trigger.
        :param state: Optional. String, for automations that act like a switch (e.g., "on", "off").
        :param value: Optional. Any JSON-compatible value, for automations that expect a specific value.
        :return: True if the automation trigger message was published successfully, False otherwise.
        :raises TypeError: If `automation_id` is not an integer.
        """
        if not isinstance(automation_id, int):
            raise TypeError("Automation ID for trigger_automation must be an integer.")
            
        payload = {"automationId": automation_id}
        if state is not None: payload["state"] = str(state)
        if value is not None: payload["value"] = value
        
        if state is None and value is None:
            # While the API might allow this (triggering with just ID), it's often less useful.
            self.log(f"Warning: trigger_automation for ID {automation_id} called without 'state' or 'value'.")
            
        return self._publish(TOPIC_AUTOMATION_TRIGGER, payload)

    def device_log(self, level, message):
        """
        Send a log message to Blynk's internal device logging system.
        These logs are typically used for debugging and monitoring device behavior from the Blynk console,
        and are different from events logged via `log_event` which appear in the device timeline.

        :param level: String, the severity level of the log message. Must be one of:
                      "trace", "debug", "info", "warn", "error".
        :param message: String, the content of the log message.
        :return: True if the log message was published successfully, False otherwise.
        :raises ValueError: If an invalid `level` is provided.
        """
        valid_levels = ["trace", "debug", "info", "warn", "error"]
        if level not in valid_levels:
            raise ValueError(f"Invalid level '{level}' for device_log. Must be one of {valid_levels}.")
        payload = {"level": level, "message": str(message)} # Ensure message is a string
        return self._publish(TOPIC_DEVICE_LOG, payload)
        
    def publish_ota_status(self, status, version=None, size=None, error_code=None, error_msg=None):
        """
        Publish status updates during a custom Over-The-Air (OTA) firmware update process.
        This is intended for use with user-implemented OTA logic, not Blynk's built-in OTA.

        :param status: String, the current status of the OTA process
                        (e.g., "initiated", "downloading", "flashing", "success", "failed").
        :param version: Optional. String, the firmware version being updated to.
        :param size: Optional. Integer, the size of the firmware in bytes.
        :param error_code: Optional. Integer, an error code if the OTA process failed.
        :param error_msg: Optional. String, a descriptive error message if the OTA process failed.
        :return: True if the OTA status message was published successfully, False otherwise.
        """
        payload = {"status": str(status)} # Status is mandatory
        if version is not None: payload["version"] = str(version)
        if size is not None: payload["size"] = int(size)
        if error_code is not None: payload["errorCode"] = int(error_code)
        if error_msg is not None: payload["errorMessage"] = str(error_msg)
        
        self.log(f"Publishing OTA Status: {payload} (Note: This is for custom OTA implementations)")
        return self._publish(TOPIC_OTA_UPDATE, payload)

    def run(self):
        """
        Process incoming MQTT messages and maintain the connection.
        This method should be called regularly and frequently in your main application loop
        to ensure timely processing of messages from the Blynk server and to allow
        `umqtt.simple` to handle keepalive (PINGREQ/PINGRESP) with the broker.
        """
        if not self.connected:
            # If not connected, there's nothing for run() to do regarding MQTT messages.
            # Reconnection logic should be handled by the main application loop if desired.
            return
            
        try:
            # `check_msg()` is non-blocking and processes any incoming messages.
            # If a message is received, it will trigger the `_mqtt_message_callback`.
            self.mqtt.check_msg()
            
            # The `umqtt.simple` library handles MQTT PINGREQ/PINGRESP for keepalive
            # automatically as part of its internal operations when `check_msg` or `wait_msg`
            # are called, or when publishing. No explicit ping from this SDK layer is needed.
            # `_last_activity_ms` is updated on TX/RX for potential custom idle checks by user.

        except OSError as e: # Network errors during check_msg usually mean connection is lost
            self.log(f"Error in run loop (OSError during check_msg): {e}. Assuming disconnection.")
            self.disconnect() # Trigger disconnect logic, including user's 'disconnect' handler
        except Exception as e: # Catch any other unexpected errors
            self.log(f"Error in run loop (check_msg): {e}")
            # Depending on the error, a disconnect might also be warranted here,
            # but OSError is the most common indicator of a lost connection.

    # --- Placeholder for features that are not directly part of the standard Blynk MQTT API ---
    #     or require more complex state management within the SDK or user application.
    def sync_virtual(self, *pin_numbers):
        """
        Placeholder method for synchronizing virtual pin states.
        The standard Blynk MQTT API does not provide a direct "sync" or "get value" command
        for virtual pins in the same way the older Blynk TCP/SSL library did.

        To achieve synchronization:
        1.  **Device-initiated:** The device can re-publish its last known state for the
            specified virtual pins using `virtual_write()`. This requires the device
            to maintain its own state.
        2.  **App-initiated:** The Blynk app, when it loads or a widget requests it, might
            send the current values of its widgets to the device via the `control` topic,
            which would be handled by the registered 'V<pin>' handlers.
        3.  **Using `property/get`:** For some widget properties (not raw datastream values),
            the server can request them using the `property/get` topic.

        This method is kept as a placeholder for conceptual similarity to older Blynk libraries
        but currently does not implement a direct MQTT sync command.

        :param pin_numbers: A list of integer virtual pin numbers to "synchronize".
        """
        self.log("sync_virtual: Blynk MQTT API has no direct 'get value' command for virtual pins. "
                 "To sync, the device can re-publish its current state for these pins, "
                 "or rely on app/server updates. For widget properties, use 'property/get' mechanism.")
        
        # Example of device-initiated re-publish (requires local state tracking):
        # for pin_num in pin_numbers:
        #    if hasattr(self, "_local_pin_states") and pin_num in self._local_pin_states:
        #        self.virtual_write(pin_num, self._local_pin_states[pin_num])
        #    else:
        #        self.log(f"sync_virtual: No local state for V{pin_num} to re-publish.")
        pass


#Example Usage 
if __name__ == '__main__':
    # --- Configuration ---
    BLYNK_AUTH_TOKEN = "YOUR_ACTUAL_BLYNK_AUTH_TOKEN" # IMPORTANT: Replace with your token
    WIFI_SSID = "YOUR_WIFI_SSID"
    WIFI_PASS = "YOUR_WIFI_PASSWORD"

    # --- Optional: Custom logger function ---
    def custom_logger(*args):
        """Simple custom logger that prepends a timestamp and 'BLYNK' tag."""
        timestamp_s = time.ticks_ms() // 1000
        print(f"[{timestamp_s}s BLYNK] {' '.join(map(str, args))}")

    # --- Network Connection (Example for ESP32/ESP8266) ---
    # This part is specific to your MicroPython board and how it connects to WiFi.
    # import network
    # sta_if = network.WLAN(network.STA_IF)
    # if not sta_if.isconnected():
    #     custom_logger(f"Connecting to WiFi network: {WIFI_SSID}...")
    #     sta_if.active(True)
    #     sta_if.connect(WIFI_SSID, WIFI_PASS)
    #     connect_attempts = 0
    #     # Wait for connection, with a timeout
    #     while not sta_if.isconnected() and connect_attempts < 20: # Approx 10 seconds timeout
    #         time.sleep_ms(500)
    #         connect_attempts += 1
    #         custom_logger(".", end="") # Progress indicator
    #     custom_logger("") # Newline after dots
    # 
    # if sta_if.isconnected():
    #     custom_logger("WiFi Connected. IP Address:", sta_if.ifconfig()[0])
    # else:
    #     custom_logger("WiFi Connection Failed. Please check credentials and network. Halting.")
    #     # machine.reset() # Or handle error appropriately, e.g., by blinking an LED
    #     raise RuntimeError("WiFi Connection Failed")


    # --- Initialize BlynkMQTT Client ---
    # Ensure network is connected before this step.
    blynk = BlynkMQTT(BLYNK_AUTH_TOKEN, 
                      log_func=custom_logger, # Use our custom logger
                      board_type="ESP32-DevKitC-Generic", # Example device info
                      fw_version="0.2.1-sdk-example",
                      app_name="BlynkMQTTSDKDemo/1.0")

    # --- Define Event Handlers using the @blynk.on decorator ---
    @blynk.on("connect")
    def handle_blynk_connect():
        custom_logger("Blynk: Successfully connected to MQTT server!")
        # Actions to perform on connection:
        blynk.virtual_write(0, f"MicroPython MQTT SDK v0.2.1 Connected at {time.ticks_ms()}")
        blynk.set_property("v0", "label", "Device Status") # Update widget label
        blynk.log_event("device_online", "Device connected via MQTT SDK v0.2.1 example.")
        
        # Example: Publish some metadata on connect
        try:
            mpy_ver = '.'.join(map(str, machine.version_tuple()))
        except AttributeError:
            mpy_ver = "unknown"
        blynk.publish_metadata({"sdk_example_version": "1.0", "micropython_version": mpy_ver})
        
        # Example: Publish location if you have GPS data (replace with actual data)
        # blynk.publish_location(37.8719, -122.2585, alt=30.5, hdop=1.2)


    @blynk.on("disconnect")
    def handle_blynk_disconnect():
        custom_logger("Blynk: Disconnected from MQTT server.")
        # Here you might want to implement reconnection logic or signal an error state (e.g., LED)

    @blynk.on("V1")  # Handler for virtual pin V1 WRITE events from server/app
    def handle_v1_write(value): # 'value' can be string, number, or list (for multi-value widgets)
        custom_logger(f"Blynk: V1 received raw value: '{value}' (type: {type(value)})")
        
        # Example: If V1 is a button, it might send "1" or "0" as strings.
        # If it's a slider, it might send a number or a list containing a number.
        processed_value = value
        if isinstance(value, list) and len(value) > 0:
            processed_value = value[0] # Take the first element if it's a list

        blynk.virtual_write(2, f"Echo from V1: {processed_value}") # Echo back to V2
        if isinstance(processed_value, (str, bytes)) and processed_value in ('1', b'1', 1):
            custom_logger("V1 Button/Switch turned ON")
            # Add your action for ON state, e.g., control a relay or LED
            blynk.virtual_write(3, "V1 is ON")
        elif isinstance(processed_value, (str, bytes)) and processed_value in ('0', b'0', 0):
            custom_logger("V1 Button/Switch turned OFF")
            # Add your action for OFF state
            blynk.virtual_write(3, "V1 is OFF")


    # Handler for server requesting a widget property value
    @blynk.on("property_get")
    def handle_property_get(pin_designator, property_name):
        custom_logger(f"Blynk: Server requested property '{property_name}' for pin '{pin_designator}'")
        if pin_designator == "v0" and property_name == "label":
            # Respond with the current label (this is just an example, could be dynamic)
            blynk.set_property("v0", "label", "Status (Updated via PropGet)")
        elif pin_designator == "v10": 
            # Example: if V10 widget needs its 'color' property
            if property_name == "color":
                # Send back the current color (e.g., if device logic changes it)
                blynk.set_property("v10", "color", "#00FF00") # Example: Green
            elif property_name == "isDisabled":
                blynk.set_property("v10", "isDisabled", False) # Example

    # Handler for automation execution responses
    @blynk.on("automation_response")
    def handle_automation_response(automation_id, status, message):
        custom_logger(f"Blynk: Automation ID {automation_id} response: Status='{status}', Message='{message or ''}'")
        if status == "success":
            blynk.virtual_write(8, f"Automation {automation_id} Succeeded")
        else:
            blynk.virtual_write(8, f"Automation {automation_id} Failed: {message or 'Unknown error'}")

    # Handler for custom OTA requests (if you implement custom OTA logic)
    # @blynk.on("ota_request")
    # def handle_ota_request(data):
    #    custom_logger(f"Blynk: Received Custom OTA Request: {data}")
    #    # Implement your custom OTA logic here.
    #    # This is highly application-specific.
    #    # Example steps:
    #    # 1. Acknowledge initiation:
    #    #    blynk.publish_ota_status("initiated", version=data.get("version"), size=data.get("expectedSize"))
    #    # 2. Download firmware from data.get("url")
    #    #    blynk.publish_ota_status("downloading", progress=50) # Optional progress
    #    # 3. Verify and flash firmware
    #    #    blynk.publish_ota_status("flashing")
    #    # 4. Report success or failure
    #    #    blynk.publish_ota_status("success", version=data.get("version"))
    #    #    OR
    #    #    blynk.publish_ota_status("failed", error_code=101, error_msg="Download failed")


    # --- Main Application Loop ---
    if blynk.connect(): # Attempt initial connection
        custom_logger("Initial connection to Blynk successful.")
        counter = 0
        last_sensor_data_send_time_s = time.ticks_seconds()
        last_uptime_send_time_s = time.ticks_seconds()

        while True:
            try:
                # Check if still connected, attempt to reconnect if not
                if not blynk.connected:
                    custom_logger("Blynk connection lost. Attempting to reconnect...")
                    if not blynk.connect(): # Try to reconnect
                        custom_logger("Reconnect failed. Will retry in 10 seconds.")
                        time.sleep(10) # Wait before retrying to avoid spamming connection attempts
                        continue # Skip the rest of the loop if not connected
                    else:
                        custom_logger("Reconnected to Blynk successfully!")
                
                blynk.run()  # Process incoming MQTT messages and maintain connection

                current_time_s = time.ticks_seconds() # Get current time in seconds

                # Send sensor data periodically (e.g., every 15 seconds)
                if time.ticks_diff(current_time_s, last_sensor_data_send_time_s) >= 15:
                    counter += 1
                    temperature = 20 + (counter % 10) # Simulated temperature
                    humidity = 50 + (counter % 20)    # Simulated humidity
                    custom_logger(f"Sending V5 (temp): {temperature}, V6 (humidity): {humidity}")
                    blynk.virtual_write(5, temperature) 
                    blynk.virtual_write(6, humidity)
                    
                    # Example: Send a notification if temperature is high
                    if temperature > 28:
                        blynk.notify(f"High temperature alert: {temperature}°C")
                    
                    # Example: Trigger an automation based on a condition
                    # if humidity < 55 and blynk.connected: # Ensure connected before triggering
                    #    blynk.trigger_automation(12345, state="on") # Replace 12345 with your automation ID

                    last_sensor_data_send_time_s = current_time_s

                # Send device uptime periodically (e.g., every 60 seconds)
                if time.ticks_diff(current_time_s, last_uptime_send_time_s) >= 60:
                    uptime_ms = time.ticks_ms()
                    uptime_s = uptime_ms // 1000
                    hours = uptime_s // 3600
                    minutes = (uptime_s % 3600) // 60
                    seconds = uptime_s % 60
                    uptime_str = f"{hours}h {minutes}m {seconds}s"
                    blynk.virtual_write(99, uptime_str) # Send uptime to V99
                    custom_logger(f"Device Uptime: {uptime_str}")

                    # Example: send a device log entry periodically
                    blynk.device_log("info", f"Device operational. Uptime: {uptime_str}. Counter: {counter}.")
                    last_uptime_send_time_s = current_time_s
                
                time.sleep_ms(50) # Small delay to yield processing to other tasks if any,
                                  # and to control the loop speed. Adjust as needed.

            except KeyboardInterrupt:
                custom_logger("Keyboard interrupt detected. Disconnecting and exiting...")
                break # Exit the main loop
            except Exception as e:
                custom_logger(f"An error occurred in the main loop: {e}")
                # Depending on the error, you might want to add more robust error handling,
                # like attempting a full device reset or a more aggressive reconnect strategy.
                time.sleep(5) # Wait a bit before continuing to avoid rapid error loops
    else:
        custom_logger("Failed to connect to Blynk on startup. Please check configuration and network.")

    # Cleanup: Disconnect from Blynk when the program ends
    if blynk.connected:
        blynk.disconnect()
    custom_logger("Program finished.")

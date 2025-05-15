# MicroPython Blynk MQTT SDK

A MicroPython library for connecting your IoT devices to the Blynk platform using the MQTT protocol. This SDK simplifies communication with Blynk, allowing you to send data, receive commands, and utilize various Blynk features with ease on MicroPython-compatible microcontrollers.

## Overview

This SDK provides a Pythonic interface to the [Blynk MQTT API](https://docs.blynk.io/en/blynk.cloud-mqtt-api/device-mqtt-api), tailored for the resource-constrained environment of MicroPython. It handles MQTT connection management (including automatic reconnection), message publishing, and subscription to relevant Blynk topics.

## Features

* **Easy Connection:** Simplified connection to the Blynk MQTT broker.
* **Authentication:** Handles authentication using your Blynk device token.
* **Virtual Pin Communication:**
    * `virtual_write()`: Send data from your device to virtual pins.
    * `@blynk.on("V<pin>")`: Decorator to handle commands/data sent from Blynk to virtual pins.
* **Automatic Reconnection:** Built-in mechanism to automatically attempt reconnection if the MQTT connection drops (configurable).
* **Device Information:** Publish device details like board type and firmware version (`publish_device_info`, `@blynk.on("info_get")`).
* **Widget Property Control:**
    * `set_property()`: Change widget properties (e.g., label, color) from your device.
    * `@blynk.on("property_get")`: Handle server requests for current widget property values.
* **Notifications:** Send push notifications to the Blynk app (`notify()`).
* **Event Logging:** Log events to the device timeline in Blynk (`log_event()`).
* **Device Logging:** Send internal device logs to Blynk for monitoring (`device_log()`).
* **Bridge Operations:** Send commands to other Blynk devices (`bridge_virtual_write()`).
* **Location Publishing:** Send device GPS coordinates (`publish_location()`).
* **Metadata Publishing:** Send custom key-value metadata (`publish_metadata()`).
* **Automation Control:**
    * `trigger_automation()`: Trigger Blynk automations from your device.
    * `@blynk.on("automation_response")`: Handle responses after triggering automations.
* **Custom OTA Support:** Hooks for implementing custom Over-The-Air firmware updates (`@blynk.on("ota_request")`, `publish_ota_status()`).
* **Flexible Logging:** Use standard `print` or provide your own custom logging function.
* **SSL/TLS Support:** Option to use secure MQTT connections (requires firmware support).

## Requirements

* A MicroPython-compatible microcontroller (e.g., ESP32, ESP8266, Raspberry Pi Pico W).
* MicroPython firmware installed on the device.
* The `umqtt.simple` library. This is part of `micropython-lib` and may need to be installed manually if not included in your firmware build.
    * You can find it here: [micropython-lib/umqtt.simple](https://github.com/micropython/micropython-lib/tree/master/umqtt.simple)
* An active internet connection for your MicroPython device.
* A Blynk account and a configured Blynk project with a device authentication token.

## Installation

1.  **Download the SDK:**
    Obtain the `blynk_mqtt_sdk.py` file from this repository.
2.  **Upload to Device:**
    Upload `blynk_mqtt_sdk.py` to the root directory of your MicroPython device's filesystem, or to a `lib` folder (ensure `lib` is in `sys.path`).
3.  **Install `umqtt.simple` (if needed):**
    If `umqtt.simple.py` is not already on your device or built into your firmware, download it from `micropython-lib` and upload it to the same location as the SDK (or your `lib` folder).

### Quick Start

Here's a basic example of how to use the SDK. For a more comprehensive example, see `demo.py`.

```python
# main.py
import time
from blynk_mqtt_sdk import BlynkMQTT # Ensure blynk_mqtt_sdk.py is on your device

# --- Configuration ---
BLYNK_AUTH_TOKEN = "YOUR_BLYNK_AUTH_TOKEN_HERE" # Replace with your actual token

# IMPORTANT: Ensure your device has an active internet connection
# (e.g., WiFi connected via a separate script or pre-configuration)

# --- Initialize BlynkMQTT Client ---
# SDK will use standard print for logging by default if log_func is not provided.
blynk = BlynkMQTT(
    auth_token=BLYNK_AUTH_TOKEN,
    log_func=print # Optional: use print for SDK logs
)

# --- Event Handlers ---
@blynk.on("connect")
def handle_connect():
    print("Blynk: Connected to server!")
    blynk.virtual_write(0, "MicroPython Client Connected!") # Send to V0
    blynk.set_property("V0", "label", "Device Status")

@blynk.on("disconnect")
def handle_disconnect():
    print("Blynk: Disconnected from server.")

@blynk.on("V1") # Handler for Virtual Pin V1
def handle_v1(value):
    print(f"Blynk: V1 received value: {value}")
    # Example: Echo value back to V2
    blynk.virtual_write(2, f"V1 sent: {value}")

# --- Main Loop ---
print("Attempting to connect to Blynk...")
if not blynk.connect():
    print("Initial connection failed. SDK will attempt to auto-reconnect.")

counter = 0
# Use time.ticks_ms() for timing in MicroPython
last_send_time_ms = time.ticks_ms()

while True:
    try:
        blynk.run() # CRITICAL: Process Blynk messages and manage connection

        if blynk.connected:
            current_time_ms = time.ticks_ms()
            # Send data every 10 seconds (10000 milliseconds)
            if time.ticks_diff(current_time_ms, last_send_time_ms) > 10000:
                counter += 1
                print(f"Sending counter to V5: {counter}")
                blynk.virtual_write(5, counter)
                last_send_time_ms = current_time_ms
        
        time.sleep_ms(50) # Small delay

    except KeyboardInterrupt:
        print("Program interrupted.")
        break
    except Exception as e:
        print(f"Error in main loop: {e}")
        time.sleep(5) # Wait before retrying loop

if blynk.connected:
    blynk.disconnect()
print("Program finished.")
```

## Detailed Usage
Initialization
```python
from blynk_mqtt_sdk import BlynkMQTT

blynk = BlynkMQTT(
    auth_token="YOUR_AUTH_TOKEN_HERE", # Replace with your actual token
    server="broker.blynk.cc",       # Optional: Default Blynk server
    port=None,                      # Optional: Default 1883 (TCP) or 8883 (SSL)
    client_id=None,                 # Optional: Auto-generated
    user=None,                      # Optional: Defaults to auth_token
    password="",                    # Optional: Defaults to empty
    ssl=False,                      # Optional: Set to True for SSL/TLS
    ssl_params={},                  # Optional: SSL parameters for MQTTClient
    log_func=print,                 # Optional: Your logging function
    keepalive=60,                   # Optional: MQTT keepalive in seconds
    board_type="MyBoard",           # Optional: For device info
    fw_version="1.0.0",             # Optional: For device info
    app_name="MyApp/1.0",           # Optional: For device info
    auto_reconnect=True,            # Optional: Enable/disable auto-reconnect (default True)
    reconnect_delay_s=10            # Optional: Delay between reconnect attempts (default 10s)
)
```

### Connecting and Disconnecting
- `blynk.connect(clean_session=True)`: Attempts to connect to the Blynk MQTT broker. Returns True on success, False on failure.
- `blynk.disconnect()`: Disconnects from the broker.
- `blynk.connected`: A boolean attribute indicating the current connection status.

### Running the Client
- `blynk.run()`: This method is crucial and must be called regularly and frequently in your main application loop. It:
    - Processes incoming MQTT messages from Blynk.
    - Manages MQTT keep-alive PINGs.
    - Handles automatic reconnection if `auto_reconnect` is enabled and the connection drops.
    
### Event Handling
Use the `@blynk.on("event_name")` decorator to register callback functions for various events:
- `@blynk.on("connect")`: Called upon successful connection/reconnection.
```python
@blynk.on("connect")
def my_connect_handler():
    print("Connected!")
```
- `@blynk.on("disconnect")`: Called when the connection is lost or blynk.disconnect() is called.
```python
@blynk.on("disconnect")
def my_disconnect_handler():
    print("Disconnected.")
```
- `@blynk.on("V<pin_number>")`: Called when data is received on a specific virtual pin from Blynk.
```python
@blynk.on("V0") # For virtual pin V0
def handle_v0_data(value): # 'value' can be string, number, or list
    print(f"V0 received: {value}")
```

- `@blynk.on("info_get")`: (Optional) Handle server requests for device info dynamically. If not set, SDK sends info provided during init.

- `@blynk.on("property_get")`: `handler(pin_designator, property_name)` - Handle server requests for widget property values. Your handler should call `blynk.set_property()` to respond.- `@blynk.on("automation_response")`: handler(automation_id, status, message) - Handle status of triggered automations.
- `@blynk.on("ota_request")`: `handler(data_dict)` - Handle custom OTA commands from Blynk.

### Sending Data and Commands
- `blynk.virtual_write(pin_number, *values)`: Send data to a virtual pin.
```python
blynk.virtual_write(1, "Hello Blynk")   # Send string to V1
blynk.virtual_write(2, 123.45)          # Send float to V2
blynk.virtual_write(3, 10, 20, "text")  # Send multiple values (as a list) to V3
```
- `blynk.set_property(pin_designator, property_name, value)`: Change a widget's property.blynk.
```python
set_property("V0", "label", "My Device Label")
blynk.set_property("V1", "color", "#FF0000") # Red color
```
- `blynk.notify(message)`: Send a push notification to the Blynk app.
```python
blynk.notify("Alert: Temperature too high!")
```
- `blynk.log_event(event_code, description="")`: Log an event to the device timeline.
```python
blynk.log_event("sensor_error", "Failed to read temperature sensor.")
```
- `blynk.device_log(level, message)`: Send a log to Blynk's internal device logging system. `level` can be "trace", "debug", "info", "warn", "error".
```python
blynk.device_log("warn", "Battery level low: 15%")
```
- `blynk.publish_device_info(board=None, fw_version=None, app_name=None)`: Send/update device info.
```python
blynk.publish_device_info(board="ESP32-DevKitC", fw_version="1.0.2-mqtt")
```
- `blynk.bridge_virtual_write(target_token, pin_designator, value)`: Send data to another Blynk device.
```python
# Assuming TARGET_AUTH_TOKEN is the token of the other device
blynk.bridge_virtual_write("TARGET_AUTH_TOKEN", "v10", "Data from bridge")
```
- `blynk.publish_location(lat, lon, alt=None, hdop=None)`: Publish GPS location.
```
# blynk.publish_location(34.0522, -118.2437, alt=71.0, hdop=1.0)
```
- `blynk.publish_metadata(metadata_dict)`: Publish custom key-value metadata.
```python
blynk.publish_metadata({"sensor_type": "BME280", "location": "Living Room"})
```
- `blynk.trigger_automation(automation_id, state=None, value=None)`: Trigger a Blynk automation.# Assuming automation ID 123 exists in your Blynk project
```python
blynk.trigger_automation(123, state="on")
```
- `blynk.publish_ota_status(status, version=None, size=None, error_code=None, error_msg=None)`: Report status for custom OTA.
```python
# Example for a custom OTA process
blynk.publish_ota_status("downloading", version="1.1.0", size=512000)
```

## Demo Application

A `demo.py` file is included in this repository, showcasing many of the SDK's features. It's a great starting point to understand how to integrate the SDK into your projects.

## Error Handling

Network errors during operations like publish or `run()` will typically result in the connection being marked as disconnected, triggering the auto-reconnect mechanism if enabled. The user's `@blynk.on("disconnect")` handler will also be called.

## Contributing

Contributions are welcome! Please feel free to submit pull requests, report issues, or suggest enhancements.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## License
This project is licensed under the MIT License. See the LICENSE.md file for details. You can find a copy of the MIT License text at https://opensource.org/licenses/MIT.

## Acknowledgements
This SDK was developed by referencing the capabilities of the Blynk MQTT API and drew structural inspiration from the original [blynk-library-python](https://github.com/vshymanskyy/blynk-library-python) SDK by Volodymyr Shymanskyy.
# demo.py
# Description: A simplified demonstration script for using the blynk_mqtt_sdk.py library
# This script shows the basic connection to Blynk using MQTT, sending data,
# and receiving commands. It relies on the SDK's auto-reconnection feature.
# NB: This version has WiFi connection logic and custom logger removed.
# Ensure your device has an active internet connection before running.

import time
import machine # For machine.unique_id(), machine.reset(), machine.version_tuple() (optional)
# Ensure blynk_mqtt_sdk.py is in the same directory or accessible in sys.path
try:
    from lib.blynk_mqtt_sdk import BlynkMQTT # Assuming SDK version 0.3.0+ with auto-reconnect
except ImportError:
    print("Error: blynk_mqtt_sdk.py not found. Please ensure it's in the same directory or in MicroPython's sys.path.")
    raise # Stop execution if the SDK is missing

# --- Configuration ---
# IMPORTANT: Replace these placeholders with your actual credentials and settings!
BLYNK_AUTH_TOKEN = "YOUR_ACTUAL_BLYNK_AUTH_TOKEN"  # Get this from your Blynk project

# --- Network Connection (Board-Specific) ---
# IMPORTANT: The WiFi connection logic has been removed from this demo script.
# You MUST ensure that your MicroPython device has an active and configured
# internet connection BEFORE running this script for it to communicate with Blynk.
print("Network connection setup is NOT included in this script.")
print("Please ensure your device is connected to the internet.")

# --- Initialize BlynkMQTT Client ---
print("Initializing BlynkMQTT client...")
# The SDK (version 0.3.0+) now has auto_reconnect=True by default.
# You can override reconnect_delay_s if needed, e.g., reconnect_delay_s=5
blynk = BlynkMQTT(
    auth_token=BLYNK_AUTH_TOKEN,
    log_func=print,  # Use standard print for SDK messages
    board_type="MicroPython Generic",
    fw_version="0.3.4-demo-sdk-reconnect", # Updated version for this change
    app_name="BlynkDemoApp/Simple",
    # auto_reconnect=True, # This is the default in SDK v0.3.0+
    # reconnect_delay_s=10 # Default is 10 seconds in SDK v0.3.0+
)

# --- Define Event Handlers using the @blynk.on decorator ---

@blynk.on("connect")
def handle_blynk_connect():
    """This function is called when the SDK successfully connects to the Blynk MQTT server."""
    print("Blynk: Successfully connected (or reconnected) to MQTT server!")
    
    blynk.virtual_write(0, f"MPy Demo Connected at {time.ticks_ms()}")
    blynk.set_property("v0", "label", "Device Status")
    blynk.log_event("device_script_started", "Simplified demo connected.")
    
    board_id_str = 'N/A'
    try:
        if hasattr(machine, 'unique_id') and callable(machine.unique_id):
            uid_bytes = machine.unique_id()
            board_id_str = "".join(["{:02x}".format(b) for b in uid_bytes])
    except Exception as e:
        print(f"Could not retrieve board_id: {e}")

    blynk.publish_metadata({
        "demo_script_version": "1.3.0-sdk-reconnect",
        "board_id": board_id_str
    })
    print("Blynk: On-connect tasks complete.")

@blynk.on("disconnect")
def handle_blynk_disconnect():
    """This function is called when the SDK disconnects from the Blynk MQTT server."""
    print("Blynk: Disconnected from MQTT server. SDK will attempt to reconnect if auto_reconnect is enabled.")

@blynk.on("V1")
def handle_v1_write(value):
    """Handles incoming data on Virtual Pin V1 from the Blynk app/server."""
    print(f"Blynk: V1 received raw value: '{value}' (type: {type(value)})")
    
    processed_value = value
    if isinstance(value, list) and len(value) > 0:
        processed_value = value[0]

    blynk.virtual_write(2, f"V1 Echo: {processed_value}")
    
    if str(processed_value) == '1':
        print("V1: Command ON received.")
        blynk.virtual_write(3, "V1 is ON")
        # Add your code here to turn something ON
    elif str(processed_value) == '0':
        print("V1: Command OFF received.")
        blynk.virtual_write(3, "V1 is OFF")
        # Add your code here to turn something OFF

@blynk.on("property_get")
def handle_property_get(pin_designator, property_name):
    """Handles requests from the Blynk server to get the current value of a widget property."""
    print(f"Blynk: Server requested property '{property_name}' for pin '{pin_designator}'")
    if pin_designator == "v0" and property_name == "label":
        uptime_s = time.ticks_ms() // 1000
        blynk.set_property("v0", "label", f"Online ({uptime_s}s)")
    elif pin_designator == "v5" and property_name == "color":
        blynk.set_property("v5", "color", "#00FF00")

@blynk.on("automation_response")
def handle_automation_response(automation_id, status, message):
    """Handles the server's response after an automation has been triggered by this device."""
    print(f"Blynk: Automation ID {automation_id} response: Status='{status}', Message='{message or ''}'")
    if status == "success":
        blynk.virtual_write(8, f"Auto {automation_id} OK")
    else:
        blynk.virtual_write(8, f"Auto {automation_id} Fail: {message or 'Unknown'}")

# --- Main Application Loop ---
def main_loop():
    """Main operational loop for the Blynk demo application."""
    print("Starting main application loop...")
    
    # Attempt initial connection.
    # Even with auto-reconnect in the SDK, an initial explicit connect is good practice.
    # The SDK's auto-reconnect will take over if this initial connection fails
    # or if the connection drops later.
    if not blynk.connect():
        print("Initial connection to Blynk failed. SDK will attempt to auto-reconnect if enabled.")
        # The loop will continue, and blynk.run() will handle reconnection attempts.

    counter = 0
    last_data_send_time_s = time.ticks_seconds()
    last_uptime_send_time_s = time.ticks_seconds()

    while True:
        try:
            # --- Call blynk.run() periodically ---
            # This is CRITICAL for Blynk communication.
            # With SDK v0.3.0+, blynk.run() is responsible for:
            #   1. Processing incoming MQTT messages from the Blynk server.
            #   2. Allowing the underlying MQTT library to handle keep-alive PINGs.
            #   3. Handling automatic reconnection if the connection is lost
            #      (provided auto_reconnect is enabled, which is the default).
            #   4. Basic error handling for message processing.
            blynk.run()


            # --- Your Application Logic ---
            # This code can run regardless of immediate connection status,
            # but operations that require Blynk (like virtual_write) will only succeed
            # if blynk.connected is True (which blynk.run() tries to maintain).
            # It's good practice to check blynk.connected before performing Blynk operations
            # if you want to avoid attempts when disconnected, or to handle that case specifically.
            
            current_time_s = time.ticks_seconds()

            # Send simulated data periodically (only if connected)
            if blynk.connected: # Check if connected before trying to send data
                if time.ticks_diff(current_time_s, last_data_send_time_s) >= 15:
                    counter += 1
                    print(f"Sending V5 (counter): {counter}")
                    # virtual_write will return False if not connected or publish fails
                    if not blynk.virtual_write(5, counter):
                         print("Failed to send V5 data (likely disconnected).")
                    
                    if counter % 10 == 0:
                        blynk.notify(f"Device counter reached {counter}!")
                    
                    last_data_send_time_s = current_time_s

                # Send device uptime periodically (only if connected)
                if time.ticks_diff(current_time_s, last_uptime_send_time_s) >= 60:
                    uptime_s_total = time.ticks_ms() // 1000
                    if not blynk.virtual_write(99, uptime_s_total): # Send uptime in seconds to V99
                        print("Failed to send uptime data (likely disconnected).")
                    else:
                        print(f"Device Uptime: {uptime_s_total}s")

                    blynk.device_log("info", f"Device uptime: {uptime_s_total}s. Counter: {counter}.")
                    last_uptime_send_time_s = current_time_s
            else:
                # Optional: Add logic here if you want to do something specific when disconnected,
                # e.g., print a status, blink an LED, or pause certain tasks.
                # For this demo, we'll just let blynk.run() handle reconnection attempts.
                # print("Currently disconnected from Blynk. SDK is attempting to reconnect...")
                pass # blynk.run() handles reconnection attempts
            
            # A small delay to control the loop speed and allow MicroPython to handle
            # other background tasks if any.
            time.sleep_ms(100) # Increased slightly as blynk.run() now does more

        except KeyboardInterrupt:
            print("Keyboard interrupt detected. Disconnecting and exiting...")
            break # Exit the main while loop
        except Exception as e:
            print(f"An unexpected error occurred in the main loop: {e}")
            # Potentially add more robust error handling here.
            time.sleep(5) # Wait a bit before continuing to avoid rapid error loops

# --- Script Execution ---
if __name__ == "__main__":
    try:
        main_loop()
    except Exception as e:
        print(f"Critical error in script execution: {e}")
    finally:
        # Cleanup: Disconnect from Blynk when the program finishes or is interrupted
        if 'blynk' in locals() and blynk and blynk.connected:
            print("Disconnecting from Blynk before exiting.")
            blynk.disconnect() # Explicitly disconnect
        print("Program finished.")

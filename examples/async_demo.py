# async_demo.py
# Description: Minimal async example for lib/blynk_mqtt_sdk_async.py.
#
# Ensure your MicroPython device has network connectivity before running.

import uasyncio as asyncio

try:
    from lib.blynk_mqtt_sdk_async import BlynkMQTT
except ImportError:
    from blynk_mqtt_sdk_async import BlynkMQTT


BLYNK_AUTH_TOKEN = "YOUR_BLYNK_AUTH_TOKEN"
BLYNK_TEMPLATE_ID = "YOUR_TEMPLATE_ID"


async def main():
    blynk = BlynkMQTT(
        auth_token=BLYNK_AUTH_TOKEN,
        template_id=BLYNK_TEMPLATE_ID,
        ssl=False,
        log_func=print,
        firmware_version="async-demo-1.0.0",
    )

    @blynk.on("connect")
    async def on_connect():
        print("Blynk connected")
        blynk.batch_set_values({
            "Temperature": 25.0,
            "Status": "online",
        })
        blynk.get_all_values()

    @blynk.on("disconnect")
    def on_disconnect():
        print("Blynk disconnected")

    @blynk.on("message")
    def on_message(topic, msg):
        print("Blynk message:", topic, msg)
        if topic.startswith("downlink/ds/"):
            datastream = topic[len("downlink/ds/"):]
            print("Datastream update:", datastream, msg)

    await blynk.start()

    counter = 0
    while True:
        if blynk.connected:
            counter += 1
            blynk.set_value("Counter", counter)
        await asyncio.sleep(10)


asyncio.run(main())

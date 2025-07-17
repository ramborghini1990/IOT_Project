import requests
import time
import threading
from flask import Flask, jsonify
from MyMQTT2 import MyMQTT

class Adaptor:
    def __init__(self):
        self.clientID = "ThingSpeak_Adaptor"
        self.broker = "test.mosquitto.org"
        self.port = 1883
        self.channel_API = "https://api.thingspeak.com/update"
        self.last_motion_time = {}
        self.latest_light_value = {}
        self.light_status = {}
        self.last_update = {}  # Stores timestamps per device


        # Map unit IDs to channel info and field
        self.unit_config = {
            "1-1-1": {"channel": "house1", "field": "field1", "api_key": "TYJBKZK6C3VMU6X0"},
            "1-1-2": {"channel": "house1", "field": "field2", "api_key": "TYJBKZK6C3VMU6X0"},
            "1-2-1": {"channel": "house1", "field": "field3", "api_key": "TYJBKZK6C3VMU6X0"},
            "2-1-1": {"channel": "house2", "field": "field1", "api_key": "639Q1WGL7VNX405K"},
            "2-1-2": {"channel": "house2", "field": "field2", "api_key": "639Q1WGL7VNX405K"},
            "2-2-1": {"channel": "house2", "field": "field3", "api_key": "639Q1WGL7VNX405K"},
        }

        self.fields_order = {
            "house1": ["field1", "field2", "field3"],
            "house2": ["field1", "field2", "field3"]
        }

        self.buffers = {
            "house1": {"field1": 0, "field2": 0, "field3": 0},
            "house2": {"field1": 0, "field2": 0, "field3": 0}
        }

        self.api_keys = {
            "house1": "TYJBKZK6C3VMU6X0",
            "house2": "639Q1WGL7VNX405K"
        }

        self.lock = threading.Lock()

        self.client = MyMQTT(self.clientID, self.broker, self.port, self)
        self.client.start()

        for unit in self.unit_config:
            h, f, u = unit.split("-")
            topic = f"ThiefDetector/sensors/{h}/{f}/{u}/#"
            self.client.mySubscribe(topic)
            print(f"[SUBSCRIBE] {unit} → {topic}")

        self.schedule_update("house1")
        self.schedule_update("house2")

    def schedule_update(self, channel):
        threading.Timer(15, self.flush_channel, args=(channel,)).start()

    def flush_channel(self, channel):
        with self.lock:
            data = self.buffers[channel].copy()
            api_key = self.api_keys[channel]
            url = f"{self.channel_API}?api_key={api_key}"
            for field in self.fields_order[channel]:
                value = data.get(field, 0)
                url += f"&{field}={value}"
            try:
                r = requests.get(url)
                print(f"[THING] {channel} → {data} → {r.status_code}")
            except Exception as e:
                print(f"[ERROR] Failed to update {channel}: {e}")
        self.schedule_update(channel)

    def notify(self, topic, payload):
        print(f"[MQTT] {topic} → {payload}")
        tokens = topic.split("/")
        if len(tokens) < 6:
            return

        unit_key = f"{tokens[2]}-{tokens[3]}-{tokens[4]}"
        sensor_type = tokens[5]
        event = payload["e"][0]
        value = event["v"]
        now = time.time()

        if unit_key not in self.unit_config:
            print(f"[WARN] No config for unit {unit_key}, skipping.")
            return

        config = self.unit_config[unit_key]
        channel = config["channel"]
        field = config["field"]

        if unit_key not in self.last_motion_time:
            self.last_motion_time[unit_key] = 0
        if unit_key not in self.light_status:
            self.light_status[unit_key] = 0
        if unit_key not in self.latest_light_value:
            self.latest_light_value[unit_key] = 0

        if sensor_type == "motion_sensor":
            if value == "Detected":
                self.last_motion_time[unit_key] = now
                self.light_status[unit_key] = 1
                self.last_update[unit_key] = time.strftime("%Y-%m-%d %H:%M:%S")


        elif sensor_type == "light_sensor":
            self.latest_light_value[unit_key] = float(value)
            self.last_update[unit_key] = time.strftime("%Y-%m-%d %H:%M:%S")


        time_since_motion = now - self.last_motion_time[unit_key]
        lux = self.latest_light_value[unit_key]

        if time_since_motion > 30 and lux > 400:
            self.light_status[unit_key] = 0
        else:
            self.light_status[unit_key] = 1

        with self.lock:
            self.buffers[channel][field] = self.light_status[unit_key]
            self.last_update[unit_key] = time.strftime("%Y-%m-%d %H:%M:%S")


    def get_channels_detail(self):
        channels = {}
        for unit_key, info in self.unit_config.items():
            channel = info["channel"]
            field = info["field"]

            if channel not in channels:
                channels[channel] = {
                    "channelId": channel,
                    "fields": {}
                }

            if field not in channels[channel]["fields"]:
                field_name = "Light or Motion"  # Customize later based on real mapping
                channels[channel]["fields"][field] = field_name
        return channels


# ---- FLASK APP TO SERVE ENDPOINT ----
app = Flask(__name__)
adaptor = Adaptor()

@app.route("/channels_detail", methods=["GET"])
def get_channel_detail_endpoint():
    return jsonify(adaptor.get_channels_detail())

@app.route("/devices", methods=["GET"])
def get_devices():
    device_list = []

    # 1. existing light_sensor entries
    for unit_key, status in adaptor.light_status.items():
        h, f, u = unit_key.split("-")
        device_list.append({
            "deviceID": int(f"{h}{f}{u}"),
            "deviceName": "light_sensor",
            "deviceStatus": "ON" if status else "OFF",
            "availableStatuses": ["DISABLE", "OFF", "ON"],
            "deviceLocation": {
                "houseID": int(h),
                "floorID": int(f),
                "unitID": int(u)
            },
            "measureType": ["light"],
            "availableServices": ["MQTT"],
            "servicesDetails": [{
                "serviceType": "MQTT",
                "topic": [f"ThiefDetector/sensors/{h}/{f}/{u}/light_sensor"]
            }],
            "lastUpdate": adaptor.last_update.get(unit_key, "NEVER")
        })

    # 2. add motion_sensor entries
    now = time.time()
    THRESHOLD = 30  # seconds of inactivity before reporting “No Motion”
    for unit_key, ts in adaptor.last_motion_time.items():
        h, f, u = unit_key.split("-")
        status = "Detected" if (now - ts) < THRESHOLD else "No Motion"
        device_list.append({
            # offset by 1000 to give motion sensors distinct IDs
            "deviceID": int(f"{h}{f}{u}") + 1000,
            "deviceName": "motion_sensor",
            "deviceStatus": status,
            "availableStatuses": ["Detected", "No Motion"],
            "deviceLocation": {
                "houseID": int(h),
                "floorID": int(f),
                "unitID": int(u)
            },
            "measureType": ["motion"],
            "availableServices": ["MQTT"],
            "servicesDetails": [{
                "serviceType": "MQTT",
                "topic": [f"ThiefDetector/sensors/{h}/{f}/{u}/motion_sensor"]
            }],
            "lastUpdate": adaptor.last_update.get(unit_key, "NEVER")
        })

    return jsonify({"devicesList": device_list})

if __name__ == "__main__":
    threading.Thread(target=app.run, kwargs={"port": 8099}).start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[EXIT] Stopped by user.")

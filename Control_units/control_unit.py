
import json
import time
import sched
import requests
import copy
import os
from datetime import datetime
from MyMQTT2 import MyMQTT

# Mapping from (houseID, floorID, unitID) to deviceID for light_switch
DEVICE_ID_MAPPING = {
    (1, 1, 1): 10101,
    (1, 1, 2): 10102,
    (1, 2, 1): 10103,
    (2, 1, 1): 20101,
    (2, 1, 2): 20102,
    (2, 2, 1): 20103,
}

class Controler():
    def __init__(self, catalogAddress):
        self.catalogAddress = catalogAddress.rstrip('/')
        self.clientID = "ThiefDetector_Controller"
        self.main_topic = self.get_main_topic()  # From catalog
        self.sensor_topics = [f"{self.main_topic}/sensors/", f"{self.main_topic.lower()}/sensors/"]
        self.hierarchy = []
        self.PERIODIC_UPDATE_INTERVAL = 60
        self.device_status_cache = {}  # cache to prevent redundant catalog updates
        self.last_motion_time = {}  # (h, f, u) -> timestamp
        self.latest_light_level = {}  # (h, f, u) -> float

        if not os.path.exists("deduplication_done.flag"):
            self.clean_duplicate_devices()
            with open("deduplication_done.flag", "w") as f:
                f.write("done")

        try:
            broker, port = self.get_broker()
            self.client = MyMQTT(self.clientID, broker, port, self)
            self.client.start()
        except Exception as e:
            print(f"Failed to initialize MQTT client: {e}")
            return

        self.scheduler = sched.scheduler(time.time, time.sleep)
        self.scheduler.enter(0, 1, self.periodic_hierarchy_update, ())
        self.scheduler.enter(10, 2, self.check_lights_off, ())
        self.scheduler.run(blocking=False)

        self.msg = {
            "bn": None,
            "e": [{"n": "actuator", "u": "command", "t": None, "v": None}]
        }

    def notify(self, topic, payload):
        try:
            msg = payload if isinstance(payload, dict) else json.loads(payload)
        except Exception as e:
            print(f"[ERROR] invalid JSON payload: {e}")
            return
        if "e" not in msg or not msg["e"]:
            print("[WARN] missing 'e' in message")
            return
        event = msg["e"][0]
        sensor_val = event.get("v")
        sensor_time = event.get("t")
        try:
            ts = float(sensor_time)
            readable = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except:
            readable = sensor_time
        parts = topic.split("/")
        if len(parts) < 6:
            print(f"[WARN] unexpected topic format: {topic}")
            return
        _, _, houseID, floorID, unitID, sensorType = parts[:6]
        try:
            h, f, u = int(houseID), int(floorID), int(unitID)
        except ValueError:
            print("[ERROR] non-int IDs in topic")
            return
        if sensorType == "motion_sensor":
            self.process_motion(h, f, u, sensor_val, readable)
        elif sensorType == "light_sensor":
            self.process_light(h, f, u, sensor_val)

    def process_motion(self, houseID, floorID, unitID, motion_detected, readable_time):
        key = (houseID, floorID, unitID)
        if motion_detected == "Detected":
            self.last_motion_time[key] = time.time()
            print(f"[ALERT] Motion in {houseID}/{floorID}/{unitID} at {readable_time}")
            self.send_command(houseID, floorID, unitID, "light_switch", "ON")
            self.update_catalog(houseID, floorID, unitID, "ON")

    def process_light(self, houseID, floorID, unitID, light_level):
        key = (houseID, floorID, unitID)
        self.latest_light_level[key] = float(light_level)

    def check_lights_off(self):
        now = time.time()
        for key, last_motion in self.last_motion_time.items():
            if now - last_motion > 30:
                light_level = self.latest_light_level.get(key, 0)
                if light_level > 400:
                    h, f, u = key
                    print(f"[ACTION] No motion & bright -> Turn OFF light in {h}/{f}/{u}")
                    self.send_command(h, f, u, "light_switch", "OFF")
                    self.update_catalog(h, f, u, "OFF")
        self.scheduler.enter(10, 2, self.check_lights_off, ())

    def send_command(self, houseID, floorID, unitID, device_name, command):
        base = self.main_topic.lower()
        topic = f"{base}/commands/{houseID}/{floorID}/{unitID}/{device_name}"
        msg = copy.deepcopy(self.msg)
        msg["bn"] = topic
        msg["e"][0]["t"] = str(time.time())
        msg["e"][0]["v"] = command
        self.client.myPublish(topic, msg)
        print(f"[CMD] {command} -> {topic}")
        url = f"http://127.0.0.1:8086/arduino_{houseID}-{floorID}-{unitID}/device_status"
        payload = {
            "deviceID": DEVICE_ID_MAPPING[(houseID, floorID, unitID)],
            "status": command
        }
        try:
            requests.put(url, json=payload)
            print(f"[HTTP] Sent command to actuator REST: {url}")
        except Exception as e:
            print(f"[ERROR] Could not update actuator REST endpoint: {e}")

    def update_catalog(self, houseID, floorID, unitID, new_status):
        did = DEVICE_ID_MAPPING.get((houseID, floorID, unitID))
        if not did:
            return
        cache_key = (houseID, floorID, unitID)
        last_status = self.device_status_cache.get(cache_key)
        if last_status == new_status:
            print(f"[CACHE] Status unchanged for {cache_key}, skipping catalog update")
            return
        self.device_status_cache[cache_key] = new_status

        payload = {
            "deviceID": did,
            "deviceLocation": {
                "houseID": str(houseID),
                "floorID": str(floorID),
                "unitID": str(unitID)
            },
            "deviceName": "light_switch",
            "deviceStatus": new_status,
            "lastUpdate": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        try:
            r = requests.put(f"{self.catalogAddress}/devices", json=payload)
            print(f"[CATALOG] Status updated for {did} -> {new_status}, code: {r.status_code}")
        except Exception as e:
            print(f"[ERROR] updating catalog: {e}")

    def get_broker(self):
        r = requests.get(f"{self.catalogAddress}/broker")
        b = r.json()
        return b.get("IP"), int(b.get("port"))

    def get_main_topic(self):
        try:
            r = requests.get(f"{self.catalogAddress}/topic")
            return r.text.strip('"')
        except:
            return "ThiefDetector"

    def periodic_hierarchy_update(self):
        try:
            resp = requests.get(f"{self.catalogAddress}/houses")
            houses = resp.json()
            new = [(int(h["houseID"]), int(f["floorID"]), int(u["unitID"]))
                   for h in houses for f in h.get("floors", []) for u in f.get("units", [])]
            self.subscribe_main_topic(new)
        except Exception as e:
            print(f"[ERROR] hierarchy update: {e}")
        finally:
            self.scheduler.enter(self.PERIODIC_UPDATE_INTERVAL, 1, self.periodic_hierarchy_update, ())

    def subscribe_main_topic(self, new_hierarchy):
        new = set(new_hierarchy)
        for add in new:
            for base in self.sensor_topics:
                sub = f"{base}{add[0]}/{add[1]}/{add[2]}/#"
                self.client.mySubscribe(sub)
        self.hierarchy = list(new_hierarchy)

    def subscribe_to_topics(self, units):
        tuples = []
        for token in units:
            try:
                h, f, u = map(int, token.split('-'))
                tuples.append((h, f, u))
            except ValueError:
                print(f"[WARN] bad unit format: {token}")
        self.subscribe_main_topic(tuples)

    def clean_duplicate_devices(self):
        try:
            devs = requests.get(f"{self.catalogAddress}/devices").json()
            latest = {}
            for d in devs:
                id, ts = d["deviceID"], datetime.strptime(d.get("lastUpdate"), "%Y-%m-%d %H:%M:%S")
                if id not in latest or ts > latest[id][1]:
                    latest[id] = (d, ts)
            for d in devs:
                if d["deviceID"] in latest and d != latest[d["deviceID"]][0]:
                    requests.delete(f"{self.catalogAddress}/devices?deviceID={d['deviceID']}")
        except Exception as e:
            print(f"[ERROR] cleanup duplicates: {e}")

if __name__ == "__main__":
    ctl = Controler("http://127.0.0.1:8080")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        ctl.client.stop()
 
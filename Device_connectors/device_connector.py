import requests
import time
import json
import copy
import cherrypy
import logging

from MyMQTT import MyMQTT
from sensors import LightSensor, MotionSensor

last_motion_times = {}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class senPublisher():
    def __init__(self, clientID, broker, port):
        self.client = MyMQTT(clientID, broker, port, None)
        self.start()

    def start(self):
        self.client.start()

    def stop(self):
        self.client.stop()

    def publish(self, topic, msg):
        print(f"[PUBLISH] Topic: {topic}, Message: {msg}")
        self.client.myPublish(topic, msg)

class Device_connector():
    exposed = True

    def __init__(self, catalog_url, DCConfiguration, baseClientID, houseID, floorID, unitID):
        self.catalog_url = catalog_url
        self.DCConfiguration = DCConfiguration if DCConfiguration else {"devices": []}
        self.houseID = houseID
        self.floorID = floorID
        self.unitID = unitID

        self.clientID = f"{baseClientID}_{houseID}_{floorID}_{unitID}_DCS"
        self.DATA_AVG_INTERVAL = self.DCConfiguration.get("DATA_AVG_INTERVAL", 10)
        self.DATA_SENDING_INTERVAL = self.DCConfiguration.get("DATA_SENDING_INTERVAL", 30)  # Increased interval

        try:
            broker, port = self.get_broker()
        except Exception as e:
            logger.error(f"Failed to get broker info: {e}")
            return

        self.senPublisher = senPublisher(self.clientID, broker, port)
        self.light_sensor = LightSensor(f"{houseID}_{floorID}_{unitID}_light")
        self.motion_sensor = MotionSensor(f"{houseID}_{floorID}_{unitID}_motion")

        self.msg_template = {
            "bn": f"ThiefDetector/sensors/{houseID}/{floorID}/{unitID}/",
            "e": [
                {
                    "n": "sensorKind",
                    "u": "unit",
                    "t": None,
                    "v": None
                }
            ]
        }

        self.registerer()

    @cherrypy.tools.json_out()
    def GET(self, *uri, **params):
        if len(uri) != 0:
            if uri[0].lower() == "devices":
                return self.DCConfiguration
            else:
                return "Invalid endpoint. Try /devices"
        return "Go to /devices to see the device configuration"

    def send_data(self):
        logger.info("Started publishing sensor data...")
        try:
            while True:
                msg_light, msg_motion = self.get_sen_data()

                # === 1. Update and publish light sensor ===
                device_payload = copy.deepcopy(self.DCConfiguration["devicesList"][0])
                device_payload["deviceStatus"] = "ON"
                device_payload["lastUpdate"] = time.strftime("%Y-%m-%d %H:%M:%S")

                try:
                    requests.put(f"{self.catalog_url}devices", json=device_payload)
                    print(f"[CATALOG] Light sensor {device_payload['deviceID']} updated.")
                except Exception as e:
                    print(f"[ERROR] Could not update light sensor in catalog: {e}")
                self.senPublisher.publish(msg_light["bn"], msg_light)
                logger.info(f"Published light data: {msg_light['e'][0]['v']} to topic: {msg_light['bn']}")
                time.sleep(self.DATA_SENDING_INTERVAL)

                # === 2. Update and publish motion sensor ===
                self.senPublisher.publish(msg_motion["bn"], msg_motion)
                logger.info(f"Published motion data: {msg_motion['e'][0]['v']} to topic: {msg_motion['bn']}")
                time.sleep(self.DATA_SENDING_INTERVAL)

                # === 3. Register motion sensor for each unit ===
                for config in self.DCConfiguration["devicesList"]:
                    unit_id = config["deviceLocation"]["unitID"]
                    floor_id = config["deviceLocation"]["floorID"]
                    house_id = config["deviceLocation"]["houseID"]
                    device_id = config["deviceID"]

                    topic = f"ThiefDetector/sensors/{house_id}/{floor_id}/{unit_id}/motion_sensor"
                    msg_motion = {
                        "bn": topic,
                        "e": [{
                            "n": "motion",
                            "u": "status",
                            "t": str(time.time()),
                            "v": "Detected"
                        }]
                    }

                    motion_payload = {
                        "deviceID": device_id + 1000,
                        "deviceName": "motion_sensor",
                        "deviceStatus": "Detected",
                        "availableStatuses": ["Detected", "No Motion"],
                        "deviceLocation": {
                            "houseID": house_id,
                            "floorID": floor_id,
                            "unitID": unit_id
                        },
                        "measureType": ["motion"],
                        "availableServices": ["MQTT"],
                        "servicesDetails": [{
                            "serviceType": "MQTT",
                            "topic": [topic]
                        }],
                        "lastUpdate": time.strftime("%Y-%m-%d %H:%M:%S")
                    }

                    try:
                        requests.put(f"{self.catalog_url}devices", json=motion_payload)
                        print(f"[CATALOG] Motion sensor updated for {unit_id}")
                    except Exception as e:
                        print(f"[ERROR] Could not update motion sensor for {unit_id}: {e}")

                    # ✅ Safely append to devicesList if not already present
                    if not any(dev["deviceID"] == motion_payload["deviceID"] for dev in self.DCConfiguration["devicesList"]):
                        self.DCConfiguration["devicesList"].append(motion_payload)

        except KeyboardInterrupt:
            logger.info("send_data loop stopped by user.")
        except Exception as e:
            logger.error(f"Error in send_data: {e}")
        finally:
            self.senPublisher.stop()
            logger.info("MQTT publisher stopped.")


    def get_sen_data(self):
        light_readings = []
        motion_readings = []
        unit_key = f"{self.houseID}-{self.floorID}-{self.unitID}"

        for _ in range(self.DATA_AVG_INTERVAL):
            light_val = self.light_sensor.generate_data()
            motion_val = self.motion_sensor.generate_data()

            light_readings.append(light_val)

            now = time.time()
            if motion_val and (unit_key not in last_motion_times or now - last_motion_times[unit_key] > 30):
                motion_readings.append(True)
                last_motion_times[unit_key] = now
            else:
                motion_readings.append(False)

            time.sleep(1)

        avg_light = round(sum(light_readings) / len(light_readings), 2)
        avg_motion = "Detected" if any(motion_readings) else "No Motion"

        msg_light = copy.deepcopy(self.msg_template)
        msg_light["bn"] += "light_sensor"
        msg_light["e"][0].update({
            "n": "light",
            "u": "lux",
            "t": str(time.time()),
            "v": avg_light
        })

        msg_motion = copy.deepcopy(self.msg_template)
        msg_motion["bn"] += "motion_sensor"
        msg_motion["e"][0].update({
            "n": "motion",
            "u": "status",
            "t": str(time.time()),
            "v": avg_motion
        })

        return msg_light, msg_motion

    def get_broker(self):
        try:
            response = requests.get(self.catalog_url + "broker")
            broker_info = response.json()
            logger.info("Broker info fetched successfully.")
            return broker_info["IP"], int(broker_info["port"])
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching broker info: {e}")
            raise

    def registerer(self):
        try:
            response = requests.post(self.catalog_url + "devices", json=self.DCConfiguration)
            if response.status_code in [200, 201]:
                logger.info("Device(s) registered successfully with the catalog.")
            elif response.status_code == 202:
                logger.info("Device(s) already exist, possibly updating them.")
                requests.put(self.catalog_url + "devices", json=self.DCConfiguration)
            else:
                logger.warning(f"Unexpected response from catalog: {response.text}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Error registering device(s) with the catalog: {e}")

if __name__ == "__main__":
    catalog_url = "http://127.0.0.1:8080/"
    with open('Device_connectors\\setting_sen.json') as f:
        settings = json.load(f)

    deviceConnectors = {}
    for DCID, config in settings["DCID_dict"].items():
        houseID = config["houseID"]
        floorID = config["floorID"]
        unitID  = config["unitID"]

        deviceConnectors[DCID] = Device_connector(
            catalog_url,
            config,
            settings["clientID"],
            houseID,
            floorID,
            unitID
        )

    try:
        while True:
            time.sleep(1)
            for dc in deviceConnectors.values():
                dc.send_data()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
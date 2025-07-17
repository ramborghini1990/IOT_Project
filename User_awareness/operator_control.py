import requests
import cherrypy
import sched
import time
import datetime
import json
import os

class OperatorControl:
    exposed = True

    def __init__(self, catalog_address, adaptor_url, thingspeak_channels_url="https://api.thingspeak.com/channels/"):
        self.catalog_address = catalog_address
        self.adaptor_url = adaptor_url
        self.thingspeak_channels_url = thingspeak_channels_url
        self.PERIODIC_UPDATE_INTERVAL = 10  # Seconds between updates
        self.catalog_path = 'catalog.json'
        self.houses = None
        self.real_time_houses = {}
        self.base_url_actuators = None
        self.channels_detail = None
        self.motion_alerts = {}  # store unitID → timestamp
        
        # Load device ownership map
        try:
            with open('device_ownership.json', 'r') as f:
                self.device_ownership = json.load(f)
        except Exception as e:
            print(f"Error loading device ownership: {e}")
            self.device_ownership = {}

        self.scheduler = sched.scheduler(time.time, time.sleep)
        # Initial update - try immediately
        self.scheduler.enter(0, 1, self.periodic_house_list_update, ())
        self.scheduler.run(blocking=False)

    @cherrypy.tools.json_out()
    def GET(self, *uri, **params):
        if len(uri) != 0:
            if uri[0] == "houses":
                # Update real-time data before returning
                self.get_realtime_house()
                
                if len(uri) > 1:
                    return self.real_time_houses.get(uri[1])
                return self.real_time_houses

            elif uri[0] == "channels_detail":
                if len(uri) > 1:
                    return self.get_channel_detail(uri[1])
                return "Enter the name of the Thingspeak channel."

            elif uri[0] == "sensing_data":
                if len(uri) > 1:
                    return self.get_latest_sensing_data(uri[1])
                return "Enter the name of the Thingspeak channel."

            elif uri[0] == "health":
                return {"status": "Operator Control is running."}
            
            elif uri[0] == "motion_alerts":
                # Return only active alerts (within the last 5 minutes)
                alerts = []
                now = time.time()
                for unit_key, ts in self.motion_alerts.items():
                    if now - ts < 300:  # 5 minutes
                        alerts.append(unit_key)
                return {"activeAlerts": alerts}

            return "Invalid URL. Visit '/houses' or '/channels_detail' for information."
        return "Visit '/houses' or '/channels_detail' or /motion_alerts for information."

    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def POST(self, *uri, **params):
        if len(uri) != 0 and uri[0] == "device_status":
            body = cherrypy.request.json
            device_id = body.get("deviceID")
            house_id = body.get("houseID")
            floor_id = body.get("floorID")
            status = body.get("status")
            
            # Validate input
            if not all([device_id, house_id, floor_id, status]):
                return {"error": "Missing required fields"}
                
            device_message = {"deviceID": device_id, "status": status}

            try:
                # Update the device status timestamp
                self.update_device_timestamp(device_id, house_id, floor_id)
                
                # Find the appropriate actuator URL
                actuator_url = self._find_actuator_url(house_id, floor_id)
                if not actuator_url:
                    return {"error": "Actuator URL not found"}
                
                # Send command to device
                response = requests.put(
                    f"{actuator_url}/device_status", 
                    json=device_message
                )
                print(f"Response from actuator connector: {response.text}")
                return {"success": [device_id, house_id, floor_id, status]}
            except requests.exceptions.RequestException as e:
                print(f"Error updating device status: {e}")
                return {"error": str(e)}

        return {"error": "Invalid POST request"}

    def _find_actuator_url(self, house_id, floor_id):
        """Find the appropriate actuator URL for a given house and floor"""
        # First check if we can build it from base URL
        if self.base_url_actuators:
            return f"{self.base_url_actuators}/actuator_{house_id}_{floor_id}"
            
        # Otherwise, search through house data
        for house in self.houses or []:
            if str(house.get('houseID')) == str(house_id):
                for floor in house.get('floors', []):
                    if str(floor.get('floorID')) == str(floor_id):
                        for unit in floor.get('units', []):
                            if unit.get('urlActuators'):
                                return unit.get('urlActuators')
        return None

    def update_device_timestamp(self, device_id, house_id, floor_id):
        """Update device timestamp when status changes"""
        if self.real_time_houses and house_id in self.real_time_houses:
            house = self.real_time_houses[house_id]
            for floor in house.get("floors", []):
                if str(floor["floorID"]) == str(floor_id):
                    for unit in floor.get("units", []):
                        for device in unit.get("devicesList", []):
                            if str(device["deviceID"]) == str(device_id):
                                # Update the timestamp
                                current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                device["lastUpdate"] = current_time
                                print(f"Updated timestamp for device {device_id} to {current_time}")
                                
                                # If we're turning a device off/on, also update its status
                                if "status" in cherrypy.request.json:
                                    device["deviceStatus"] = cherrypy.request.json["status"]
                                    
                                return True
        return False

    def get_channel_detail(self, channel_name):
        """Get ThingSpeak channel details from the adaptor"""
        try:
            response = requests.get(f"{self.adaptor_url}/channels_detail")
            channels = response.json()
            return channels.get(channel_name)
        except requests.exceptions.RequestException as e:
            print(f"Error retrieving Thingspeak channel details: {e}")
            return None

    def get_latest_sensing_data(self, channel_name):
        """Get latest data from ThingSpeak channel"""
        channel_detail = self.get_channel_detail(channel_name)
        if channel_detail:
            try:
                fields = channel_detail["fields"]
                channel_id = channel_detail["channelId"]
                response = requests.get(f"{self.thingspeak_channels_url}{channel_id}/feeds.json?results=5")
                data_list = response.json()["feeds"]

                current_data = {}
                for record in data_list:
                    for field, value in record.items():
                        if field.startswith("field") and value:
                            current_data[fields[field]] = value
                return current_data
            except requests.exceptions.RequestException as e:
                print(f"Error retrieving Thingspeak data: {e}")
                return {"error": str(e)}
        return {"error": "Channel not found"}

    def get_realtime_house(self):
        """Get real-time house data with device status updates"""
        # First, make sure we have the base house structure
        if not self.houses:
            self._load_houses()

        # Now update with real-time data
        self.real_time_houses = {}
        for house in self.houses:
            house_id = house["houseID"]
            self.real_time_houses[house_id] = {
                "houseID": house_id,
                "houseName": house.get("houseName", f"House {house_id}"),
                "floors": []
            }

            for floor in house.get("floors", []):
                floor_data = {"floorID": floor["floorID"], "units": []}
                
                for unit in floor.get("units", []):
                    unit_id = unit["unitID"]
                    url_sensors = unit.get("urlSensors")
                    url_actuators = unit.get("urlActuators")
                    
                    if not url_sensors or not url_actuators:
                        continue
                        
                    # Fetch device data for this unit
                    device_list = self.fetch_device_data(url_sensors, url_actuators)
                    
                    # Update timestamps for all devices
                    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    for dev in device_list.get("devicesList", []):
                        if not dev.get("lastUpdate") or dev.get("lastUpdate") == "2024-02-17 12:00:00":
                            dev["lastUpdate"] = current_time
                    
                    # Check for motion detection and update alerts
                    for dev in device_list.get("devicesList", []):
                        if dev.get("deviceName") == "motion_sensor" and dev.get("deviceStatus") == "Detected":
                            unit_key = f"{house_id}-{floor['floorID']}-{unit_id}"
                            self.motion_alerts[unit_key] = time.time()
                            print(f"Motion detected in {unit_key} at {datetime.datetime.now()}")
                            
                            # Check if this corresponds to a known device and update its location
                            device_id = dev.get("deviceID")
                            if device_id in self.device_ownership:
                                location = self.device_ownership.get(device_id)
                                print(f"Device {device_id} belongs to {location}")
                    
                    # Add the unit to the floor structure
                    unit_data = {
                        "unitID": unit_id,
                        "devicesList": device_list.get("devicesList", [])
                    }
                    floor_data["units"].append(unit_data)
                
                # Add the floor to the house structure
                self.real_time_houses[house_id]["floors"].append(floor_data)

    def _load_houses(self):
        """Load house data either from catalog service or local file"""
        self.houses = []
        
        # First try to load from catalog service
        try:
            response = requests.get(f"{self.catalog_address}/houses")
            if response.status_code == 200:
                self.houses = response.json()
                return
        except requests.exceptions.RequestException as e:
            print(f"Error loading houses from catalog service: {e}")
            
        # Fall back to local catalog file
        try:
            if os.path.exists(self.catalog_path):
                with open(self.catalog_path, 'r') as f:
                    catalog = json.load(f)
                    self.houses = catalog.get("housesList", [])
                    print(f"Loaded {len(self.houses)} houses from local catalog file")
            else:
                print(f"Catalog file not found at {self.catalog_path}")
        except Exception as e:
            print(f"Error reading catalog file: {e}")

    def fetch_device_data(self, url_sensors, url_actuators):
        """Fetch device data from sensors and actuators endpoints"""
        devices = []
        
        # Try to get sensor data
        try:
            sensors_response = requests.get(url_sensors)
            if sensors_response.status_code == 200:
                sensors_data = sensors_response.json()
                
                # Handle different response formats
                if isinstance(sensors_data, dict) and "devicesList" in sensors_data:
                    devices.extend(sensors_data["devicesList"])
                elif isinstance(sensors_data, list):
                    devices.extend(sensors_data)
                else:
                    print(f"Unexpected sensor data format: {sensors_data}")
        except requests.exceptions.RequestException as e:
            print(f"Error fetching sensor data: {e}")

        # Try to get actuator data
        try:
            actuators_response = requests.get(url_actuators)
            if actuators_response.status_code == 200:
                actuators_data = actuators_response.json()
                
                # Handle different response formats
                if isinstance(actuators_data, dict) and "devicesList" in actuators_data:
                    devices.extend(actuators_data["devicesList"])
                elif isinstance(actuators_data, list):
                    devices.extend(actuators_data)
                else:
                    print(f"Unexpected actuator data format: {actuators_data}")
        except requests.exceptions.RequestException as e:
            print(f"Error fetching actuator data: {e}")
        
        # Ensure all devices have timestamps
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for device in devices:
            if not device.get("lastUpdate"):
                device["lastUpdate"] = current_time
                
        return {"devicesList": devices}

    def periodic_house_list_update(self):
        """Periodic task to update house list and check for motion alerts"""
        # Load houses from catalog service or local file
        self._load_houses()
        
        # Update the base actuator URL if possible
        self.update_base_actuator_url()
        
        # Check and log active motion alerts
        now = time.time()
        active_alerts = []
        for unit_key, ts in self.motion_alerts.items():
            if now - ts < 300:  # 5 minutes
                active_alerts.append(unit_key)
        
        if active_alerts:
            print(f"Active motion alerts: {active_alerts}")

        # Schedule the next update
        self.scheduler.enter(self.PERIODIC_UPDATE_INTERVAL, 1, self.periodic_house_list_update, ())

    def update_base_actuator_url(self):
        """Extract base actuator URL from house data if available"""
        for house in self.houses or []:
            for floor in house.get("floors", []):
                for unit in floor.get("units", []):
                    if unit.get("urlActuators"):
                        # Extract the base URL (scheme, host, port)
                        parts = unit["urlActuators"].strip().split("/")
                        if len(parts) >= 3:
                            self.base_url_actuators = "/".join(parts[:3])
                            return

if __name__ == "__main__":
    conf = {
        "/": {
            "request.dispatch": cherrypy.dispatch.MethodDispatcher(),
            "tools.sessions.on": True,
            "cors.expose.on": True
        }
    }
    catalog_address = "http://127.0.0.1:8080/"
    adaptor_url = "http://127.0.0.1:8099/"
    
    # Create and mount the operator control service
    operator_control = OperatorControl(catalog_address, adaptor_url)
    cherrypy.config.update({"server.socket_port": 8095})
    cherrypy.tree.mount(operator_control, "/", conf)
    cherrypy.engine.start()

    try:
        # Keep the server running
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Keyboard interrupt detected. Shutting down...")
    finally:
        cherrypy.engine.stop()
        cherrypy.engine.block()
from MyMQTT import MyMQTT
import requests
import time
import json
import copy
import cherrypy


class Device_connector_act():
    exposed = True

    def __init__(self, catalog_url, DCConfiguration, baseClientID, DCID):
        """
        - catalog_url: The URL of your ThiefDetector catalog (e.g., "http://127.0.0.1:8080/")
        - DCConfiguration: The JSON config for this Device Connector (including 'devicesList')
        - baseClientID: Base name for the MQTT client
        - DCID: e.g., "houseID-floorID-unitID"
        """
        self.catalog_url = catalog_url
        self.DCConfiguration = DCConfiguration
        self.clientID = f"{baseClientID}_{DCID}_DCA"
        self.devices = self.DCConfiguration.get("devicesList", [])

        # Attempt to parse DCID in the format "houseID-floorID-unitID"
        try:
            self.houseID, self.floorID, self.unitID = DCID.split("-")
        except ValueError as e:
            print(f"Error parsing DCID '{DCID}'. Expected format 'houseID-floorID-unitID'. Error: {e}")
            return

        # Request broker info from the catalog
        try:
            broker, port = self.get_broker()
        except (TypeError, ValueError, requests.exceptions.RequestException, json.JSONDecodeError) as e:
            print(f"Failed to get the broker's information. Possibly server is down. Error: {e}")
            return

        # Create MQTT client
        self.client = MyMQTT(self.clientID, broker, port, self)
        self.client.start()
        print(f"MQTT client '{self.clientID}' started.")

        # Subscribe to the ThiefDetector commands topic for this house/floor/unit
        self.topic = f"ThiefDetector/commands/{self.houseID}/{self.floorID}/{self.unitID}/#"
        self.client.mySubscribe(self.topic)
        print(f"Subscribed to topic: {self.topic}")

    ########################################################
    # GET method
    ########################################################
    @cherrypy.tools.json_out()
    def GET(self, *uri, **params):
        """
        Returns the list of actuator devices if the user calls /devices.
        Otherwise, returns usage instructions.
        """
        if len(uri) != 0:
            if uri[0] == "devices":
                return self.devices
            else:
                return "Wrong URL. Go to '/devices' to see the devices list."
        return "Go to '/devices' to see the devices list."

    ########################################################
    # PUT method
    ########################################################
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def PUT(self, *uri, **params):
        """
        Updates a device's status if the user calls /device_status with JSON:
        {
            "deviceID": <integer or string ID>,
            "status": <"ON", "OFF", ...>
        }
        """
        if len(uri) != 0 and uri[0] == "device_status":
            body = cherrypy.request.json
            deviceID = body.get("deviceID")
            newStatus = body.get("status")

            for device in self.devices:
                # Match by deviceID
                if str(device["deviceID"]) == str(deviceID):
                    print(f"Device {deviceID} -> {newStatus}")
                    device.update({"deviceStatus": newStatus})
                    return {"message": f"Device {deviceID} updated to {newStatus}"}

            return {"error": f"Device {deviceID} not found."}
        else:
            return {"error": "Invalid request. Use /device_status to update device status."}

    ########################################################
    # notify (MQTT callback)
    ########################################################
    def notify(self, topic, payload):
        """
        Called whenever a message arrives on our subscribed topics.
        We parse the JSON, figure out which device it references,
        and update that device's status accordingly.
        """
        try:
            msg = json.loads(payload)
            # e.g., msg might look like:
            # {
            #   "bn": "...",
            #   "e": [
            #       { "n": "fan_switch", "u": "status", "t": "...", "v": "ON" }
            #   ]
            # }
            event = msg.get("e", [{}])[0]
            deviceStatusValue = event.get("v", "unknown")

            # Extract the device name from the last element of the topic
            # e.g., "thiefDetector/commands/1/1/1/light_switch" => "light_switch"
            deviceName = topic.split("/")[-1]

            # Update matching device in self.devices
            for device in self.devices:
                # Compare lowercased deviceName => device["deviceName"]
                if device["deviceName"].lower() == deviceName.lower():
                    print(f"Updating {deviceName} status to {deviceStatusValue}")
                    device["deviceStatus"] = deviceStatusValue
                    device["lastUpdate"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    


                    # Optionally, you could also PUT/POST to the catalog to sync the device status
                    # We'll demonstrate a simple update to the catalog endpoint, if desired:
                    try:
                        requests.put(self.catalog_url + "devices", json=device)
                    except requests.exceptions.RequestException as e:
                        print(f"Failed to update device {deviceName} in catalog: {e}")
        except json.JSONDecodeError as e:
            print(f"Failed to decode MQTT message payload: {e}")
        except Exception as e:
            print(f"Unexpected error in notify: {e}")

    ########################################################
    # stop (cleanly disconnect from MQTT)
    ########################################################
    def stop(self):
        """Stops the MQTT client."""
        self.client.stop()
        print(f"MQTT client '{self.clientID}' stopped.")

    ########################################################
    # get_broker (catalog request)
    ########################################################
    def get_broker(self):
        """
        Retrieves broker info from the catalog at e.g.:
          GET <catalog_url>/broker => { "IP": "...", "port": ... }
        """
        try:
            req_b = requests.get(self.catalog_url + "broker")
            broker_json = req_b.json()
            broker, port = broker_json["IP"], int(broker_json["port"])
            print("Broker info received.\n")
            return broker, port
        except requests.exceptions.RequestException as e:
            print(f"Error fetching broker info: {e}")
            raise

    ########################################################
    # registerer (optional: if you want to register the devices in the catalog)
    ########################################################
    def registerer(self):
        """
        If needed, you can call this method to register each device
        from self.devices into the ThiefDetector catalog.
        """
        for device in self.devices:
            device["lastUpdate"] = time.strftime("%Y-%m-%d %H:%M:%S")
            try:
                response = requests.post(self.catalog_url + "devices", json=device)
                if response.status_code in [200, 201]:
                    print(f"Device {device['deviceName']} registered successfully.")
                elif response.status_code == 202:
                    print(f"Device {device['deviceName']} already registered; trying to update.")
                    requests.put(self.catalog_url + "devices", json=device)
                else:
                    print(f"Unexpected response for {device['deviceName']}: {response.text}")
            except requests.exceptions.RequestException as e:
                print(f"Error registering device {device['deviceName']}: {e}")

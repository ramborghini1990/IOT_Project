import cherrypy
import json
import time
from device_connector import Device_connector
import os

# Updated file path for sensor settings
settingSenFile = os.path.abspath("Device_connectors/setting_sen.json")
print(f"✅ Loading setting_sen.json from: {settingSenFile}")

if __name__ == "__main__":
    catalog_url = "http://127.0.0.1:8080/"

    try:
        with open(settingSenFile) as fp:
            setting = json.load(fp)
    except FileNotFoundError:
        print(f"Configuration file '{settingSenFile}' not found.")
        exit(1)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON in '{settingSenFile}': {e}")
        exit(1)

    baseClientID = setting["clientID"]
    DCID_dict = setting["DCID_dict"]

    deviceConnectors = {}

    for DCID, config in DCID_dict.items():
        houseID = config["houseID"]
        floorID = config["floorID"]
        unitID  = config["unitID"]

        DC_name = f"raspberry_{DCID}"
        deviceConnectors[DC_name] = Device_connector(
            catalog_url,
            config,
            baseClientID,
            houseID,
            floorID,
            unitID
        )

    conf = {
        "/": {
            'request.dispatch': cherrypy.dispatch.MethodDispatcher(),
            'tools.sessions.on': True
        }
    }
    cherrypy.config.update({'server.socket_port': 8085})

    for DC_name, DC in deviceConnectors.items():
        cherrypy.tree.mount(DC, f'/{DC_name}', conf)
    cherrypy.engine.start()

    import threading
    threads = []
    for DC in deviceConnectors.values():
        t = threading.Thread(target=DC.send_data, daemon=True)
        threads.append(t)
        t.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Keyboard interrupt detected. Shutting down...")
        cherrypy.engine.stop()

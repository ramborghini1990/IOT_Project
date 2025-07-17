from device_connector_actuator import Device_connector_act
import json
import time
import cherrypy


if __name__ == "__main__":
    # 1) Set the ThiefDetector catalog URL
    catalog_url = "http://127.0.0.1:8080/"

    # 2) Path to your actuator setting file
    settingActFile = "Device_connectors/setting_act.json"

    # 3) Load the actuator configuration (which should have "clientID" and "DCID_dict")
    try:
        with open(settingActFile) as fp:
            settingAct = json.load(fp)
    except FileNotFoundError:
        print(f"Configuration file '{settingActFile}' not found.")
        exit(1)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON in '{settingActFile}': {e}")
        exit(1)

    baseClientID = settingAct["clientID"]
    DCID_act_dict = settingAct["DCID_dict"]

    # 4) Create a dictionary to store Device_connector_act instances
    deviceConnectorsAct = {}

    # 5) For each DCID in DCID_act_dict, create the Device_connector_act object
    for DCID, plantConfig in DCID_act_dict.items():
        DC_name = f"arduino_{DCID}"
        deviceConnectorsAct[DC_name] = Device_connector_act(
            catalog_url,
            plantConfig,
            baseClientID,
            DCID
        )
        print(f"Device_connector_act created for {DC_name}")

    # 6) CherryPy configuration
    conf = {
        "/": {
            'request.dispatch': cherrypy.dispatch.MethodDispatcher(),
            'tools.sessions.on': True
        }
    }
    cherrypy.config.update({'server.socket_port': 8086})

    # 7) Main loop for registration, server mounting, etc.
    try:
        t = 0
        while t < 600:  # run for 600 iterations (10 minutes)
            # Every 100 seconds, register devices
            if t % 100 == 0:
                for DC_name, DC in deviceConnectorsAct.items():
                    DC.registerer()  # register the devices for this actuator connector
                    time.sleep(1)

                    # Mount the device in CherryPy only on the first iteration
                    if t == 0:
                        cherrypy.tree.mount(DC, f'/{DC_name}', conf)
                        print(f"Mounted {DC_name} to CherryPy")
                    time.sleep(1)

                # Start the CherryPy server on the first iteration
                if t == 0:
                    cherrypy.engine.start()
                    print("CherryPy server started on port 8086")

            # Wait 1 second before the next iteration
            time.sleep(1)
            t += 1

    except KeyboardInterrupt:
        print("Keyboard interrupt detected. Shutting down...")
        # Gracefully stop each actuator's MQTT client
        for DC in deviceConnectorsAct.values():
            DC.stop()
        # Stop CherryPy
        cherrypy.engine.block()

    finally:
        # Ensure each device connector is stopped
        for DC in deviceConnectorsAct.values():
            DC.stop()
        # Ensure the CherryPy service is terminated properly
        cherrypy.engine.block()

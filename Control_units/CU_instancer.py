import requests
import sched
import time
import json
import math
import copy
import threading
from control_unit import Controler  

class CU_instancer():
    def __init__(self, catalogAddress):
        self.catalogAddress = catalogAddress
        self.availableUnitsList = []
        self.PERIODIC_UPDATE_INTERVAL = 60  # seconds
        self.NUM_UNITS_PER_CONTROLLER = 5   # number of units each controller manages

        self.controllers = {}
        self.unit_assignment = {}

        self.scheduler = sched.scheduler(time.time, time.sleep)
        self.scheduler.enter(0, 1, self.periodic_unit_list_update, ())
        self.scheduler.run(blocking=False)

        self.update_unit_list()
        self.controller_creator()
        self.scheduler.enter(0, 2, self.subscribe_to_all, ())
        self.scheduler.run()

    def subscribe_to_all(self):
        for controller_name, controller in self.controllers.items():
            assigned_units = [unit for unit, ctrl in self.unit_assignment.items() if ctrl == controller_name]
            controller.subscribe_to_topics(assigned_units)
            print(f"[SUBSCRIBE] {controller_name} subscribed to: {assigned_units}")

        self.scheduler.enter(self.PERIODIC_UPDATE_INTERVAL, 2, self.subscribe_to_all, ())

    def controller_creator(self):
        needed_controllers = math.ceil(len(self.availableUnitsList) / self.NUM_UNITS_PER_CONTROLLER)
        for i in range(needed_controllers):
            name = f"controller_{i}"
            controller = Controler(self.catalogAddress)
            # Keep the reference to the controller in the client for notifications
            controller.client.notifier = controller
            print(f"[INIT] {name} initialized")
            self.controllers[name] = controller

        # Distribute units
        idx = 0
        for unit in self.availableUnitsList:
            assigned_controller = f"controller_{idx // self.NUM_UNITS_PER_CONTROLLER}"
            self.unit_assignment[unit] = assigned_controller
            idx += 1

    def update_unit_list(self):
        try:
            resp = requests.get(f"{self.catalogAddress}houses")
            houses = resp.json()
            self.availableUnitsList = []
            for house in houses:
                for floor in house.get("floors", []):
                    for unit in floor.get("units", []):
                        if unit.get("devicesList"):
                            uid = f"{house['houseID']}-{floor['floorID']}-{unit['unitID']}"
                            if uid not in self.availableUnitsList:
                                self.availableUnitsList.append(uid)
                                print(f"[UNIT] Added {uid}")
            self.availableUnitsList.sort()
            print(f"[UPDATE] Unit list refreshed. Total: {len(self.availableUnitsList)}")
        except Exception as e:
            print(f"[ERROR] Failed to update unit list: {e}")

    def periodic_unit_list_update(self):
        self.update_unit_list()
        self.scheduler.enter(self.PERIODIC_UPDATE_INTERVAL, 1, self.periodic_unit_list_update, ())

if __name__ == "__main__":
    catalogAddress = "http://127.0.0.1:8080/"
    cu_instancer = CU_instancer(catalogAddress)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[EXIT] Keyboard interrupt detected. Shutting down...")
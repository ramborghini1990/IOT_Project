from flask import Flask, render_template, request, jsonify
import requests
import json
import os

app = Flask(__name__)

class UserAwareness:
    def __init__(self, operator_control_url, adaptor_url=None):
        self.operator_control_url = operator_control_url
        self.adaptor_url = adaptor_url
        self.houses = []
        self.catalog_path = 'catalog.json'

    def update_house_list(self):
        """
        Update house list from operator control or directly from catalog if needed
        """
        try:
            # First try to get houses from operator control service
            response = requests.get(f"{self.operator_control_url}/houses")
            print("House list update request sent to operator control")
            
            if response.status_code == 200:
                raw = response.json()
                
                # Accept either dict or list
                if isinstance(raw, dict):
                    candidates = raw.values()
                elif isinstance(raw, list):
                    candidates = raw
                else:
                    candidates = []
                
                # Filter houses that have devices
                self.houses = [
                    h for h in candidates
                    if any(
                        device
                        for floor in h.get("floors", [])
                        for unit in floor.get("units", [])
                        for device in unit.get("devicesList", [])
                    )
                ]
            else:
                # If operator control fails, fall back to local catalog
                self._update_from_catalog()
        except requests.exceptions.RequestException as e:
            print(f"Error during GET request to fetch houses: {e}")
            # Fall back to local catalog if API request fails
            self._update_from_catalog()

    def _update_from_catalog(self):
        """Use catalog.json as fallback if operator service is unavailable"""
        try:
            if os.path.exists(self.catalog_path):
                with open(self.catalog_path, 'r') as f:
                    catalog_data = json.load(f)
                    self.houses = catalog_data.get('housesList', [])
                    print("House list updated from local catalog file")
            else:
                print(f"Catalog file not found at {self.catalog_path}")
                self.houses = []
        except Exception as e:
            print(f"Error reading catalog file: {e}")
            self.houses = []

    def get_channel_detail(self, channel_name):
        try:
            response = requests.get(f"{self.operator_control_url}/channels_detail/{channel_name}")
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error during GET request for Thingspeak channel details: {e}")
            return None

    def post_device_status(self, device_detail):
        try:
            # Ensure all required fields are present
            required_fields = ["deviceID", "houseID", "floorID", "status"]
            for field in required_fields:
                if field not in device_detail:
                    print(f"Missing required field {field} in device status update")
                    return False
                    
            response = requests.post(
                f"{self.operator_control_url}/device_status", 
                json=device_detail
            )
            print(f"Response from operator control on device status update: {response.text}")
            return response.status_code == 200
        except requests.exceptions.RequestException as e:
            print(f"Error posting device status: {e}")
            return False

    def get_houses(self):
        return self.houses

    def get_motion_alerts(self):
        """Get current motion alerts from operator control"""
        try:
            response = requests.get(f"{self.operator_control_url}/motion_alerts")
            if response.status_code == 200:
                return response.json().get("activeAlerts", [])
            return []
        except requests.exceptions.RequestException as e:
            print(f"Error getting motion alerts: {e}")
            return []

def get_button_class(status):
    return {
        "ON": "green",
        "OFF": "blue",
        "DISABLE": "red",
    }.get(status, "orange")

@app.route('/send_status_message', methods=['POST'])
def send_status_message():
    device_info = request.json
    status = device_info.get("status")
    
    if not status:
        return jsonify({'error': 'Missing status in request'}), 400

    try:
        operator_control_url = "http://127.0.0.1:8095/"
        user_awareness = UserAwareness(operator_control_url)
        success = user_awareness.post_device_status(device_info)
        
        if not success:
            return jsonify({'error': 'Failed to update device status'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    if status == "DISABLE":
        return jsonify({'message': f'{status} status is not available at the moment.'})
    return jsonify({'message': 'Device status updated successfully.'})

@app.route('/')
def index():
    operator_control_url = "http://127.0.0.1:8095/"
    user_awareness = UserAwareness(operator_control_url)
    user_awareness.update_house_list()
    houses = user_awareness.get_houses()
    
    # Normalize house data to include all required fields
    normalized_houses = []
    for h in houses:
        normalized_house = {
            'houseID': h.get('houseID'),
            'houseName': h.get('houseName', f"House {h.get('houseID')}"),
            'floors': []
        }
        
        for floor in h.get('floors', []):
            normalized_floor = {
                'floorID': floor.get('floorID'),
                'units': []
            }
            
            for unit in floor.get('units', []):
                normalized_unit = {
                    'unitID': unit.get('unitID'),
                    'devicesList': []
                }
                
                # Ensure each device has all required fields
                for device in unit.get('devicesList', []):
                    normalized_device = {
                        'deviceID': device.get('deviceID'),
                        'deviceName': device.get('deviceName', 'Unknown Device'),
                        'deviceStatus': device.get('deviceStatus', 'UNKNOWN'),
                        'houseID': h.get('houseID'),
                        'floorID': floor.get('floorID'),
                        'unitID': unit.get('unitID'),
                        'lastUpdate': device.get('lastUpdate', 'Unknown')
                    }
                    normalized_unit['devicesList'].append(normalized_device)
                
                normalized_floor['units'].append(normalized_unit)
            normalized_house['floors'].append(normalized_floor)
        normalized_houses.append(normalized_house)
    
    # Extract all devices into a flat list for the devices section
    devices = []
    for h in normalized_houses:
        for floor in h.get('floors', []):
            for unit in floor.get('units', []):
                for device in unit.get('devicesList', []):
                    devices.append(device)

    # Get motion alerts
    motion_alerts = user_awareness.get_motion_alerts()

    return render_template(
        'index.html',
        houses=normalized_houses,
        devices=devices,
        motion_alerts=motion_alerts
    )

@app.route('/house/<houseID>')
def house_detail(houseID):
    operator_control_url = "http://127.0.0.1:8095/"
    user_awareness = UserAwareness(operator_control_url)
    
    # First try to get house data from the operator control
    try:
        res = requests.get(f"http://127.0.0.1:8080/house/{houseID}")
        house = res.json()
    except:
        # If that fails, get from local house list
        user_awareness.update_house_list()
        houses = user_awareness.get_houses()
        house = next((h for h in houses if str(h.get('houseID')) == str(houseID)), None)
    
    if house:
        # Prepare channel data for ThingSpeak charts
        channel_data = {}
        thingspeak_channel_id = None
        
        # Map houseID to ThingSpeak channel ID
        if str(houseID) == "1":
            thingspeak_channel_id = "2884625"
        elif str(houseID) == "2":
            thingspeak_channel_id = "2884626"
        
        # Simple field mapping for ThingSpeak
        fields = {
            "motion": {"field_name": "field1"},
            "light": {"field_name": "field2"}
        }
        
        return render_template(
            'house_detail.html',
            house=house,
            get_button_class=get_button_class,
            channelID=thingspeak_channel_id,
            fields=fields
        )
    else:
        return "House not found."

if __name__ == '__main__':
    app.run(debug=True)
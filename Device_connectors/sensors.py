import random
import time

class LightSensor():
    def __init__(self, sensor_id, min_lux=0, max_lux=1000):
        
        self.sensor_id = sensor_id
        self.MIN_LIGHT = min_lux
        self.MAX_LIGHT = max_lux
        
        
        self.senKind = "Light"
        self.unit = "lux"

   
    def generate_data(self):
        value = round(random.uniform(self.MIN_LIGHT, self.MAX_LIGHT), 2)
        return value

    
    def get_info(self):
        return (self.sensor_id, self.senKind, self.unit)


class MotionSensor():
    def __init__(self, sensor_id):
        self.sensor_id = sensor_id
        self.senKind = "Motion"
        self.unit = "boolean"  

    def generate_data(self):
        # 10% chance to return True (motion detected)
        return random.choices([True, False], weights=[1, 15])[0]

    def get_info(self):
        return (self.sensor_id, self.senKind, self.unit)

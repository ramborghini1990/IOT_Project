import paho.mqtt.publish as publish

publish.single(
    topic="thief_detector/sensors/1/1/motion",
    payload='{"e":[{"n":"motion","u":"status","t":"1713723600","v":"Detected"}]}',
    hostname="test.mosquitto.org"
)

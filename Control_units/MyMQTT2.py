import json
import paho.mqtt.client as PahoMQTT

class MyMQTT:
    def __init__(self, clientID, broker, port, notifier):
        self.broker = broker
        self.port = port
        self.notifier = notifier  # Object that handles notifications (e.g., your main controller class)
        self.clientID = clientID
        self._topic = []
        self._isSubscriber = False

        # Create an instance of paho.mqtt.client
        self._paho_mqtt = PahoMQTT.Client(client_id=clientID, clean_session=True)


        # Register the callback methods
        self._paho_mqtt.on_connect = self.myOnConnect
        self._paho_mqtt.on_message = self.myOnMessageReceived

    def myOnConnect(self, paho_mqtt, userdata, flags, rc):
        print(f"Connected to {self.broker} with result code: {rc}")

    def myOnMessageReceived(self, paho_mqtt, userdata, msg):
        """
        A new message is received on a subscribed topic.
        Forward the topic and payload to the notifier for further handling.
        """
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
            self.notifier.notify(msg.topic, payload)
        except json.JSONDecodeError as e:
            print(f"Failed to decode JSON message on topic {msg.topic}: {e}")
        except Exception as e:
            print(f"Error processing message on topic {msg.topic}: {e}")

    def myPublish(self, topic, msg):
        """
        Publish a message to a specific topic.
        """
        try:
            self._paho_mqtt.publish(topic, json.dumps(msg), qos=2)
            print(f"Published message to {topic}: {msg}")
        except Exception as e:
            print(f"Failed to publish message to {topic}: {e}")

    def mySubscribe(self, topic):
        """
        Subscribe to a topic.
        """
        try:
            self._paho_mqtt.subscribe(topic, qos=2)
            self._isSubscriber = True
            self._topic.append(topic)
            print(f"Subscribed to topic: {topic}")
        except Exception as e:
            print(f"Failed to subscribe to {topic}: {e}")

    def start(self):
        """
        Start the MQTT client and connect to the broker.
        """
        try:
            self._paho_mqtt.connect(self.broker, self.port)
            self._paho_mqtt.loop_start()
            print("MQTT client started.")
        except Exception as e:
            print(f"Failed to start MQTT client: {e}")

    def unsubscribe(self, topic):
        """
        Unsubscribe from a specific topic.
        """
        try:
            if self._isSubscriber:
                self._paho_mqtt.unsubscribe(topic)
                self._topic.remove(topic)
                print(f"Unsubscribed from topic: {topic}")
        except Exception as e:
            print(f"Failed to unsubscribe from {topic}: {e}")

    def stop(self):
        """
        Stop the MQTT client and disconnect from the broker.
        """
        try:
            if self._isSubscriber:
                for topic in self._topic:
                    self._paho_mqtt.unsubscribe(topic)
            self._paho_mqtt.loop_stop()
            self._paho_mqtt.disconnect()
            print("MQTT client stopped.")
        except Exception as e:
            print(f"Failed to stop MQTT client: {e}")

# Thief Detector IoT System

![Security Badge](https://img.shields.io/badge/status-in%20development-blue)
![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

A comprehensive, microservice-based IoT system for home security monitoring. This project simulates a network of sensors and actuators to detect and respond to potential intrusions, providing real-time updates through a web interface, a ThingSpeak dashboard, and a Telegram bot.

---

## Features

- **Microservice Architecture**: The system is broken down into independent services for scalability and maintainability.
- **Real-time Monitoring**: A web interface provides a live overview of all connected devices and their statuses.
- **Intelligent Automation**: The system automatically turns lights on when motion is detected and off when the area is clear and well-lit.
- **Cloud Integration**: Sensor data is pushed to ThingSpeak for historical analysis and visualization.
- **Remote Control**: A Telegram bot allows users to claim and monitor devices from anywhere.
- **Dynamic Service Discovery**: A central catalog service allows components to discover each other dynamically.
- **Simulated Devices**: Includes simulated light and motion sensors for easy testing and development without physical hardware.

---

## Architecture Overview

The Thief Detector system follows a microservice architecture. Each component is a standalone service that communicates with others through REST APIs and an MQTT message broker. This decoupled design makes the system robust, scalable, and easy to modify.

Here’s a high-level overview of the data flow:

1.  **Device Connectors (Sensors)** (`device_connector.py`) simulate sensor readings and publish them to an MQTT broker.
2.  The **Control Unit** (`control_unit.py`) subscribes to sensor topics and implements the core security logic.
3.  When a response is needed, the **Control Unit** publishes a command to a different MQTT topic.
4.  **Device Connectors (Actuators)** (`device_connector_actuator.py`) subscribe to command topics and simulate an actuator's response.
5.  The **ThingSpeak Adaptor** (`adaptor.py`) also subscribes to sensor topics and pushes the data to the ThingSpeak cloud platform.
6.  All services register with and query the **Catalog Registry** (`catalog_registry.py`) to get configuration details like broker IP and API endpoints.
7.  The **Operator Control** service (`operator_control.py`) acts as a gateway, aggregating data to provide a unified API for front-end clients.
8.  The **Web Interface** and **Telegram Bot** are the user-facing clients that communicate with the Operator Control service.

---

## Components

### 1. Catalog Registry (`catalog_registry.py`)
- **Purpose**: The single source of truth for the entire system. It's a RESTful service that manages a `catalog.json` file.
- **Functionality**:
    - Provides broker connection details to all MQTT clients.
    - Allows services to register new devices and update their status.
    - Implements schema validation to ensure data integrity.
    - Periodically cleans up inactive devices.

### 2. Device Connectors (`device_connector.py` & `device_connector_actuator.py`)
- **Purpose**: These services simulate the behavior of physical IoT devices.
- **Functionality**:
    - **Sensor Connector**: Generates simulated sensor data and publishes it to MQTT.
    - **Actuator Connector**: Subscribes to MQTT command topics to update the state of simulated actuators.
    - Both are instantiated by their respective "instancer" scripts based on configuration files.

### 3. Control Unit (`control_unit.py`)
- **Purpose**: This is the brain of the system, containing the core automation logic.
- **Functionality**:
    - Subscribes to all sensor data topics via MQTT.
    - Implements the main security logic (e.g., turning lights on/off).
    - Publishes commands to actuators via MQTT.

### 4. ThingSpeak Adaptor (`adaptor.py`)
- **Purpose**: Acts as a bridge between the local MQTT broker and the ThingSpeak cloud platform.
- **Functionality**:
    - Subscribes to sensor topics.
    - Buffers data and periodically sends it to ThingSpeak channels.

### 5. Operator Control (`operator_control.py`)
- **Purpose**: An API gateway that simplifies interactions for front-end clients.
- **Functionality**:
    - Aggregates data from the Catalog and Device Connectors.
    - Provides a clean, unified REST API for clients.
    - Tracks and reports active motion alerts.

### 6. Web Interface (`interface.py`, `index.html`, etc.)
- **Purpose**: Provides a user-friendly web dashboard for monitoring.
- **Functionality**:
    - A Flask-based web server that renders HTML templates.
    - Displays all devices and their statuses in real-time.

### 7. Telegram Bot (`telegram_bot.py`)
- **Purpose**: Allows users to interact with the system via the Telegram app.
- **Functionality**:
    - Provides an interface for users to claim ownership of a device.
    - Allows users to request the current status of their device.

---

## Getting Started

To run the system, you'll need to start each microservice, preferably in a separate terminal.

### Prerequisites

- Python 3.8+
- The following Python libraries: `requests`, `paho-mqtt`, `cherrypy`, `flask`, `telepot`

You can install all dependencies with pip:
```bash
pip install requests paho-mqtt cherrypy flask telepot
```

### Running the Services

Start the services in the following order:

1.  **Catalog Registry**:
    ```bash
    python catalog_registry.py
    ```
2.  **Device Connectors (Sensors)**:
    ```bash
    python DC_instancer.py
    ```
3.  **Device Connectors (Actuators)**:
    ```bash
    python DC_instancer_actuator.py
    ```
4.  **Control Unit**:
    ```bash
    python CU_instancer.py
    ```
5.  **ThingSpeak Adaptor**:
    ```bash
    python adaptor.py
    ```
6.  **Operator Control**:
    ```bash
    python operator_control.py
    ```
7.  **Web Interface**:
    ```bash
    python interface.py
    ```
8.  **Telegram Bot**: (Make sure to add your bot token)
    ```bash
    python telegram_bot.py
    ```

Once all services are running, you can access the web interface at `http://127.0.0.1:5000/`.


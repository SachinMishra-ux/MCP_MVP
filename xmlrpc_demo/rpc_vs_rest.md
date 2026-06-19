# Side-by-Side Comparison: XML-RPC (RPC) vs. FastAPI (REST)

This guide illustrates the practical differences between **Remote Procedure Calls (RPC)** and **Representational State Transfer (REST)** using a real-world use case: **Controlling a Smart Light Bulb**.

---

## The Use Case: Smart Light Bulb API
Our API controls a smart bulb that has a status (`on` / `off`) and a brightness level (`0` to `100`).

---

## 1. The XML-RPC Paradigm (Action-Oriented)
In RPC, the API exposes **verbs/functions** that the client calls directly.

### Server Code (`rpc_server.py`)
```python
from xmlrpc.server import SimpleXMLRPCServer

# Simulated Database/Hardware State
light_state = {"status": "off", "brightness": 50}

def turn_on():
    light_state["status"] = "on"
    return "Light turned ON"

def set_brightness(level):
    # Manual validation is REQUIRED in RPC
    if not isinstance(level, int):
        return "Error: Level must be an integer"
    if 0 <= level <= 100:
        light_state["brightness"] = level
        return f"Brightness set to {level}%"
    return "Error: Level must be between 0 and 100"

# Bind to localhost
server = SimpleXMLRPCServer(("127.0.0.1", 9801), allow_none=True)
server.register_function(turn_on, "turn_on")
server.register_function(set_brightness, "set_brightness")

print("🔌 XML-RPC Light Server running on port 9801...")
server.serve_forever()
```

### Client Code (`rpc_client.py`)
```python
import xmlrpc.client

# Connect to the single server endpoint
server = xmlrpc.client.ServerProxy("http://127.0.0.1:9801")

# Directly execute remote methods
print(server.turn_on())
print(server.set_brightness(85))
```

---

## 2. The FastAPI / REST Paradigm (Resource-Oriented)
In REST, we treat the light bulb state as a **resource (noun)** at the URL `/lightbulb`. We use HTTP methods (`GET` / `PUT`) to read and write it.

### Server Code (`rest_server.py`)
```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()

# Simulated Database/Hardware State
light_state = {"status": "off", "brightness": 50}

# Pydantic Schema handles validation automatically
class LightStateUpdate(BaseModel):
    status: str
    brightness: int = Field(..., ge=0, le=100) # Brightness must be 0-100

@app.get("/lightbulb")
def get_light_state():
    return light_state # Returned automatically as JSON

@app.put("/lightbulb")
def update_light_state(new_state: LightStateUpdate):
    light_state["status"] = new_state.status
    light_state["brightness"] = new_state.brightness
    return {"message": "State updated", "current": light_state}
```

### Client Code (`rest_client.py`)
```python
import requests

# Send an HTTP PUT request to modify the resource
new_state = {"status": "on", "brightness": 85}
response = requests.put("http://127.0.0.1:8000/lightbulb", json=new_state)

print(response.json())
```

---

## 🧠 Key Differences to Highlight to Students

### 1. Data Validation & Security
* **XML-RPC:** If a client sends `server.set_brightness(150)` or `server.set_brightness("bright")`, the function will execute unless the developer writes manual validation checks. If checks are missing, the server will crash or operate with corrupted state data.
* **FastAPI (REST):** FastAPI uses **Pydantic** to validate incoming payloads *before* they touch your business logic. If a client sends an invalid brightness value, FastAPI instantly rejects it and returns a standard HTTP `422 Unprocessable Entity` JSON error showing exactly what field failed validation.

### 2. URL Endpoint Design
* **XML-RPC:** Uses **one single URL** (e.g., `http://127.0.0.1:9801/`). All function names are passed in the XML body payload.
* **FastAPI (REST):** Uses **standardized resources** mapped to HTTP verbs:
  * `GET /lightbulb` (Read State)
  * `PUT /lightbulb` (Overwrite State)

### 3. Modern Client Compatibility
* **REST (JSON)** is supported natively by web browsers. Building a button in a React or mobile application that sends a JSON payload to `/lightbulb` takes just 3 lines of JavaScript.
* **XML-RPC (XML)** is extremely verbose and difficult to handle in front-end frameworks, as Javascript developers have to construct custom XML strings and parse complex XML DOM structures.

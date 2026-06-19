# Hosted / Remote MCP Server Architecture Guide

This guide explains how to connect a remote, cloud-hosted MCP server to local applications (like FreeCAD or CATIA) running on your local machine behind firewalls/NATs.

---

## The Networking Challenge: Inbound vs. Outbound

```text
  [ Cloud (Public IP) ]                 │              [ Local Home/Office LAN (Private IP) ]
  ┌───────────────────────┐             │              ┌─────────────────────────────────────┐
  │  Remote MCP Server    │ ────────X (Blocked) ─────> │ Local FreeCAD (127.0.0.1:9800)      │
  └───────────────────────┘             │              └─────────────────────────────────────┘
                                   FIREWALL / NAT
```

* **Inbound Blocked:** Cloud servers cannot make direct connection requests into your laptop. Your router's firewall blocks all incoming unsolicited traffic.
* **Outbound Allowed:** Your laptop is allowed to make connections out to the internet (how you browse the web). We can exploit this to create a bridge.

---

## Solution 1: Outbound WebSocket Connection (Secure & Live)

Instead of the server calling your laptop, you run a small **Local Agent** on your laptop that initiates a WebSocket connection *out* to the cloud.

### 🗺️ Architecture Flow

```text
 [ Claude Client ]
        │
        │ (JSON-RPC)
        ▼
 [ Remote MCP Server (Cloud) ] 
        │
        │ <─── Outbound WebSocket connection (Kept Open) ───>
        ▼
 [ Local Agent Script (Your PC) ]
        │
        │ (Local XML-RPC / Windows COM)
        ▼
 [ FreeCAD / CATIA ]
```

### Simple Implementation Concept

#### 1. The Cloud Server WebSocket Listener
The hosted MCP server acts as a WebSocket hub. It holds onto connected local agents and relays commands.
```python
# Part of remote_mcp.py running on AWS/Heroku
active_connections = {}

async def register_agent(websocket):
    active_connections["my_laptop"] = websocket
    try:
        await websocket.wait_until_closed()
    finally:
        del active_connections["my_laptop"]

@mcp.tool()
async def execute_cad_code(code: str) -> str:
    # Send the code over the active WebSocket channel to the local laptop
    ws = active_connections.get("my_laptop")
    if not ws:
         return "Error: Local agent is offline."
         
    await ws.send_json({"action": "execute", "code": code})
    response = await ws.recv_json() # Wait for results
    return response["stdout"]
```

#### 2. The Local Agent Script (Runs on your Laptop)
This script runs in the background of your local machine.
```python
# local_agent.py running on your laptop
import websockets
import xmlrpc.client
import asyncio
import json

async def run_agent():
    # Connect OUTBOUND to the cloud server
    async with websockets.connect("wss://your-cloud-mcp.herokuapp.com/agent") as ws:
        # Connect to local FreeCAD
        freecad = xmlrpc.client.ServerProxy("http://127.0.0.1:9800")
        
        async for message in ws:
            data = json.loads(message)
            if data["action"] == "execute":
                # Run the command locally
                res = freecad.execute(data["code"])
                # Send the response back to the cloud
                await ws.send(json.dumps(res))

asyncio.run(run_agent())
```

---

## Solution 2: Queue-Based Architecture (Asynchronous)

Best for multi-user environments or slower operations. We use a cloud message broker (like RabbitMQ, Redis, or AWS SQS).

### 🗺️ Architecture Flow

```text
  [ Remote MCP Server ] ──── Pushes Task ───> [ Cloud Message Queue ]
                                                       │
                                                       │ (Long-Polls Queue)
                                                       ▼
                                           [ Local Worker on Laptop ]
                                                       │
                                                       │ (Executes CAD scripts)
                                                       ▼
                                              [ FreeCAD / CATIA ]
```

### The Workflow:
1. Claude requests a shape: *"Draw a sphere."*
2. The remote MCP server generates the Python CAD script and pushes it as a JSON task into the queue.
3. The local worker on your laptop fetches the task from the queue, runs it inside FreeCAD, takes a screenshot, and pushes the result back to a response queue.
4. The remote MCP server retrieves the response and displays it to Claude.
5. **Security Advantage:** There are absolutely no listening ports open on your local computer. The security is fully managed by the Cloud Queue credentials.

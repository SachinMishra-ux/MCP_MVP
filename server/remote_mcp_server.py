import os
import json
import asyncio
import uuid
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastmcp import FastMCP

# Initialize FastMCP Server
mcp = FastMCP("Remote FreeCAD Server")

# Get the Starlette app from FastMCP configured for SSE transport
mcp_app = mcp.http_app(transport="sse", path="/sse")

# Global reference to active local agent connection and pending requests map
active_agent = None
agent_lock = asyncio.Lock()
pending_requests = {}

# Define MCP Tools (Relaying commands to the local agent)
@mcp.tool()
async def execute_freecad_python(code: str) -> str:
    """Executes Python code on the remote user's local FreeCAD instance."""
    global active_agent
    if not active_agent:
        return "Error: Local FreeCAD Agent is offline."
        
    request_id = uuid.uuid4().hex
    future = asyncio.get_running_loop().create_future()
    pending_requests[request_id] = future
        
    try:
        async with agent_lock:
            await active_agent.send_json({
                "action": "execute", 
                "code": code,
                "request_id": request_id
            })
        
        # Wait for response from the main websocket loop (timeout after 30s)
        response = await asyncio.wait_for(future, timeout=30.0)
        
        output = []
        if response.get("success"):
            output.append("### Execution Success")
            if response.get("stdout"):
                output.append(f"**Stdout:**\n```\n{response['stdout']}\n```")
        else:
            output.append("### Execution Failed")
            if response.get("stderr"):
                output.append(f"**Error Details:**\n```\n{response['stderr']}\n```")
        return "\n\n".join(output)
    except asyncio.TimeoutError:
        return "Error: Request timed out waiting for local agent response."
    except Exception as e:
        return f"Error communicating with local agent: {e}"
    finally:
        pending_requests.pop(request_id, None)

@mcp.tool()
async def get_document_objects() -> str:
    """Retrieves document object hierarchy from local FreeCAD."""
    global active_agent
    if not active_agent:
        return "Error: Local FreeCAD Agent is offline."
        
    request_id = uuid.uuid4().hex
    future = asyncio.get_running_loop().create_future()
    pending_requests[request_id] = future
        
    try:
        async with agent_lock:
            await active_agent.send_json({
                "action": "get_structure",
                "request_id": request_id
            })
            
        response = await asyncio.wait_for(future, timeout=30.0)
        if not response.get("success"):
            return "Error retrieving document hierarchy."
        
        objects = response.get("objects", [])
        if not objects:
            return "No active document or document is empty."
            
        lines = ["### Active Document Structure:"]
        for idx, obj in enumerate(objects):
            lines.append(f"{idx+1}. **{obj['name']}** (Label: '{obj['label']}', Type: `{obj['type']}`)")
        return "\n".join(lines)
    except asyncio.TimeoutError:
        return "Error: Request timed out waiting for local agent response."
    except Exception as e:
        return f"Error: {e}"
    finally:
        pending_requests.pop(request_id, None)

# Initialize FastAPI App with FastMCP's lifespan context
app = FastAPI(lifespan=mcp_app.lifespan)

# Add CORS Middleware to allow CORS requests from the browser-based Inspector
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the FastMCP sub-app under /mcp (which hosts /mcp/sse and /mcp/messages)
app.mount("/mcp", mcp_app)

# WebSocket Endpoint for Local Agent to Connect
@app.websocket("/ws/agent")
async def websocket_agent_endpoint(websocket: WebSocket):
    global active_agent
    await websocket.accept()
    print("🔌 Local Agent connected from laptop!")
    active_agent = websocket
    try:
        while True:
            # We listen for all responses in the main loop to keep the socket read clean
            message_text = await websocket.receive_text()
            try:
                message = json.loads(message_text)
                request_id = message.get("request_id")
                if request_id and request_id in pending_requests:
                    pending_requests[request_id].set_result(message)
            except json.JSONDecodeError:
                print(f"Received invalid JSON from agent: {message_text}")
    except WebSocketDisconnect:
        print("❌ Local Agent disconnected.")
        # Fail any pending requests so the caller is unblocked
        for future in list(pending_requests.values()):
            if not future.done():
                future.set_exception(WebSocketDisconnect("Agent disconnected"))
    finally:
        active_agent = None

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

import asyncio
import websockets
import xmlrpc.client
import json
import os

# Change this to your public cloud app URL (e.g. wss://my-mcp.onrender.com/ws/agent)
# Defaults to localhost for testing the connection locally first
CLOUD_WS_URL = "wss://FreeCADMCPServer.fastmcp.app/ws/agent"
LOCAL_RPC_URL = "http://127.0.0.1:9875"

async def run_agent():
    local_freecad = xmlrpc.client.ServerProxy(LOCAL_RPC_URL, allow_none=True)
    
    # Check for authentication token in environment variables
    token = os.environ.get("FASTMCP_API_KEY")
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        print("🔑 Authentication token loaded from FASTMCP_API_KEY.")
    else:
        print("⚠️ Warning: FASTMCP_API_KEY environment variable is not set. If your server is hosted on fastmcp.app, the connection will be rejected with HTTP 401.")

    print(f"Connecting to remote cloud server at: {CLOUD_WS_URL}...")
    async for websocket in websockets.connect(CLOUD_WS_URL, additional_headers=headers):
        try:
            print("🎉 Connected! Waiting for CAD commands from Cloud MCP...")
            async for message in websocket:
                task = json.loads(message)
                action = task.get("action")
                request_id = task.get("request_id")
                
                if action == "execute":
                    code = task.get("code")
                    print(f"Executing incoming code block...")
                    result = local_freecad.execute(code)
                    result["request_id"] = request_id
                    await websocket.send(json.dumps(result))
                    
                elif action == "get_structure":
                    print("Fetching document structure...")
                    result = local_freecad.get_structure()
                    result["request_id"] = request_id
                    await websocket.send(json.dumps(result))
                    
        except websockets.ConnectionClosed:
            print("⚠️ Connection closed. Reconnecting in 5 seconds...")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"❌ Error occurred: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(run_agent())
    except KeyboardInterrupt:
        print("\nStopping agent...")

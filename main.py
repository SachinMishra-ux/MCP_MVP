import os
import sys
import argparse
import asyncio
import json
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

# Add client source to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), "client", "src", "mcp_client"))

try:
    from client import LLMMCPClient
except ImportError:
    # If packaged, might be in a different location or already in path
    try:
        from mcp_client.client import LLMMCPClient
    except ImportError:
        LLMMCPClient = None

from mcp.server.fastmcp import FastMCP

# Define the local MCP Server (Local Filesystem)
mcp = FastMCP("local-filesystem")

@mcp.resource("system://info")
def get_system_info() -> str:
    """Provides information about the local file system MCP server."""
    return "Local Filesystem MCP Server v1.0. Connected and providing direct disk access."

@mcp.tool()
def read_file(path: str) -> str:
    """Reads the contents of a file on the local file system.
    
    Args:
        path: Absolute path to the file to read
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file {path}: {e}"

@mcp.tool()
def list_directory(path: str) -> list[str]:
    """Lists files and folders in a given directory.
    
    Args:
        path: Absolute path to the directory
    """
    try:
        if not os.path.exists(path):
            return [f"Error: Directory {path} does not exist"]
        return os.listdir(path)
    except Exception as e:
        return [f"Error listing directory {path}: {e}"]


# FastAPI Application
app = FastAPI(title="MCP Gateway API", version="1.0.0")
mcp_client: Optional[LLMMCPClient] = None

class ChatRequest(BaseModel):
    message: str
    history: Optional[List[Dict[str, Any]]] = None

class ChatResponse(BaseModel):
    response: str
    model: str

@app.on_event("startup")
async def startup_event():
    global mcp_client
    config_path = os.environ.get("MCP_CONFIG_PATH", "config.json")
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
        config_path = os.path.join(base_path, config_path)
    
    print(f"Starting MCP Client with config: {config_path}")
    mcp_client = LLMMCPClient(config_path)
    # Initialize connections on startup
    await mcp_client.connect_servers()

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    if not mcp_client:
        raise HTTPException(status_code=500, detail="MCP Client not initialized")
    
    try:
        response_text = await mcp_client.chat(request.message, request.history)
        return ChatResponse(response=response_text, model=mcp_client.model)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tools")
async def get_tools():
    if not mcp_client:
        return []
    return mcp_client.available_tools

@app.get("/status")
async def get_status():
    if not mcp_client:
        return {"status": "not_initialized"}
    return {
        "status": "ready",
        "connected_servers": mcp_client.connected_servers,
        "model": mcp_client.model
    }

async def run_cli():
    config_path = os.environ.get("MCP_CONFIG_PATH", "config.json")
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
        config_path = os.path.join(base_path, config_path)
        
    client = LLMMCPClient(config_path)
    await client.run_chat_loop()

def main():
    parser = argparse.ArgumentParser(description="Unified MCP Gateway (FastAPI + MCP Server)")
    parser.add_argument("--mcp-server", action="store_true", help="Run in MCP Server mode (local tools)")
    parser.add_argument("--cli", action="store_true", help="Run in interactive CLI mode")
    parser.add_argument("--port", type=int, default=8000, help="Port for FastAPI server")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host for FastAPI server")
    
    args = parser.parse_args()
    
    if args.mcp_server:
        # Run the local tool server
        print("Starting Local MCP Server (Filesystem)...")
        mcp.run()
    elif args.cli:
        # Run the interactive loop
        asyncio.run(run_cli())
    else:
        # Run the FastAPI server
        print(f"Starting MCP Gateway API on {args.host}:{args.port}...")
        uvicorn.run(app, host=args.host, port=args.port)

if __name__ == "__main__":
    main()

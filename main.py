import os
import sys
import argparse
import asyncio
import json
import uvicorn
import httpx
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

# Standard flat imports (fixes PyInstaller NoneType error)
try:
    from mcp_client_logic import LLMMCPClient
except ImportError:
    # Fallback for different package structures
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
    thread_id: Optional[str] = "default"
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
        # LangGraph handles history internally using thread_id.
        # We pass the message and thread_id to the client.
        response_text = await mcp_client.chat(
            request.message, 
            thread_id=request.thread_id or "default"
        )
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

async def run_sse_bridge(sse_url: str, api_key: str, base_prefix: str = "", verify_ssl: bool = True):
    """
    Direct integration of sse_bridge logic for Chromosome/AgentBuilder servers.
    One SSE connection handles receiving the endpoint AND all subsequent responses.
    """
    sse_headers = {
        "x-api-key": api_key,
        "Accept": "text/event-stream",
        "Cache-Control": "no-store",
    }
    post_headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
    }

    # Shared state between coroutines
    post_url_ready = asyncio.Event()
    post_url = None

    sys.stderr.write(f"[bridge] Initializing bridge for: {sse_url}\n")
    sys.stderr.write(f"[bridge] SSL Verification: {'Enabled' if verify_ssl else 'Disabled'}\n")

    async with httpx.AsyncClient(timeout=None, verify=verify_ssl) as client:
        async def sse_reader():
            nonlocal post_url
            endpoint_received = False
            try:
                sys.stderr.write("[bridge] Attempting SSE connection...\n")
                async with client.stream("GET", sse_url, headers=sse_headers) as sse:
                    if sse.status_code != 200:
                        sys.stderr.write(f"[bridge] SSE Connection Failed: HTTP {sse.status_code}\n")
                        return

                    sys.stderr.write("[bridge] SSE connected successfully\n")

                    async for line in sse.aiter_lines():
                        if not line or line.startswith(":") or line.startswith("event:"):
                            continue

                        if line.startswith("data:"):
                            payload = line[len("data:"):].strip()
                            if not endpoint_received:
                                # First data line = endpoint path
                                if base_prefix and not payload.startswith(base_prefix):
                                    fixed_path = base_prefix + payload
                                else:
                                    fixed_path = payload

                                parsed = urlparse(sse_url)
                                post_url = f"{parsed.scheme}://{parsed.netloc}{fixed_path}"
                                sys.stderr.write(f"[bridge] POST Endpoint discovered: {post_url}\n")
                                endpoint_received = True
                                post_url_ready.set()
                            else:
                                if payload:
                                    try:
                                        json.loads(payload) # verify JSON
                                        sys.stdout.write(payload + "\n")
                                        sys.stdout.flush()
                                    except:
                                        pass
            except Exception as e:
                sys.stderr.write(f"[bridge] SSE error: {e}\n")
                # Ensure we don't hang stdin_reader forever on error
                post_url_ready.set()

        async def stdin_reader():
            sys.stderr.write("[bridge] Stdin reader started, listening for stdio...\n")
            
            loop = asyncio.get_event_loop()
            
            # Windows stdin handling for asyncio
            def win_read():
                return sys.stdin.readline()
                
            while True:
                # Always read first to avoid blocking the OS pipe
                line = await loop.run_in_executor(None, win_read)
                
                if not line: break
                
                line = line.strip()
                if not line: continue
                
                # If we haven't found the endpoint yet, wait now (but only after receiving data)
                if not post_url:
                    sys.stderr.write("[bridge] Request received but SSE endpoint not ready. Waiting for discovery...\n")
                    await post_url_ready.wait()
                    if not post_url:
                        sys.stderr.write("[bridge] SSE discovery failed. Request dropped.\n")
                        continue
                
                try:
                    payload = json.loads(line if isinstance(line, str) else line.decode())
                    await client.post(post_url, json=payload, headers=post_headers)
                except Exception as e:
                    sys.stderr.write(f"[bridge] Execution error: {e}\n")

        await asyncio.gather(sse_reader(), stdin_reader())

def main():
    parser = argparse.ArgumentParser(description="Unified MCP Gateway (FastAPI + MCP Server + Bridge)")
    parser.add_argument("--mcp-server", action="store_true", help="Run in MCP Server mode (local tools)")
    parser.add_argument("--cli", action="store_true", help="Run in interactive CLI mode")
    parser.add_argument("--bridge", action="store_true", help="Run in SSE Bridge mode")
    parser.add_argument("--url", type=str, help="SSE URL for bridge mode")
    parser.add_argument("--key", type=str, help="API Key for bridge mode")
    parser.add_argument("--prefix", type=str, default="", help="Prefix for discovered POST URL")
    parser.add_argument("--no-verify", action="store_false", dest="verify", help="Disable SSL verification")
    parser.add_argument("--port", type=int, default=8000, help="Port for FastAPI server")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host for FastAPI server")
    parser.set_defaults(verify=True)
    
    args = parser.parse_args()
    
    if args.bridge:
        if not args.url or not args.key:
            print("Error: --url and --key are required for bridge mode.")
            sys.exit(1)
        asyncio.run(run_sse_bridge(args.url, args.key, base_prefix=args.prefix, verify_ssl=args.verify))
    elif args.mcp_server:
        print("Starting Local MCP Server (Filesystem)...")
        mcp.run()
    elif args.cli:
        asyncio.run(run_cli())
    else:
        print(f"Starting MCP Gateway API on {args.host}:{args.port}...")
        uvicorn.run(app, host=args.host, port=args.port)

if __name__ == "__main__":
    main()

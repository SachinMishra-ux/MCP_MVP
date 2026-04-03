import os
import sys
import argparse
import asyncio
import json
import uvicorn
import httpx
from contextlib import asynccontextmanager
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
mcp_client: Optional[LLMMCPClient] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global mcp_client
    if LLMMCPClient is None:
        raise RuntimeError(
            "FATAL: mcp_client_logic failed to import. "
            "Ensure langchain_litellm, langgraph and all dependencies are bundled correctly."
        )
    config_path = os.environ.get("MCP_CONFIG_PATH", "config.json")
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
        config_path = os.path.join(base_path, config_path)
    
    print(f"Starting MCP Client with config: {config_path}")
    mcp_client = LLMMCPClient(config_path)
    await mcp_client.connect_servers()
    yield
    # Shutdown: nothing to explicitly clean up (os._exit handles it)

app = FastAPI(title="MCP Gateway API", version="1.0.0", lifespan=lifespan)

class ChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = "default"
    history: Optional[List[Dict[str, Any]]] = None

class ChatResponse(BaseModel):
    response: str
    model: str

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
    SSE <-> stdio bridge for Chromosome/AgentBuilder MCP servers.

    Architecture (mirrors reference repo pattern):
      - sse_reader  : Keeps ONE SSE connection open forever, discovers the POST
                      endpoint from the first data line, then pipes all subsequent
                      JSON-RPC responses → stdout.
      - stdin_reader: Reads JSON-RPC requests from stdin and puts them in a queue
                      immediately — never blocks waiting for SSE.
      - dispatcher  : Waits for the endpoint to be discovered, then drains the
                      queue and sends every queued+new request via HTTP POST.

    The Queue prevents the "initialize deadlock": the MCP client sends initialize
    right away; we buffer it, discover the endpoint via SSE, then flush.
    """
    sse_headers  = {"x-api-key": api_key, "Accept": "text/event-stream", "Cache-Control": "no-store"}
    post_headers = {"x-api-key": api_key, "Content-Type": "application/json"}

    post_url_ready = asyncio.Event()
    post_url_holder = []          # list used as a mutable cell (nonlocal + list trick)
    request_queue: asyncio.Queue = asyncio.Queue()

    sys.stderr.write(f"[bridge] Starting bridge → {sse_url}\n")
    sys.stderr.write(f"[bridge] SSL verify: {verify_ssl}\n")
    sys.stderr.flush()

    async with httpx.AsyncClient(timeout=None, verify=verify_ssl) as client:

        # ── 1. SSE reader ────────────────────────────────────────────────────
        async def sse_reader():
            try:
                sys.stderr.write("[bridge] Connecting to SSE...\n")
                sys.stderr.flush()
                async with client.stream("GET", sse_url, headers=sse_headers) as resp:
                    if resp.status_code != 200:
                        sys.stderr.write(f"[bridge] SSE HTTP error: {resp.status_code}\n")
                        sys.stderr.flush()
                        post_url_ready.set()   # unblock dispatcher so it can exit cleanly
                        return

                    sys.stderr.write("[bridge] SSE stream opened\n")
                    sys.stderr.flush()
                    endpoint_received = False

                    async for line in resp.aiter_lines():
                        if not line or line.startswith(":") or line.startswith("event:"):
                            continue
                        if not line.startswith("data:"):
                            continue

                        data = line[5:].strip()   # strip "data:"
                        if not data:
                            continue

                        if not endpoint_received:
                            # First data line = relative path of the POST endpoint
                            path = data
                            if base_prefix and not path.startswith(base_prefix):
                                path = base_prefix + path
                            parsed = urlparse(sse_url)
                            post_url_holder.append(f"{parsed.scheme}://{parsed.netloc}{path}")
                            sys.stderr.write(f"[bridge] POST endpoint: {post_url_holder[0]}\n")
                            sys.stderr.flush()
                            endpoint_received = True
                            post_url_ready.set()   # signal dispatcher
                        else:
                            # Subsequent data lines = JSON-RPC responses from server → stdout
                            try:
                                json.loads(data)   # validate
                                sys.stdout.write(data + "\n")
                                sys.stdout.flush()
                            except json.JSONDecodeError:
                                pass   # silently skip non-JSON SSE noise

            except Exception as exc:
                sys.stderr.write(f"[bridge] SSE error: {exc}\n")
                sys.stderr.flush()
                post_url_ready.set()   # don't leave dispatcher blocked

        # ── 2. stdin reader ──────────────────────────────────────────────────
        async def stdin_reader():
            """Reads stdin lines and enqueues them immediately — never blocks."""
            sys.stderr.write("[bridge] stdin reader ready\n")
            sys.stderr.flush()
            loop = asyncio.get_event_loop()

            def _read_line():
                return sys.stdin.readline()

            while True:
                line = await loop.run_in_executor(None, _read_line)
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    await request_queue.put(msg)
                except json.JSONDecodeError as exc:
                    sys.stderr.write(f"[bridge] Bad JSON from stdin: {exc}\n")
                    sys.stderr.flush()

            await request_queue.put(None)   # sentinel → tell dispatcher to stop

        # ── 3. dispatcher ────────────────────────────────────────────────────
        async def dispatcher():
            """Waits for SSE endpoint, then drains queue and forwards via POST."""
            sys.stderr.write("[bridge] dispatcher waiting for SSE endpoint...\n")
            sys.stderr.flush()
            await post_url_ready.wait()

            if not post_url_holder:
                sys.stderr.write("[bridge] No endpoint discovered — exiting dispatcher.\n")
                sys.stderr.flush()
                return

            url = post_url_holder[0]
            sys.stderr.write(f"[bridge] dispatcher active, forwarding to {url}\n")
            sys.stderr.flush()

            while True:
                msg = await request_queue.get()
                if msg is None:   # sentinel
                    break
                try:
                    resp = await client.post(url, json=msg, headers=post_headers)
                    sys.stderr.write(f"[bridge] POST {msg.get('method','?')} → {resp.status_code}\n")
                    sys.stderr.flush()
                except Exception as exc:
                    sys.stderr.write(f"[bridge] POST error: {exc}\n")
                    sys.stderr.flush()

        await asyncio.gather(sse_reader(), stdin_reader(), dispatcher())


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

# client/client.py
import sys
import os
import json
import traceback
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
import uvicorn

import httpx
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent
from pydantic import Field, create_model
from typing import Any
from urllib.parse import urlparse as _urlparse

load_dotenv()

# Project root resolution that works when imported, run directly, or as a PyInstaller bundle
if getattr(sys, 'frozen', False):
    # Running as a bundled executable
    project_root = os.path.dirname(sys.executable)
else:
    # Running in a normal Python environment
    current_script_path = os.path.abspath(__file__)
    client_dir = os.path.dirname(current_script_path)
    project_root = os.path.abspath(os.path.join(client_dir, ".."))


def load_mcp_config():
    config_path = os.path.join(project_root, "config.json")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found at: {config_path}")

    print(f"📂 Reading config from: {config_path}")
    with open(config_path, "r") as f:
        config_data = json.load(f)

    if "mcpServers" in config_data:
        config_data = config_data["mcpServers"]

    servers = {}
    for server_name, settings in config_data.items():
        transport = settings.get("transport", "stdio")

        if transport == "sse":
            url = settings.get("url")
            api_key = settings.get("api_key") or settings.get("headers", {}).get("x-api-key")
            prefix = settings.get("prefix", "")

            if not url or not api_key:
                print(f"⚠️ Skipping SSE server '{server_name}': URL or API key missing.")
                continue

            # We'll use our own bridge mode by spawning this same application
            if getattr(sys, 'frozen', False):
                # Frozen: run the executable itself in bridge mode
                command = sys.executable
                args = ["--bridge", "--url", url, "--key", api_key]
                if prefix:
                    args += ["--prefix", prefix]
            else:
                # Dev: run 'python main.py' in bridge mode
                command = sys.executable
                main_script = os.path.join(project_root, "main.py")
                args = [main_script, "--bridge", "--url", url, "--key", api_key]
                if prefix:
                    args += ["--prefix", prefix]

            servers[server_name] = {
                "_transport": "sse_direct",  # handled in-process; no subprocess needed
                "url": url,
                "api_key": api_key,
                "prefix": prefix,
            }
            print(f"🌉 SSE direct registered: {server_name} → {url}")
        elif transport == "stdio":
            custom_command = settings.get("command")
            custom_args = settings.get("args", [])
            custom_env = settings.get("env", {})

            resolved_env = {
                k: os.getenv(v, v) for k, v in custom_env.items()
            }
            full_env = {**os.environ, **resolved_env} if resolved_env else None

            if custom_command:
                executable = custom_command
                if custom_command == "python" or custom_command == "python3":
                    executable = sys.executable
                
                # If command is a relative path, resolve it against project_root
                if not os.path.isabs(executable) and not executable.startswith(("uvx", "npx")):
                    candidate_path = os.path.abspath(os.path.join(project_root, executable))
                    if os.path.exists(candidate_path):
                        executable = candidate_path
                    elif os.path.exists(candidate_path + ".exe"): # Windows fallback
                        executable = candidate_path + ".exe"
                
                server_config = {
                    "transport": "stdio",
                    "command": executable,
                    "args": custom_args,
                }
                if full_env:
                    server_config["env"] = full_env

                servers[server_name] = server_config
                print(f"🔧 stdio (custom cmd) registered: {server_name} → {executable}")
    
            else:
                script_rel_path = settings.get("script_path")
                if not script_rel_path:
                    continue
                script_abs_path = os.path.join(project_root, script_rel_path)
                servers[server_name] = {
                    "transport": "stdio",
                    "command": sys.executable,
                    "args": [script_abs_path],
                }
                print(f"🖥️ stdio server registered: {server_name} → {script_abs_path}")

    return servers


# ---------------------------------------------------------------------------
# In-process SSE MCP client (avoids subprocess bridge on Windows)
# ---------------------------------------------------------------------------

async def _sse_rpc(sse_url: str, api_key: str, prefix: str,
                   method: str, params: dict, timeout: float = 30.0) -> dict:
    """
    Open a fresh SSE session, perform the MCP initialize handshake,
    execute ONE method call, and return the JSON-RPC result dict.
    No subprocess is spawned — everything runs in the gateway process.
    """
    sse_hdrs = {"x-api-key": api_key, "Accept": "text/event-stream", "Cache-Control": "no-store"}
    post_hdrs = {"x-api-key": api_key, "Content-Type": "application/json"}
    q: asyncio.Queue = asyncio.Queue()
    ready = asyncio.Event()
    purl: list = [None]

    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout), verify=False) as http:

        async def _sse_reader():
            async with http.stream("GET", sse_url, headers=sse_hdrs) as resp:
                resp.raise_for_status()
                async for ln in resp.aiter_lines():
                    if not ln or ln.startswith(":") or ln.startswith("event:"): continue
                    if ln.startswith("data:"):
                        data = ln[5:].strip()
                        if purl[0] is None:
                            path = (prefix + data) if prefix and not data.startswith(prefix) else data
                            p = _urlparse(sse_url)
                            purl[0] = f"{p.scheme}://{p.netloc}{path}"
                            ready.set()
                        else:
                            try:
                                await q.put(json.loads(data))
                            except Exception:
                                pass

        sse_task = asyncio.ensure_future(_sse_reader())
        try:
            await asyncio.wait_for(ready.wait(), timeout=timeout)
            url = purl[0]

            # MCP initialize
            await http.post(url, headers=post_hdrs, json={
                "jsonrpc": "2.0", "id": 0, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                            "clientInfo": {"name": "mcp-gateway", "version": "1.0"}}
            })
            await asyncio.wait_for(q.get(), timeout=timeout)

            # initialized notification (fire-and-forget)
            await http.post(url, headers=post_hdrs, json={
                "jsonrpc": "2.0", "method": "notifications/initialized", "params": {}
            })

            # actual method call
            await http.post(url, headers=post_hdrs, json={
                "jsonrpc": "2.0", "id": 1, "method": method, "params": params
            })
            result_msg = await asyncio.wait_for(q.get(), timeout=timeout)
            return result_msg.get("result", {})
        finally:
            sse_task.cancel()
            try:
                await sse_task
            except asyncio.CancelledError:
                pass


def _make_tool_input_model(tool_name: str, schema: dict):
    """Build a Pydantic model from an MCP tool's inputSchema."""
    properties = schema.get("properties", {})
    required_fields = schema.get("required", [])
    fields: dict = {}
    for pname, pschema in properties.items():
        ptype_str = pschema.get("type", "string")
        ptype: Any = str
        if ptype_str in ("number", "integer"): ptype = float
        elif ptype_str == "boolean": ptype = bool
        elif ptype_str == "array": ptype = list
        elif ptype_str == "object": ptype = dict
        default = ... if pname in required_fields else None
        desc = pschema.get("description", pname)
        fields[pname] = (ptype, Field(default, description=desc))
    if not fields:
        return type("EmptyInput", (object,), {"__annotations__": {}})
    return create_model(f"{tool_name}Input", **fields)


async def get_sse_tools_direct(server_name: str, sse_url: str, api_key: str,
                                prefix: str = "", timeout: float = 30.0) -> list:
    """
    Discover AND wrap tools from an SSE MCP server entirely in-process.
    Returns LangChain StructuredTool objects with async execution support.
    """
    raw = await _sse_rpc(sse_url, api_key, prefix, "tools/list", {}, timeout=timeout)
    tool_defs = raw.get("tools", [])
    lc_tools = []

    for t in tool_defs:
        name = t["name"]
        desc = t.get("description", "")
        schema = t.get("inputSchema", {})
        input_model = _make_tool_input_model(name, schema)

        # Capture closure variables explicitly
        _url, _key, _pfx, _tname = sse_url, api_key, prefix, name

        async def _arun(_n=_tname, _u=_url, _k=_key, _p=_pfx, **kwargs):
            result = await _sse_rpc(_u, _k, _p, "tools/call",
                                    {"name": _n, "arguments": kwargs}, timeout=60.0)
            content = result.get("content", [])
            parts = [c.get("text", str(c)) for c in content if isinstance(c, dict)]
            return "\n".join(parts) if parts else str(result)

        lc_tools.append(StructuredTool(
            name=name,
            description=desc,
            args_schema=input_model,
            coroutine=_arun,
        ))

    return lc_tools


async def get_tools_safe(all_servers: dict) -> tuple[list, list]:
    all_tools = []
    failed_servers = []

    for server_name, server_config in all_servers.items():
        try:
            print(f"🔌 Connecting to '{server_name}'...")

            if server_config.get("_transport") == "sse_direct":
                # In-process SSE client: avoids slow subprocess startup on Windows
                tools = await asyncio.wait_for(
                    get_sse_tools_direct(
                        server_name,
                        server_config["url"],
                        server_config["api_key"],
                        server_config.get("prefix", ""),
                    ),
                    timeout=30.0,
                )
            else:
                client = MultiServerMCPClient({server_name: server_config})
                # Use a longer timeout (60s) for tool discovery to account for slow startup (especially on Windows)
                tools = await asyncio.wait_for(client.get_tools(), timeout=60.0)

            all_tools.extend(tools)
            print(f"✅ Loaded {len(tools)} tools from '{server_name}'")
        except asyncio.TimeoutError:
            print(f"⏱️ Timeout connecting to '{server_name}' — skipping.")
            failed_servers.append(server_name)
        except Exception as e:
            print(f"❌ Failed to load tools from '{server_name}': {e}")
            failed_servers.append(server_name)

    return all_tools, failed_servers


mcp_servers = {}
cached_tools = []
failed_servers = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mcp_servers, cached_tools, failed_servers
    try:
        mcp_servers = load_mcp_config()
        print(f"🔌 Servers configured: {list(mcp_servers.keys())}")
        
        # Discover and cache tools at startup
        print("🔍 Initializing MCP tools...")
        cached_tools, failed_servers = await get_tools_safe(mcp_servers)
        
        if failed_servers:
            print(f"⚠️ Some servers failed to load at startup: {failed_servers}")
        print(f"✅ Startup complete. {len(cached_tools)} tools cached.")
        
        yield
    except Exception as e:
        print(f"❌ Error during startup: {e}")
        raise
    finally:
        print("🔌 Shutting down...")


app = FastAPI(lifespan=lifespan)


class QueryRequest(BaseModel):
    prompt: str
    thread_id: str = "default_thread"

# Initialize in-memory checkpointer
memory = MemorySaver()


@app.post("/chat")
async def chat_endpoint(request: QueryRequest):
    global mcp_servers, cached_tools, failed_servers

    if not mcp_servers:
        raise HTTPException(status_code=500, detail="No MCP servers configured")

    try:
        # Use cached tools instead of re-discovering them
        tools = cached_tools
        failed = failed_servers

        if not tools:
            # OPTIONAL: If no tools were cached at startup, try one more time or fail
            if not failed:
                 raise HTTPException(status_code=503, detail="No tools available.")
            else:
                 raise HTTPException(
                    status_code=503,
                    detail=f"No tools available. All servers failed at startup: {failed}"
                )

        if failed:
            print(f"⚠️ Proceeding with cached tools (excluding failed: {failed})")

        llm = AzureChatOpenAI(
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
            azure_deployment=os.getenv("AZURE_DEPLOYMENT_NAME")
        )

        # Create the agent with memory persistence
        agent = create_react_agent(llm, tools, checkpointer=memory)
        
        # Configure the thread ID for history
        config = {"configurable": {"thread_id": request.thread_id}}
        
        # Invoke the agent
        inputs = {"messages": [HumanMessage(content=request.prompt)]}
        result = await agent.ainvoke(inputs, config=config)
        
        # Get the final response message
        final_message = result["messages"][-1]
        result_content = final_message.content
        
        if failed:
            result_content += f"\n\n⚠️ Note: These servers were unavailable: {failed}"
            
        return {"response": result_content}

    except HTTPException:
        raise
    except Exception as e:
        print("❌ Exception in chat_endpoint:")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tools")
async def list_tools():
    # Return cached tools directly
    return {
        "loaded": [t.name for t in cached_tools],
        "failed_servers": failed_servers
    }

def start_gateway(host="0.0.0.0", port=8010):
    print(f"🚀 Starting MCP Gateway on {host}:{port}...")
    uvicorn.run(app, host=host, port=port)

if __name__ == "__main__":
    start_gateway()

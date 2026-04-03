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

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, ToolMessage

load_dotenv()

# Project root resolution that works when imported or run directly
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
            if not url:
                print(f"⚠️ Skipping SSE server '{server_name}': no URL specified.")
                continue
            servers[server_name] = {
                "transport": "sse",
                "url": url,
                "headers": settings.get("headers", {}),
            }
            print(f"🌐 SSE server registered: {server_name} → {url}")
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
                
                server_config = {
                    "transport": "stdio",
                    "command": executable,
                    "args": custom_args,
                }
                if full_env:
                    server_config["env"] = full_env

                servers[server_name] = server_config
                print(f"🔧 stdio (custom cmd) registered: {server_name} → {custom_command}")
    
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


async def get_tools_safe(all_servers: dict) -> tuple[list, list]:
    all_tools = []
    failed_servers = []

    for server_name, server_config in all_servers.items():
        try:
            print(f"🔌 Connecting to '{server_name}'...")
            client = MultiServerMCPClient({server_name: server_config})
            tools = await asyncio.wait_for(client.get_tools(), timeout=15.0)
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mcp_servers
    try:
        mcp_servers = load_mcp_config()
        print(f"🔌 Servers configured: {list(mcp_servers.keys())}")
        yield
    except Exception as e:
        print(f"❌ Error during startup: {e}")
        raise
    finally:
        print("🔌 Shutting down...")


app = FastAPI(lifespan=lifespan)


class QueryRequest(BaseModel):
    prompt: str


@app.post("/chat")
async def chat_endpoint(request: QueryRequest):
    global mcp_servers

    if not mcp_servers:
        raise HTTPException(status_code=500, detail="No MCP servers configured")

    try:
        tools, failed = await get_tools_safe(mcp_servers)

        if not tools:
            raise HTTPException(
                status_code=503,
                detail=f"No tools available. All servers failed: {failed}"
            )

        if failed:
            print(f"⚠️ Proceeding without failed servers: {failed}")

        tool_map = {tool.name: tool for tool in tools}
        print(f"🛠️ Available tools: {list(tool_map.keys())}")

        llm = AzureChatOpenAI(
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
            azure_deployment=os.getenv("AZURE_DEPLOYMENT_NAME"),
            temperature=0
        )

        llm_with_tools = llm.bind_tools(tools)
        messages = [HumanMessage(content=request.prompt)]
        response = await llm_with_tools.ainvoke(messages)
        messages.append(response)

        if response.tool_calls:
            print(f"🛠️ LLM requested tools: {[t['name'] for t in response.tool_calls]}")
            for tc in response.tool_calls:
                t_name = tc["name"]
                t_args = tc["args"]
                t_id = tc["id"]

                if t_name in tool_map:
                    try:
                        print(f"  ▶ Running {t_name} with {t_args}...")
                        result = await tool_map[t_name].ainvoke(t_args)
                        messages.append(ToolMessage(tool_call_id=t_id, content=str(result)))
                    except Exception as tool_err:
                        err_msg = f"Error executing {t_name}: {str(tool_err)}"
                        print(f"  ❌ {err_msg}")
                        messages.append(ToolMessage(tool_call_id=t_id, content=err_msg))
                else:
                    print(f"  ❌ Tool '{t_name}' not found.")
                    messages.append(ToolMessage(tool_call_id=t_id, content="Error: Tool not found"))

            final_response = await llm_with_tools.ainvoke(messages)
            
            result_content = final_response.content
            if failed:
                result_content += f"\n\n⚠️ Note: These servers were unavailable: {failed}"
            return {"response": result_content}

        return {"response": response.content}

    except HTTPException:
        raise
    except Exception as e:
        print("❌ Exception in chat_endpoint:")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tools")
async def list_tools():
    tools, failed = await get_tools_safe(mcp_servers)
    return {
        "loaded": [t.name for t in tools],
        "failed_servers": failed
    }

def start_gateway(host="0.0.0.0", port=8010):
    print(f"🚀 Starting MCP Gateway on {host}:{port}...")
    uvicorn.run(app, host=host, port=port)

if __name__ == "__main__":
    start_gateway()

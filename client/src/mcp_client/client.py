import asyncio
import json
import sys
import os
from typing import Dict, Any, List

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from contextlib import AsyncExitStack

from config_utils import setup_llm_config
import litellm

litellm.suppress_debug_info = True


class LLMMCPClient:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.stack = AsyncExitStack()
        self.sessions: Dict[str, ClientSession] = {}
        self.available_tools = []
        self.connected_servers = []

        env_path = os.environ.get("ENV_PATH", ".env")
        setup_llm_config(env_path)
        self.model = os.environ.get("LLM_MODEL")

    def _load_config(self) -> Dict[str, Any]:
        if not os.path.exists(self.config_path):
            return {"mcpServers": {}}
        with open(self.config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _get_sse_bridge_path(self):
        """Resolve sse_bridge path for dev + exe"""
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(__file__)

        return os.path.join(base_path, "sse_bridge.py")

    async def connect_servers(self):
        config = self._load_config()
        servers = config.get("mcpServers", {})

        for name, server_config in servers.items():
            try:
                print(f"Connecting to {name}...")

                url = server_config.get("url")

                if url:
                    # 🔥 SSE via bridge
                    api_key = server_config.get("api_key") or os.environ.get("MCP_API_KEY")

                    if not api_key:
                        print(f"[!] Missing API key for {name}")
                        continue

                    sse_bridge_path = self._get_sse_bridge_path()

                    if not os.path.exists(sse_bridge_path):
                        print(f"[!] sse_bridge.py not found at {sse_bridge_path}")
                        continue

                    print(f"[{name}] Using SSE Bridge → {url}")

                    server_params = StdioServerParameters(
                        command=sys.executable,
                        args=[sse_bridge_path, url, api_key],
                    )

                    transport_ctx = stdio_client(server_params)

                else:
                    # 🔥 Normal stdio servers
                    command = server_config.get("command")
                    args = server_config.get("args", [])
                    env = server_config.get("env", None)

                    if not command:
                        print(f"Error: No command or url for {name}")
                        continue

                    server_params = StdioServerParameters(
                        command=command,
                        args=args,
                        env=env
                    )

                    transport_ctx = stdio_client(server_params)

                stdio_transport = await self.stack.enter_async_context(transport_ctx)
                read, write = stdio_transport

                session = await self.stack.enter_async_context(ClientSession(read, write))
                await session.initialize()

                self.sessions[name] = session
                self.connected_servers.append(name)

                print(f"Connected to {name} successfully.")

            except Exception as e:
                print(f"\n[!] Failed to connect to MCP server '{name}': {e}")
                continue

        await self._cache_tools()

    async def _cache_tools(self):
        self.available_tools = []
        for server_name, session in self.sessions.items():
            try:
                response = await session.list_tools()
                for tool in response.tools:
                    self.available_tools.append({
                        "server": server_name,
                        "mcp_tool": tool
                    })
            except Exception as e:
                print(f"Warning: Could not list tools for {server_name}: {e}")

    def _get_llm_tools(self) -> List[Dict[str, Any]]:
        llm_tools = []
        for t in self.available_tools:
            mcp_tool = t["mcp_tool"]
            llm_tools.append({
                "type": "function",
                "function": {
                    "name": mcp_tool.name,
                    "description": mcp_tool.description or "",
                    "parameters": mcp_tool.inputSchema
                }
            })
        return llm_tools

    async def chat(self, user_msg: str, history: List[Dict[str, Any]] = None) -> str:
        if not self.sessions:
            await self.connect_servers()

        server_names = ", ".join(self.connected_servers) or "No servers connected"

        system_prompt = (
            "You are an AI connected to MCP servers: "
            f"{server_names}. Use tools when needed."
        )

        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_msg})

        while True:
            response = await litellm.acompletion(
                model=self.model,
                messages=messages,
                tools=self._get_llm_tools() if self.available_tools else None
            )

            msg = response.choices[0].message
            messages.append(msg.model_dump())

            if msg.tool_calls:
                for tool_call in msg.tool_calls:
                    name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments or "{}")

                    print(f"[{self.model}] Executing {name}")

                    server = next(
                        (t["server"] for t in self.available_tools if t["mcp_tool"].name == name),
                        None
                    )

                    if not server:
                        result_text = f"Tool {name} not found"
                    else:
                        try:
                            result = await self.sessions[server].call_tool(name, arguments=args)
                            result_text = "\n".join(
                                item.text for item in result.content if item.type == "text"
                            )
                        except Exception as e:
                            result_text = f"Tool error: {e}"

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": name,
                        "content": result_text
                    })
            else:
                return msg.content


def run_llm_client():
    config_path = os.environ.get("MCP_CONFIG_PATH", "config.json")

    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
        config_path = os.path.join(base_path, config_path)
        os.environ["ENV_PATH"] = os.path.join(base_path, ".env")

    client = LLMMCPClient(config_path)
    asyncio.run(client.connect_servers())
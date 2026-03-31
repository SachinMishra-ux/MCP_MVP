import asyncio
import json
import sys
import os
import traceback
from typing import Dict, Any, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
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
        
        # Using environment file path if packaged, else just local .env
        env_path = os.environ.get("ENV_PATH", ".env")
        setup_llm_config(env_path)
        self.model = os.environ.get("LLM_MODEL")

    def _load_config(self) -> Dict[str, Any]:
        if not os.path.exists(self.config_path):
            return {"mcpServers": {}}
        with open(self.config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    async def connect_servers(self):
        config = self._load_config()
        servers = config.get("mcpServers", {})
        
        for name, server_config in servers.items():
            try:
                print(f"Connecting to {name}...")
                
                # Check for SSE URL vs Stdio command
                url = server_config.get("url")
                if url:
                    # SSE Transport
                    transport_ctx = sse_client(url)
                else:
                    # Stdio Transport
                    command = server_config.get("command")
                    args = server_config.get("args", [])
                    env = server_config.get("env", None)
                    if not command:
                        print(f"Error: No command or url found for server {name}")
                        continue
                    
                    server_params = StdioServerParameters(command=command, args=args, env=env)
                    transport_ctx = stdio_client(server_params)

                # Each server gets its own sub-exit stack to prevent one crash 
                # from causing the RuntimeError: Attempted to exit cancel scope
                # mentioned in documentation when using global stack during failure.
                stdio_transport = await self.stack.enter_async_context(transport_ctx)
                read, write = stdio_transport
                session = await self.stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                
                self.sessions[name] = session
                self.connected_servers.append(name)
                print(f"Connected to {name} successfully.")
                
            except Exception as e:
                print(f"\n[!] Failed to connect to MCP server '{name}': {e}")
                # We do NOT let one bad server crash the whole client
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
        """
        Unified chat method that handles tools and LLM logic.
        Can be called by FastAPI or CLI.
        """
        if not self.sessions:
            await self.connect_servers()

        server_names = ", ".join(self.connected_servers) or "No servers connected"
        system_prompt = (
            "You are a sophisticated AI assistant connected to the Model Context Protocol (MCP). "
            f"You have direct access to the following connected MCP servers: {server_names}. "
            "When the user asks about your capabilities, servers, or resources, explain that you "
            f"are connected to these MCP servers ({server_names}) and you can use their attached tools to read systems, files, and external APIs. "
            "Use the provided tools to help the user directly."
        )
        
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_msg})
        
        # Agentic tool calling loop
        error_retries = 0
        max_error_retries = 3
        while True:
            try:
                kwargs = {
                    "model": self.model,
                    "messages": messages,
                    "tools": self._get_llm_tools() if self.available_tools else None
                }
                
                # Extract any custom endpoints from env
                azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT") or os.environ.get("AZURE_API_BASE")
                if azure_endpoint:
                    kwargs["api_base"] = azure_endpoint
                if os.environ.get("AZURE_API_VERSION"):
                    kwargs["api_version"] = os.environ.get("AZURE_API_VERSION")

                response = await litellm.acompletion(**kwargs)
                error_retries = 0
            except Exception as e:
                error_str = str(e)
                print(f"[DEBUG] LiteLLM Error: {error_str}")
                error_retries += 1
                if error_retries >= max_error_retries:
                    return f"Error: Repeated failures while talking to AI ({error_str})"
                
                messages.append({
                    "role": "user", 
                    "content": f"System Warning: Your previous tool call failed with: {error_str}. Do NOT call any tools. Just respond to the user in natural language explaining what went wrong."
                })
                continue

            response_msg = response.choices[0].message
            messages.append(response_msg.model_dump())
            
            if response_msg.tool_calls:
                for tool_call in response_msg.tool_calls:
                    func_name = tool_call.function.name
                    try:
                        func_args = json.loads(tool_call.function.arguments)
                    except:
                        func_args = {}
                        
                    print(f"[{self.model}] Executing tool '{func_name}'")
                    
                    target_server = None
                    for t in self.available_tools:
                        if t["mcp_tool"].name == func_name:
                            target_server = t["server"]
                            break
                            
                    if not target_server:
                        result_text = f"Tool {func_name} not found across active MCP servers."
                    else:
                        try:
                            session = self.sessions[target_server]
                            result = await session.call_tool(func_name, arguments=func_args)
                            result_text = "\n".join(
                                item.text for item in result.content if item.type == "text"
                            )
                        except Exception as e:
                            result_text = f"Error executing tool: {e}"
                            
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": func_name,
                        "content": result_text
                    })
            else: 
                return response_msg.content

    async def run_chat_loop(self):
        """Legacy CLI loop for backward compatibility."""
        try:
            await self.connect_servers()
        except Exception as e:
            print(f"Error connecting to servers: {e}")
            return

        print("\n" + "="*50)
        print(f"MCP Client Ready! Using Model: {self.model}")
        print("Type 'exit' or 'quit' to close.")
        print("="*50 + "\n")
        
        history = []
        while True:
            try:
                user_msg = input("You: ").strip()
                if user_msg.lower() in ('quit', 'exit'):
                    break
                if not user_msg:
                    continue
                
                response = await self.chat(user_msg, history)
                history.append({"role": "user", "content": user_msg})
                history.append({"role": "assistant", "content": response})
                print(f"\nAI: {response}\n")
                
            except (EOFError, KeyboardInterrupt):
                break

        print("\nShutting down connections...")
        os._exit(0)


def run_llm_client():
    config_path = os.environ.get("MCP_CONFIG_PATH", "config.json")
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
        config_path = os.path.join(base_path, config_path)
        os.environ["ENV_PATH"] = os.path.join(base_path, ".env")
        
    client = LLMMCPClient(config_path)
    asyncio.run(client.run_chat_loop())

if __name__ == "__main__":
    run_llm_client()

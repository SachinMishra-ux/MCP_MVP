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
        
        # Using environment file path if packaged, else just local .env
        env_path = os.environ.get("ENV_PATH", ".env")
        setup_llm_config(env_path)
        self.model = os.environ.get("LLM_MODEL")

    def _load_config(self) -> Dict[str, Any]:
        with open(self.config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    async def connect_servers(self):
        config = self._load_config()
        servers = config.get("mcpServers", {})
        
        for name, server_config in servers.items():
            print(f"Connecting to {name}...")
            command = server_config.get("command")
            args = server_config.get("args", [])
            env = server_config.get("env", None)
            
            server_params = StdioServerParameters(command=command, args=args, env=env)
            
            stdio_transport = await self.stack.enter_async_context(stdio_client(server_params))
            read, write = stdio_transport
            session = await self.stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            
            self.sessions[name] = session
            print(f"Connected to {name} successfully.")
            
        await self._cache_tools()

    async def _cache_tools(self):
        self.available_tools = []
        self.connected_servers = list(self.sessions.keys())
        for server_name, session in self.sessions.items():
            response = await session.list_tools()
            for tool in response.tools:
                self.available_tools.append({
                    "server": server_name,
                    "mcp_tool": tool
                })

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

    async def run_chat_loop(self):
        try:
            await self.connect_servers()
        except Exception as e:
            print(f"Error connecting to servers: {e}")
            return

        print("\n" + "="*50)
        print(f"MCP Client Ready! Using Model: {self.model}")
        print("Type 'exit' or 'quit' to close.")
        print("="*50 + "\n")
        
        
        server_names = ", ".join(self.connected_servers)
        system_prompt = (
            "You are a sophisticated AI assistant connected to the Model Context Protocol (MCP). "
            f"You have direct access to the following connected MCP servers: {server_names}. "
            "When the user asks about your capabilities, servers, or resources, explain that you "
            f"are connected to these MCP servers ({server_names}) and you can use their attached tools to read systems, files, and external APIs. "
            "Use the provided tools to help the user directly."
        )
        
        messages = [{"role": "system", "content": system_prompt}]
        
        while True:
            try:
                user_msg = input("You: ").strip()
                if user_msg.lower() in ('quit', 'exit'):
                    break
                if not user_msg:
                    continue
            except (EOFError, KeyboardInterrupt):
                break

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
                    if os.environ.get("AZURE_OPENAI_ENDPOINT"):
                        kwargs["api_base"] = os.environ.get("AZURE_OPENAI_ENDPOINT")
                    elif os.environ.get("AZURE_API_BASE"):
                        kwargs["api_base"] = os.environ.get("AZURE_API_BASE")
                    
                    if os.environ.get("AZURE_API_VERSION"):
                        kwargs["api_version"] = os.environ.get("AZURE_API_VERSION")

                    response = await litellm.acompletion(**kwargs)
                    error_retries = 0  # Reset on success
                except Exception as e:
                    error_str = str(e)
                    # For authentication or connection issues, we ask to reconfigure
                    if "AuthenticationError" in error_str or "APIConnectionError" in error_str or "NotFoundError" in error_str or "invalid_api_key" in error_str or "model_decommissioned" in error_str:
                        print(f"\n[!] LLM Connection Error: {error_str}")
                        print("[!] Hint: Make sure the Model Name actually exists on your selected provider and your API Key is valid.")
                        retry = input("Would you like to reconfigure your LLM settings now? (y/n): ").strip().lower()
                        if retry == 'y':
                            env_path = os.environ.get("ENV_PATH", ".env")
                            if os.path.exists(env_path):
                                os.remove(env_path)
                            for key in ["LLM_MODEL", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GROQ_API_KEY", "AZURE_API_KEY"]:
                                if key in os.environ:
                                    del os.environ[key]
                            from config_utils import setup_llm_config
                            setup_llm_config(env_path)
                            self.model = os.environ.get("LLM_MODEL")
                            print(f"\nResuming query with model {self.model}...\n")
                            error_retries = 0
                            continue
                        else:
                            break
                    else:
                        error_retries += 1
                        print(f"\n[DEBUG] LiteLLM Error: {error_str}")
                        if error_retries >= max_error_retries:
                            print(f"\nAI: Sorry, I encountered a repeated error and couldn't complete your request. Please try rephrasing your question.\n")
                            break
                        # Feed error back to LLM so it can respond naturally (but only up to max_error_retries times)
                        messages.append({
                            "role": "user", 
                            "content": f"System Warning: Your previous tool call failed with: {error_str}. Do NOT call any tools. Just respond to the user in natural language explaining what went wrong."
                        })
                        continue

                response_msg = response.choices[0].message
                
                # Append the assistant's message to the conversation
                # litellm returns objects that can be directly passed back in many cases, but we need dict representation
                messages.append(response_msg.model_dump())
                
                if response_msg.tool_calls:
                    for tool_call in response_msg.tool_calls:
                        func_name = tool_call.function.name
                        try:
                            func_args = json.loads(tool_call.function.arguments)
                        except:
                            func_args = {}
                            
                        print(f"[{self.model}] Executing tool '{func_name}' with kwargs: {func_args}")
                        
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
                    # End of agentic loop
                    print(f"\nAI: {response_msg.content}\n")
                    break

        print("\nShutting down connections...")
        os._exit(0)


def run_llm_client():
    config_path = os.environ.get("MCP_CONFIG_PATH", "config.json")
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
        config_path = os.path.join(base_path, config_path)
        # Check if environment file is generated next to executable
        os.environ["ENV_PATH"] = os.path.join(base_path, ".env")
        
    if not os.path.exists(config_path):
        print(f"Error: {config_path} not found.")
        sys.exit(1)
        
    client = LLMMCPClient(config_path)
    asyncio.run(client.run_chat_loop())

if __name__ == "__main__":
    run_llm_client()

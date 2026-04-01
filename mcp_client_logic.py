import asyncio
import json
import sys
import os
import traceback
from typing import Dict, Any, List, Optional, Annotated, Sequence
from typing_extensions import TypedDict

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from contextlib import AsyncExitStack

from config_utils import setup_llm_config
import litellm

# LangGraph & LangChain imports
from langchain_community.chat_models import ChatLiteLLM
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

litellm.suppress_debug_info = True

class State(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]

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
        
        # Initialize LangGraph components
        self.checkpointer = MemorySaver()
        self.app = None
        self.tools = []

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
            
        await self._setup_graph()

    async def _setup_graph(self):
        """Initializes the LangGraph with MCP tools."""
        # 1. Fetch tools from all servers
        self.available_tools = []
        langchain_tools = []
        
        for server_name, session in self.sessions.items():
            try:
                response = await session.list_tools()
                for t in response.tools:
                    self.available_tools.append({"server": server_name, "mcp_tool": t})
                    
                    # Create a closure-safe tool for LangChain
                    def create_tool(s_name, m_tool):
                        async def mcp_tool_func(**kwargs):
                            session = self.sessions[s_name]
                            result = await session.call_tool(m_tool.name, arguments=kwargs)
                            return "\n".join(item.text for item in result.content if item.type == "text")
                        
                        # Set metadata to match LangChain requirements
                        mcp_tool_func.__name__ = m_tool.name
                        mcp_tool_func.__doc__ = m_tool.description or ""
                        return tool(mcp_tool_func)

                    langchain_tools.append(create_tool(server_name, t))
            except Exception as e:
                print(f"Warning: Could not list tools for {server_name}: {e}")

        # 2. Setup LLM (Using ChatLiteLLM to preserve working litellm connectivity)
        # This automatically handles azure/, openai/, etc. prefixes using your .env
        llm = ChatLiteLLM(
            model=self.model,
            streaming=True,
            handle_tool_calling_errors=True
        )

        # 3. Create the Graph
        model_with_tools = llm.bind_tools(langchain_tools)

        def call_model(state: State):
            messages = state['messages']
            response = model_with_tools.invoke(messages)
            return {"messages": [response]}

        # Define the nodes and edges
        workflow = StateGraph(State)
        workflow.add_node("agent", call_model)
        workflow.add_node("tools", ToolNode(langchain_tools))

        workflow.add_edge(START, "agent")
        
        def should_continue(state: State):
            messages = state['messages']
            last_message = messages[-1]
            if last_message.tool_calls:
                return "tools"
            return END

        workflow.add_conditional_edges("agent", should_continue)
        workflow.add_edge("tools", "agent")

        self.app = workflow.compile(checkpointer=self.checkpointer)
        print(f"LangGraph initialized with {len(langchain_tools)} tools.")

    async def chat(self, user_msg: str, history: List[Dict[str, Any]] = None, thread_id: str = "default") -> str:
        """
        Unified chat method using LangGraph for persistence.
        """
        if not self.app:
            await self.connect_servers()

        config = {"configurable": {"thread_id": thread_id}}
        
        # Start with system prompt if this is a new thread
        state = await self.app.aget_state(config)
        if not state.values:
            server_names = ", ".join(self.connected_servers) or "No servers connected"
            system_prompt = (
                "You are a sophisticated AI assistant connected to the Model Context Protocol (MCP). "
                f"You have direct access to the following connected MCP servers: {server_names}. "
                "Use the provided tools to help the user directly."
            )
            initial_input = {"messages": [SystemMessage(content=system_prompt), HumanMessage(content=user_msg)]}
        else:
            initial_input = {"messages": [HumanMessage(content=user_msg)]}

        # Run the graph
        async for event in self.app.astream(initial_input, config=config, stream_mode="values"):
            final_event = event
        
        last_message = final_event["messages"][-1]
        return last_message.content

    async def run_chat_loop(self):
        """Interactive CLI loop."""
        await self.connect_servers()
        print("\n" + "="*50)
        print(f"MCP Client Ready (LangGraph Persistent)! Using Model: {self.model}")
        print("Type 'exit' to close.")
        print("="*50 + "\n")
        
        while True:
            try:
                user_msg = input("You: ").strip()
                if user_msg.lower() in ('quit', 'exit'):
                    break
                if not user_msg:
                    continue
                
                response = await self.chat(user_msg, thread_id="cli-user")
                print(f"\nAI: {response}\n")
                
            except (EOFError, KeyboardInterrupt):
                break

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

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "client/src/mcp_client"))

import litellm
litellm.set_verbose = True
import asyncio
from client import LLMMCPClient

async def run():
    client = LLMMCPClient("release/config.json")
    client.model = "groq/llama-3.3-70b-versatile"
    os.environ["GROQ_API_KEY"] = "your-groq-api-key-here"
    await client.connect_servers()
    
    messages = [{"role": "system", "content": "You are a helpful AI assistant connected to an external system. Use the provided tools to help the user."}, {"role": "user", "content": "hi"}]
    print("\n" + "-"*30)
    print("Calling litellm with tools:", [t["mcp_tool"].name for t in client.available_tools])
    try:
        response = await litellm.acompletion(
            model=client.model,
            messages=messages,
            tools=client._get_llm_tools() if client.available_tools else None
        )
        print("SUCCESS")
    except Exception as e:
        print(f"ERROR: {type(e).__name__} - {str(e)}")
    
    try:
        await client.stack.aclose()
    except: pass

asyncio.run(run())

import sys
import os
import asyncio
sys.path.append("/Users/sachinmishra/Desktop/MCP_MVP/client/src/mcp_client")
import litellm
import logging

from client import LLMMCPClient
from mcp.types import TextContent

async def run():
    os.environ["LLM_MODEL"] = "groq/qwen/qwen3-32b"
    os.environ["GROQ_API_KEY"] = "your-groq-api-key-here"
    os.environ["MCP_CONFIG_PATH"] = "/Users/sachinmishra/Desktop/MCP_MVP/release/config.json"
    client = LLMMCPClient(os.environ["MCP_CONFIG_PATH"])
    await client.connect_servers()
    
    messages = [
        {"role": "system", "content": "You are connected to MCP..."},
        {"role": "user", "content": "list directory /Users/sachinmishra/Desktop"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_6Tf0",
                    "type": "function",
                    "function": {
                        "name": "list_directory",
                        "arguments": "{\"path\": \"/Users/sachinmishra/Desktop\"}"
                    }
                }
            ]
        },
        {
            "role": "tool",
            "tool_call_id": "call_6Tf0",
            "name": "list_directory",
            "content": str([TextContent(type='text', text='file1.txt\nfile2.txt')])
        }
    ]
    
    try:
        response = await litellm.acompletion(
            model=client.model,
            messages=messages,
            tools=client._get_llm_tools()
        )
        print("SUCCESS:", response)
    except Exception as e:
        print("FAILED EXCEPTION MSG:", str(e))
        print("FAILED EXCEPTION TYPE:", type(e))

asyncio.run(run())

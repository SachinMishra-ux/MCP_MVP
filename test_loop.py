import sys
import os
import asyncio
sys.path.append("/Users/sachinmishra/Desktop/MCP_MVP/client/src")
import litellm
import logging

from mcp_client.client import LLMMCPClient

async def run():
    os.environ["LLM_MODEL"] = "groq/qwen/qwen3-32b"
    os.environ["GROQ_API_KEY"] = "your-groq-api-key-here"
    os.environ["MCP_CONFIG_PATH"] = "/Users/sachinmishra/Desktop/MCP_MVP/release/config.json"
    client = LLMMCPClient(os.environ["MCP_CONFIG_PATH"])
    await client.connect_servers()
    
    # simulate the loop
    messages = [
        {"role": "system", "content": "You are connected to MCP..."},
        {"role": "user", "content": "list directory /Users/sachinmishra/Desktop/MCP_MVP/release"}
    ]
    
    response = await litellm.acompletion(
        model=client.model,
        messages=messages,
        tools=client._get_llm_tools()
    )
    
    tool_calls = response.choices[0].message.tool_calls
    print("TOOL CALLS:", tool_calls)
    
    assistant_msg = {
        "role": "assistant",
        "content": response.choices[0].message.content or ""
    }
    
    if tool_calls:
        assistant_msg["tool_calls"] = [
            {
                "id": t.id,
                "type": t.type,
                "function": {
                    "name": t.function.name,
                    "arguments": t.function.arguments
                }
            } for t in tool_calls
        ]
        
    messages.append(assistant_msg)
    
    # fake execute
    if tool_calls:
        messages.append({
            "role": "tool",
            "tool_call_id": assistant_msg["tool_calls"][0]["id"],
            "name": assistant_msg["tool_calls"][0]["function"]["name"],
            "content": "[TextContent(type='text', text='config.json')]"
        })
    
    try:
        response2 = await litellm.acompletion(
            model=client.model,
            messages=messages,
            tools=client._get_llm_tools()
        )
        print("SECOND SUCCESS:", response2)
    except Exception as e:
        print("SECOND FAILED EXCEPTION MSG:", str(e))
        print("SECOND FAILED EXCEPTION TYPE:", type(e))

asyncio.run(run())

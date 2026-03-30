import litellm
import os
import asyncio

async def test():
    try:
        os.environ["GROQ_API_KEY"] = "your-groq-api-key-here"
        response = await litellm.acompletion(
            model="groq/qwen/qwen3-32b",
            messages=[
                {"role": "user", "content": "list dir"},
                {"role": "assistant", "content": "", "tool_calls": [{"id": "call_123", "type": "function", "function": {"name": "list_directory", "arguments": "{\"path\": \".\"}"}}]},
                {"role": "tool", "tool_call_id": "call_123", "name": "list_directory", "content": "file.txt"}
            ],
            tools=[{
                "type": "function",
                "function": {
                    "name": "list_directory",
                    "description": "List files",
                    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}
                }
            }]
        )
        print("SUCCESS:", response)
    except Exception as e:
        print("EXCEPTION CLASS:", type(e).__name__)
        print("EXCEPTION STR:", str(e))

asyncio.run(test())

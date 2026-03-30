import litellm
import os
import asyncio

async def test():
    try:
        os.environ["GROQ_API_KEY"] = "your-groq-api-key-here"
        response = await litellm.acompletion(
            model="groq/qwen/qwen3-32b",
            messages=[{"role": "user", "content": "What kind of MCP server access do you have?"}],
            tools=[{
                "type": "function",
                "function": {
                    "name": "list_directory",
                    "description": "List files",
                    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}
                }
            }]
        )
        print("SUCCESS:", response.choices[0].message)
    except Exception as e:
        print("EXCEPTION CLASS:", type(e).__name__)
        print("EXCEPTION STR:", str(e))

asyncio.run(test())

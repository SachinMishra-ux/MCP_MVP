import litellm
import os
litellm.set_verbose = True
from dotenv import load_dotenv
import asyncio

async def test():
    load_dotenv("release/.env")
    print(f"Loaded Key: {os.environ.get('GROQ_API_KEY')}")
    print(f"Loaded Model: {os.environ.get('LLM_MODEL')}")
    
    try:
        response = await litellm.acompletion(
            model=os.environ.get('LLM_MODEL'),
            messages=[{"role": "user", "content": "hi"}],
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

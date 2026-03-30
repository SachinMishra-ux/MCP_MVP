import sys
sys.path.append("/Users/sachinmishra/Desktop/MCP_MVP/venv/lib/python3.12/site-packages")
import litellm
import asyncio
import os

async def run():
    try:
        os.environ["GROQ_API_KEY"] = ""  # Empty key
        response = await litellm.acompletion(
            model="groq/llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": "hi"}],
            api_key=""
        )
        print("Success")
    except Exception as e:
        print("EXCEPTION CLASS:", type(e).__name__)
        print("EXCEPTION TYPE STR:", str(type(e)))
        print("EXCEPTION MSG:", str(e))

asyncio.run(run())

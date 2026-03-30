import litellm
import asyncio

async def run():
    try:
        response = await litellm.acompletion(
            model="groq/llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": "hi"}],
            api_key=""
        )
    except Exception as e:
        print("EXCEPTION CLASS:", e.__class__.__name__)
        print("EXCEPTION MSG:", str(e))

asyncio.run(run())

import litellm
import os
import asyncio

async def test():
    try:
        os.environ["GROQ_API_KEY"] = "your-groq-api-key-here"
        response = await litellm.acompletion(
            model="groq/qwen/qwen3-32b",
            messages=[{"role": "user", "content": "hi"}],
        )
        print("SUCCESS:", response.choices[0].message.content)
    except Exception as e:
        print("EXCEPTION CLASS:", type(e).__name__)
        print("EXCEPTION STR:", str(e))

asyncio.run(test())

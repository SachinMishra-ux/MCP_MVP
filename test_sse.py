import asyncio
import httpx

async def test():
    url = 'https://chromosome.tatatechnologies.com/agentbuilder-api/api/v1/mcp/project/f6c70ae9-ae3a-4be1-97c4-631e773eac5b/sse'
    headers = {
        'x-api-key': 'sk-X-R9VlE6FJL0E16KRu1Sp1Edisi2KmSR6luTM5gcCRc',
        'Accept': 'text/event-stream'
    }
    
    print(f"Connecting to {url}...")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            async with client.stream('GET', url, headers=headers) as sse:
                print(f"Status: {sse.status_code}")
                async for line in sse.aiter_lines():
                    if line:
                        print(line)
                        if line.startswith("data:"):
                            break
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test())

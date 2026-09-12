"""SSE is only a wakeup signal. Periodic MCP pulls remain necessary."""
import asyncio
import httpx

async def watch_telemetry(url: str, api_key: str, changed: asyncio.Event, *, client=None):
    """Coalesce events into one flag; never assume SSE contains canonical reading IDs."""
    owned=client is None
    client=client or httpx.AsyncClient(timeout=httpx.Timeout(30,read=45))
    delay=.5
    try:
        while True:
            try:
                async with client.stream('GET',url,headers={'X-API-Key':api_key,'Accept':'text/event-stream'}) as response:
                    response.raise_for_status()
                    changed.set()  # reconciliation is required after every connection
                    has_data=False
                    async for line in response.aiter_lines():
                        if line=='':
                            if has_data:changed.set()
                            has_data=False
                        elif line.startswith('data:'):has_data=True
                    delay=.5
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (401,403):raise
            except httpx.TransportError:
                pass
            changed.set()  # trigger a reconciliation attempt after disconnection
            await asyncio.sleep(delay)
            delay=min(delay*2,15)
    finally:
        if owned:await client.aclose()

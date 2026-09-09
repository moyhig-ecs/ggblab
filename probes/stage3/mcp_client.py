"""Minimal MCP client (streamable HTTP) for measuring a Jupyter MCP server from the execution layer.
usage: python mcp_client.py <url> list
       python mcp_client.py <url> call <tool> '<json-args>'
"""
import asyncio, json, sys
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main(url, cmd, tool=None, args=None):
    async with streamablehttp_client(url) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            if cmd == "list":
                t = await s.list_tools()
                for x in t.tools:
                    props = list((x.inputSchema or {}).get("properties", {}).keys())
                    print(f"- {x.name}({', '.join(props)}) :: {(x.description or '').strip().splitlines()[0][:120]}")
                print(f"# {len(t.tools)} tools")
            else:
                res = await s.call_tool(tool, json.loads(args or "{}"))
                for c in res.content:
                    print(getattr(c, "text", c)[:3000])


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2], *(sys.argv[3:5])))

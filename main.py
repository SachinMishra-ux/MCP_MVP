import argparse
import sys
import asyncio

# Add project root to sys.path to ensure absolute imports work
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from client.client import start_gateway
from server.server import mcp
from server.sse_bridge import main_bridge

def main():
    parser = argparse.ArgumentParser(description="Unified MCP Application (mcp_app)")
    
    # Mode selection
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--server", action="store_true", help="Run as Local MCP Server (stdio)")
    group.add_argument("--bridge", action="store_true", help="Run as SSE-to-stdio Bridge")
    
    # Bridge specific arguments
    parser.add_argument("--url", type=str, help="SSE URL (required for bridge mode)")
    parser.add_argument("--key", type=str, help="API Key (required for bridge mode)")
    parser.add_argument("--prefix", type=str, default="", help="Prefix for discovered POST URL (bridge mode)")
    
    # Gateway specific arguments
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Gateway host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8010, help="Gateway port (default: 8010)")

    args = parser.parse_args()

    if args.server:
        # ── 1. LOCAL MCP SERVER MODE ───────────────────────────────────────────
        # This mode provides 'read_file', 'list_directory', etc. via stdio.
        mcp.run()
        
    elif args.bridge:
        # ── 2. SSE BRIDGE MODE ────────────────────────────────────────────────
        # This mode translates between SSE (remote) and stdio (local).
        if not args.url or not args.key:
            print("Error: --url and --key are required for bridge mode.")
            sys.exit(1)
        
        try:
            asyncio.run(main_bridge(args.url, args.key, args.prefix))
        except KeyboardInterrupt:
            pass
            
    else:
        # ── 3. DEFAULT: GATEWAY MODE ──────────────────────────────────────────
        # This mode runs the FastAPI server that talks to all MCP servers.
        start_gateway(host=args.host, port=args.port)

if __name__ == "__main__":
    main()

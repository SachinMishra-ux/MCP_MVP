import os
import sys
import uuid
import json
import asyncio
import httpx
from mcp.server.fastmcp import FastMCP

# Define the local MCP Server (Local Filesystem)
mcp = FastMCP("local-filesystem")

@mcp.resource("system://info")
def get_system_info() -> str:
    """Provides information about the local file system MCP server."""
    return "Local Filesystem MCP Server v1.0. Connected and providing direct disk access."

@mcp.tool()
def read_file(path: str) -> str:
    """Reads the contents of a file on the local file system.
    
    Args:
        path: Absolute path to the file to read
    """
    try:
        # Resolve path relative to current WD if not absolute
        if not os.path.isabs(path):
            path = os.path.abspath(path)
            
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file {path}: {e}"

@mcp.tool()
def list_directory(path: str) -> list[str]:
    """Lists files and folders in a given directory.
    
    Args:
        path: Absolute path to the directory
    """
    try:
        if not os.path.isabs(path):
            path = os.path.abspath(path)
            
        if not os.path.exists(path):
            return [f"Error: Directory {path} does not exist"]
        return os.listdir(path)
    except Exception as e:
        return [f"Error listing directory {path}: {e}"]
        

if __name__ == "__main__":
    # Launching the MCP server via stdio
    mcp.run()

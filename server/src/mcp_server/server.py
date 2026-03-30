from mcp.server.fastmcp import FastMCP
import os

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
        if not os.path.exists(path):
            return [f"Error: Directory {path} does not exist"]
        return os.listdir(path)
    except Exception as e:
        return [f"Error listing directory {path}: {e}"]

def run_server():
    mcp.run()

if __name__ == "__main__":
    run_server()

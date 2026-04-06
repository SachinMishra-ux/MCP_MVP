import os
import sys
import uuid
import json
import asyncio
import httpx
from mcp.server.fastmcp import FastMCP

from dotenv import load_dotenv

# -------------------------
# LOAD ENV
# -------------------------
load_dotenv()

CATIA_EXE = os.getenv("CATIA_EXE")
CATVBA_BASE_DIR = os.getenv("CATVBA_BASE_DIR")

if not CATIA_EXE or not CATVBA_BASE_DIR:
    raise Exception("❌ Missing CATIA config in .env")


# -------------------------
# LOAD SCRIPT MAPPING
# -------------------------
def load_scripts():
    config_path = os.path.join(os.getcwd(), "catvba_scripts.json")

    if not os.path.exists(config_path):
        print("⚠️ No script mapping file found, using direct names")
        return {}

    with open(config_path) as f:
        return json.load(f).get("scripts", {})

SCRIPTS_MAP = load_scripts()


# Define the local MCP Server (Local Filesystem)
mcp = FastMCP("local-filesystem")


# -------------------------
# UTIL: RESOLVE SCRIPT PATH
# -------------------------
def resolve_script(script_key: str) -> str:

    # if mapping exists → use it
    if script_key in SCRIPTS_MAP:
        filename = SCRIPTS_MAP[script_key]
    else:
        # fallback → assume direct filename
        filename = script_key

    script_path = os.path.join(CATVBA_BASE_DIR, filename)

    if not os.path.exists(script_path):
        raise Exception(f"❌ Script not found: {script_path}")

    return script_path

@mcp.resource("system://info")
def get_system_info() -> str:
    """Provides information about the local file system MCP server."""
    return "Local Filesystem MCP Server v1.0. Connected and providing direct disk access."


# -------------------------
# TOOL: RUN CATVBA SCRIPT
# -------------------------
@mcp.tool()
def run_catvba(script: str, macro: str = "CAT.Main"):
    """
    Run a CATIA CATVBA macro

    Args:
        script: script key or filename
        macro: macro name inside CATVBA
    """

    script_path = resolve_script(script)

    try:
        command = [
            CATIA_EXE,
            "-batch",
            "-macro",
            f"{script_path},{macro}"
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True
        )

        return {
            "status": "success",
            "script": script,
            "macro": macro,
            "stdout": result.stdout,
            "stderr": result.stderr
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


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


@mcp.tool()
def run_structure_design_rule_checker() -> str:
    """Runs Structure Design Rule Checker CATVBA script in CATIA."""
    try:
        macro_path = r"C:\path\Structure Design Rule Checker 4.catvba"
        module_name = "Module1"
        macro_name = "Main"

        import win32com.client
        import time

        try:
            catia = win32com.client.GetActiveObject("CATIA.Application")
        except:
            catia = win32com.client.Dispatch("CATIA.Application")
            catia.Visible = True

        time.sleep(2)

        catia.SystemService.ExecuteScript(
            macro_path,
            1,
            module_name,
            macro_name,
            []
        )

        return "Structure Design Rule Checker executed successfully."

    except Exception as e:
        return f"Execution failed: {str(e)}"
        

if __name__ == "__main__":
    # Launching the MCP server via stdio
    mcp.run()

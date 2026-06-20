import os
import xmlrpc.client
import base64
from fastmcp import FastMCP

# Initialize FastMCP Server
mcp = FastMCP("FreeCAD Server")

# FreeCAD Bridge URL (default local port)
FREECAD_RPC_URL = "http://127.0.0.1:9875"

def get_rpc_client():
    return xmlrpc.client.ServerProxy(FREECAD_RPC_URL, allow_none=True)

@mcp.tool()
def execute_freecad_python(code: str) -> str:
    """
    Executes raw Python code inside a running FreeCAD instance.
    You can use the 'App' (FreeCAD) and 'Gui' (FreeCADGui) modules.
    For example: 
    - App.newDocument("DocName")
    - import Part; box = Part.makeBox(10, 10, 10); Part.show(box)
    - App.ActiveDocument.recompute()
    """
    try:
        client = get_rpc_client()
        result = client.execute(code)
        
        output = []
        if result.get("success"):
            output.append("### Execution Success")
            if result.get("stdout"):
                output.append(f"**Stdout:**\n```\n{result['stdout']}\n```")
        else:
            output.append("### Execution Failed")
            if result.get("stderr"):
                output.append(f"**Error Details:**\n```\n{result['stderr']}\n```")
                
        return "\n\n".join(output)
    except ConnectionRefusedError:
        return "Error: Could not connect to FreeCAD. Please ensure FreeCAD is open and the bridge server is running."
    except Exception as e:
        return f"Error communicating with FreeCAD: {str(e)}"

@mcp.tool()
def get_document_objects() -> str:
    """
    Retrieves a list of all objects, their types, and labels in the active FreeCAD document.
    Use this to understand the current scene hierarchy.
    """
    try:
        client = get_rpc_client()
        result = client.get_structure()
        
        if not result.get("success"):
            return "Error retrieving document hierarchy."
            
        objects = result.get("objects", [])
        if not objects:
            return "No active document or document is empty."
            
        lines = ["### Active Document Structure:"]
        for idx, obj in enumerate(objects):
            lines.append(f"{idx+1}. **{obj['name']}** (Label: '{obj['label']}', Type: `{obj['type']}`)")
        return "\n".join(lines)
    except ConnectionRefusedError:
        return "Error: Could not connect to FreeCAD."
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def capture_viewport_image() -> str:
    """
    Takes a screenshot of the current active 3D view in FreeCAD and returns it.
    Use this tool to visually verify your modeling operations.
    """
    import tempfile
    try:
        # Create a temp file path for the screenshot
        tmp_dir = tempfile.gettempdir()
        filepath = os.path.join(tmp_dir, "freecad_screenshot.png")
        
        client = get_rpc_client()
        result = client.screenshot(filepath)
        
        if not result.get("success"):
            return f"Error taking screenshot: {result.get('error', 'Unknown error')}"
            
        # Read file and encode in base64
        with open(filepath, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
            
        # Return base64 image representation so AI client can show/analyze it
        return f"image/png;base64,{encoded_string}"
    except ConnectionRefusedError:
        return "Error: Could not connect to FreeCAD."
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == "__main__":
    mcp.run()

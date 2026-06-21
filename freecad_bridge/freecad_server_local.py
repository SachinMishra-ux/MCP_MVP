import sys
import io
import queue
import threading
import traceback
from xmlrpc.server import SimpleXMLRPCServer

from PySide6 import QtCore

# Import FreeCAD modules safely
import FreeCAD as App
try:
    import FreeCADGui as Gui
except ImportError:
    Gui = None

# Thread-safe queue for main thread execution
task_queue = queue.Queue()

# Default local port
PORT = 9875

def safe_execute(code_str):
    """Executes Python code on the main thread and captures outputs."""
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = buffer_out = io.StringIO()
    sys.stderr = buffer_err = io.StringIO()
    
    success = False
    error_msg = ""
    
    try:
        # Provide FreeCAD modules in global context
        globals_dict = {
            "FreeCAD": App,
            "App": App,
            "Gui": Gui,
        }
        if Gui:
            globals_dict["FreeCADGui"] = Gui

        # Execute code block
        exec(code_str, globals_dict)
        success = True
    except Exception as e:
        error_msg = traceback.format_exc()
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        
    return {
        "success": success,
        "stdout": buffer_out.getvalue(),
        "stderr": buffer_err.getvalue() or error_msg
    }

def take_screenshot(filepath):
    """Saves the current active view image (requires GUI)."""
    if not Gui or not Gui.activeView():
        return {"success": False, "error": "GUI or active view not available"}
    try:
        view = Gui.activeView()
        view.saveImage(filepath, 1024, 768, "Current")
        return {"success": True, "filepath": filepath}
    except Exception as e:
        return {"success": False, "error": str(e)}

class FreeCADRPCMethods:
    """Methods exposed via XML-RPC to the local MCP server."""
    def execute(self, code_str):
        response_event = threading.Event()
        response_data = {}
        
        # Enqueue the task for execution on the main GUI thread
        task_queue.put({
            "action": "execute",
            "code": code_str,
            "event": response_event,
            "response": response_data
        })
        
        # Block until the main thread processes it (timeout after 30s)
        completed = response_event.wait(timeout=30.0)
        if not completed:
            return {"success": False, "stdout": "", "stderr": "Execution timed out waiting for FreeCAD main thread."}
        return response_data

    def screenshot(self, filepath):
        response_event = threading.Event()
        response_data = {}
        
        task_queue.put({
            "action": "screenshot",
            "filepath": filepath,
            "event": response_event,
            "response": response_data
        })
        
        completed = response_event.wait(timeout=10.0)
        if not completed:
            return {"success": False, "error": "Screenshot operation timed out."}
        return response_data

    def get_structure(self):
        # Gather active document shapes & labels
        if not App.ActiveDocument:
            return {"success": True, "objects": []}
            
        objects_info = []
        for obj in App.ActiveDocument.Objects:
            objects_info.append({
                "name": obj.Name,
                "label": obj.Label,
                "type": obj.TypeId,
            })
        return {"success": True, "objects": objects_info}

def poll_queue():
    """Timer callback that executes queued items in the main Qt thread."""
    while not task_queue.empty():
        try:
            task = task_queue.get_nowait()
            action = task["action"]
            event = task["event"]
            response = task["response"]
            
            if action == "execute":
                res = safe_execute(task["code"])
                response.update(res)
            elif action == "screenshot":
                res = take_screenshot(task["filepath"])
                response.update(res)
                
            event.set()
        except queue.Empty:
            break
        except Exception as e:
            print(f"Error polling queue: {e}")

# Global timer reference to prevent garbage collection
timer = None

def start_rpc_server(port=PORT):
    global timer
    # Setup XML-RPC server
    server = SimpleXMLRPCServer(("127.0.0.1", port), logRequests=False, allow_none=True)
    server.register_instance(FreeCADRPCMethods())
    
    # Run server in a daemon background thread
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    
    # Setup QTimer to process tasks in FreeCAD's GUI loop
    timer = QtCore.QTimer()
    timer.timeout.connect(poll_queue)
    timer.start(50) # check queue every 50 milliseconds
    
    print(f"FreeCAD Remote RPC server successfully started on port {port}")

# Automatically start if loaded inside FreeCAD console
if __name__ == "__main__":
    start_rpc_server()

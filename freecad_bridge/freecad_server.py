import sys
import io
import json
import os
import queue
import threading
import traceback
from xmlrpc.server import SimpleXMLRPCServer

from PySide6 import QtCore
try:
    from PySide6.QtWebSockets import QWebSocket
    from PySide6.QtNetwork import QNetworkRequest
except ImportError:
    from PySide2.QtWebSockets import QWebSocket
    from PySide2.QtNetwork import QNetworkRequest

# Import FreeCAD modules safely
import FreeCAD as App
try:
    import FreeCADGui as Gui
except ImportError:
    Gui = None

# =====================================================================
# CONFIGURATION
# =====================================================================
# 1. Local Setup Port (XML-RPC)
LOCAL_RPC_PORT = 9875

# 2. Remote Cloud Setup URL (WebSocket)
# Set this to your deployed Render/Cloud URL to enable cloud-hosted mode.
# Keep it as empty string "" if you only want to use it locally.
WS_URL = "wss://freecadmcpserver.onrender.com/ws/agent" 

# =====================================================================
# CORE IMPLEMENTATION
# =====================================================================

# Thread-safe queue for main thread execution
task_queue = queue.Queue()

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

def get_document_objects():
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

# ---------------------------------------------------------------------
# MODE A: LOCAL XML-RPC SERVER (For Local Std進 execution)
# ---------------------------------------------------------------------

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
        return get_document_objects()

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

# ---------------------------------------------------------------------
# MODE B: REMOTE WEBSOCKET AGENT (For Cloud/Render execution)
# ---------------------------------------------------------------------

class FreeCADWebSocketAgent(QtCore.QObject):
    def __init__(self, url):
        super().__init__()
        self.url = url
        self.client = QWebSocket()
        
        # Connect signals to slots
        self.client.connected.connect(self.on_connected)
        self.client.textMessageReceived.connect(self.on_message_received)
        self.client.disconnected.connect(self.on_disconnected)
        
    def start(self):
        print(f"Connecting to remote Cloud MCP server at: {self.url}...")
        request = QNetworkRequest(QtCore.QUrl(self.url))
        
        # Support authentication tokens for platforms like fastmcp.app
        token = os.environ.get("FASTMCP_API_KEY")
        if token:
            request.setRawHeader(b"Authorization", f"Bearer {token}".encode("utf-8"))
            print("🔑 Authorization token loaded from FASTMCP_API_KEY env.")
            
        self.client.open(request)
        
    def on_connected(self):
        print("🎉 Connected! FreeCAD is now linked to Cloud MCP.")
        
    def on_disconnected(self):
        print("⚠️ WebSocket disconnected. Reconnecting in 5 seconds...")
        QtCore.QTimer.singleShot(5000, self.start)
        
    def on_message_received(self, message_str):
        try:
            task = json.loads(message_str)
            action = task.get("action")
            request_id = task.get("request_id")
            
            if action == "execute":
                code = task.get("code")
                print("Executing incoming CAD command...")
                result = safe_execute(code)
                result["request_id"] = request_id
                self.client.sendTextMessage(json.dumps(result))
                
            elif action == "get_structure":
                print("Fetching active document structure...")
                result = get_document_objects()
                result["request_id"] = request_id
                self.client.sendTextMessage(json.dumps(result))
                
        except Exception as e:
            print(f"Error handling cloud message: {e}")

# Global references to prevent garbage collection
timer = None
agent_instance = None

def start_services():
    global timer, agent_instance
    
    # 1. Start Local XML-RPC Server (for Local Mode)
    print(f"Starting local XML-RPC server on port {LOCAL_RPC_PORT}...")
    server = SimpleXMLRPCServer(("127.0.0.1", LOCAL_RPC_PORT), logRequests=False, allow_none=True)
    server.register_instance(FreeCADRPCMethods())
    
    # Run XML-RPC in a background daemon thread
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    
    # Setup QTimer to process tasks in FreeCAD's GUI loop
    timer = QtCore.QTimer()
    timer.timeout.connect(poll_queue)
    timer.start(50) # check queue every 50ms
    print(f"✅ Local XML-RPC server successfully started on port {LOCAL_RPC_PORT}")
    
    # 2. Start Remote WebSocket Agent (if WS_URL is provided)
    if WS_URL:
        print("Remote cloud mode enabled.")
        agent_instance = FreeCADWebSocketAgent(WS_URL)
        agent_instance.start()
    else:
        print("ℹ️ Remote cloud mode disabled (WS_URL is empty). Running in Local Mode only.")

if __name__ == "__main__":
    start_services()

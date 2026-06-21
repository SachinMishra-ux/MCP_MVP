import sys
import io
import json
import os
import traceback

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

# Configure your remote Render WebSocket server URL
# By default, points to your live Render deployment
WS_URL = "wss://freecadmcpserver.onrender.com/ws/agent"

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

# Global instance reference to prevent Python's garbage collector from destroying it
agent_instance = None

def start_agent():
    global agent_instance
    agent_instance = FreeCADWebSocketAgent(WS_URL)
    agent_instance.start()

if __name__ == "__main__":
    start_agent()

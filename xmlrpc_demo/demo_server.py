import os
import platform
import time
from xmlrpc.server import SimpleXMLRPCServer

def get_system_status():
    """Returns basic system diagnostics without needing external libraries."""
    system_info = {
        "os": platform.system(),
        "release": platform.release(),
        "architecture": platform.machine(),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    
    # Get CPU load averages (supported on macOS and Linux)
    try:
        system_info["cpu_load_1m"] = os.getloadavg()[0]
    except (AttributeError, OSError):
        system_info["cpu_load_1m"] = "N/A (Windows)"
        
    return system_info

def compute_factorial(n):
    """Offloads a math calculation to the server."""
    print(f"Server executing: compute_factorial({n})")
    if n < 0:
        return 0
    result = 1
    for i in range(1, n + 1):
        result *= i
    return result

# Start the server on port 9800 (localhost)
server = SimpleXMLRPCServer(("127.0.0.1", 9800), allow_none=True)
server.register_function(get_system_status, "get_system_status")
server.register_function(compute_factorial, "compute_factorial")

print("🚀 XML-RPC Demo Server is running on http://127.0.0.1:9800")
print("Press Ctrl+C to stop the server.")

try:
    server.serve_forever()
except KeyboardInterrupt:
    print("\nStopping server...")

import xmlrpc.client

# Connect to the remote server running on port 9800
server = xmlrpc.client.ServerProxy("http://127.0.0.1:9800", allow_none=True)

try:
    print("📞 Requesting system status from remote server...")
    status = server.get_system_status()
    print("\n--- Remote System Diagnostics ---")
    print(f"Operating System: {status['os']} {status['release']}")
    print(f"Architecture:     {status['architecture']}")
    print(f"Server Local Time:{status['time']}")
    print(f"CPU Load (1m):    {status['cpu_load_1m']}")
    print("---------------------------------\n")
    
    print("📞 Requesting remote math computation (Factorial of 10)...")
    factorial_result = server.compute_factorial(10)
    print(f"Result returned from server: 10! = {factorial_result}\n")
    
    print("🎉 All remote calls succeeded!")
except ConnectionRefusedError:
    print("❌ Error: Could not connect to the server.")
    print("Make sure you run 'python3 demo_server.py' in a separate terminal first.")
except Exception as e:
    print(f"❌ An error occurred: {e}")

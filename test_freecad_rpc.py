import xmlrpc.client

try:
    # Connect to the XML-RPC server running inside FreeCAD
    client = xmlrpc.client.ServerProxy("http://127.0.0.1:9875", allow_none=True)
    
    print("1. Testing execution command...")
    # This code will run inside FreeCAD's main thread
    result = client.execute("import FreeCAD; print('Hello inside FreeCAD!')")
    print("   Result:", result)
    
    print("2. Testing document structure lookup...")
    struct = client.get_structure()
    print("   Structure:", struct)
    
    print("\n🎉 Connection test successful! The FreeCAD XML-RPC bridge is working perfectly.")
except Exception as e:
    print("\n❌ Error connecting to FreeCAD bridge server:")
    print(e)
    print("Make sure FreeCAD is running and you executed freecad_server.py in its Python console.")

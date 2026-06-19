# API Paradigms Compared: XML-RPC vs. JSON-RPC 2.0 vs. REST

This document provides a technical and conceptual comparison of three major API paradigms: **XML-RPC**, **JSON-RPC 2.0**, and **REST**. 

---

## 1. Quick Comparison Matrix

| Specification | XML-RPC | JSON-RPC 2.0 | REST (FastAPI / HTTP) |
| :--- | :--- | :--- | :--- |
| **Philosophy** | **Action-Centric** (Verbs / Functions) | **Action-Centric** (Verbs / Functions) | **Resource-Centric** (Nouns / States) |
| **Payload Format** | XML | JSON | JSON (typically), XML, or Plain Text |
| **Transport Layer** | HTTP POST | Transport Agnostic (stdio, WebSockets, TCP, HTTP) | HTTP Only (GET, POST, PUT, DELETE, etc.) |
| **Payload Weight** | Heavy (verbose XML tags) | Very Light | Light |
| **Core Strengths** | Built into standard Python library | Supports Batching and Fire-and-forget Notifications | Self-documenting, caching support, native browser support |
| **Weaknesses** | Slow parsing, outdated | No native browser URL caching | Requires endpoint design, high boilerplate |

---

## 2. Deep Dive: Code on the Wire

How does the same operation—**adding two numbers (`5` and `10`)**—look as it travels across the network in each paradigm?

### A. XML-RPC
Uses XML structures to declare the function name and argument values.
```xml
<!-- Request -->
<methodCall>
  <methodName>add</methodName>
  <params>
    <param><value><int>5</int></value></param>
    <param><value><int>10</int></value></param>
  </params>
</methodCall>

<!-- Response -->
<methodResponse>
  <params>
    <param><value><int>15</int></value></param>
  </params>
</methodResponse>
```

### B. JSON-RPC 2.0
Uses a lightweight JSON object containing the function name, arguments, and a transaction ID.
```json
// Request
{
  "jsonrpc": "2.0",
  "method": "add",
  "params": [5, 10],
  "id": 42
}

// Response
{
  "jsonrpc": "2.0",
  "result": 15,
  "id": 42
}
```

### C. REST API
Uses a specific HTTP method (`POST`) and target URL route (`/calculator/sum`), transmitting inputs in a JSON body.
```http
POST /calculator/sum HTTP/1.1
Content-Type: application/json

{
  "num1": 5,
  "num2": 10
}

HTTP/1.1 200 OK
Content-Type: application/json

{
  "result": 15
}
```

---

## 3. When to Use Which & Real-World Use Cases

### 🌐 REST (FastAPI / Express / Spring Boot)
**Best for:** General web applications, public APIs, mobile app backends, and CRUD (Create, Read, Update, Delete) systems.
* **Why:** Web browsers naturally speak HTTP and JSON. REST allows web caching (e.g., caching a `GET /user/profile` request) and standardized status codes (`200 OK`, `404 Not Found`, `500 Server Error`).
* **Use Case:** Building an online e-commerce shop where you need clear resources like `/products`, `/orders`, and `/users`.

### ⚡ JSON-RPC 2.0
**Best for:** Real-time bi-directional systems, stdin/stdout processes, WebSockets, and developer tooling.
* **Why:** It supports **Notifications** (sending messages without waiting for a reply) and **Batching** (grouping 50 database lookups into a single network packet). It is also transport-agnostic, meaning it can run over a command line pipe (stdio) instead of full HTTP web servers.
* **Use Cases:**
  * **LSP (Language Server Protocol):** Used by VS Code to query code auto-completes and syntax highlights in real-time as you type.
  * **MCP (Model Context Protocol):** Used by LLM clients (like Claude Desktop) to execute local commands and fetch files.

### 🔌 XML-RPC
**Best for:** Simple script execution bridges, legacy systems, and sandboxed embedded runtimes.
* **Why:** Zero-configuration setup. The Python standard library includes `xmlrpc.server` and `xmlrpc.client` by default. You can spin up a server in 5 lines of code without running `pip install` or installing external dependencies.
* **Use Case:** Interfacing with embedded interpreters inside large C++ desktop packages (like Blender, FreeCAD, or Maya) where installing third-party frameworks like FastAPI is highly complex or restricted.

---

## 4. Case Study: The FreeCAD MCP Server Pipeline

In our project, we implemented a **two-link hybrid pipeline** that uses both **JSON-RPC** and **XML-RPC** to execute actions:

```text
  [ Claude Desktop ]
          │
          │  Link 1: JSON-RPC (2.0)
          │  - Over stdin/stdout pipes (no HTTP overhead)
          │  - Required by the MCP standard
          ▼
  [ External MCP Server (Terminal) ]
          │
          │  Link 2: XML-RPC
          │  - Over Local HTTP (http://127.0.0.1:9800)
          │  - Built-in to Python standard library
          ▼
  [ FreeCAD Application Process ]
```

### The Division of Labor:
1. **Claude to MCP Server (JSON-RPC 2.0):** Claude Desktop talks to our terminal server using JSON-RPC over OS pipes (`stdin`/`stdout`). This is fast, has zero network overhead, and matches the strict MCP specification.
2. **MCP Server to FreeCAD (XML-RPC):** The terminal server forwards the generated CAD script to FreeCAD over an XML-RPC connection. We used XML-RPC here because FreeCAD's internal Python engine already contains the `xmlrpc.server` library by default. We didn't have to break FreeCAD's custom interpreter by trying to force-install heavy web packages like FastAPI.

---


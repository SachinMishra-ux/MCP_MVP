# Unified MCP + FastAPI Architecture Plan

This plan aims to consolidate the current MCP Client and Server into a single, production-ready executable that exposes a FastAPI interface for external chatbots.

## Architecture Overview

The proposed flow is as follows:
1.  **External Chatbot**: Hits a REST endpoint on the FastAPI server.
2.  **FastAPI**: Forwards the query to a persistent **MCP Client** instance.
3.  **MCP Client**: Interacts with the LLM and calls tools from the **MCP Server**.
4.  **MCP Server**: Executes the local tools (e.g., filesystem access).
5.  **Response**: Results flow back through the client and FastAPI to the chatbot.

## User Review Required

> [!IMPORTANT]
> To achieve a **single-EXE** deployment, the executable will serve dual purposes. When launched, it will start the FastAPI server. The FastAPI server will then spawn *itself* as a child process with a special flag (e.g., `--mcp-server`) to run the MCP Server logic.

> [!NOTE]
> This approach keeps the code modular but simplifies distribution to a single file.

## Proposed Changes

### Core Logic

#### [NEW] [main.py](file:///Users/sachinmishra/Desktop/MCP_MVP/main.py)
A unified entry point that handles switching between API mode and MCP Server mode.
- **API Mode**: Starts `uvicorn` and initializes the `LLMMCPClient`.
- **MCP Server Mode**: Starts the `FastMCP` server.

#### [MODIFY] [client.py](file:///Users/sachinmishra/Desktop/MCP_MVP/client/src/mcp_client/client.py)
Refactor `LLMMCPClient` to replace the interactive `input()` loop with an async `chat(message)` method that can be called by FastAPI.

### Build System

#### [MODIFY] [build.py](file:///Users/sachinmishra/Desktop/MCP_MVP/build.py)
Update the build script to:
1.  Target `main.py` instead of separate client/server files.
2.  Produce a single `mcp_app.exe`.
3.  Update the default `config.json` to use `./mcp_app.exe --mcp-server` as the command for the local server.

## Open Questions

1.  **Authentication**: Do you need basic API key authentication for the FastAPI endpoint, or will it be in a secured internal network?
2.  **Chatbot Type**: Which chatbot (e.g., Slack, Custom Web UI) are you planning to connect first? This might influence the structure of the JSON response from FastAPI.

## Verification Plan

### Automated Tests
- Run `python main.py --mcp-server` to verify the server starts.
- Run `python main.py` to verify the FastAPI server starts.
- Use `curl` to send a test query to the `/chat` endpoint.

### Manual Verification
- Build the project using `python build.py`.
- Run the resulting `release/mcp_app.exe`.
- Verify that the FastAPI server correctly communicates with the internal MCP server via the single executable.

import subprocess
import shutil
import os
import sys
import json


def build_project(entry_file, output_name, dest_dir):
    print(f"Building {output_name}...")

    pyinstaller_cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", output_name,
        "--onefile",

        # Paths
        "--paths", "server/src",

        # ✅ Hidden imports
        "--hidden-import", "tiktoken_ext.openai_public",
        "--hidden-import", "tiktoken_ext.core_bpe",
        "--hidden-import", "langchain_litellm",
        "--hidden-import", "langchain_core",
        "--hidden-import", "langchain_community",
        "--hidden-import", "langgraph",

        # ✅ Collect ALL data files for these packages
        "--collect-all", "litellm",
        "--collect-all", "tiktoken",
        "--collect-all", "fastapi",
        "--collect-all", "uvicorn",
        "--collect-all", "langchain_litellm",
        "--collect-all", "langchain",
        "--collect-all", "langchain_core",
        "--collect-all", "langchain_community",
        "--collect-all", "langgraph",
        "--collect-all", "mcp",

        # ✅ Copy metadata
        "--copy-metadata", "tiktoken",
        "--copy-metadata", "litellm",
        "--copy-metadata", "langchain_litellm",
        "--copy-metadata", "langchain",
        "--copy-metadata", "langchain_core",
        "--copy-metadata", "langgraph",

        "--distpath", dest_dir,
        entry_file
    ]

    subprocess.run(pyinstaller_cmd, check=True)


def main():
    release_dir = "release"

    # Clean old builds
    if os.path.exists(release_dir):
        shutil.rmtree(release_dir)
    os.makedirs(release_dir)

    print("=== Building MCP Gateway ===")
    build_project("main.py", "mcp_app", release_dir)

    # Cleanup PyInstaller artifacts
    shutil.rmtree("build", ignore_errors=True)
    if os.path.exists("mcp_app.spec"):
        os.remove("mcp_app.spec")
    shutil.rmtree("dist", ignore_errors=True)

    print("\n=== Generating Config ===")

    binary_name = "mcp_app.exe" if sys.platform == "win32" else "./mcp_app"

    config = {
        "mcpServers": {
            "local-filesystem": {
                "command": binary_name,
                "args": ["--mcp-server"]
            },
            "web-fetcher": {
                "command": "uvx",
                "args": ["mcp-server-fetch", "--ignore-robots-txt"]
            },
            "lf-customer_demo": {
                "url": "https://chromosome.tatatechnologies.com/agentbuilder-api/api/v1/mcp/project/e8b22014-fb98-4fbd-aac5-d3ad8a23c7b9/sse",
                "api_key": "YOUR_API_KEY"
            }
        }
    }

    with open(os.path.join(release_dir, "config.json"), "w") as f:
        json.dump(config, f, indent=2)

    with open(os.path.join(release_dir, ".env.example"), "w") as f:
        f.write(
            "# LLM config example\n"
            "# LLM_MODEL=openai/gpt-4o\n"
            "# OPENAI_API_KEY=your_key_here\n"
        )

    print("\nBuild complete -> release/")


if __name__ == "__main__":
    main()
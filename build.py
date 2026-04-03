import subprocess
import shutil
import os
import sys
import json
import importlib.metadata


def is_package_installed(name: str) -> bool:
    """Check if a package has metadata (is properly installed)."""
    try:
        importlib.metadata.distribution(name)
        return True
    except importlib.metadata.PackageNotFoundError:
        return False


def build_project(entry_file, output_name, dest_dir):
    print(f"Building {output_name} from {entry_file}...")

    # Packages that MUST have --collect-all (always present in requirements.txt)
    collect_all_packages = [
        "litellm", "tiktoken", "fastapi", "uvicorn",
        "langchain", "langchain_core", "langchain_community",
        "langgraph", "mcp", "langchain_mcp_adapters", "langchain_openai"
    ]

    # Packages for --copy-metadata (only if installed to avoid CI failures)
    copy_metadata_packages = [
        "tiktoken", "litellm", "langchain", "langchain_core", "langgraph",
        "langchain_mcp_adapters"
    ]

    pyinstaller_cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", output_name,
        "--onefile",
        "--clean",

        # Hidden imports
        "--hidden-import", "tiktoken_ext.openai_public",
        "--hidden-import", "tiktoken_ext.core_bpe",
        "--hidden-import", "langchain_core",
        "--hidden-import", "langchain_community",
        "--hidden-import", "langchain_mcp_adapters",
        "--hidden-import", "langchain_openai",
        "--hidden-import", "client.client",
        "--hidden-import", "server.server",
        "--hidden-import", "server.sse_bridge"
    ]

    # Add --collect-all for all required packages
    for pkg in collect_all_packages:
        if is_package_installed(pkg):
            pyinstaller_cmd += ["--collect-all", pkg]

    # Add --copy-metadata only for packages that have metadata
    for pkg in copy_metadata_packages:
        if is_package_installed(pkg):
            pyinstaller_cmd += ["--copy-metadata", pkg]

    pyinstaller_cmd += ["--distpath", dest_dir, entry_file]

    subprocess.run(pyinstaller_cmd, check=True)


def main():
    release_dir = "release"

    # Clean old builds
    if os.path.exists(release_dir):
        shutil.rmtree(release_dir)
    os.makedirs(release_dir)

    # Build UNIFIED MCP App
    print("\n=== Building Unified MCP App (mcp_app) ===")
    build_project("main.py", "mcp_app", release_dir)

    # Cleanup PyInstaller artifacts
    shutil.rmtree("build", ignore_errors=True)
    if os.path.exists("mcp_app.spec"):
        os.remove("mcp_app.spec")

    print("\n=== Generating Release Config ===")

    binary_name = "./mcp_app" if sys.platform != "win32" else "mcp_app.exe"

    config = {
        "mcpServers": {
            "local-filesystem": {
                "command": binary_name,
                "args": ["--server"]
            },
            "web-fetcher": {
                "command": "uvx",
                "args": ["mcp-server-fetch", "--ignore-robots-txt"]
            }
        }
    }

    with open(os.path.join(release_dir, "config.json"), "w") as f:
        json.dump(config, f, indent=2)

    with open(os.path.join(release_dir, ".env.example"), "w") as f:
        f.write(
            "# Azure OpenAI Credentials\n"
            "AZURE_OPENAI_API_KEY=your_key_here\n"
            "AZURE_OPENAI_ENDPOINT=https://your-endpoint.openai.azure.com/\n"
            "AZURE_OPENAI_API_VERSION=2024-02-01\n"
            "AZURE_DEPLOYMENT_NAME=gpt-4o\n"
        )

    print("\nBuild complete -> release/")


if __name__ == "__main__":
    main()
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
    print(f"Building {output_name}...")

    # Packages that MUST have --collect-all (always present in requirements.txt)
    collect_all_packages = [
        "litellm", "tiktoken", "fastapi", "uvicorn",
        "langchain", "langchain_core", "langchain_community",
        "langgraph", "mcp",
    ]

    # langchain_litellm: collect-all only if installed
    optional_collect = ["langchain_litellm"]

    # Packages for --copy-metadata (only if installed to avoid CI failures)
    copy_metadata_packages = [
        "tiktoken", "litellm", "langchain", "langchain_core", "langgraph",
        "langchain_litellm",
    ]

    pyinstaller_cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", output_name,
        "--onefile",
        "--paths", "server/src",

        # Hidden imports
        "--hidden-import", "tiktoken_ext.openai_public",
        "--hidden-import", "tiktoken_ext.core_bpe",
        "--hidden-import", "langchain_core",
        "--hidden-import", "langchain_community",
        "--hidden-import", "langgraph",
    ]

    # Add --collect-all for all required packages
    for pkg in collect_all_packages:
        pyinstaller_cmd += ["--collect-all", pkg]

    # Add optional packages only if installed
    for pkg in optional_collect:
        if is_package_installed(pkg):
            print(f"  [+] Bundling optional: {pkg}")
            pyinstaller_cmd += ["--collect-all", pkg]
            pyinstaller_cmd += ["--hidden-import", pkg]
        else:
            print(f"  [!] Skipping optional (not installed): {pkg}")

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
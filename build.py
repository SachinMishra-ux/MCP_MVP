import subprocess
import shutil
import os
import sys

def build_project(entry_file, output_name, dest_dir):
    print(f"Building {output_name}...")
    
    # Base pyinstaller command using the current python executable
    pyinstaller_cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", output_name,
        "--onefile",
        "--collect-all", "litellm",
        "--collect-all", "tiktoken",
        "--collect-all", "fastapi",
        "--collect-all", "uvicorn",
        "--copy-metadata", "tiktoken",
        "--copy-metadata", "litellm",
        "--hidden-import", "tiktoken_ext.openai_public",
        "--hidden-import", "tiktoken_ext.core_bpe",
        "--distpath", dest_dir,
        entry_file
    ]
    
    try:
        subprocess.run(pyinstaller_cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error: PyInstaller failed with exit code {e.returncode}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: Failed to run PyInstaller: {e}")
        sys.exit(1)

def main():
    release_dir = "release"
    if os.path.exists(release_dir):
        shutil.rmtree(release_dir)
    os.makedirs(release_dir)

    # Build the single unified gateway
    print("=== Building Unified MCP Gateway ===")
    build_project("main.py", "mcp_app", release_dir)

    # Clean PyInstaller artifacts
    if os.path.exists("build"):
        shutil.rmtree("build")
    if os.path.exists("mcp_app.spec"):
        os.remove("mcp_app.spec")
    if os.path.exists("dist"):
        shutil.rmtree("dist")

    print("\n=== Generating Configurations ===")
    
    # Determine binary name based on OS (use .exe for windows, but ./ prefix for config)
    binary_name = "mcp_app.exe" if sys.platform == "win32" else "./mcp_app"
    
    config_content = {
        "mcpServers": {
            "local-filesystem": {
                "command": binary_name,
                "args": ["--mcp-server"]
            },
            "web-fetcher": {
                "command": "uvx",
                "args": ["mcp-server-fetch", "--ignore-robots-txt"]
            }
        }
    }
    
    with open(os.path.join(release_dir, "config.json"), "w") as f:
        json.dump(config_content, f, indent=2)

    env_content = """# You can specify your LLM configuration here manually 
# LLM_MODEL=openai/gpt-4o
# OPENAI_API_KEY=your_key_here
"""
    with open(os.path.join(release_dir, ".env.example"), "w") as f:
        f.write(env_content)
        
    print("\n" + "="*50)
    print("Build complete! Your distribution is ready in the 'release/' folder.")
    print("Unified Binary: release/mcp_app")
    print("To distribute, simply copy the 'release/' directory.")
    print("="*50 + "\n")

if __name__ == "__main__":
    import json
    main()

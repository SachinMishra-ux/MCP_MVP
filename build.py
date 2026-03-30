import subprocess
import shutil
import os

def build_project(entry_file, output_name, dest_dir):
    print(f"Building {output_name}...")
    subprocess.run([
        "pyinstaller", 
        "--name", output_name,
        "--onefile",
        "--collect-all", "litellm",
        "--collect-all", "tiktoken",
        "--copy-metadata", "tiktoken",
        "--copy-metadata", "litellm",
        "--hidden-import", "tiktoken_ext.openai_public",
        "--hidden-import", "tiktoken_ext.core_bpe",
        "--distpath", dest_dir,
        entry_file
    ], check=True)

def main():
    if not shutil.which("pyinstaller"):
        print("Error: pyinstaller not found.")
        return

    release_dir = "release"
    if os.path.exists(release_dir):
        shutil.rmtree(release_dir)
    os.makedirs(release_dir)

    print("=== Building Client ===")
    build_project("client/src/mcp_client/client.py", "mcp_client", release_dir)

    print("=== Building Server ===")
    build_project("server/src/mcp_server/server.py", "mcp_server", release_dir)

    # Clean PyInstaller artifacts
    if os.path.exists("build"):
        shutil.rmtree("build")
    for spec in ["mcp_client.spec", "mcp_server.spec"]:
        if os.path.exists(spec):
            os.remove(spec)
    if os.path.exists("dist"):
        shutil.rmtree("dist")

    print("\n=== Generating Configurations ===")
    config_content = """{
  "mcpServers": {
    "local-filesystem": {
      "command": "./mcp_server",
      "args": []
    },
    "web-fetcher": {
      "command": "uvx",
      "args": ["mcp-server-fetch", "--ignore-robots-txt"]
    }
  }
}"""
    with open(os.path.join(release_dir, "config.json"), "w") as f:
        f.write(config_content)

    env_content = """# You can specify your LLM configuration here manually if you prefer not to use the interactive wizard
# LLM_MODEL=openai/gpt-4o
# OPENAI_API_KEY=your_key_here
"""
    with open(os.path.join(release_dir, ".env.example"), "w") as f:
        f.write(env_content)
        
    print("\n" + "="*50)
    print("Build complete! Your distribution is ready in the 'release/' folder.")
    print("To distribute, simply copy the 'release/' directory to another machine.")
    print("="*50 + "\n")

if __name__ == "__main__":
    main()

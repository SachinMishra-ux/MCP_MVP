import os
import getpass
from dotenv import load_dotenv, set_key

def setup_llm_config(env_path: str = ".env"):
    load_dotenv(env_path)
    
    model = os.environ.get("LLM_MODEL")
    if model:
        return
        
    print("\n" + "="*50)
    print("Welcome to MCP Client First-Time Setup!")
    print("No LLM configuration detected.")
    print("="*50)
    
    print("Select an LLM Provider:")
    print("1. OpenAI (e.g., openai/gpt-4o)")
    print("2. Anthropic (e.g., anthropic/claude-3-5-sonnet-20241022)")
    print("3. Groq (e.g., groq/llama-3.3-70b-versatile)")
    print("4. Azure Openai (e.g., azure/gpt-4o)")
    print("5. Other (litellm compatible format)")
    
    choice = input("Enter choice (1-5): ").strip()
    
    extra_env = {}

    if choice == "1":
        model_name = input("Enter Model [openai/gpt-4o]: ").strip() or "openai/gpt-4o"
        # Ensure openai prefix
        if not model_name.startswith("openai/"):
            model_name = "openai/" + model_name
        api_key_name = "OPENAI_API_KEY"
    elif choice == "2":
        model_name = input("Enter Model [anthropic/claude-3-5-sonnet-20241022]: ").strip() or "anthropic/claude-3-5-sonnet-20241022"
        if not model_name.startswith("anthropic/"):
            model_name = "anthropic/" + model_name
        api_key_name = "ANTHROPIC_API_KEY"
    elif choice == "3":
        model_name = input("Enter Model [groq/llama-3.3-70b-versatile]: ").strip() or "groq/llama-3.3-70b-versatile"
        if not model_name.startswith("groq/"):
            model_name = "groq/" + model_name
        api_key_name = "GROQ_API_KEY"
    elif choice == "4":
        model_name = input("Enter Model [azure/gpt-4o-mini]: ").strip() or "azure/gpt-4o-mini"
        if not model_name.startswith("azure/"):
            model_name = "azure/" + model_name
        api_key_name = "AZURE_API_KEY"
        endpoint = input("Enter Azure OpenAI Endpoint (e.g., https://your-resource.openai.azure.com/): ").strip()
        api_version = input("Enter Azure API Version [2024-02-15-preview]: ").strip() or "2024-02-15-preview"
        extra_env["AZURE_OPENAI_ENDPOINT"] = endpoint
        extra_env["AZURE_API_VERSION"] = api_version
    else:
        model_name = input("Enter Model ID (e.g., provider/model_name): ").strip()
        api_key_name = input("Enter Env Var Name for API Key (e.g., GEMINI_API_KEY): ").strip()
        
    api_key_value = getpass.getpass(f"Enter your {api_key_name}: ")
    
    if not os.path.exists(env_path):
        open(env_path, "w").close()
    
    set_key(env_path, "LLM_MODEL", model_name)
    set_key(env_path, api_key_name, api_key_value)
    
    os.environ["LLM_MODEL"] = model_name
    os.environ[api_key_name] = api_key_value
    
    for key, value in extra_env.items():
        if value:
            set_key(env_path, key, value)
            os.environ[key] = value
    
    print("\nConfiguration saved securely to .env file!")
    print("="*50 + "\n")

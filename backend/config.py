from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    # LLM — swap provider/model here (see CLAUDE.md "Model Swapping")
    anthropic_api_key: str = ""
    llm_provider: str = "anthropic"           # "anthropic" | "openai" | "lmstudio" | "local"
    model: str = "claude-3-5-sonnet-20241022"
    lmstudio_base_url: str = "http://localhost:1234/v1"
    openai_api_key: str = ""                  # frontier option (Advisor tab)
    openai_model: str = "o3"                  # default when provider=openai
    custom_base_url: str = ""                 # any OpenAI-compatible server
    custom_api_key: str = ""                  # (Groq, OpenRouter, Gemini, ...)
    custom_model: str = ""

    # Database
    database_url: str = "sqlite:///./data/companion.db"

    # EQL logs + maps (custom dir searched first — e.g. the Brewall pack)
    eql_game_dir: str = r"G:\Daybreak Game Company\Installed Games\EverQuest Legends"
    eql_log_dir: str = r"G:\Daybreak Game Company\Installed Games\EverQuest Legends\Logs"
    eql_maps_dir: str = r"G:\Daybreak Game Company\Installed Games\EverQuest Legends\maps"
    eql_maps_custom_dir: str = r"G:\Daybreak Game Company\Installed Games\EverQuest Legends\maps\Dark Brewall"
    eql_log_path: str | None = None           # full path override (wins over dir scan)
    eql_character_name: str | None = None     # prefer this character's log file

    # MCP (optional -- the advisor degrades to ungrounded counsel when absent)
    mcp_enabled: bool = True
    mcp_server_dir: str = r"G:\projects\everquest-legends-mcp"
    mcp_node_path: str = "node"

    # App
    environment: str = "development"
    debug: bool = False
    frontend_origin: str = "http://localhost:3000"


settings = Settings()

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

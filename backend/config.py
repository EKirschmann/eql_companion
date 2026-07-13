from pathlib import Path

from pydantic import model_validator
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

    # EQL install — set EQL_GAME_DIR in .env; Logs/ and maps/ derive from it
    # unless individually overridden. Default = the launcher's standard path.
    eql_game_dir: str = (r"C:\Users\Public\Daybreak Game Company"
                         r"\Installed Games\EverQuest Legends")
    eql_log_dir: str = ""                     # default: <game dir>\Logs
    eql_maps_dir: str = ""                    # default: <game dir>\maps
    eql_maps_custom_dir: str = ""             # default: <maps>\Dark Brewall (Brewall pack; optional)
    eql_log_path: str | None = None           # full path override (wins over dir scan)
    eql_character_name: str | None = None     # prefer this character's log file

    @model_validator(mode="after")
    def _derive_game_paths(self):
        game = Path(self.eql_game_dir)
        if not self.eql_log_dir:
            self.eql_log_dir = str(game / "Logs")
        if not self.eql_maps_dir:
            self.eql_maps_dir = str(game / "maps")
        if not self.eql_maps_custom_dir:
            self.eql_maps_custom_dir = str(Path(self.eql_maps_dir) / "Dark Brewall")
        return self

    # MCP (optional -- the advisor degrades to ungrounded counsel when absent)
    mcp_enabled: bool = True
    mcp_server_dir: str = ""                  # clone path; empty = wiki over HTTP
    mcp_node_path: str = "node"

    # App
    environment: str = "development"
    debug: bool = False
    frontend_origin: str = "http://localhost:3000"


settings = Settings()

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

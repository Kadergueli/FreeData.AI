import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass(frozen=True)
class Settings:
    csv_path: str = os.getenv("FREEDATA_CSV_PATH", "freedatatd-markets-full.csv").strip()
    supabase_url: str = os.getenv("SUPABASE_URL", "").strip()
    supabase_key: str = os.getenv("SUPABASE_KEY", os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
    supabase_db_url: str = os.getenv("SUPABASE_DB_URL", "").strip()
    allowed_origins: str = os.getenv("ALLOWED_ORIGINS", "*").strip()
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "").strip()
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.2").strip()

    @property
    def data_backend(self) -> str:
        if self.supabase_url and self.supabase_key:
            return "supabase_rest"
        if self.supabase_db_url:
            return "supabase"
        return "csv"

    @property
    def cors_origins_list(self) -> list[str]:
        if self.allowed_origins == "*":
            return ["*"]
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


settings = Settings()
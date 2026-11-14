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
    # Clé de LECTURE (publique / anon) utilisée par l'API.
    supabase_key: str = os.getenv("SUPABASE_KEY", "").strip()
    # Clé d'ÉCRITURE (service_role) : uniquement pour scripts/update_predictions.py.
    supabase_service_key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    supabase_db_url: str = os.getenv("SUPABASE_DB_URL", "").strip()
    allowed_origins: str = os.getenv("ALLOWED_ORIGINS", "*").strip()
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "").strip()
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.2").strip()
    llm_api_key: str = os.getenv("LLM_API_KEY", "").strip()
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1").strip()
    llm_chat_model: str = os.getenv("LLM_CHAT_MODEL", "llama-3.3-70b-versatile").strip()
    embed_api_key: str = os.getenv("EMBED_API_KEY", "").strip()
    embed_base_url: str = os.getenv("EMBED_BASE_URL", "https://api.jina.ai/v1/embeddings").strip()
    embed_model: str = os.getenv("EMBED_MODEL", "jina-embeddings-v3").strip()
    # Jeton exigé (en-tête X-Admin-Token) par POST /api/v1/refresh. Vide = endpoint désactivé.
    admin_token: str = os.getenv("ADMIN_TOKEN", "").strip()
    # Une série dont le dernier relevé a plus de N mois de retard sur le relevé le plus
    # récent n'est plus servie par l'API (0 = pas de filtre).
    # Écarte les relevés marqués OUTLIER (is_flagged_outlier) AVANT le modèle : un prix aberrant
    # (jusqu'à 12 482 XAF/kg pour une moyenne de ~900) fausse prévisions et volatilité. 0 = désactivé.
    exclude_flagged_outliers: bool = os.getenv("EXCLUDE_FLAGGED_OUTLIERS", "1").strip().lower() not in ("0", "false", "no")
    # Le LLM (tier premium) choisit l'analyse à lancer parmi une liste fermée ; 0 = règles seules.
    llm_routing: bool = os.getenv("LLM_ROUTING", "1").strip().lower() not in ("0", "false", "no")
    max_staleness_months: int = int(os.getenv("MAX_STALENESS_MONTHS", "3"))

    @property
    def read_key(self) -> str:
        """Clé utilisée pour lire. Repli sur service_role par compatibilité (journalisé au démarrage)."""
        return self.supabase_key or self.supabase_service_key

    @property
    def write_key(self) -> str:
        """Clé utilisée pour écrire les tables Gold (script mensuel)."""
        return self.supabase_service_key or self.supabase_key

    @property
    def read_key_is_privileged(self) -> bool:
        return not self.supabase_key and bool(self.supabase_service_key)

    @property
    def data_backend(self) -> str:
        if self.supabase_url and self.read_key:
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

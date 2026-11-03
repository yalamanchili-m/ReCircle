from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_name: str = "ReCircle API"
    api_prefix: str = "/api"

    database_url: str = "postgresql+psycopg://recircle_app:local_dev_password@localhost:5432/recircle"

    jwt_secret: str = "replace-with-a-long-random-local-secret"
    access_token_minutes: int = 60

    frontend_origin: str = "http://localhost:3000"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    ollama_timeout_seconds: int = 20

    # Material Intelligence: Sentence-BERT is strictly opt-in. When disabled
    # (or the package/model is unavailable) the engine falls back to the
    # deterministic TF-IDF baseline and reports the method used.
    sbert_enabled: bool = False
    sbert_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"

    # Neo4j is an optional read-optimized projection of PostgreSQL. With it
    # disabled or unreachable, every PostgreSQL-only workflow keeps working.
    neo4j_enabled: bool = False
    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # Regulation-news aggregation fetches only keyless public feeds. LLM story
    # summaries are strictly opt-in; without them items carry labeled
    # source-excerpt summaries and everything works offline.
    regulation_llm_summaries_enabled: bool = False
    regulation_fetch_timeout_seconds: int = 15
    regulation_max_items_per_source: int = 25

    # External data ingestion (Phase 15) is staged local-file import only:
    # admins execute file imports in explicit API calls. Size caps keep
    # imported content bounded; CSV text is parsed, never executed.
    data_ingestion_max_file_mb: int = 50

    # ERP integration boundary (Phase 16): staging-file size/row caps for
    # preview and confirm, matching the governance of Phase 15 imports.
    erp_max_file_mb: int = 10
    erp_max_rows: int = 50_000
    erp_export_max_rows: int = 100_000


@lru_cache
def get_settings() -> Settings:
    return Settings()

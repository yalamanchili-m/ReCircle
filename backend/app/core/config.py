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


@lru_cache
def get_settings() -> Settings:
    return Settings()

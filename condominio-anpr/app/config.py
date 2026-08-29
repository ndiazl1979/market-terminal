"""Configuración leída desde variables de entorno / archivo .env."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    secret_key: str = "dev-inseguro-cambiar"
    admin_user: str = "admin"
    admin_password: str = "admin"

    database_url: str = "sqlite:///./data/condominio.db"
    snapshot_dir: str = "./data/snapshots"

    # Barrera
    gate_mode: str = "dummy"          # dahua | http | dummy
    dahua_host: str = "192.168.1.108"
    dahua_user: str = "admin"
    dahua_password: str = ""
    dahua_channel: int = 1
    gate_http_url: str = ""

    # ANPR
    anpr_ingest_token: str = ""
    open_on_unknown_plate: bool = False

    # Sesión
    token_ttl_hours: int = 12


settings = Settings()

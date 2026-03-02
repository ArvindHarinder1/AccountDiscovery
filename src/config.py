"""
Account Discovery Prototype — Configuration
Loads settings from .env file using pydantic-settings.
"""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # Azure Data Explorer (Kusto)
    kusto_cluster_uri: str = Field(default="")
    kusto_database: str = Field(default="accounts")
    kusto_tenant_id: str = Field(default="")
    kusto_subscription_id: str = Field(default="")

    # AI Provider: "azure_openai", "github_models", or "none"
    ai_provider: str = Field(default="none")

    # Azure OpenAI (CLI token auth — no secrets needed)
    azure_openai_endpoint: str = Field(default="")
    azure_openai_deployment: str = Field(default="gpt-4o")
    azure_openai_api_version: str = Field(default="2024-10-21")

    # GitHub Models (legacy — requires PAT)
    github_token: str = Field(default="")
    ai_model: str = Field(default="openai/gpt-4o")
    ai_base_url: str = Field(default="https://models.inference.ai.azure.com")

    # Microsoft Graph API (correlation reports)
    graph_tenant_id: str = Field(default="")  # defaults to kusto_tenant_id if empty
    graph_subscription_id: str = Field(default="")  # defaults to graph_tenant_id if empty (tenant-level accounts)
    graph_service_principal_id: str = Field(default="")  # SP id of the target app

    # Data source: "local", "kusto", or "graph"
    data_source: str = Field(default="local")

    # Matching thresholds
    match_threshold_high: int = Field(default=80)
    match_threshold_medium: int = Field(default=50)
    match_threshold_low: int = Field(default=25)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


def get_settings() -> Settings:
    s = Settings()
    # Fall back to kusto_tenant_id for Graph if not set
    if not s.graph_tenant_id:
        s.graph_tenant_id = s.kusto_tenant_id
    # Fall back to graph_tenant_id for Graph subscription if not set
    if not s.graph_subscription_id:
        s.graph_subscription_id = s.graph_tenant_id
    return s

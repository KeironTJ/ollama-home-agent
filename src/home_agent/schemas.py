from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8_000)
    session_id: str | None = Field(default=None, max_length=100)


class ApprovalDecision(BaseModel):
    approved: bool


class SetupConfig(BaseModel):
    ollama_url: str = Field(min_length=1, max_length=500)
    ollama_model: str = Field(min_length=1, max_length=100)
    proxmox_url: str = Field(min_length=1, max_length=500)
    proxmox_token_id: str = Field(default="", max_length=200)
    proxmox_ca_file: str = Field(default="", max_length=1_000)
    proxmox_insecure_tls: bool = False
    proxmox_allowed_nodes: list[str] = Field(default_factory=list, max_length=100)
    proxmox_allowed_guests: list[int] = Field(default_factory=list, max_length=1_000)

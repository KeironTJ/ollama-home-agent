from typing import Annotated

from pydantic import BaseModel, Field

ServiceName = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.@-]+$", max_length=100)]
PortNumber = Annotated[int, Field(ge=1, le=65535)]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8_000)
    session_id: str | None = Field(default=None, max_length=100)


class ApprovalDecision(BaseModel):
    approved: bool


class SshHostConfig(BaseModel):
    alias: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    hostname: str = Field(min_length=1, max_length=253)
    services: list[ServiceName] = Field(default_factory=list, max_length=100)
    ports: list[PortNumber] = Field(default_factory=list, max_length=100)
    ssh_port: int = Field(default=22, ge=1, le=65535)


class SetupConfig(BaseModel):
    ollama_url: str = Field(min_length=1, max_length=500)
    ollama_model: str = Field(min_length=1, max_length=100)
    proxmox_url: str = Field(min_length=1, max_length=500)
    proxmox_token_id: str = Field(default="", max_length=200)
    proxmox_ca_file: str = Field(default="", max_length=1_000)
    proxmox_insecure_tls: bool = False
    proxmox_allowed_nodes: list[str] = Field(default_factory=list, max_length=100)
    proxmox_allowed_guests: list[int] = Field(default_factory=list, max_length=1_000)
    ssh_username: str = Field(default="diagnostic-agent", min_length=1, max_length=100)
    ssh_key_file: str = Field(default="", max_length=1_000)
    ssh_hosts: list[SshHostConfig] = Field(default_factory=list, max_length=100)

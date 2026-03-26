from dataclasses import dataclass, field


@dataclass
class LLMConfig:
    provider: str
    model: str
    base_url: str | None = None
    api_key: str | None = None
    temperature: float = 0.7
    auth_mode: str = "api_key"
    codex_auth_file: str | None = None
    codex_bridge_issuer: str = "https://auth.openai.com"
    codex_api_base: str = "https://api.openai.com/v1"
    codex_bridge_start_timeout: float = 15.0


@dataclass
class EmailConfig:
    smtp_server: str
    smtp_port: int
    sender: str
    receiver: str
    sender_password: str


@dataclass
class CommonConfig:
    description: str
    num_workers: int = 4
    save: bool = False
    save_dir: str = "./history"

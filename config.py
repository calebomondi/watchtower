from os import environ
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Config:
    google_api_key: str = field(default_factory=lambda: environ.get("GOOGLE_API_KEY", ""))
    groq_api_key: str = field(default_factory=lambda: environ.get("GROQ_API_KEY", ""))
    dashscope_api_key: str = field(default_factory=lambda: environ.get("DASHSCOPE_API_KEY", ""))
    dashscope_base_url: str = field(default_factory=lambda: environ.get("DASHSCOPE_BASE_URL", ""))

    @classmethod
    def from_env(cls) -> "Config":
        return cls()

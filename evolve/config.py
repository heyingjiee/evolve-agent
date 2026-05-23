import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from anthropic import Anthropic


@dataclass
class Config:
    model: str
    api_key: str
    base_url: str
    max_tokens: int
    temperature: float
    prompt: Optional[str]
    resume: Optional[str]
    workspace: Path

    @classmethod
    def from_env(cls, **args) -> "Config":
        from dotenv import load_dotenv

        load_dotenv(override=True)

        base_url = os.getenv("BASE_URL") or os.getenv("ANTHROPIC_BASE_URL") or ""
        api_key = os.getenv("API_KEY") or os.getenv("ANTHROPIC_API_KEY") or ""
        model = os.getenv("MODEL") or os.getenv("MODEL_ID") or ""
        if not api_key:
            raise ValueError("API_KEY or ANTHROPIC_API_KEY environment variable is not set")
        if not model:
            raise ValueError("MODEL or MODEL_ID environment variable is not set")

        return cls(
            model=model,
            api_key=api_key,
            base_url=base_url,
            max_tokens=int(os.getenv("MAX_TOKENS", "4096")),
            temperature=float(os.getenv("TEMPERATURE", "0")),
            prompt=args.get("prompt"),
            resume=args.get("resume"),
            workspace=Path(args.get("workspace", ".")).resolve(),
        )

    def build_client(self) -> Anthropic:
        return Anthropic(
            base_url=self.base_url or None,
            api_key=self.api_key,
        )

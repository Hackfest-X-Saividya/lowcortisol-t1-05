"""Application settings.

Values come from ``backend/.env`` (never printed or logged) and the environment.
Everything except the six secrets has a default here. ``get_settings()`` is cached;
tests call ``get_settings.cache_clear()`` after changing the environment.
"""

from __future__ import annotations

import base64
import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BACKEND_DIR / ".env"

AIMode = Literal["cloud", "mock"]
LLMName = Literal["gemini", "groq", "mock"]
ImageName = Literal["cloudflare", "pollinations", "mock"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE) if ENV_FILE.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- secrets (from .env; empty = not configured) ---------------------------------
    gemini_api_key: SecretStr = SecretStr("")
    groq_api_key: SecretStr = SecretStr("")
    cloudflare_account_id: SecretStr = SecretStr("")
    cloudflare_api_token: SecretStr = SecretStr("")
    jwt_secret: SecretStr = SecretStr("")
    file_master_key_b64: SecretStr = SecretStr("")

    # ---- app ------------------------------------------------------------------------
    app_env: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:5173"
    log_level: str = "INFO"
    database_url: str = "sqlite+aiosqlite:///./data/nishaan.db"
    file_store_dir: str = "./data/files"
    assets_dir: str = str(BACKEND_DIR / "assets")
    auto_create_db: bool = True  # create tables + triggers on startup if the DB is empty

    # ---- auth -----------------------------------------------------------------------
    jwt_access_ttl_min: int = 15
    jwt_refresh_ttl_days: int = 7
    witness_token_ttl_min: int = 240
    login_rate_limit: str = "10/minute"
    login_max_failures: int = 5
    login_lock_minutes: int = 15

    # ---- AI providers ---------------------------------------------------------------
    ai_mode: AIMode = "cloud"  # cloud | mock
    cloud_mode_ack: bool = True
    llm_primary: LLMName = "groq"  # groq | gemini | mock (Groq: fastest for the live interview)
    # Verify the current model names: https://ai.google.dev/gemini-api/docs/models
    gemini_model: str = "gemini-3-flash-preview"
    # 0 = no "thinking" (fastest, right for a live interview); -1 = model default
    gemini_thinking_budget: int = 0
    # Text-to-speech for the interviewer's voice when the browser has none for the language
    gemini_tts_model: str = "gemini-3.8-flash-tts"
    gemini_tts_voice: str = "Kore"
    tts_enabled: bool = True
    # Seconds a provider is skipped after a quota error (429) or outage, so calls go
    # straight to the fallback instead of waiting on retries
    provider_cooldown_s: int = 300
    # Verify in the Groq console: https://console.groq.com/docs/models
    groq_llm_model: str = "openai/gpt-oss-120b"
    # separate per-model rate limits: used at once when the main model answers 429
    groq_llm_fallback_model: str = "openai/gpt-oss-20b"
    groq_reasoning_effort: str = "low"  # low | medium | high (gpt-oss models only)
    # Verify in the Groq console: https://console.groq.com/docs/speech-to-text
    groq_asr_model: str = "whisper-large-v3"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    image_primary: ImageName = "cloudflare"  # cloudflare | pollinations | mock
    # Verify in the Cloudflare Workers AI catalogue: https://developers.cloudflare.com/workers-ai/models/
    # Realistic portraits (verified 2026-10-28): Lucid Origin, then Phoenix, then SDXL via chain
    # flux-1-schnell: realistic and about 50x cheaper in neurons than Lucid Origin (about 60
    # neurons per portrait, so the 10,000/day free allowance lasts ~150 renders)
    cf_image_model: str = "@cf/black-forest-labs/flux-1-schnell"
    cf_image_fallback_model: str = "@cf/stabilityai/stable-diffusion-xl-base-1.0"
    cf_inpaint_model: str = "@cf/runwayml/stable-diffusion-v1-5-inpainting"
    cloudflare_base_url: str = "https://api.cloudflare.com/client/v4"
    pollinations_base_url: str = "https://image.pollinations.ai/prompt"
    pollinations_model: str = "flux"
    pollinations_timeout_s: float = 45.0
    inpaint_enabled: bool = True
    provider_cache: bool = True
    http_timeout_s: float = 60.0
    max_retries: int = 3
    llm_temperature: float = 0.2

    # ---- jobs -----------------------------------------------------------------------
    jobs_inline: bool = False  # run jobs synchronously inside the request (tests)

    # ---- image pipeline -------------------------------------------------------------
    face_size_px: int = 1024
    stability_max_drift_px: float = 3.0
    stability_min_ssim_outside: float = 0.995
    max_audio_mb: int = 20
    max_image_mb: int = 10
    face_check_max_yaw_deg: float = 15.0
    face_check_max_pitch_deg: float = 15.0
    face_check_min_width_ratio: float = 0.35
    generation_max_attempts: int = 3
    warp_internal_px: int = 512  # warp is computed at this size and upscaled (speed)
    sketch_blur_sigma: float = 9.0
    sketch_xdog_sigma: float = 1.0
    sketch_xdog_k: float = 1.6
    sketch_xdog_tau: float = 0.98
    sketch_xdog_phi: float = 10.0
    sketch_edge_weight: float = 0.55
    export_size_px: int = 2048

    # ---- interview ------------------------------------------------------------------
    interview_max_questions: int = 12
    interview_live_max_questions: int = 24  # live sketch interview asks more, shorter questions

    @field_validator("cors_origins")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    # ---- derived ----------------------------------------------------------------------
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def backend_dir(self) -> Path:
        return BACKEND_DIR

    @property
    def assets_path(self) -> Path:
        return Path(self.assets_dir)

    @property
    def file_store_path(self) -> Path:
        p = Path(self.file_store_dir)
        return p if p.is_absolute() else BACKEND_DIR / p

    @property
    def resolved_database_url(self) -> str:
        """Make a relative sqlite path absolute to the backend dir so cwd does not matter."""
        url = self.database_url
        prefix = "sqlite+aiosqlite:///"
        if url.startswith(prefix) and ":memory:" not in url:
            rel = url[len(prefix) :]
            if rel.startswith("./"):
                rel = rel[2:]
            if not Path(rel).is_absolute():
                return prefix + (BACKEND_DIR / rel).as_posix()
        return url

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key.get_secret_value())

    @property
    def groq_configured(self) -> bool:
        return bool(self.groq_api_key.get_secret_value())

    @property
    def cloudflare_configured(self) -> bool:
        return bool(
            self.cloudflare_account_id.get_secret_value()
            and self.cloudflare_api_token.get_secret_value()
        )

    @property
    def mock_mode(self) -> bool:
        """True when no cloud provider may be used (AI_MODE=mock or CLOUD_MODE_ACK=false)."""
        return self.ai_mode == "mock" or not self.cloud_mode_ack

    @property
    def llm_chain(self) -> list[str]:
        """Ordered providers to try for LLM calls, always ending in mock."""
        if self.mock_mode or self.llm_primary == "mock":
            return ["mock"]
        order = ["gemini", "groq"] if self.llm_primary == "gemini" else ["groq", "gemini"]
        chain = [
            p
            for p in order
            if (p == "gemini" and self.gemini_configured) or (p == "groq" and self.groq_configured)
        ]
        return chain + ["mock"]

    @property
    def asr_chain(self) -> list[str]:
        if self.mock_mode or not self.groq_configured:
            return ["mock"]
        return ["groq", "mock"]

    @property
    def image_chain(self) -> list[str]:
        if self.mock_mode or self.image_primary == "mock":
            return ["mock"]
        order = (
            ["cloudflare", "pollinations"]
            if self.image_primary == "cloudflare"
            else ["pollinations", "cloudflare"]
        )
        chain = [p for p in order if p != "cloudflare" or self.cloudflare_configured]
        return chain + ["mock"]

    @property
    def inpaint_chain(self) -> list[str]:
        if self.mock_mode:
            return ["mock"]
        if self.inpaint_enabled and self.cloudflare_configured:
            return ["cloudflare"]
        return []

    @property
    def cloud_active(self) -> bool:
        return not self.mock_mode and (
            self.gemini_configured or self.groq_configured or self.cloudflare_configured
        )

    @property
    def data_mode(self) -> str:
        return "cloud_demo" if self.cloud_active else "local_mock"

    def jwt_secret_value(self) -> str:
        v = self.jwt_secret.get_secret_value()
        if v:
            return v
        return _ephemeral("JWT_SECRET")

    def file_master_key(self) -> bytes:
        v = self.file_master_key_b64.get_secret_value()
        if v:
            raw = base64.b64decode(v)
            if len(raw) < 32:
                raise ValueError("FILE_MASTER_KEY_B64 must decode to at least 32 bytes")
            return raw
        return base64.b64decode(_ephemeral("FILE_MASTER_KEY_B64"))

    def provider_status(self) -> dict[str, str]:
        """Human readable status per provider; never includes key material."""
        if self.mock_mode:
            why = "AI_MODE=mock" if self.ai_mode == "mock" else "CLOUD_MODE_ACK=false"
            m = f"mock ({why})"
            return {"gemini": m, "groq": m, "cloudflare": m, "pollinations": m}
        return {
            "gemini": "configured" if self.gemini_configured else "missing key - using mock",
            "groq": "configured" if self.groq_configured else "missing key - using mock",
            "cloudflare": "configured"
            if self.cloudflare_configured
            else "missing key - using fallback",
            "pollinations": "available (no key needed)",
        }


_EPHEMERAL: dict[str, str] = {}


def _ephemeral(name: str) -> str:
    """Generate a per-process random secret when a key is missing from .env.

    Used so the app still starts in development. Production refuses to start without
    real values (see ``app.main``).
    """
    if name not in _EPHEMERAL:
        if name == "FILE_MASTER_KEY_B64":
            _EPHEMERAL[name] = base64.b64encode(secrets.token_bytes(32)).decode()
        else:
            _EPHEMERAL[name] = secrets.token_urlsafe(48)
    return _EPHEMERAL[name]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def settings_with(**overrides: object) -> Settings:
    """Build a Settings instance with explicit overrides (used by tests and scripts)."""
    env_backup = dict(os.environ)
    try:
        for k, v in overrides.items():
            os.environ[k.upper()] = str(v)
        return Settings()
    finally:
        os.environ.clear()
        os.environ.update(env_backup)

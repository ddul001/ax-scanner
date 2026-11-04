"""Process configuration: every knob comes from the environment (see `.env.example`)."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./ax.db"
    meta_api_key: str = ""
    meta_api_base: str = "https://api.meta.ai/v1"
    meta_model: str = "muse-spark-1.3"
    meta_reasoning_effort: str = ""  # "", "minimal", "low", ... ; empty = model default (slow, ~2k reasoning tokens)
    locale: str = "en"

    bot_user_agent: str = "AivexiaScanBot/1.0 (+https://aivexia.ro/bot)"
    fetch_timeout_s: float = 10.0
    allow_ignore_robots: bool = True  # the opt-in 'scan ignoring robots.txt' (owners auditing their own site); False on a public deploy
    fetch_retries: int = 1  # extra attempts for transient failures (connect/timeout errors, 429/502/503/504)
    fetch_retry_delay_s: float = 0.8
    probe_delay_s: float = 0.6  # pause between the user-agent probe requests (a burst looks like an attack to a WAF)
    probe_retry_delay_s: float = 2.0  # pause before a blocked probe is repeated
    llm_timeout_s: float = 45.0
    step0_budget_s: float = 130.0  # one Muse call may take 45s and is retried once; the fetches come on top
    scan_budget_s: float = 420.0
    llm_retry_delay_s: float = 1.5  # one retry of a Muse call that timed out or got 429/5xx
    journey_retry: bool = True  # a journey that ended in a loop or a Muse error gets one more attempt; the best verdict counts
    journey_max_steps: int = 8
    journey_budget_s: float = 150.0
    journey_reasoning_effort: str = ""  # "" = model default; "low" is faster but listed fewer form fields in one live run
    journey_delay_s: float = 0.3  # politeness delay between journey requests
    classification_cache_days: int = 7
    confirm_threshold: float = 0.7
    rate_limit_per_min: int = 10
    max_scans_per_day: int = 0  # public deploy: cap on new scans per rolling 24 h across all visitors (0 = no cap); protects the Meta API budget


settings = Settings()

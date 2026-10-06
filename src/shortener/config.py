import os


class Config:
    """Read settings from environment variables (set by Terraform in AWS)."""

    def __init__(self) -> None:
        self.links_table = os.environ.get("LINKS_TABLE", "links")
        self.clicks_table = os.environ.get("CLICKS_TABLE", "clicks_daily")
        self.limits_table = os.environ.get("LIMITS_TABLE", "rate_limits")
        self.clicks_queue_url = os.environ.get("CLICKS_QUEUE_URL", "")
        self.base_url = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
        self.rate_limit_per_minute = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "20"))
        self.code_length = int(os.environ.get("CODE_LENGTH", "7"))

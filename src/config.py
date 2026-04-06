"""项目配置."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"


class Settings(BaseSettings):
    """应用配置，支持 .env 文件和环境变量."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_prefix="GHH_",
        extra="ignore",
    )

    # GitHub 配置
    github_token: str = ""
    github_api_base: str = "https://api.github.com"
    github_trending_url: str = "https://github.com/trending"

    # 爬虫配置
    request_timeout: int = 30
    request_retries: int = 3
    trending_languages: list[str] = Field(
        default_factory=lambda: ["", "python", "typescript", "javascript", "rust", "go"]
    )
    trending_periods: list[str] = Field(
        default_factory=lambda: ["daily", "weekly"]
    )

    # 评分配置
    score_weight_star_speed: float = 0.40       # Star 日增速权重
    score_weight_acceleration: float = 0.20     # 增速加速度权重
    score_weight_relative_growth: float = 0.20  # 相对增长率权重
    score_weight_freshness: float = 0.10        # 新鲜度权重
    score_weight_community: float = 0.10        # 社区响应度权重

    # 过滤配置
    min_stars_today: int = 50                   # 最低日增 star 门槛
    exclude_patterns: list[str] = Field(
        default_factory=lambda: ["awesome-", "awesome_", "interview", "leetcode"]
    )
    exclude_topics: list[str] = Field(
        default_factory=lambda: ["awesome-list", "awesome", "interview-questions"]
    )

    # 推送配置（预留）
    wecom_webhook_url: str = ""

    # 报告配置
    report_top_n: int = 30                       # 报告中展示的项目数量

    @property
    def data_dir(self) -> Path:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        return DATA_DIR

    @property
    def reports_dir(self) -> Path:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        return REPORTS_DIR

    @property
    def github_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "github-hot-hub/0.1",
        }
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"
        return headers


settings = Settings()

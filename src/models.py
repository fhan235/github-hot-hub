"""数据模型定义."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class TrendPeriod(str, Enum):
    """Trending 时间维度."""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class BurstType(str, Enum):
    """爆发类型标签."""
    NEW_STAR = "new_star"           # 🔥 新星爆发：项目创建 < 7 天
    ACCELERATING = "accelerating"   # 📈 加速上升：增速加速度为正
    RESURGENCE = "resurgence"       # 🔄 二次翻红：老项目突然爆发
    STEADY_HOT = "steady_hot"       # 🏆 持续霸榜：连续多天上榜

    @property
    def emoji(self) -> str:
        return {
            self.NEW_STAR: "🔥",
            self.ACCELERATING: "📈",
            self.RESURGENCE: "🔄",
            self.STEADY_HOT: "🏆",
        }[self]

    @property
    def label(self) -> str:
        return {
            self.NEW_STAR: "新星爆发",
            self.ACCELERATING: "加速上升",
            self.RESURGENCE: "二次翻红",
            self.STEADY_HOT: "持续霸榜",
        }[self]


class TrendingRepo(BaseModel):
    """从 GitHub Trending 页面爬取的仓库基本信息."""
    full_name: str                          # owner/repo
    description: str = ""
    language: str = ""
    stars_today: int = 0                    # 今日新增 star
    total_stars: int = 0
    forks: int = 0
    url: str = ""
    period: TrendPeriod = TrendPeriod.DAILY


class RepoDetail(BaseModel):
    """通过 GitHub API 获取的仓库详细信息."""
    full_name: str
    description: str = ""
    language: str = ""
    topics: list[str] = Field(default_factory=list)
    total_stars: int = 0
    forks_count: int = 0
    open_issues_count: int = 0
    watchers_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    pushed_at: datetime | None = None
    homepage: str = ""
    license_name: str = ""
    is_fork: bool = False
    is_archived: bool = False
    default_branch: str = "main"


class ScoredRepo(BaseModel):
    """经过评分的仓库，包含爆发度分数和各项指标."""
    full_name: str
    url: str = ""
    description: str = ""
    language: str = ""
    topics: list[str] = Field(default_factory=list)

    # 原始数据
    total_stars: int = 0
    stars_today: int = 0                    # 今日新增
    stars_yesterday: int = 0                # 昨日新增（从历史数据取）
    forks_count: int = 0
    open_issues_count: int = 0
    created_at: datetime | None = None

    # 评分结果
    score: float = 0.0                      # 综合爆发度分数 (0-100)
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    burst_types: list[BurstType] = Field(default_factory=list)

    # 分类
    category: str = ""                      # 技术领域分类

    # LLM 分析
    llm_analysis: str = ""                  # LLM 生成的分析文本

    # 元数据
    scored_at: datetime = Field(default_factory=datetime.now)


class DailySnapshot(BaseModel):
    """每日快照，用于持久化存储和历史对比."""
    date: str                               # YYYY-MM-DD
    repos: dict[str, int] = Field(default_factory=dict)  # full_name -> star count
    collected_at: datetime = Field(default_factory=datetime.now)

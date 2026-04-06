"""火爆度评分算法.

根据多维度指标计算仓库的 "爆发度" 分数。
核心目标：识别「正在爆发」的项目，而非「好项目」。
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

from src.config import settings
from src.models import BurstType, RepoDetail, ScoredRepo, TrendingRepo

logger = logging.getLogger(__name__)


# 技术领域关键词映射
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "AI/LLM": [
        "llm", "gpt", "chatgpt", "openai", "langchain", "transformer", "diffusion",
        "stable-diffusion", "machine-learning", "deep-learning", "neural", "ai",
        "artificial-intelligence", "nlp", "computer-vision", "rag", "agent",
        "copilot", "embedding", "fine-tuning", "lora", "gguf", "ollama", "vllm",
    ],
    "前端框架": [
        "react", "vue", "svelte", "nextjs", "nuxt", "angular", "frontend",
        "tailwind", "css", "ui-library", "component", "vite",
    ],
    "后端框架": [
        "backend", "api", "rest", "graphql", "fastapi", "django", "flask",
        "express", "gin", "fiber", "spring", "microservice",
    ],
    "DevOps/基础设施": [
        "docker", "kubernetes", "k8s", "terraform", "ci-cd", "devops",
        "monitoring", "observability", "infrastructure", "cloud",
    ],
    "编程语言/工具": [
        "compiler", "runtime", "language", "cli", "terminal", "shell",
        "editor", "ide", "linter", "formatter", "package-manager",
    ],
    "安全": [
        "security", "vulnerability", "pentest", "ctf", "encryption",
        "authentication", "authorization",
    ],
    "数据库": [
        "database", "sql", "nosql", "redis", "postgresql", "sqlite",
        "vector-database", "search-engine",
    ],
}


class HotScorer:
    """火爆度评分器."""

    def __init__(
        self,
        history: dict[str, int] | None = None,
    ) -> None:
        """初始化评分器.

        Args:
            history: 历史 star 数据 {full_name: yesterday_star_count}
        """
        self.history = history or {}

    def score(
        self,
        trending: TrendingRepo,
        detail: RepoDetail | None = None,
    ) -> ScoredRepo | None:
        """对单个仓库评分.

        Args:
            trending: Trending 页面数据
            detail: API 详细数据（可选，有则更准确）

        Returns:
            ScoredRepo 或 None（被过滤掉时）
        """
        full_name = trending.full_name

        # ---- 预过滤 ----
        if self._should_exclude(trending, detail):
            logger.debug("过滤: %s", full_name)
            return None

        # ---- 收集原始数据 ----
        stars_today = trending.stars_today
        total_stars = detail.total_stars if detail else trending.total_stars
        forks_count = detail.forks_count if detail else trending.forks
        open_issues = detail.open_issues_count if detail else 0
        created_at = detail.created_at if detail else None
        topics = detail.topics if detail else []
        stars_yesterday = self.history.get(full_name, 0)

        # ---- 计算各维度分数 (均归一化到 0-100) ----
        breakdown: dict[str, float] = {}

        # 1. Star 日增速 (40%)
        # 使用对数缩放：50 -> ~39, 200 -> ~53, 1000 -> ~69, 5000 -> ~85, 10000 -> ~92
        speed_score = min(100, math.log1p(stars_today) / math.log1p(10000) * 100)
        breakdown["star_speed"] = round(speed_score, 1)

        # 2. 增速加速度 (20%)
        if stars_yesterday > 0:
            acceleration = stars_today - stars_yesterday
            if acceleration > 0:
                accel_score = min(100, math.log1p(acceleration) / math.log1p(5000) * 100)
            else:
                accel_score = max(0, 50 + acceleration / max(stars_yesterday, 1) * 50)
        else:
            # 没有历史数据时，给一个中等分数
            accel_score = 50.0
        breakdown["acceleration"] = round(accel_score, 1)

        # 3. 相对增长率 (20%)
        # 100 star 涨 200 = 200% 比 50000 star 涨 200 = 0.4% 更"爆发"
        if total_stars > 0:
            growth_rate = stars_today / total_stars
            relative_score = min(100, growth_rate * 200)  # 50% 日增长 = 满分
        else:
            relative_score = 100.0 if stars_today > 0 else 0.0
        breakdown["relative_growth"] = round(relative_score, 1)

        # 4. 新鲜度 (10%)
        freshness_score = self._calc_freshness(created_at)
        breakdown["freshness"] = round(freshness_score, 1)

        # 5. 社区响应度 (10%)
        community_signal = forks_count * 2 + open_issues
        community_score = min(100, math.log1p(community_signal) / math.log1p(1000) * 100)
        breakdown["community"] = round(community_score, 1)

        # ---- 加权汇总 ----
        total_score = (
            speed_score * settings.score_weight_star_speed
            + accel_score * settings.score_weight_acceleration
            + relative_score * settings.score_weight_relative_growth
            + freshness_score * settings.score_weight_freshness
            + community_score * settings.score_weight_community
        )

        # ---- 判断爆发类型 ----
        burst_types = self._determine_burst_types(
            stars_today=stars_today,
            stars_yesterday=stars_yesterday,
            total_stars=total_stars,
            created_at=created_at,
        )

        # ---- 分类 ----
        category = self._categorize(trending, detail)

        return ScoredRepo(
            full_name=full_name,
            url=trending.url,
            description=detail.description if detail else trending.description,
            language=detail.language if detail else trending.language,
            topics=topics,
            total_stars=total_stars,
            stars_today=stars_today,
            stars_yesterday=stars_yesterday,
            forks_count=forks_count,
            open_issues_count=open_issues,
            created_at=created_at,
            score=round(total_score, 1),
            score_breakdown=breakdown,
            burst_types=burst_types,
            category=category,
        )

    def score_batch(
        self,
        trending_list: list[TrendingRepo],
        details: dict[str, RepoDetail] | None = None,
    ) -> list[ScoredRepo]:
        """批量评分并排序.

        Args:
            trending_list: Trending 仓库列表
            details: 仓库详情字典（可选）

        Returns:
            按分数降序排列的 ScoredRepo 列表
        """
        details = details or {}
        scored: list[ScoredRepo] = []

        for trending in trending_list:
            detail = details.get(trending.full_name)
            result = self.score(trending, detail)
            if result:
                scored.append(result)

        scored.sort(key=lambda r: r.score, reverse=True)
        logger.info("评分完成，有效项目 %d 个 (过滤前 %d 个)", len(scored), len(trending_list))
        return scored

    def _should_exclude(self, trending: TrendingRepo, detail: RepoDetail | None) -> bool:
        """判断是否应该过滤掉."""
        name_lower = trending.full_name.lower()

        # 排除模式匹配
        for pattern in settings.exclude_patterns:
            if pattern in name_lower:
                return True

        # 最低门槛
        if trending.stars_today < settings.min_stars_today:
            return True

        # 排除 fork 和归档仓库
        if detail:
            if detail.is_fork or detail.is_archived:
                return True
            # 排除特定 topic
            for topic in detail.topics:
                if topic.lower() in settings.exclude_topics:
                    return True

        return False

    @staticmethod
    def _calc_freshness(created_at: datetime | None) -> float:
        """计算新鲜度分数. 越新分数越高."""
        if not created_at:
            return 50.0  # 无数据时给中等分

        now = datetime.now(timezone.utc)
        age_days = (now - created_at).days

        if age_days <= 7:
            return 100.0
        elif age_days <= 30:
            return 80.0
        elif age_days <= 90:
            return 60.0
        elif age_days <= 365:
            return 40.0
        elif age_days <= 365 * 3:
            return 20.0
        else:
            return 10.0

    @staticmethod
    def _determine_burst_types(
        stars_today: int,
        stars_yesterday: int,
        total_stars: int,
        created_at: datetime | None,
    ) -> list[BurstType]:
        """判断爆发类型标签."""
        types: list[BurstType] = []

        # 新星爆发：项目创建 < 7 天
        if created_at:
            age_days = (datetime.now(timezone.utc) - created_at).days
            if age_days <= 7:
                types.append(BurstType.NEW_STAR)

        # 加速上升：今日增量 > 昨日增量
        if stars_yesterday > 0 and stars_today > stars_yesterday * 1.5:
            types.append(BurstType.ACCELERATING)

        # 二次翻红：老项目突然爆发
        if created_at:
            age_days = (datetime.now(timezone.utc) - created_at).days
            if age_days > 180 and total_stars > 1000 and stars_today > total_stars * 0.05:
                types.append(BurstType.RESURGENCE)

        # 如果没有命中其他类型，但 star 增速很高，标记为持续霸榜
        if not types and stars_today >= 200:
            types.append(BurstType.STEADY_HOT)

        return types

    def _categorize(self, trending: TrendingRepo, detail: RepoDetail | None) -> str:
        """根据 topics、语言和描述自动分类."""
        signals: list[str] = []

        if detail:
            signals.extend([t.lower() for t in detail.topics])
            if detail.description:
                signals.extend(detail.description.lower().split())
        if trending.description:
            signals.extend(trending.description.lower().split())
        if trending.language:
            signals.append(trending.language.lower())

        # 匹配分类
        best_category = "其他"
        best_match_count = 0

        for category, keywords in CATEGORY_KEYWORDS.items():
            match_count = sum(1 for kw in keywords if kw in signals)
            if match_count > best_match_count:
                best_match_count = match_count
                best_category = category

        return best_category

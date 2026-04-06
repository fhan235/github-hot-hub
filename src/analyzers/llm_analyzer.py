"""LLM 智能分析器.

使用 DeepSeek 分析项目为什么火、是干什么的、值不值得关注。
兼容 OpenAI SDK 格式。
"""

from __future__ import annotations

import logging
from datetime import datetime

from openai import OpenAI

from src.config import settings
from src.models import ScoredRepo

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一位资深技术观察者，擅长分析 GitHub 开源项目的技术趋势。
你的任务是对每个热门项目给出简洁有力的分析。

要求：
1. **是什么**：一句话说清楚项目的核心功能和定位
2. **为什么火**：结合数据和技术背景分析爆火原因（2-3 句话）
3. **值得关注吗**：给出你的判断和理由（1-2 句话）

风格要求：
- 简洁、有洞察力、不废话
- 用中文回答
- 每个部分前加对应的标题标记
- 总长度控制在 200 字以内"""


def _build_user_prompt(repo: ScoredRepo) -> str:
    """构建单个项目的分析 prompt."""
    today = datetime.now().strftime("%Y-%m-%d")

    parts = [
        f"项目：{repo.full_name}",
        f"链接：{repo.url}",
        f"日期：{today}",
        f"语言：{repo.language or '未知'}",
        f"描述：{repo.description or '无描述'}",
        f"今日 Star 增量：+{repo.stars_today:,}",
        f"总 Star：{repo.total_stars:,}",
    ]

    if repo.stars_yesterday > 0:
        parts.append(f"昨日 Star 增量：+{repo.stars_yesterday:,}")

    if repo.created_at:
        age_days = (datetime.now() - repo.created_at.replace(tzinfo=None)).days
        parts.append(f"项目年龄：{age_days} 天")

    if repo.topics:
        parts.append(f"Topics：{', '.join(repo.topics[:10])}")

    if repo.forks_count > 0:
        parts.append(f"Fork 数：{repo.forks_count:,}")

    if repo.open_issues_count > 0:
        parts.append(f"Open Issues：{repo.open_issues_count:,}")

    burst_labels = [f"{bt.emoji} {bt.label}" for bt in repo.burst_types]
    if burst_labels:
        parts.append(f"爆发标签：{', '.join(burst_labels)}")

    parts.append(f"爆发度评分：{repo.score:.1f}/100")

    return "\n".join(parts)


class LLMAnalyzer:
    """基于 DeepSeek 的项目智能分析器."""

    def __init__(self) -> None:
        if not settings.llm_api_key:
            self._client = None
            logger.warning("未配置 GHH_LLM_API_KEY，LLM 分析将不可用")
        else:
            self._client = OpenAI(
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
            )

    @property
    def available(self) -> bool:
        """LLM 是否可用."""
        return self._client is not None and settings.llm_enabled

    def analyze(self, repo: ScoredRepo) -> str:
        """分析单个项目.

        Args:
            repo: 经过评分的仓库

        Returns:
            分析文本，失败时返回空字符串
        """
        if not self.available:
            return ""

        user_prompt = _build_user_prompt(repo)

        try:
            response = self._client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=settings.llm_max_tokens,
                temperature=settings.llm_temperature,
            )
            content = response.choices[0].message.content or ""
            logger.debug("LLM 分析完成: %s (%d 字)", repo.full_name, len(content))
            return content.strip()

        except Exception as e:
            logger.error("LLM 分析失败 (%s): %s", repo.full_name, e)
            return ""

    def analyze_batch(
        self, repos: list[ScoredRepo], top_n: int = 10
    ) -> dict[str, str]:
        """批量分析项目.

        Args:
            repos: 按分数排序的仓库列表
            top_n: 分析前 N 个项目（LLM 调用有成本，不需要全部分析）

        Returns:
            字典 {full_name: 分析文本}
        """
        if not self.available:
            logger.warning("LLM 不可用，跳过分析")
            return {}

        results: dict[str, str] = {}
        analyze_repos = repos[:top_n]

        for i, repo in enumerate(analyze_repos, 1):
            logger.info("LLM 分析 [%d/%d]: %s", i, len(analyze_repos), repo.full_name)
            analysis = self.analyze(repo)
            if analysis:
                results[repo.full_name] = analysis

        logger.info("LLM 分析完成: %d/%d 个项目", len(results), len(analyze_repos))
        return results

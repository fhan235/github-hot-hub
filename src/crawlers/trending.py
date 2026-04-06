"""GitHub Trending 页面爬虫.

爬取 https://github.com/trending 页面，提取当前热门仓库列表。
这是发现火爆项目的主要数据源。
"""

from __future__ import annotations

import logging
import re

import httpx
from bs4 import BeautifulSoup

from src.config import settings
from src.models import TrendPeriod, TrendingRepo

logger = logging.getLogger(__name__)


class TrendingCrawler:
    """GitHub Trending 页面爬虫."""

    def __init__(self) -> None:
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                timeout=settings.request_timeout,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                follow_redirects=True,
            )
        return self._client

    def crawl(
        self,
        language: str = "",
        period: TrendPeriod = TrendPeriod.DAILY,
    ) -> list[TrendingRepo]:
        """爬取指定语言和时间维度的 Trending 列表.

        Args:
            language: 编程语言过滤，空字符串表示不限
            period: 时间维度 (daily/weekly/monthly)

        Returns:
            TrendingRepo 列表
        """
        url = self._build_url(language, period)
        logger.info("正在爬取 Trending: %s", url)

        for attempt in range(settings.request_retries):
            try:
                resp = self.client.get(url)
                resp.raise_for_status()
                repos = self._parse_html(resp.text, period)
                logger.info("成功获取 %d 个项目 (语言=%s, 周期=%s)", len(repos), language or "all", period.value)
                return repos
            except httpx.HTTPError as e:
                logger.warning("第 %d 次请求失败: %s", attempt + 1, e)
                if attempt == settings.request_retries - 1:
                    logger.error("爬取 Trending 失败，已达最大重试次数")
                    raise
        return []

    def crawl_all(self) -> list[TrendingRepo]:
        """爬取所有配置的语言和时间维度，去重合并.

        Returns:
            去重后的 TrendingRepo 列表
        """
        seen: dict[str, TrendingRepo] = {}

        for lang in settings.trending_languages:
            for period_str in settings.trending_periods:
                period = TrendPeriod(period_str)
                try:
                    repos = self.crawl(language=lang, period=period)
                    for repo in repos:
                        key = repo.full_name
                        # 优先保留 daily 数据（stars_today 更准确）
                        if key not in seen or period == TrendPeriod.DAILY:
                            seen[key] = repo
                except Exception as e:
                    logger.error("爬取失败 (语言=%s, 周期=%s): %s", lang, period_str, e)

        result = list(seen.values())
        logger.info("合计去重后获得 %d 个 Trending 项目", len(result))
        return result

    def _build_url(self, language: str, period: TrendPeriod) -> str:
        url = settings.github_trending_url
        if language:
            url += f"/{language}"
        url += f"?since={period.value}"
        return url

    def _parse_html(self, html: str, period: TrendPeriod) -> list[TrendingRepo]:
        """解析 Trending 页面 HTML."""
        soup = BeautifulSoup(html, "lxml")
        repos: list[TrendingRepo] = []

        # Trending 页面的每个仓库是一个 article.Box-row
        articles = soup.select("article.Box-row")
        if not articles:
            logger.warning("未找到任何 article.Box-row 元素，页面结构可能已变化")
            return repos

        for article in articles:
            try:
                repo = self._parse_article(article, period)
                if repo:
                    repos.append(repo)
            except Exception as e:
                logger.warning("解析单个仓库失败: %s", e)

        return repos

    def _parse_article(self, article: BeautifulSoup, period: TrendPeriod) -> TrendingRepo | None:
        """解析单个仓库的 HTML 元素."""

        # 仓库名称: h2 > a 的 href 形如 /owner/repo
        h2 = article.select_one("h2")
        if not h2:
            return None
        link = h2.select_one("a")
        if not link:
            return None
        href = link.get("href", "").strip("/")
        if not href or "/" not in href:
            return None
        full_name = href  # owner/repo

        # 描述
        desc_tag = article.select_one("p")
        description = desc_tag.get_text(strip=True) if desc_tag else ""

        # 编程语言
        lang_tag = article.select_one("[itemprop='programmingLanguage']")
        language = lang_tag.get_text(strip=True) if lang_tag else ""

        # 总 star 数 (第一个带 .octicon-star 的链接)
        star_links = article.select("a.Link--muted")
        total_stars = 0
        forks = 0
        for sl in star_links:
            href_val = sl.get("href", "")
            text = sl.get_text(strip=True).replace(",", "")
            if "/stargazers" in href_val:
                total_stars = self._parse_number(text)
            elif "/forks" in href_val:
                forks = self._parse_number(text)

        # 今日/本周/本月新增 star
        stars_today = 0
        span_stars = article.select_one("span.d-inline-block.float-sm-right")
        if span_stars:
            text = span_stars.get_text(strip=True).replace(",", "")
            match = re.search(r"([\d,]+)", text)
            if match:
                stars_today = int(match.group(1).replace(",", ""))

        return TrendingRepo(
            full_name=full_name,
            description=description,
            language=language,
            stars_today=stars_today,
            total_stars=total_stars,
            forks=forks,
            url=f"https://github.com/{full_name}",
            period=period,
        )

    @staticmethod
    def _parse_number(text: str) -> int:
        """解析数字字符串，支持 '1,234' 和 '1.2k' 格式."""
        text = text.strip().replace(",", "")
        if not text:
            return 0
        # 处理 k/m 后缀
        if text.lower().endswith("k"):
            return int(float(text[:-1]) * 1000)
        if text.lower().endswith("m"):
            return int(float(text[:-1]) * 1000000)
        try:
            return int(text)
        except ValueError:
            return 0

    def close(self) -> None:
        if self._client and not self._client.is_closed:
            self._client.close()

    def __enter__(self) -> TrendingCrawler:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

"""GitHub API 数据采集器.

通过 GitHub REST API 获取仓库的详细信息，
包括 topics、创建时间、issue 数量等 Trending 页面没有的数据。
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

import httpx

from src.config import settings
from src.models import RepoDetail

logger = logging.getLogger(__name__)


class GitHubAPIClient:
    """GitHub REST API 客户端."""

    def __init__(self) -> None:
        self._client: httpx.Client | None = None
        self._rate_limit_remaining: int = 60
        self._rate_limit_reset: float = 0

    @property
    def client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                base_url=settings.github_api_base,
                timeout=settings.request_timeout,
                headers=settings.github_headers,
                follow_redirects=True,
            )
        return self._client

    def get_repo_detail(self, full_name: str) -> RepoDetail | None:
        """获取仓库详细信息.

        Args:
            full_name: 仓库全名，格式 owner/repo

        Returns:
            RepoDetail 或 None（失败时）
        """
        self._check_rate_limit()

        for attempt in range(settings.request_retries):
            try:
                resp = self.client.get(f"/repos/{full_name}")
                self._update_rate_limit(resp)

                if resp.status_code == 404:
                    logger.warning("仓库不存在: %s", full_name)
                    return None
                if resp.status_code == 403:
                    self._handle_rate_limit(resp)
                    continue

                resp.raise_for_status()
                data = resp.json()
                return self._parse_repo(data)

            except httpx.HTTPError as e:
                logger.warning("获取仓库详情失败 (%s), 第 %d 次: %s", full_name, attempt + 1, e)
                if attempt == settings.request_retries - 1:
                    return None

        return None

    def get_repo_details_batch(self, full_names: list[str]) -> dict[str, RepoDetail]:
        """批量获取仓库详情.

        Args:
            full_names: 仓库全名列表

        Returns:
            字典 {full_name: RepoDetail}
        """
        results: dict[str, RepoDetail] = {}
        total = len(full_names)

        for i, name in enumerate(full_names, 1):
            logger.info("获取仓库详情 [%d/%d]: %s", i, total, name)
            detail = self.get_repo_detail(name)
            if detail:
                results[name] = detail

        logger.info("成功获取 %d/%d 个仓库的详细信息", len(results), total)
        return results

    def _parse_repo(self, data: dict) -> RepoDetail:
        """将 API 响应解析为 RepoDetail."""
        license_info = data.get("license") or {}

        return RepoDetail(
            full_name=data.get("full_name", ""),
            description=data.get("description") or "",
            language=data.get("language") or "",
            topics=data.get("topics", []),
            total_stars=data.get("stargazers_count", 0),
            forks_count=data.get("forks_count", 0),
            open_issues_count=data.get("open_issues_count", 0),
            watchers_count=data.get("subscribers_count", 0),
            created_at=self._parse_datetime(data.get("created_at")),
            updated_at=self._parse_datetime(data.get("updated_at")),
            pushed_at=self._parse_datetime(data.get("pushed_at")),
            homepage=data.get("homepage") or "",
            license_name=license_info.get("spdx_id") or "",
            is_fork=data.get("fork", False),
            is_archived=data.get("archived", False),
            default_branch=data.get("default_branch", "main"),
        )

    @staticmethod
    def _parse_datetime(dt_str: str | None) -> datetime | None:
        if not dt_str:
            return None
        try:
            return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    def _update_rate_limit(self, resp: httpx.Response) -> None:
        """从响应头更新速率限制信息."""
        remaining = resp.headers.get("X-RateLimit-Remaining")
        reset_at = resp.headers.get("X-RateLimit-Reset")
        if remaining is not None:
            self._rate_limit_remaining = int(remaining)
        if reset_at is not None:
            self._rate_limit_reset = float(reset_at)

        if self._rate_limit_remaining <= 10:
            logger.warning("GitHub API 速率限制剩余: %d", self._rate_limit_remaining)

    def _check_rate_limit(self) -> None:
        """如果速率限制即将耗尽，等待重置."""
        if self._rate_limit_remaining <= 5:
            wait_time = max(0, self._rate_limit_reset - time.time()) + 1
            if wait_time > 0:
                logger.warning("速率限制即将耗尽，等待 %.0f 秒...", wait_time)
                time.sleep(min(wait_time, 300))  # 最多等 5 分钟

    def _handle_rate_limit(self, resp: httpx.Response) -> None:
        """处理 403 速率限制响应."""
        self._update_rate_limit(resp)
        wait_time = max(0, self._rate_limit_reset - time.time()) + 1
        logger.warning("触发速率限制 (403)，等待 %.0f 秒...", wait_time)
        time.sleep(min(wait_time, 300))

    def close(self) -> None:
        if self._client and not self._client.is_closed:
            self._client.close()

    def __enter__(self) -> GitHubAPIClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

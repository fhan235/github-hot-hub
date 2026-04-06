"""Markdown 报告生成器.

将评分结果生成可读的 Markdown 报告。
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from src.config import settings
from src.models import ScoredRepo

logger = logging.getLogger(__name__)


class MarkdownReporter:
    """Markdown 格式的每日报告生成器."""

    def generate(self, repos: list[ScoredRepo], top_n: int | None = None) -> str:
        """生成 Markdown 报告.

        Args:
            repos: 按分数排序的仓库列表
            top_n: 展示的项目数量，默认使用配置值

        Returns:
            Markdown 格式的报告字符串
        """
        top_n = top_n or settings.report_top_n
        today = datetime.now().strftime("%Y-%m-%d")
        display_repos = repos[:top_n]

        lines: list[str] = []
        lines.append(f"# 🔥 GitHub 热点速报 | {today}")
        lines.append("")
        lines.append(f"> 本报告自动生成，共发现 **{len(repos)}** 个热门项目，展示 Top {len(display_repos)}")
        lines.append("")
        lines.append("---")
        lines.append("")

        for rank, repo in enumerate(display_repos, 1):
            lines.extend(self._format_repo(rank, repo))
            lines.append("")

        # 统计摘要
        lines.append("---")
        lines.append("")
        lines.append("## 📊 统计摘要")
        lines.append("")
        lines.extend(self._format_summary(repos))
        lines.append("")
        lines.append("---")
        lines.append(f"*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")

        return "\n".join(lines)

    def save(self, repos: list[ScoredRepo], output_dir: Path | None = None) -> Path:
        """生成并保存报告到文件.

        Returns:
            报告文件路径
        """
        output_dir = output_dir or settings.reports_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        now_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = output_dir / f"hot-report-{now_str}.md"

        content = self.generate(repos)
        path.write_text(content, encoding="utf-8")
        logger.info("报告已保存: %s", path)
        return path

    def _format_repo(self, rank: int, repo: ScoredRepo) -> list[str]:
        """格式化单个仓库."""
        # 排名图标
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"**{rank}.**")

        # 爆发标签
        burst_labels = " ".join(
            f"{bt.emoji} {bt.label}" for bt in repo.burst_types
        ) if repo.burst_types else ""

        lines = [
            f"### {medal} [{repo.full_name}]({repo.url})",
            "",
            f"⭐ **+{repo.stars_today:,} today** (总计 {repo.total_stars:,})"
            f" | 🏷️ {repo.category} | {repo.language or 'N/A'}"
            f" | 🔥 评分: **{repo.score:.1f}**",
            "",
        ]

        if burst_labels:
            lines.append(f"标签: {burst_labels}")
            lines.append("")

        if repo.description:
            lines.append(f"> {repo.description}")
            lines.append("")

        # LLM 智能分析
        if repo.llm_analysis:
            lines.append("#### 🤖 AI 分析")
            lines.append("")
            lines.append(repo.llm_analysis)
            lines.append("")

        # 评分细节 (折叠)
        lines.append("<details>")
        lines.append("<summary>📈 评分详情</summary>")
        lines.append("")
        lines.append("| 维度 | 分数 |")
        lines.append("|------|------|")
        dim_labels = {
            "star_speed": "⭐ Star 增速",
            "acceleration": "🚀 增速加速度",
            "relative_growth": "📊 相对增长率",
            "freshness": "🆕 新鲜度",
            "community": "👥 社区响应",
        }
        for key, label in dim_labels.items():
            val = repo.score_breakdown.get(key, 0)
            bar = self._score_bar(val)
            lines.append(f"| {label} | {val:.1f} {bar} |")
        lines.append("")
        if repo.topics:
            lines.append(f"Topics: {', '.join(f'`{t}`' for t in repo.topics[:10])}")
            lines.append("")
        lines.append("</details>")

        return lines

    def _format_summary(self, repos: list[ScoredRepo]) -> list[str]:
        """生成统计摘要."""
        lines = []

        # 按分类统计
        category_counts: dict[str, int] = {}
        for r in repos:
            category_counts[r.category] = category_counts.get(r.category, 0) + 1

        lines.append("**按领域分布：**")
        lines.append("")
        for cat, count in sorted(category_counts.items(), key=lambda x: -x[1]):
            lines.append(f"- {cat}: {count} 个项目")

        lines.append("")

        # 按语言统计
        lang_counts: dict[str, int] = {}
        for r in repos:
            lang = r.language or "Unknown"
            lang_counts[lang] = lang_counts.get(lang, 0) + 1

        lines.append("**按语言分布：**")
        lines.append("")
        for lang, count in sorted(lang_counts.items(), key=lambda x: -x[1])[:10]:
            lines.append(f"- {lang}: {count} 个")

        return lines

    @staticmethod
    def _score_bar(score: float, width: int = 10) -> str:
        """生成简易进度条."""
        filled = round(score / 100 * width)
        return "█" * filled + "░" * (width - filled)

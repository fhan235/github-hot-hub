"""GitHub Hot Hub — 主入口.

完整流程:
1. 爬取 GitHub Trending 页面
2. 通过 GitHub API 补充详细信息
3. 加载历史数据，计算爆发度评分
4. 保存今日快照
5. 生成 Markdown 报告
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from src.config import settings
from src.crawlers.github_api import GitHubAPIClient
from src.crawlers.trending import TrendingCrawler
from src.reporters.markdown_reporter import MarkdownReporter
from src.scorers.hot_scorer import HotScorer
from src.storage.snapshot_store import SnapshotStore

console = Console()


def setup_logging(verbose: bool = False) -> None:
    """配置日志."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="%H:%M:%S",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


def run(top_n: int | None = None, skip_api: bool = False) -> None:
    """执行完整的采集-评分-报告流程."""
    top_n = top_n or settings.report_top_n

    console.rule("[bold blue]🔥 GitHub Hot Hub[/bold blue]")
    console.print(f"[dim]开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]")
    console.print()

    # 1. 爬取 Trending
    console.print("[bold]📡 Step 1: 爬取 GitHub Trending...[/bold]")
    with TrendingCrawler() as crawler:
        trending_repos = crawler.crawl_all()

    if not trending_repos:
        console.print("[red]❌ 未获取到任何 Trending 项目，退出[/red]")
        sys.exit(1)

    console.print(f"  ✅ 获取到 [green]{len(trending_repos)}[/green] 个 Trending 项目")
    console.print()

    # 2. 通过 API 补充详情
    details = {}
    if not skip_api:
        console.print("[bold]🔍 Step 2: 获取仓库详细信息...[/bold]")
        if not settings.github_token:
            console.print("  [yellow]⚠️  未配置 GITHUB_TOKEN，API 请求将受限 (60次/小时)[/yellow]")
            console.print("  [dim]提示: 在 .env 中配置 GHH_GITHUB_TOKEN=your_token[/dim]")

        names = [r.full_name for r in trending_repos]
        with GitHubAPIClient() as api:
            details = api.get_repo_details_batch(names)

        console.print(f"  ✅ 获取到 [green]{len(details)}[/green] 个仓库的详细信息")
    else:
        console.print("[bold]⏭️  Step 2: 跳过 API 获取 (--skip-api)[/bold]")
    console.print()

    # 3. 加载历史数据 & 评分
    console.print("[bold]📊 Step 3: 计算爆发度评分...[/bold]")
    store = SnapshotStore()
    yesterday_stars = store.get_yesterday_stars()

    scorer = HotScorer(history=yesterday_stars)
    scored_repos = scorer.score_batch(trending_repos, details)
    console.print(f"  ✅ 评分完成，[green]{len(scored_repos)}[/green] 个有效项目")
    console.print()

    # 4. 保存今日快照
    console.print("[bold]💾 Step 4: 保存今日数据快照...[/bold]")
    today_data = {}
    for repo in scored_repos:
        today_data[repo.full_name] = repo.total_stars
    # 也保存从 trending 来的未被过滤掉的数据
    for repo in trending_repos:
        if repo.full_name not in today_data:
            if repo.full_name in details:
                today_data[repo.full_name] = details[repo.full_name].total_stars
            else:
                today_data[repo.full_name] = repo.total_stars
    store.save_today(today_data)
    console.print(f"  ✅ 已保存 {len(today_data)} 个仓库的 star 数据")
    console.print()

    # 5. 生成报告
    console.print("[bold]📝 Step 5: 生成报告...[/bold]")
    reporter = MarkdownReporter()
    report_path = reporter.save(scored_repos)
    console.print(f"  ✅ 报告已保存: [link=file://{report_path}]{report_path}[/link]")
    console.print()

    # 6. 清理旧快照
    store.cleanup_old_snapshots(keep_days=30)

    # 7. 在终端展示 Top N
    _print_top_repos(scored_repos[:top_n])

    console.rule("[bold green]✅ 完成[/bold green]")


def _print_top_repos(repos: list) -> None:
    """在终端用 rich 表格展示 Top 项目."""
    if not repos:
        return

    table = Table(title="🔥 Today's Hot Repos", show_lines=True)
    table.add_column("#", style="bold", width=3)
    table.add_column("项目", style="cyan", max_width=35)
    table.add_column("⭐ Today", justify="right", style="yellow")
    table.add_column("总 Star", justify="right")
    table.add_column("评分", justify="right", style="bold red")
    table.add_column("分类", style="green")
    table.add_column("标签", max_width=20)

    for i, repo in enumerate(repos, 1):
        burst = " ".join(f"{bt.emoji}" for bt in repo.burst_types)
        table.add_row(
            str(i),
            repo.full_name,
            f"+{repo.stars_today:,}",
            f"{repo.total_stars:,}",
            f"{repo.score:.1f}",
            repo.category,
            burst,
        )

    console.print(table)
    console.print()


def main() -> None:
    """CLI 入口."""
    parser = argparse.ArgumentParser(
        description="🔥 GitHub Hot Hub - 发现正在爆发的 GitHub 项目",
    )
    parser.add_argument(
        "-n", "--top",
        type=int,
        default=None,
        help=f"展示的项目数量 (默认 {settings.report_top_n})",
    )
    parser.add_argument(
        "--skip-api",
        action="store_true",
        help="跳过 GitHub API 获取，仅使用 Trending 页面数据",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="显示详细日志",
    )

    args = parser.parse_args()
    setup_logging(verbose=args.verbose)

    try:
        run(top_n=args.top, skip_api=args.skip_api)
    except KeyboardInterrupt:
        console.print("\n[yellow]用户中断[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"\n[red]❌ 错误: {e}[/red]")
        logging.exception("执行失败")
        sys.exit(1)


if __name__ == "__main__":
    main()

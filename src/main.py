"""GitHub Hot Hub — 主入口.

完整流程:
1. 爬取 GitHub Trending 页面
2. 通过 GitHub API 补充详细信息
3. 加载历史数据，计算爆发度评分
4. LLM 智能分析（Top N）
5. 保存今日快照
6. 生成 Markdown 报告
7. 推送到企业微信（可选）
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
from src.analyzers.llm_analyzer import LLMAnalyzer
from src.notifiers.wecom import WeComNotifier
from src.reporters.markdown_reporter import MarkdownReporter
from src.scorers.hot_scorer import HotScorer
from src.storage.snapshot_store import SnapshotStore

logger = logging.getLogger(__name__)
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


def run(
    top_n: int | None = None,
    skip_api: bool = False,
    notify: bool = False,
    skip_llm: bool = False,
) -> None:
    """执行完整的采集-评分-分析-报告流程."""
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

    # 4. LLM 智能分析
    if not skip_llm:
        console.print("[bold]🤖 Step 4: AI 智能分析...[/bold]")
        analyzer = LLMAnalyzer()
        if analyzer.available:
            # 只分析 Top N 项目（节约 API 调用）
            llm_top_n = min(top_n, 30)
            analyses = analyzer.analyze_batch(scored_repos, top_n=llm_top_n)
            # 写入到 ScoredRepo 对象
            for repo in scored_repos:
                if repo.full_name in analyses:
                    repo.llm_analysis = analyses[repo.full_name]
            console.print(f"  ✅ AI 分析完成，{len(analyses)} 个项目已生成分析")
        else:
            console.print("  [yellow]⚠️  LLM 不可用（未配置 GHH_LLM_API_KEY 或已禁用），跳过[/yellow]")
    else:
        console.print("[bold]⏭️  Step 4: 跳过 LLM 分析 (--skip-llm)[/bold]")
    console.print()

    # 5. 保存今日快照
    console.print("[bold]💾 Step 5: 保存今日数据快照...[/bold]")
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

    # 6. 生成报告
    console.print("[bold]📝 Step 6: 生成报告...[/bold]")
    reporter = MarkdownReporter()
    report_path = reporter.save(scored_repos)
    console.print(f"  ✅ 报告已保存: [link=file://{report_path}]{report_path}[/link]")
    console.print()

    # 7. 企业微信推送（带去重）
    if notify:
        console.print("[bold]📮 Step 7: 推送到企业微信...[/bold]")
        notifier = WeComNotifier()
        if notifier.webhook_url:
            # 去重：过滤冷却期内已推送的项目
            push_repos = scored_repos
            if settings.dedup_enabled:
                recently_notified = store.get_recently_notified(
                    cooldown_days=settings.dedup_cooldown_days
                )
                if recently_notified:
                    original_count = len(push_repos)
                    push_repos = _filter_dedup(push_repos, recently_notified)
                    skipped = original_count - len(push_repos)
                    if skipped > 0:
                        console.print(
                            f"  🔄 去重过滤: 跳过 [yellow]{skipped}[/yellow] 个"
                            f"冷却期内项目（{settings.dedup_cooldown_days} 天）"
                        )

            if not push_repos:
                console.print("  [yellow]⚠️ 去重后无新项目可推送，跳过[/yellow]")
            else:
                # 企微消息有长度限制，推送 Top 5 并展示 AI 分析
                push_top_n = min(top_n, 5)
                success = notifier.notify(push_repos, top_n=push_top_n)
                if success:
                    # 记录本次推送的项目
                    notified_names = [r.full_name for r in push_repos[:push_top_n]]
                    notified_scores = {r.full_name: r.score for r in push_repos[:push_top_n]}
                    store.update_notified(notified_names, notified_scores)
                    console.print("  ✅ 企业微信推送成功")
                else:
                    console.print("  [red]❌ 企业微信推送失败[/red]")
        else:
            console.print("  [yellow]⚠️  未配置 GHH_WECOM_WEBHOOK_URL，跳过推送[/yellow]")
        console.print()

    # 8. 清理旧数据
    store.cleanup_old_snapshots(keep_days=30)
    store.cleanup_old_notified(keep_days=30)

    # 9. 在终端展示 Top N
    _print_top_repos(scored_repos[:top_n])

    console.rule("[bold green]✅ 完成[/bold green]")


def _filter_dedup(
    repos: list,
    recently_notified: dict[str, float],
) -> list:
    """过滤冷却期内已推送的项目.

    如果项目分数比上次推送时大幅上升（超过 dedup_score_boost），
    仍然允许再次推送。

    Args:
        repos: 评分后的仓库列表
        recently_notified: {full_name: last_score}

    Returns:
        过滤后的仓库列表
    """
    result = []
    boost = settings.dedup_score_boost

    for repo in repos:
        last_score = recently_notified.get(repo.full_name)
        if last_score is None:
            # 冷却期内未推送过，保留
            result.append(repo)
        elif repo.score - last_score >= boost:
            # 分数大幅上升，允许再次推送
            logger.info(
                "去重例外: %s 分数 %.1f → %.1f (+%.1f ≥ %.1f)",
                repo.full_name, last_score, repo.score,
                repo.score - last_score, boost,
            )
            result.append(repo)
        else:
            logger.debug(
                "去重跳过: %s (上次 %.1f, 本次 %.1f, 冷却中)",
                repo.full_name, last_score, repo.score,
            )

    return result


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
    table.add_column("AI", max_width=3)

    for i, repo in enumerate(repos, 1):
        burst = " ".join(f"{bt.emoji}" for bt in repo.burst_types)
        ai_mark = "✅" if repo.llm_analysis else ""
        table.add_row(
            str(i),
            repo.full_name,
            f"+{repo.stars_today:,}",
            f"{repo.total_stars:,}",
            f"{repo.score:.1f}",
            repo.category,
            burst,
            ai_mark,
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
        "--skip-llm",
        action="store_true",
        help="跳过 LLM 智能分析",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="显示详细日志",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="推送结果到企业微信",
    )

    args = parser.parse_args()
    setup_logging(verbose=args.verbose)

    try:
        run(top_n=args.top, skip_api=args.skip_api, notify=args.notify, skip_llm=args.skip_llm)
    except KeyboardInterrupt:
        console.print("\n[yellow]用户中断[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"\n[red]❌ 错误: {e}[/red]")
        logging.exception("执行失败")
        sys.exit(1)


if __name__ == "__main__":
    main()

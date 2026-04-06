# 🔥 GitHub Hot Hub

> 发现 GitHub 上正在爆发的热门项目，打破技术信息差。

## 功能

- **爬取 GitHub Trending** — 自动采集多语言、多周期的 Trending 榜单
- **GitHub API 补充** — 获取项目详细信息（topics、创建时间、issue 等）
- **火爆度评分** — 多维度评分算法，识别"正在爆发"的项目
- **智能过滤** — 排除 awesome-list、面试题等非技术项目
- **每日报告** — 生成 Markdown 格式的热点速报
- **历史追踪** — 记录每日快照，计算 star 增速加速度

## 评分体系

| 维度 | 权重 | 说明 |
|------|------|------|
| ⭐ Star 日增速 | 40% | 短时间内的 star 新增数量 |
| 🚀 增速加速度 | 20% | 今日增量 vs 昨日增量 |
| 📊 相对增长率 | 20% | 日增量 / 总 star 数 |
| 🆕 新鲜度 | 10% | 项目越新分数越高 |
| 👥 社区响应 | 10% | fork + issue 活跃度 |

### 爆发类型标签

- 🔥 **新星爆发** — 项目创建 < 7 天
- 📈 **加速上升** — 增速加速度为正且显著
- 🔄 **二次翻红** — 老项目突然爆发
- 🏆 **持续霸榜** — 连续高 star 增速

## 快速开始

### 1. 安装依赖

```bash
cd github-hot-hub
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. 配置

```bash
cp .env.example .env
# 编辑 .env，填入你的 GitHub Token
```

获取 GitHub Token: [Settings → Tokens](https://github.com/settings/tokens) → Generate new token (classic) → 勾选 `public_repo`

### 3. 运行

```bash
# 完整运行（Trending + API）
python -m src.main

# 仅使用 Trending 数据（不需要 Token，更快）
python -m src.main --skip-api

# 显示 Top 5
python -m src.main -n 5

# 详细日志
python -m src.main -v
```

## 项目结构

```
github-hot-hub/
├── src/
│   ├── crawlers/
│   │   ├── trending.py       # GitHub Trending 页面爬虫
│   │   └── github_api.py     # GitHub REST API 客户端
│   ├── scorers/
│   │   └── hot_scorer.py     # 火爆度评分算法
│   ├── reporters/
│   │   └── markdown_reporter.py  # Markdown 报告生成
│   ├── notifiers/            # (预留) 企业微信推送等
│   ├── storage/
│   │   └── snapshot_store.py # 本地数据快照存储
│   ├── config.py             # 项目配置
│   ├── models.py             # 数据模型
│   └── main.py               # 主入口
├── data/                     # 每日快照数据
├── reports/                  # 生成的报告
├── tests/                    # 测试
├── pyproject.toml
├── .env.example
└── README.md
```

## 后续规划

- [ ] 企业微信推送
- [ ] LLM 分析"为什么火"
- [ ] Web Dashboard
- [ ] 定时任务自动运行

## License

MIT

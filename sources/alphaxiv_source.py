import argparse
import json
import os

from base_source import BaseSource
from config import LLMConfig, CommonConfig
from email_utils.huggingface_template import get_paper_block_html
from email_utils.base_template import get_stars
from fetchers.alphaxiv_fetcher import fetch_explore


class AlphaXivSource(BaseSource):
    name = "alphaxiv"
    default_title = "alphaXiv Hot Papers"

    def __init__(self, source_args: dict, llm_config: LLMConfig, common_config: CommonConfig):
        super().__init__(source_args, llm_config, common_config)
        self.sort = source_args.get("sort", "Hot")
        self.platform_source = source_args.get("platform_source", "GitHub")
        self.interval = source_args.get("interval", "7 Days")
        self.max_papers = source_args.get("max_papers", 30)
        self.week_id = ""

        if self.interval.strip().lower() == "7 days":
            iso = self.run_local_datetime.isocalendar()
            self.week_id = f"{iso.year}-W{iso.week:02d}"
            self._reconfigure_storage([self.name, "weekly"], self.week_id)

        cache_key = f"{self.sort.lower()}_{self.platform_source}_{self.interval}_{self.max_papers}"
        cached = self._load_fetch_cache(cache_key)
        if cached is not None:
            self.papers = cached
        else:
            self.papers = fetch_explore(
                sort=self.sort,
                max_results=self.max_papers * 2,
                source=self.platform_source,
                interval=self.interval,
            )
            if self.papers:
                self._save_fetch_cache(cache_key, self.papers)

    @staticmethod
    def add_arguments(parser: argparse.ArgumentParser):
        parser.add_argument(
            "--alphaxiv_sort",
            type=str,
            choices=["Hot", "Likes"],
            default=os.getenv("ALPHAXIV_SORT", "Hot"),
            help="[alphaXiv] Which ranking tab to fetch",
        )
        parser.add_argument(
            "--alphaxiv_source",
            type=str,
            default=os.getenv("ALPHAXIV_SOURCE", "GitHub"),
            help="[alphaXiv] Platform source filter, e.g. GitHub",
        )
        parser.add_argument(
            "--alphaxiv_interval",
            type=str,
            default=os.getenv("ALPHAXIV_INTERVAL", "7 Days"),
            help="[alphaXiv] Interval filter, e.g. 7 Days",
        )
        parser.add_argument(
            "--alphaxiv_max_papers",
            type=int,
            default=int(os.getenv("ALPHAXIV_MAX_PAPERS", "30")),
            help="[alphaXiv] Max hot papers to recommend",
        )

    @staticmethod
    def extract_args(args) -> dict:
        return {
            "sort": args.alphaxiv_sort,
            "platform_source": args.alphaxiv_source,
            "interval": args.alphaxiv_interval,
            "max_papers": args.alphaxiv_max_papers,
        }

    def get_max_items(self) -> int:
        return self.max_papers

    def delta_snapshot_mode(self) -> bool:
        return bool(self.week_id)

    def fetch_items(self) -> list[dict]:
        print(f"[{self.name}] {len(self.papers)} papers fetched from alphaXiv ({self.sort})")
        return self.papers

    def get_item_cache_id(self, item: dict) -> str:
        return "alphaxiv_" + item.get("alpha_id", "unknown").replace("/", "_").replace(".", "_")

    def build_eval_prompt(self, item: dict) -> str:
        authors = ", ".join(item.get("authors", [])[:5])
        tags = ", ".join(item.get("tags", [])[:6])
        prompt = """
            你是一个有帮助的前沿 AI 研究助手，帮助我构建热门论文追踪系统。
            以下是我感兴趣的研究方向描述：
            {}
        """.format(self.description)
        prompt += """
            以下是一篇来自 alphaXiv 热榜的论文：
            标题: {}
            日期: {}
            作者: {}
            平台摘要: {}
            标签: {}
            热度数据: likes={} | resources={} | views={}
            榜单来源: {} | 时间窗口: {}
        """.format(
            item["title"],
            item.get("publish_date", ""),
            authors,
            item.get("summary", ""),
            tags or "无标签",
            item.get("likes", 0),
            item.get("resource_count", 0),
            item.get("view_count", 0),
            item.get("platform_source", self.platform_source),
            item.get("interval", self.interval),
        )
        prompt += """
            这是一个平台已排序的热门论文候选。请你在平台热度基础上，再按我的研究方向重写总结并打分。
        """
        prompt += self._method_first_summary_instruction("热门论文")
        return prompt

    def parse_eval_response(self, item: dict, response: str) -> dict:
        response = response.strip("```").strip("json")
        data = json.loads(response)
        return {
            "title": item["title"],
            "alpha_id": item.get("alpha_id", ""),
            "summary": self._ensure_str(data["summary"]),
            "score": float(data["relevance"]),
            "url": item.get("paper_url", ""),
            "blog_url": item.get("blog_url", ""),
            "resources_url": item.get("resources_url", ""),
            "repo_url": item.get("repo_url", ""),
            "publish_date": item.get("publish_date", ""),
            "authors": ", ".join(item.get("authors", [])),
            "tags": item.get("tags", []),
            "likes": item.get("likes", 0),
            "resource_count": item.get("resource_count", 0),
            "view_count": item.get("view_count", 0),
            "sort": item.get("sort", self.sort),
            "platform_source": item.get("platform_source", self.platform_source),
            "interval": item.get("interval", self.interval),
            "_source_rank_kind": f"alphaXiv-{self.sort}",
        }

    def render_item_html(self, item: dict) -> str:
        rate = get_stars(item.get("score", 0))
        return get_paper_block_html(
            item["title"],
            rate,
            item.get("alpha_id", ""),
            item["summary"],
            item.get("url", ""),
            item.get("likes", 0),
        )

    def get_theme_color(self) -> str:
        return "155,52,91"

    def get_section_header(self) -> str:
        return (
            f'<div class="section-title" style="border-bottom-color: #9d345b;">'
            f'🔥 alphaXiv {self.sort} Papers ({self.platform_source}, {self.interval})</div>'
        )

    def build_summary_overview(self, recommendations: list[dict]) -> str:
        lines = []
        for i, item in enumerate(recommendations):
            lines.append(
                f"{i + 1}. {item['title']} "
                f"(likes={item.get('likes', 0)}, resources={item.get('resource_count', 0)}, views={item.get('view_count', 0)}) "
                f"- Score: {item.get('score', 0)} - {item['summary']}"
            )
        return "\n".join(lines)

    def get_summary_prompt_template(self) -> str:
        return """
            请直接输出一段 HTML 片段，严格遵循以下结构，不要包含 JSON、Markdown 或多余说明：
            <div class="summary-wrapper">
              <div class="summary-section">
                <h2>平台热榜总览</h2>
                <p>总结今天 alphaXiv 热榜里最值得看的论文，以及它们为什么会热。</p>
              </div>
              <div class="summary-section">
                <h2>重点热门论文</h2>
                <ol class="summary-list">
                  <li class="summary-item">
                    <div class="summary-item__header"><span class="summary-item__title">论文标题</span><span class="summary-pill">热榜</span></div>
                    <p><strong>一句话结论：</strong>...</p>
                    <p><strong>问题与方法：</strong>...</p>
                    <p><strong>Pipeline / 训练配方：</strong>...</p>
                    <p><strong>为什么值得看：</strong>...</p>
                  </li>
                </ol>
              </div>
              <div class="summary-section">
                <h2>补充观察</h2>
                <p>指出哪些热门论文与你的研究方向强相关，哪些虽然弱相关但值得跟踪。</p>
              </div>
            </div>

            用中文撰写内容。重点推荐部分建议返回 3-5 篇热门论文。
            不要只说“这篇论文很火”，请尽量写清它解决的问题、方法核心和 pipeline。
        """

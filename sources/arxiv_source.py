import argparse
import json

from base_source import BaseSource
from config import LLMConfig, CommonConfig
from fetchers.arxiv_fetcher import fetch_papers_for_categories
from email_utils.base_template import get_stars
from email_utils.arxiv_template import get_paper_block_html


class ArxivSource(BaseSource):
    name = "arxiv"
    default_title = "Daily arXiv"

    def __init__(self, source_args: dict, llm_config: LLMConfig, common_config: CommonConfig):
        super().__init__(source_args, llm_config, common_config)
        self.categories = source_args.get("categories", ["cs.AI"])
        self.max_entries = source_args.get("max_entries", 100)
        self.max_papers = source_args.get("max_papers", 60)

        cache_key = f"papers_{'_'.join(sorted(self.categories))}_{self.max_entries}"
        cached = self._load_fetch_cache(cache_key)
        if cached is not None:
            self.papers_by_category = cached
        else:
            self.papers_by_category = fetch_papers_for_categories(
                self.categories,
                max_entries=self.max_entries,
            )
            if self.papers_by_category:
                self._save_fetch_cache(cache_key, self.papers_by_category)

    @staticmethod
    def add_arguments(parser: argparse.ArgumentParser):
        parser.add_argument(
            "--arxiv_categories", nargs="+", default=["cs.AI"],
            help="[arXiv] Categories to fetch (e.g. cs.AI cs.CL cs.CV)",
        )
        parser.add_argument(
            "--arxiv_max_entries", type=int, default=100,
            help="[arXiv] Max entries to fetch per category from arXiv listing",
        )
        parser.add_argument(
            "--arxiv_max_papers", type=int, default=60,
            help="[arXiv] Max papers to recommend after scoring",
        )

    @staticmethod
    def extract_args(args) -> dict:
        return {
            "categories": args.arxiv_categories,
            "max_entries": args.arxiv_max_entries,
            "max_papers": args.arxiv_max_papers,
        }

    def get_max_items(self) -> int:
        return self.max_papers

    def fetch_items(self) -> list[dict]:
        seen: dict[str, dict] = {}
        for _cat, papers in self.papers_by_category.items():
            for paper in papers:
                aid = paper.get("arxiv_id", "")
                if aid and aid not in seen:
                    seen[aid] = paper
        print(f"[{self.name}] {len(seen)} unique papers after dedup across categories")
        return list(seen.values())

    def get_item_cache_id(self, item: dict) -> str:
        return "paper_" + item.get("arxiv_id", "unknown").replace("/", "_").replace(".", "_")

    def build_eval_prompt(self, item: dict) -> str:
        prompt = """
            你是一个有帮助的学术研究助手，可以帮助我构建每日论文推荐系统。
            以下是我最近研究领域的描述：
            {}
        """.format(self.description)
        prompt += """
            以下是我从 arXiv 爬取的论文，我为你提供了标题和摘要：
            标题: {}
            摘要: {}
        """.format(item["title"], item["abstract"])
        prompt += self._method_first_summary_instruction("论文")
        return prompt

    def parse_eval_response(self, item: dict, response: str) -> dict:
        response = response.strip("```").strip("json")
        data = json.loads(response)
        return {
            "title": item["title"],
            "arxiv_id": item.get("arxiv_id", ""),
            "abstract": item.get("abstract", ""),
            "summary": self._ensure_str(data["summary"]),
            "score": float(data["relevance"]),
            "pdf_url": item.get("pdf_url", ""),
            "url": item.get("abstract_url", "") or item.get("pdf_url", ""),
        }

    def render_item_html(self, item: dict) -> str:
        rate = get_stars(item.get("score", 0))
        return get_paper_block_html(
            item["title"],
            rate,
            item.get("arxiv_id", ""),
            item["summary"],
            item.get("pdf_url", ""),
        )

    def get_theme_color(self) -> str:
        return "179,27,27"

    def get_section_header(self) -> str:
        cats = ", ".join(self.categories)
        return f'<div class="section-title" style="border-bottom-color: #b31b1b;">📄 arXiv Papers ({cats})</div>'

    def build_summary_overview(self, recommendations: list[dict]) -> str:
        lines = []
        for i, r in enumerate(recommendations):
            lines.append(
                f"{i + 1}. {r['title']} (arXiv: {r.get('arxiv_id', '')}) "
                f"- Score: {r.get('score', 0)} - {r['summary']}"
            )
        return "\n".join(lines)

    def get_summary_prompt_template(self) -> str:
        return """
            请直接输出一段 HTML 片段，严格遵循以下结构，不要包含 JSON、Markdown 或多余说明：
            <div class="summary-wrapper">
              <div class="summary-section">
                <h2>今日arXiv研究趋势</h2>
                <p>分析今天论文体现的研究趋势，解释其与我研究兴趣的联系...</p>
              </div>
              <div class="summary-section">
                <h2>重点推荐</h2>
                <ol class="summary-list">
                  <li class="summary-item">
                    <div class="summary-item__header"><span class="summary-item__title">论文标题</span><span class="summary-pill">相关性</span></div>
                    <p><strong>一句话结论：</strong>...</p>
                    <p><strong>问题与方法：</strong>...</p>
                    <p><strong>Pipeline / 训练配方：</strong>...</p>
                    <p><strong>为什么值得看：</strong>...</p>
                  </li>
                </ol>
              </div>
              <div class="summary-section">
                <h2>补充观察</h2>
                <p>值得持续关注的方向或潜在研究机会...</p>
              </div>
            </div>

            用中文撰写内容，重点推荐部分建议返回 3-5 篇论文。
            不要只写趋势口号，请尽量说清每篇论文解决的问题、方法核心和 pipeline / training recipe。
        """

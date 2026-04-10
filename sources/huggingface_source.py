import argparse
import json
import time
from datetime import datetime

from base_source import BaseSource
from config import LLMConfig, CommonConfig
from fetchers.huggingface_fetcher import get_daily_papers, get_trending_models_api, get_weekly_papers
from email_utils.base_template import get_stars, framework, get_empty_html
from email_utils.huggingface_template import get_paper_block_html, get_model_block_html
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
import os


class HuggingFaceSource(BaseSource):
    name = "huggingface"
    default_title = "Daily HuggingFace"

    def __init__(self, source_args: dict, llm_config: LLMConfig, common_config: CommonConfig):
        self.period = source_args.get("period", "daily")
        self.week_id = source_args.get("week_id", "")
        super().__init__(source_args, llm_config, common_config)
        self.content_types = [ct.lower() for ct in source_args.get("content_type", ["papers", "models"])]
        self.max_papers = source_args.get("max_papers", 30)
        self.max_models = source_args.get("max_models", 15)

        if self.period == "weekly":
            if not self.week_id:
                iso = self.run_local_datetime.isocalendar()
                self.week_id = f"{iso.year}-W{iso.week:02d}"
            self._reconfigure_storage([self.name, "weekly"], self.week_id)

        self.papers = []
        self.models = []
        if "papers" in self.content_types:
            cache_key = "daily_papers" if self.period == "daily" else f"weekly_papers_{self.week_id}"
            cached = self._load_fetch_cache(cache_key)
            if cached is not None:
                self.papers = cached
            else:
                if self.period == "weekly":
                    self.papers = get_weekly_papers(self.week_id, self.max_papers * 2)
                else:
                    self.papers = get_daily_papers(self.max_papers * 2)
                if self.papers:
                    self._save_fetch_cache(cache_key, self.papers)
            print(f"[{self.name}] {len(self.papers)} {self.period} papers")
        if "models" in self.content_types:
            cached = self._load_fetch_cache("trending_models")
            if cached is not None:
                self.models = cached
            else:
                self.models = get_trending_models_api(self.max_models * 2)
                if self.models:
                    self._save_fetch_cache("trending_models", self.models)
            print(f"[{self.name}] {len(self.models)} trending models")

    @staticmethod
    def add_arguments(parser: argparse.ArgumentParser):
        parser.add_argument(
            "--hf_content_type", nargs="+", choices=["papers", "models"],
            default=["papers", "models"],
            help="[HuggingFace] Content types to fetch",
        )
        parser.add_argument(
            "--hf_period", type=str, choices=["daily", "weekly"], default=os.getenv("HF_PERIOD", "daily"),
            help="[HuggingFace] Fetch daily papers or a weekly paper list",
        )
        parser.add_argument(
            "--hf_week_id", type=str, default=os.getenv("HF_WEEK_ID", ""),
            help="[HuggingFace] Specific weekly page such as 2026-W15",
        )
        parser.add_argument(
            "--hf_max_papers", type=int, default=30,
            help="[HuggingFace] Max papers to recommend",
        )
        parser.add_argument(
            "--hf_max_models", type=int, default=15,
            help="[HuggingFace] Max models to recommend",
        )

    @staticmethod
    def extract_args(args) -> dict:
        return {
            "content_type": args.hf_content_type,
            "period": args.hf_period,
            "week_id": args.hf_week_id,
            "max_papers": args.hf_max_papers,
            "max_models": args.hf_max_models,
        }

    def fetch_items(self) -> list[dict]:
        items = []
        for p in self.papers:
            p["_hf_type"] = "paper"
            items.append(p)
        for m in self.models:
            m["_hf_type"] = "model"
            items.append(m)
        return items

    def get_item_cache_id(self, item: dict) -> str:
        if item.get("_hf_type") == "paper":
            period_prefix = item.get("hf_period", self.period)
            return period_prefix + "_paper_" + item.get("id", "unknown")
        else:
            return "model_" + item.get("model_id", "unknown").replace("/", "_")

    def build_eval_prompt(self, item: dict) -> str:
        if item.get("_hf_type") == "paper":
            return self._build_paper_prompt(item)
        else:
            return self._build_model_prompt(item)

    def _build_paper_prompt(self, item: dict) -> str:
        prompt = """
            你是一个有帮助的AI研究助手，可以帮助我构建每日HuggingFace论文推荐系统。
            以下是我感兴趣的研究领域描述：
            {}
        """.format(self.description)
        prompt += """
            以下是今天HuggingFace Daily Papers中的一篇论文：
            标题: {}
            摘要: {}
            社区点赞数: {}
            周榜信息: period={} | week={} | discussion={} | resources={}
        """.format(
            item["title"],
            item["abstract"],
            item.get("upvotes", 0),
            item.get("hf_period", self.period),
            item.get("hf_week", self.week_id),
            item.get("discussion_count", 0),
            item.get("resource_count", 0),
        )
        prompt += """
            1. 先给一句话结论（TLDR），要求直观易懂。
            2. 说明这篇论文解决什么问题。
            3. 说明方法核心以及 pipeline / training recipe。
            4. 说明它和已有方法比新在哪里。
            5. 请评估这篇论文与我研究领域的相关性，并给出 0-10 的评分。其中 0 表示完全不相关，10 表示高度相关。

            请按以下 JSON 格式给出你的回答：
            {
                "summary": "一个连续的中文段落，内部自然覆盖：一句话结论、问题、方法核心、pipeline/training recipe、新意、为什么值得看、与我方向的关系。不要嵌套JSON/dict。",
                "relevance": <你的评分>
            }
            重要：summary 必须是一段纯文本字符串，不要返回嵌套的 JSON 对象或字典。
            使用中文回答。
            直接返回上述 JSON 格式，无需任何额外解释。
        """
        return prompt

    def _build_model_prompt(self, item: dict) -> str:
        tags = item.get("tags", [])
        prompt = """
            你是一个有帮助的AI研究助手，可以帮助我发现有用的AI模型。
            以下是我感兴趣的研究领域描述：
            {}
        """.format(self.description)
        prompt += """
            以下是HuggingFace上的一个热门模型：
            模型ID: {}
            描述: {}
            下载量: {}
            点赞数: {}
            标签: {}
        """.format(
            item["model_id"],
            item.get("description", "") or "无描述",
            item.get("downloads", 0),
            item.get("likes", 0),
            ", ".join(tags) if tags else "无标签",
        )
        prompt += """
            1. 先给一句话结论（TLDR），要求直观易懂。
            2. 说明这个模型解决什么问题、适用于什么任务。
            3. 说明它的系统结构、使用流程、典型 pipeline 或部署方式。
            4. 说明它和常见方案相比新在哪里，或者为什么它最近值得关注。
            5. 请评估这个模型对我研究/工作的有用程度，并给出 0-10 的评分。其中 0 表示完全没用，10 表示非常有用。

            请按以下 JSON 格式给出你的回答：
            {
                "summary": "一个连续的中文段落，内部自然覆盖：一句话结论、任务/问题、模型/系统核心、使用流程或 pipeline、亮点、为什么值得看、与我方向的关系。不要嵌套JSON/dict。",
                "usefulness": <你的评分>
            }
            重要：summary 必须是一段纯文本字符串，不要返回嵌套的 JSON 对象或字典。
            使用中文回答。
            直接返回上述 JSON 格式，无需任何额外解释。
        """
        return prompt

    def parse_eval_response(self, item: dict, response: str) -> dict:
        response = response.strip("```").strip("json")
        data = json.loads(response)

        if item.get("_hf_type") == "paper":
            return {
                "_hf_type": "paper",
                "title": item["title"],
                "id": item.get("id", ""),
                "abstract": item.get("abstract", ""),
                "summary": self._ensure_str(data["summary"]),
                "score": float(data["relevance"]),
                "upvotes": item.get("upvotes", 0),
                "discussion_count": item.get("discussion_count", 0),
                "resource_count": item.get("resource_count", 0),
                "hf_period": item.get("hf_period", self.period),
                "hf_week": item.get("hf_week", self.week_id),
                "url": item["paper_url"],
            }
        else:
            return {
                "_hf_type": "model",
                "title": item["model_id"],
                "id": item.get("model_id", ""),
                "description": item.get("description", ""),
                "summary": self._ensure_str(data["summary"]),
                "score": float(data["usefulness"]),
                "downloads": item.get("downloads", 0),
                "likes": item.get("likes", 0),
                "tags": item.get("tags", []),
                "url": item["model_url"],
            }

    def render_item_html(self, item: dict) -> str:
        rate = get_stars(item.get("score", 0))
        if item.get("_hf_type") == "paper":
            return get_paper_block_html(
                item["title"], rate, item["id"], item["summary"],
                item["url"], item.get("upvotes", 0),
            )
        else:
            return get_model_block_html(
                item["title"], rate, item["id"], item["summary"],
                item["url"], item.get("likes", 0), item.get("downloads", 0),
            )

    def get_theme_color(self) -> str:
        return "255,111,0"

    def get_section_header(self) -> str:
        label = "Weekly" if self.period == "weekly" else "Daily"
        suffix = f" ({self.week_id})" if self.period == "weekly" and self.week_id else ""
        return f'<div class="section-title" style="border-bottom-color: #ff6f00;">🤗 HuggingFace {label}{suffix}</div>'

    def get_max_items(self) -> int:
        return self.max_papers + self.max_models

    def delta_snapshot_mode(self) -> bool:
        return self.period == "weekly"

    def get_recommendations(self) -> list[dict]:
        """Override: process papers and models separately with independent limits."""
        all_items = self.fetch_items()
        if not all_items:
            print(f"[{self.name}] No items fetched.")
            return []

        papers = [i for i in all_items if i.get("_hf_type") == "paper"]
        models = [i for i in all_items if i.get("_hf_type") == "model"]

        paper_recs = self._process_batch(papers, "papers") if papers else []
        model_recs = self._process_batch(models, "models") if models else []

        paper_recs = sorted(paper_recs, key=lambda x: x.get("score", 0), reverse=True)
        model_recs = sorted(model_recs, key=lambda x: x.get("score", 0), reverse=True)

        if self.delta_snapshot_mode():
            paper_recs = [
                item for item in paper_recs
                if item.get("_cache_id", "") in self.new_history_ids
            ]
            model_recs = [
                item for item in model_recs
                if item.get("_cache_id", "") in self.new_history_ids
            ]

        paper_recs = paper_recs[:self.max_papers]
        model_recs = model_recs[:self.max_models]

        combined = sorted(paper_recs + model_recs, key=lambda x: x.get("score", 0), reverse=True)[:self.MAX_RECOMMEND]

        if self.save_dir and combined:
            self._save_markdown(combined)

        return combined

    def _process_batch(self, items: list[dict], label: str) -> list[dict]:
        results = []
        print(f"[{self.name}] Processing {len(items)} {label}...")
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(self.num_workers) as executor:
            futures = [executor.submit(self.process_item, item) for item in items]
            for future in tqdm(as_completed(futures), total=len(futures),
                               desc=f"[{self.name}] {label}", unit="item"):
                result = future.result()
                if result:
                    results.append(result)
        return results

    def render_email(self, recommendations: list[dict]) -> str:
        """Override: render papers and models in separate sections."""
        papers = [r for r in recommendations if r.get("_hf_type") == "paper"]
        models = [r for r in recommendations if r.get("_hf_type") == "model"]

        if not papers and not models:
            return framework.replace("__CONTENT__", get_empty_html())

        parts = []

        if papers:
            parts.append('<div class="section-title" style="border-bottom-color: #ff6f00;">📄 Daily Papers</div>')
            for i, p in enumerate(tqdm(papers, desc=f"[{self.name}] Rendering papers")):
                parts.append(self.render_item_html(p))

        if models:
            parts.append('<div class="section-title" style="border-bottom-color: #1976d2;">🤖 Trending Models</div>')
            for i, m in enumerate(tqdm(models, desc=f"[{self.name}] Rendering models")):
                parts.append(self.render_item_html(m))

        summary = self.summarize(recommendations)
        content = summary + "<br>" + "</br><br>".join(parts) + "</br>"
        email_html = framework.replace("__CONTENT__", content)

        # Save to history as snapshot (not used as cache)
        if self.save_dir:
            email_path = os.path.join(self.save_dir, f"{self.name}_{self.period}_email_{self.run_stamp}.html")
            os.makedirs(os.path.dirname(email_path), exist_ok=True)
            with open(email_path, "w", encoding="utf-8") as f:
                f.write(email_html)

        return email_html

    def build_summary_overview(self, recommendations: list[dict]) -> str:
        papers = [r for r in recommendations if r.get("_hf_type") == "paper"]
        models = [r for r in recommendations if r.get("_hf_type") == "model"]

        overview = ""
        if papers:
            overview += "=== Papers ===\n"
            for i, p in enumerate(papers):
                overview += f"{i + 1}. {p['title']} - {p['summary']}\n"
        if models:
            overview += "\n=== Models ===\n"
            for i, m in enumerate(models):
                overview += f"{i + 1}. {m['title']} - {m['summary']}\n"
        return overview

    def get_summary_prompt_template(self) -> str:
        return """
            请直接输出一段 HTML 片段，严格遵循以下结构，不要包含 JSON、Markdown 或多余说明：
            <div class="summary-wrapper">
              <div class="summary-section">
                <h2>今日趋势</h2>
                <p>...</p>
              </div>
              <div class="summary-section">
                <h2>重点推荐</h2>
                <ol class="summary-list">
                  <li class="summary-item">
                    <div class="summary-item__header"><span class="summary-item__title">标题</span><span class="summary-pill">类型</span></div>
                    <p><strong>一句话结论：</strong>...</p>
                    <p><strong>问题与方法 / 系统：</strong>...</p>
                    <p><strong>Pipeline / 使用方式：</strong>...</p>
                    <p><strong>为什么值得看：</strong>...</p>
                  </li>
                </ol>
              </div>
              <div class="summary-section">
                <h2>补充观察</h2>
                <p>暂无或其他补充。</p>
              </div>
            </div>

            用中文撰写内容，重点推荐部分建议返回 3-5 项内容。
            不要只写流行度判断，请尽量说清论文/模型的工作机制和 pipeline。
        """

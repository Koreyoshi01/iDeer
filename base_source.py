from abc import ABC, abstractmethod
from config import LLMConfig, EmailConfig, CommonConfig
from llm.GPT import GPT
from llm.Ollama import Ollama
from email_utils.base_template import framework, get_stars, get_summary_html, render_summary_sections, get_empty_html
from tqdm import tqdm
import json
import os
import argparse
from datetime import datetime, timezone
import time
import smtplib
from email.header import Header
from email.mime.text import MIMEText
from email.utils import parseaddr, formataddr
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading


class BaseSource(ABC):
    name: str = ""
    default_title: str = "Daily Recommender"

    def __init__(self, source_args: dict, llm_config: LLMConfig, common_config: CommonConfig):
        self.llm_config = llm_config
        self.common_config = common_config
        self.source_args = source_args
        self.num_workers = common_config.num_workers
        self.temperature = llm_config.temperature
        self.run_datetime = datetime.now(timezone.utc)
        self.run_date = self.run_datetime.strftime("%Y-%m-%d")
        self.description = common_config.description
        self.lock = threading.Lock()

        self.save_dir = None
        self.cache_dir = None
        if common_config.save:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            self.save_dir = os.path.join(base_dir, common_config.save_dir, self.name, self.run_date)
            self.cache_dir = os.path.join(self.save_dir, "json")
            os.makedirs(self.cache_dir, exist_ok=True)

        provider = llm_config.provider.lower()
        if provider == "ollama":
            self.model = Ollama(llm_config.model)
        elif provider in ("openai", "siliconflow"):
            self.model = GPT(llm_config.model, llm_config.base_url, llm_config.api_key)
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")
        print(f"[{self.name}] Model initialized: {llm_config.model} via {provider}")

    @staticmethod
    @abstractmethod
    def add_arguments(parser: argparse.ArgumentParser):
        """Register source-specific CLI arguments (with prefix)."""
        pass

    @abstractmethod
    def fetch_items(self) -> list[dict]:
        """Fetch raw items from the data source."""
        pass

    @abstractmethod
    def build_eval_prompt(self, item: dict) -> str:
        """Build LLM evaluation prompt for a single item."""
        pass

    @abstractmethod
    def parse_eval_response(self, item: dict, response: str) -> dict:
        """Parse LLM response into a structured result dict. Must include 'score' key."""
        pass

    @abstractmethod
    def render_item_html(self, item: dict) -> str:
        """Render a single recommendation item as HTML."""
        pass

    @abstractmethod
    def build_summary_overview(self, recommendations: list[dict]) -> str:
        """Build a text overview of recommendations for the summary LLM prompt."""
        pass

    @abstractmethod
    def get_summary_prompt_template(self) -> str:
        """Return the HTML template instruction for the summary LLM prompt."""
        pass

    @abstractmethod
    def get_section_header(self) -> str:
        """Return the section header HTML (e.g. '<div class="section-title">...')."""
        pass

    @abstractmethod
    def get_item_cache_id(self, item: dict) -> str:
        """Return a unique cache filename (without extension) for an item."""
        pass

    def get_max_items(self) -> int:
        """Return the max number of items to recommend. Override in subclass."""
        return 30

    def process_item(self, item: dict, max_retries: int = 5) -> dict | None:
        retry_count = 0
        cache_id = self.get_item_cache_id(item)
        cache_path = os.path.join(self.cache_dir, f"{cache_id}.json") if self.cache_dir else None

        if cache_path and os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                print(f"Cache loaded: {cache_path}")
                return cached
            except (json.JSONDecodeError, OSError) as e:
                print(f"Cache load failed ({cache_path}): {e}, refetching.")

        while retry_count < max_retries:
            try:
                prompt = self.build_eval_prompt(item)
                response = self.model.inference(prompt, temperature=self.temperature)
                result = self.parse_eval_response(item, response)

                if cache_path:
                    try:
                        with self.lock:
                            with open(cache_path, "w", encoding="utf-8") as f:
                                json.dump(result, f, ensure_ascii=False, indent=2)
                    except OSError as e:
                        print(f"Cache write failed ({cache_path}): {e}")
                return result

            except Exception as e:
                retry_count += 1
                print(f"[{self.name}] Error processing item {cache_id}: {e}")
                print(f"Retry {retry_count}/{max_retries}...")
                if retry_count == max_retries:
                    print(f"Max retries reached, skipping {cache_id}")
                    return None
                time.sleep(1)
        return None

    def get_recommendations(self) -> list[dict]:
        raw_items = self.fetch_items()
        if not raw_items:
            print(f"[{self.name}] No items fetched.")
            return []

        recommendations = []
        print(f"[{self.name}] Processing {len(raw_items)} items with LLM...")

        with ThreadPoolExecutor(self.num_workers) as executor:
            futures = [executor.submit(self.process_item, item) for item in raw_items]
            for future in tqdm(as_completed(futures), total=len(futures),
                               desc=f"[{self.name}] Processing", unit="item"):
                result = future.result()
                if result:
                    recommendations.append(result)

        recommendations = sorted(
            recommendations, key=lambda x: x.get("score", 0), reverse=True
        )[:self.get_max_items()]

        if self.save_dir:
            self._save_markdown(recommendations)

        return recommendations

    def _save_markdown(self, recommendations: list[dict]):
        save_path = os.path.join(self.save_dir, f"{self.run_date}.md")
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(f"# {self.default_title} Recommendations\n")
            f.write(f"## Date: {self.run_date}\n\n")
            for i, r in enumerate(recommendations):
                f.write(f"### {i + 1}. {r.get('title', 'Unknown')}\n")
                f.write(f"- **Score:** {r.get('score', 0)}\n")
                f.write(f"- **Summary:** {r.get('summary', 'N/A')}\n")
                f.write(f"- **URL:** {r.get('url', '')}\n\n")

    def summarize(self, recommendations: list[dict]) -> str:
        overview = self.build_summary_overview(recommendations)
        template = self.get_summary_prompt_template()

        prompt_context = """
            你是一个有帮助的助手，帮助我追踪热门内容。
            以下是我感兴趣的领域描述：
            {}
        """.format(self.description)
        content_context = """
            以下是今天的热门内容摘要：
            {}
        """.format(overview)

        prompt = prompt_context + content_context + template

        def _clean_response(raw: str) -> str:
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                cleaned = cleaned.strip()
                if "\n" in cleaned:
                    first_line, rest = cleaned.split("\n", 1)
                    if first_line.strip().lower() in ("json", "html"):
                        cleaned = rest
            return cleaned.strip()

        try:
            raw = self.model.inference(prompt, temperature=self.temperature)
            cleaned = _clean_response(raw)
            return get_summary_html(cleaned, self.get_theme_color())
        except Exception as e:
            print(f"[{self.name}] Summary generation failed: {e}")
            fallback = {
                "trend_summary": "Summary generation failed.",
                "recommendations": [],
                "additional_observation": "None.",
            }
            return render_summary_sections(fallback, self.get_theme_color())

    def get_theme_color(self) -> str:
        """Override to customize theme. Default is neutral gray."""
        return "36,41,46"

    def render_email(self, recommendations: list[dict]) -> str:
        email_cache = os.path.join(self.save_dir, f"{self.name}_email.html") if self.save_dir else None
        if email_cache and os.path.exists(email_cache):
            with open(email_cache, "r", encoding="utf-8") as f:
                print(f"[{self.name}] Email loaded from cache: {email_cache}")
                return f.read()

        if not recommendations:
            return framework.replace("__CONTENT__", get_empty_html())

        parts = [self.get_section_header()]
        for i, r in enumerate(tqdm(recommendations, desc=f"[{self.name}] Rendering", unit="item")):
            rate = get_stars(r.get("score", 0))
            parts.append(self.render_item_html(r))

        summary = self.summarize(recommendations)
        content = summary + "<br>" + "</br><br>".join(parts) + "</br>"
        email_html = framework.replace("__CONTENT__", content)

        if email_cache:
            os.makedirs(os.path.dirname(email_cache), exist_ok=True)
            with open(email_cache, "w", encoding="utf-8") as f:
                f.write(email_html)

        return email_html

    def send_email(self, email_config: EmailConfig, title: str | None = None):
        title = title or self.default_title
        recommendations = self.get_recommendations()
        html = self.render_email(recommendations)

        def _format_addr(s):
            name, addr = parseaddr(s)
            return formataddr((Header(name, "utf-8").encode(), addr))

        msg = MIMEText(html, "html", "utf-8")
        msg["From"] = _format_addr(f"{title} <{email_config.sender}>")

        receivers = [addr.strip() for addr in email_config.receiver.split(",")]
        msg["To"] = ",".join([_format_addr(f"You <{addr}>") for addr in receivers])

        today = self.run_datetime.strftime("%Y/%m/%d")
        msg["Subject"] = Header(f"{title} {today}", "utf-8").encode()

        try:
            server = smtplib.SMTP(email_config.smtp_server, email_config.smtp_port)
            server.starttls()
        except Exception as e:
            print(f"TLS failed: {e}, trying SSL...")
            server = smtplib.SMTP_SSL(email_config.smtp_server, email_config.smtp_port)

        server.login(email_config.sender, email_config.sender_password)
        server.sendmail(email_config.sender, receivers, msg.as_string())
        server.quit()
        print(f"[{self.name}] Email sent to {receivers}")

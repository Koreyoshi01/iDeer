from abc import ABC, abstractmethod
from config import LLMConfig, EmailConfig, CommonConfig
from llm.GPT import GPT
from llm import Ollama
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
        self.run_local_datetime = self.run_datetime.astimezone()
        self.run_date = self.run_local_datetime.strftime("%Y-%m-%d")
        self.run_stamp = self.run_local_datetime.strftime("%Y-%m-%d-%H_%M_%S")
        self.description = common_config.description
        self.profile_hash = common_config.profile_hash
        self.lock = threading.Lock()

        base_dir = os.path.dirname(os.path.abspath(__file__))

        # --- Cache layer 1: shared fetch cache (interest-independent) ---
        self.fetch_cache_dir = os.path.join(
            base_dir, common_config.state_dir, "fetch_cache", self.name, self.run_date
        )
        os.makedirs(self.fetch_cache_dir, exist_ok=True)

        # --- Cache layer 2: eval cache (isolated by profile_hash) ---
        self.eval_cache_dir = None
        if self.profile_hash:
            self.eval_cache_dir = os.path.join(
                base_dir, common_config.state_dir, "eval_cache",
                self.name, self.run_date, self.profile_hash,
            )
            os.makedirs(self.eval_cache_dir, exist_ok=True)

        # --- History: final output mirror (unchanged structure for UI) ---
        self.save_dir = None
        self.cache_dir = None  # legacy alias kept for compatibility
        if common_config.save:
            self.save_dir = os.path.join(base_dir, common_config.save_dir, self.name, self.run_date)
            self.cache_dir = os.path.join(self.save_dir, "json")
            os.makedirs(self.cache_dir, exist_ok=True)
        self.existing_history_ids = set()
        self.new_history_ids = set()
        if self.cache_dir and os.path.isdir(self.cache_dir):
            self.existing_history_ids = {
                os.path.splitext(name)[0]
                for name in os.listdir(self.cache_dir)
                if name.endswith(".json")
            }

        provider = llm_config.provider.lower()
        if provider == "ollama":
            if Ollama is None:
                raise ModuleNotFoundError("ollama package is required when provider=ollama")
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

    # Maximum items in the final email/output. Subclass get_max_items() controls
    # per-source fetch limits; this caps the actual recommendations delivered.
    MAX_RECOMMEND = 15

    def get_max_items(self) -> int:
        """Return the max number of items to recommend. Override in subclass."""
        return 30

    @staticmethod
    def _ensure_str(value) -> str:
        """Ensure a value is a plain string. LLMs sometimes return dicts/lists
        for the summary field when the user description is structured."""
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            # Flatten nested dict into readable text
            parts = []
            for k, v in value.items():
                if isinstance(v, dict):
                    sub = "；".join(f"{sk}: {sv}" for sk, sv in v.items())
                    parts.append(f"【{k}】{sub}")
                else:
                    parts.append(f"【{k}】{v}")
            return " ".join(parts)
        if isinstance(value, list):
            return "；".join(str(item) for item in value)
        return str(value)

    def _load_fetch_cache(self, key: str) -> list[dict] | None:
        """Load shared fetch cache (interest-independent)."""
        from cache_utils import safe_read_json
        path = os.path.join(self.fetch_cache_dir, f"{key}.json")
        data = safe_read_json(path)
        if data is not None and isinstance(data, list):
            print(f"[{self.name}] Fetch cache hit: {key} ({len(data)} items)")
        return data if isinstance(data, list) else None

    def _save_fetch_cache(self, key: str, items: list[dict]):
        """Save shared fetch cache (interest-independent)."""
        from cache_utils import atomic_write_json
        path = os.path.join(self.fetch_cache_dir, f"{key}.json")
        try:
            atomic_write_json(path, items)
        except OSError as e:
            print(f"[{self.name}] Fetch cache write failed: {e}")

    def process_item(self, item: dict, max_retries: int = 5) -> dict | None:
        from cache_utils import atomic_write_json, safe_read_json

        retry_count = 0
        cache_id = self.get_item_cache_id(item)

        # Primary: profile-isolated eval cache (state/eval_cache/<source>/<date>/<profile_hash>/)
        eval_path = os.path.join(self.eval_cache_dir, f"{cache_id}.json") if self.eval_cache_dir else None

        if eval_path:
            cached = safe_read_json(eval_path)
            if cached is not None:
                print(f"[{self.name}] Eval cache hit: {cache_id}")
                if isinstance(cached, dict):
                    cached = {**cached, "_cache_id": cache_id}
                # Mirror to history for UI
                self._mirror_to_history(cache_id, cached)
                return cached

        while retry_count < max_retries:
            try:
                prompt = self.build_eval_prompt(item)
                response = self.model.inference(prompt, temperature=self.temperature)
                result = self.parse_eval_response(item, response)
                result["_cache_id"] = cache_id

                # Write to eval cache (profile-isolated, atomic)
                if eval_path:
                    try:
                        atomic_write_json(eval_path, result)
                    except OSError as e:
                        print(f"[{self.name}] Eval cache write failed ({eval_path}): {e}")

                # Mirror to history for UI
                self._mirror_to_history(cache_id, result)
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

    def _mirror_to_history(self, cache_id: str, result: dict):
        """Write eval result to history/json/ for UI compatibility."""
        if not self.cache_dir:
            return
        history_path = os.path.join(self.cache_dir, f"{cache_id}.json")
        if os.path.exists(history_path):
            return
        try:
            with self.lock:
                self.new_history_ids.add(cache_id)
                with open(history_path, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def _reconfigure_storage(self, history_parts: list[str], scope_key: str):
        """Switch history/cache storage to a custom scope such as weekly buckets."""
        base_dir = os.path.dirname(os.path.abspath(__file__))

        self.fetch_cache_dir = os.path.join(
            base_dir, self.common_config.state_dir, "fetch_cache", *history_parts, scope_key
        )
        os.makedirs(self.fetch_cache_dir, exist_ok=True)

        self.eval_cache_dir = None
        if self.profile_hash:
            self.eval_cache_dir = os.path.join(
                base_dir,
                self.common_config.state_dir,
                "eval_cache",
                *history_parts,
                scope_key,
                self.profile_hash,
            )
            os.makedirs(self.eval_cache_dir, exist_ok=True)

        self.save_dir = None
        self.cache_dir = None
        if self.common_config.save:
            self.save_dir = os.path.join(base_dir, self.common_config.save_dir, *history_parts, scope_key)
            self.cache_dir = os.path.join(self.save_dir, "json")
            os.makedirs(self.cache_dir, exist_ok=True)
        self.existing_history_ids = set()
        self.new_history_ids = set()
        if self.cache_dir and os.path.isdir(self.cache_dir):
            self.existing_history_ids = {
                os.path.splitext(name)[0]
                for name in os.listdir(self.cache_dir)
                if name.endswith(".json")
            }

    def delta_snapshot_mode(self) -> bool:
        return False

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
        )
        if self.delta_snapshot_mode():
            recommendations = [
                item for item in recommendations
                if item.get("_cache_id", "") in self.new_history_ids
            ]
        limit = min(self.get_max_items(), self.MAX_RECOMMEND)
        recommendations = recommendations[:limit]

        if self.save_dir and recommendations:
            self._save_markdown(recommendations)

        return recommendations

    def _save_markdown(self, recommendations: list[dict]):
        save_path = os.path.join(self.save_dir, f"{self.run_stamp}.md")
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(f"# {self.default_title} Recommendations\n")
            f.write(f"## Date: {self.run_date}\n\n")
            for i, r in enumerate(recommendations):
                f.write(f"### {i + 1}. {r.get('title', 'Unknown')}\n")
                f.write(f"- **Score:** {r.get('score', 0)}\n")
                f.write(f"- **Summary:** {r.get('summary', 'N/A')}\n")
                f.write(f"- **URL:** {r.get('url', '')}\n\n")

    def _parse_interest_fields(self) -> list[str]:
        """Parse interest field names from description text."""
        fields = []
        for line in self.description.splitlines():
            line = line.strip()
            # Match lines like "1. Agent - ..." or "2. Safety"
            if line and line[0].isdigit() and '. ' in line:
                field = line.split('. ', 1)[1].split(' - ')[0].strip()
                if field:
                    fields.append(field)
            if line.lower().startswith("i'm not interested") or line.lower().startswith("i am not interested"):
                break
        return fields

    @staticmethod
    def _method_first_summary_instruction(source_label: str, score_label: str = "相关性") -> str:
        return f"""
            请评估这个{source_label}，并按下面结构输出：
            1. 用中文先给出一句话结论（TLDR），要求便于快速理解。
            2. 说明它解决什么问题，或它在说什么核心事情。
            3. 说明方法核心 / 系统核心 / pipeline / training recipe（如果是论文或技术内容必须尽量写清楚）。
            4. 说明它与已有方法相比新在哪里，或者为什么它今天值得看。
            5. 说明它与我研究方向的关系，并给出 0-10 的{score_label}评分。

            请按以下 JSON 格式给出你的回答：
            {{
                "summary": "使用一个连续的中文段落，但内部必须自然覆盖：一句话结论、问题、方法核心、pipeline/training recipe、新意、值得关注的原因、与我方向的关系。不要嵌套 JSON。",
                "relevance": <你的评分>
            }}

            重要要求：
            - summary 必须是纯文本字符串，不要返回嵌套 JSON 或字典。
            - 不要空泛地说“提出了一个新方法”。请尽量说清楚方法由哪些关键模块或训练阶段组成。
            - 如果是博客、推文、repo 或新闻，没有严格训练流程，也要尽量说清楚它的系统流程、使用方式、工作机制或事件脉络。
            - 请根据你自己给出的评分控制详略：
              - 0-4 分：保持简洁，但仍要说清问题和核心机制，不要空泛。
              - 5-7 分：给出中等密度说明，至少点明方法和基本 pipeline。
              - 8-10 分：给出更详细的 method/pipeline/training recipe，把更多注意力放在高相关高质量内容上。
            - 使用中文回答,同时保留cs专业术语(英文)。
            - 直接返回 JSON，不要额外解释。
        """

    def summarize(self, recommendations: list[dict]) -> str:
        overview = self.build_summary_overview(recommendations)
        fields = self._parse_interest_fields()

        prompt_context = """
            你是一个有帮助的助手，帮助我追踪热门内容。
            以下是我感兴趣的领域描述：
            {}
        """.format(self.description)
        content_context = """
            以下是今天的热门内容摘要：
            {}
        """.format(overview)

        if fields and len(fields) >= 2:
            fields_sections = "\n".join([
                f"""              <div class="summary-section">
                <h2>{f} 方向</h2>
                <ol class="summary-list">
                  <li class="summary-item">
                    <div class="summary-item__header"><span class="summary-item__title">标题/名称</span><span class="summary-pill">类型</span></div>
                    <p class="summary-item__stats">⭐ XXX stars (+YYY today) 或 👍 ZZ upvotes 或 ❤️ NN likes</p>
                    <p><strong>一句话结论：</strong>...</p>
                    <p><strong>问题与方法：</strong>...</p>
                    <p><strong>Pipeline / 训练配方：</strong>...</p>
                    <p><strong>为什么值得看：</strong>...</p>
                  </li>
                </ol>
                <p><em>如果今天没有与此方向相关的内容，请写"今日暂无相关内容"。</em></p>
              </div>""" for f in fields
            ])
            template = f"""
            请直接输出一段 HTML 片段，严格遵循以下结构，不要包含 JSON、Markdown 或多余说明。
            重要：请按我的 {len(fields)} 个兴趣方向（{', '.join(fields)}）分别总结，每个方向一个独立的 section，
            列出该方向下最相关的 2-4 项内容。

            <div class="summary-wrapper">
              <div class="summary-section">
                <h2>今日总览</h2>
                <p>简要概括今天各方向的整体动态（2-3句话）...</p>
              </div>
{fields_sections}
              <div class="summary-section">
                <h2>补充观察</h2>
                <p>跨方向的共同趋势或其他值得关注的内容...</p>
              </div>
            </div>

            用中文撰写内容。每个方向 section 中的推荐项请包含推荐理由和关键亮点。
            重要：每个推荐项必须包含真实的互动数据（如 GitHub 项目的 stars/today stars、论文的 upvotes、模型的 likes/downloads、推文的点赞/转发），从上面的摘要中提取，放在 <p class="summary-item__stats"> 标签中。禁止省略此数据行。
            重要：不要只写空泛趋势判断。请尽量说清每个推荐项在“做什么、怎么做、为什么值得看”。
            """
        else:
            template = self.get_summary_prompt_template()

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
        if not recommendations:
            return framework.replace("__CONTENT__", get_empty_html())

        parts = [self.get_section_header()]
        for i, r in enumerate(tqdm(recommendations, desc=f"[{self.name}] Rendering", unit="item")):
            rate = get_stars(r.get("score", 0))
            parts.append(self.render_item_html(r))

        summary = self.summarize(recommendations)
        content = summary + "<br>" + "</br><br>".join(parts) + "</br>"
        email_html = framework.replace("__CONTENT__", content)

        # Save to history as a snapshot (not used as cache)
        if self.save_dir:
            email_path = os.path.join(self.save_dir, f"{self.name}_email_{self.run_stamp}.html")
            os.makedirs(os.path.dirname(email_path), exist_ok=True)
            with open(email_path, "w", encoding="utf-8") as f:
                f.write(email_html)

        return email_html

    @staticmethod
    def _send_email_html(html: str, email_config: EmailConfig, title: str, run_datetime=None):
        """Send an HTML email. Decoupled from recommendation fetching for reuse."""
        if run_datetime is None:
            run_datetime = datetime.now(timezone.utc)

        # Skip if email config is incomplete
        if not email_config.receiver or not email_config.sender or not email_config.smtp_server:
            print(f"[{title}] Email not sent: incomplete email configuration")
            return

        def _format_addr(s):
            name, addr = parseaddr(s)
            return formataddr((Header(name, "utf-8").encode(), addr))

        msg = MIMEText(html, "html", "utf-8")
        msg["From"] = _format_addr(f"{title} <{email_config.sender}>")

        receivers = [addr.strip() for addr in email_config.receiver.split(",")]
        msg["To"] = ",".join([_format_addr(f"You <{addr}>") for addr in receivers])

        today = run_datetime.strftime("%Y/%m/%d")
        msg["Subject"] = Header(f"{title} {today}", "utf-8").encode()

        try:
            if email_config.smtp_port == 465:
                server = smtplib.SMTP_SSL(email_config.smtp_server, email_config.smtp_port, timeout=20)
            else:
                server = smtplib.SMTP(email_config.smtp_server, email_config.smtp_port, timeout=20)
                server.ehlo()
                server.starttls()
                server.ehlo()
        except Exception as e:
            print(f"Primary SMTP mode failed: {e}, trying SSL fallback...")
            server = smtplib.SMTP_SSL(email_config.smtp_server, email_config.smtp_port, timeout=20)

        server.login(email_config.sender, email_config.sender_password)
        server.sendmail(email_config.sender, receivers, msg.as_string())
        server.quit()
        print(f"Email '{title}' sent to {receivers}")

    def send_email(self, email_config: EmailConfig, title: str | None = None):
        title = title or self.default_title
        recommendations = self.get_recommendations()
        html = self.render_email(recommendations)
        self._send_email_html(html, email_config, title, self.run_datetime)
        return recommendations

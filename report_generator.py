"""Generate a cross-source personalized narrative report from daily recommendations."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any

from base_source import BaseSource
from config import CommonConfig, EmailConfig, LLMConfig
from email_utils.report_template import render_report_email
from llm.GPT import GPT
from llm import Ollama

REPORT_EMAIL_TITLE = "Daily Personal Briefing"


class ReportGenerator:
    def __init__(
        self,
        all_recs: dict[str, list[dict]],
        profile_text: str,
        llm_config: LLMConfig,
        common_config: CommonConfig,
        report_title: str = REPORT_EMAIL_TITLE,
        min_score: float = 4.0,
        max_items: int = 18,
        theme_count: int = 4,
        prediction_count: int = 4,
        idea_count: int = 4,
    ):
        self.all_recs = all_recs
        self.profile_text = profile_text.strip()
        self.llm_config = llm_config
        self.common_config = common_config
        self.report_title = report_title
        self.min_score = min_score
        self.max_items = max_items
        self.theme_count = theme_count
        self.prediction_count = prediction_count
        self.idea_count = idea_count

        self.run_datetime = datetime.now(timezone.utc)
        self.run_local_datetime = self.run_datetime.astimezone()
        self.run_date = self.run_local_datetime.strftime("%Y-%m-%d")
        self.run_stamp = self.run_local_datetime.strftime("%Y-%m-%d-%H_%M_%S")

        self.model = self._build_model(llm_config)

        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.save_dir = os.path.join(base_dir, common_config.save_dir, "reports", self.run_date)
        self.email_cache_path = os.path.join(self.save_dir, f"report_{self.run_stamp}.html")

        if common_config.save:
            os.makedirs(self.save_dir, exist_ok=True)

    @staticmethod
    def _build_model(llm_config: LLMConfig):
        provider = llm_config.provider.lower()
        if provider == "ollama":
            if Ollama is None:
                raise ModuleNotFoundError("ollama package is required when provider=ollama")
            return Ollama(llm_config.model)
        if provider in ("openai", "siliconflow"):
            return GPT(llm_config.model, llm_config.base_url, llm_config.api_key)
        raise ValueError(f"Unsupported LLM provider: {provider}")

    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _truncate(text: str, limit: int) -> str:
        text = str(text or "").strip().replace("\n", " ")
        if len(text) <= limit:
            return text
        return text[: limit - 3].rstrip() + "..."

    @staticmethod
    def _dedupe_key(source_name: str, rec: dict) -> str:
        if source_name == "alphaxiv":
            paper_id = str(rec.get("alpha_id", "")).strip()
            if paper_id:
                return f"paper:{paper_id}"
        if source_name == "huggingface" and rec.get("_hf_type") == "paper":
            paper_id = str(rec.get("id", "")).strip()
            if paper_id:
                return f"paper:{paper_id}"
        if source_name == "arxiv":
            paper_id = str(rec.get("arxiv_id", "")).strip()
            if paper_id:
                return f"paper:{paper_id}"
        if source_name == "semanticscholar":
            title = str(rec.get("title", "")).strip().lower()
            if title:
                return f"paper-title:{title}"
        title = str(rec.get("title", "")).strip().lower()
        if title:
            return f"title:{title}"
        return f"{source_name}:{id(rec)}"

    @staticmethod
    def _format_time(text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        try:
            return datetime.fromisoformat(raw).astimezone().strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return raw

    def _normalize_item(self, source_name: str, rec: dict) -> dict:
        source_label = {
            "github": "GitHub",
            "huggingface": "HuggingFace",
            "alphaxiv": "alphaXiv",
            "twitter": "X/Twitter",
            "arxiv": "arXiv",
            "semanticscholar": "Semantic Scholar",
        }.get(source_name, source_name)
        score = self._safe_float(rec.get("score", 0))
        summary = str(rec.get("summary", "")).strip()
        url = str(rec.get("url", "")).strip()

        normalized = {
            "source": source_name,
            "source_label": source_label,
            "score": round(score, 2),
            "title": str(rec.get("title", "Untitled")).strip(),
            "summary": summary,
            "url": url,
            "category": str(rec.get("category", "")).strip(),
            "time": "",
            "metrics": "",
            "entity": "",
            "detail": "",
        }

        if source_name == "github":
            normalized["entity"] = str(rec.get("repo_name", rec.get("title", ""))).strip()
            normalized["detail"] = " / ".join(
                part
                for part in [
                    str(rec.get("language", "")).strip(),
                    self._truncate(rec.get("description", ""), 220),
                    "；".join(str(x).strip() for x in rec.get("highlights", [])[:3] if str(x).strip()),
                ]
                if part
            )
            normalized["metrics"] = (
                f"stars={int(rec.get('stars', 0) or 0)}, "
                f"stars_today={int(rec.get('stars_today', 0) or 0)}, "
                f"forks={int(rec.get('forks', 0) or 0)}"
            )
        elif source_name == "huggingface":
            hf_type = str(rec.get("_hf_type", "")).strip() or "item"
            normalized["category"] = hf_type
            normalized["entity"] = str(rec.get("id", rec.get("title", ""))).strip()
            if hf_type == "paper":
                normalized["detail"] = self._truncate(rec.get("abstract", ""), 260)
                normalized["metrics"] = f"upvotes={int(rec.get('upvotes', 0) or 0)}"
            else:
                tags = ", ".join(str(x).strip() for x in rec.get("tags", [])[:6] if str(x).strip())
                normalized["detail"] = " / ".join(
                    part for part in [self._truncate(rec.get("description", ""), 200), tags] if part
                )
                normalized["metrics"] = (
                    f"likes={int(rec.get('likes', 0) or 0)}, "
                    f"downloads={int(rec.get('downloads', 0) or 0)}"
                )
        elif source_name == "alphaxiv":
            normalized["category"] = str(rec.get("sort", "Hot")).strip() or "Hot"
            normalized["entity"] = str(rec.get("alpha_id", rec.get("title", ""))).strip()
            tags = ", ".join(str(x).strip() for x in rec.get("tags", [])[:6] if str(x).strip())
            normalized["detail"] = " / ".join(
                part
                for part in [
                    self._truncate(rec.get("summary", ""), 260),
                    tags,
                ]
                if part
            )
            normalized["metrics"] = (
                f"likes={int(rec.get('likes', 0) or 0)}, "
                f"resources={int(rec.get('resource_count', 0) or 0)}, "
                f"views={int(rec.get('view_count', 0) or 0)}"
            )
        elif source_name in {"arxiv", "semanticscholar"}:
            normalized["entity"] = str(rec.get("arxiv_id", rec.get("paper_id", rec.get("title", "")))).strip()
            normalized["detail"] = self._truncate(rec.get("abstract", ""), 260)
            if source_name == "semanticscholar":
                normalized["metrics"] = f"citations={int(rec.get('citation_count', 0) or 0)}"
        elif source_name == "twitter":
            author = str(rec.get("author_name", rec.get("author_username", ""))).strip()
            handle = str(rec.get("author_username", "")).strip()
            normalized["entity"] = f"{author} (@{handle})" if author and handle else author or handle
            normalized["time"] = self._format_time(rec.get("created_at", ""))
            normalized["detail"] = " / ".join(
                part
                for part in [
                    self._truncate(rec.get("text", ""), 280),
                    "；".join(str(x).strip() for x in rec.get("key_points", [])[:3] if str(x).strip()),
                ]
                if part
            )
            normalized["metrics"] = (
                f"likes={int(rec.get('likes', 0) or 0)}, "
                f"retweets={int(rec.get('retweets', 0) or 0)}, "
                f"replies={int(rec.get('replies', 0) or 0)}"
            )

        return normalized

    def _filter_items(self) -> list[dict]:
        normalized: list[dict] = []
        dedupe_priority = {
            "alphaxiv": 4,
            "huggingface": 3,
            "arxiv": 2,
            "semanticscholar": 1,
            "github": 1,
            "twitter": 1,
        }
        best_by_key: dict[str, dict] = {}
        for source_name, recs in self.all_recs.items():
            source_items = [self._normalize_item(source_name, rec) for rec in recs]
            source_items.sort(key=lambda item: item.get("score", 0), reverse=True)
            qualified = [item for item in source_items if item.get("score", 0) >= self.min_score]
            if not qualified:
                qualified = source_items[: min(3, len(source_items))]
            for rec, item in zip(recs, source_items):
                if item not in qualified:
                    continue
                key = self._dedupe_key(source_name, rec)
                current = best_by_key.get(key)
                if current is None:
                    best_by_key[key] = item
                    continue
                current_rank = (
                    current.get("score", 0),
                    dedupe_priority.get(str(current.get("source", "")), 0),
                )
                candidate_rank = (
                    item.get("score", 0),
                    dedupe_priority.get(source_name, 0),
                )
                if candidate_rank > current_rank:
                    best_by_key[key] = item

        normalized.extend(best_by_key.values())

        if not normalized:
            return []

        by_source: dict[str, list[dict]] = {}
        for item in normalized:
            by_source.setdefault(item["source"], []).append(item)

        selected: list[dict] = []
        source_names = sorted(
            by_source.keys(),
            key=lambda name: by_source[name][0].get("score", 0),
            reverse=True,
        )
        index_by_source = {name: 0 for name in source_names}

        while len(selected) < self.max_items:
            added_any = False
            for source_name in source_names:
                source_items = by_source[source_name]
                source_index = index_by_source[source_name]
                if source_index >= len(source_items):
                    continue
                selected.append(source_items[source_index])
                index_by_source[source_name] += 1
                added_any = True
                if len(selected) >= self.max_items:
                    break
            if not added_any:
                break

        return selected

    def _format_item_for_prompt(self, item: dict, index: int) -> str:
        lines = [
            f"[{index}] source={item.get('source')} / score={item.get('score', 0)}",
            f"title={item.get('title', '')}",
        ]
        if item.get("entity"):
            lines.append(f"entity={item.get('entity')}")
        if item.get("category"):
            lines.append(f"category={item.get('category')}")
        if item.get("time"):
            lines.append(f"time={item.get('time')}")
        if item.get("metrics"):
            lines.append(f"metrics={item.get('metrics')}")
        if item.get("summary"):
            lines.append(f"summary={item.get('summary')}")
        if item.get("detail"):
            lines.append(f"detail={item.get('detail')}")
        if item.get("url"):
            lines.append(f"url={item.get('url')}")
        return "\n".join(lines)

    def _build_prompt(self, filtered_items: list[dict]) -> str:
        items_text = "\n\n".join(
            self._format_item_for_prompt(item, index)
            for index, item in enumerate(filtered_items, 1)
        )
        profile_excerpt = self._truncate(self.profile_text, 6000)

        return f"""You are writing a personalized cross-platform daily briefing for a single reader.

The output language must be Simplified Chinese, but keep the reasoning prompt in English and do not return any explanatory preamble.

Reader profile:
{profile_excerpt}

Curated source material for today:
{items_text}

Your job:
1. First write a top-level overview of today's most important developments.
2. Then organize the report into exactly four sections when evidence exists:
   - Platform Hot Papers
   - Direction-Strong Picks
   - X Latest / Hot Dynamics
   - GitHub / HuggingFace / Resource Trends
3. Prefer cross-source synthesis when possible. Connect social signals, repos, papers, and models into a single narrative.
4. Be explicit about uncertainty. Separate observed facts from inference.
5. Do not invent evidence. Every concrete claim should be grounded in the provided material.
6. End with a synthesis that connects the sections, then produce a small set of high-quality research ideas.

Output strict JSON only. No markdown fence. No extra text.

Schema:
{{
  "report_title": "A sharp Chinese report title",
  "subtitle": "One-sentence Chinese subtitle tailored to the reader",
  "opening": "2-3 connected Chinese paragraphs that read like an analyst briefing",
  "themes": [
    {{
      "title": "Use one of: 平台热榜论文 / 强相关方向精选 / X最新与热门动态 / GitHub与HuggingFace资源趋势",
      "narrative": "One substantial Chinese section narrative",
      "signals": [
        {{
          "source": "github/twitter/huggingface/arxiv/semanticscholar",
          "title": "signal title",
          "why_it_matters": "one-sentence Chinese significance",
          "url": "https://..."
        }}
      ]
    }}
  ],
  "interpretation": {{
    "thesis": "1-2 Chinese paragraphs that connect the four sections into a coherent synthesis",
    "implications": "1 Chinese paragraph on what is changing next and what deserves follow-up"
  }},
  "predictions": [
    {{
      "prediction": "Chinese prediction",
      "time_horizon": "e.g. 1-2周 / 1-3个月",
      "confidence": "高/中/低",
      "rationale": "Chinese rationale grounded in today's signals"
    }}
  ],
  "ideas": [
    {{
      "title": "Chinese idea title",
      "detail": "Chinese idea description with core method intuition",
      "why_now": "Why this is timely now",
      "basis": "What papers/signals this idea is based on"
    }}
  ],
  "watchlist": [
    {{
      "item": "Chinese watch item",
      "reason": "Chinese reason"
    }}
  ]
}}

Requirements:
- Use the four section titles above when evidence exists; if one section has no real evidence, omit it rather than inventing content.
- Keep "themes" to at most {self.theme_count}.
- Keep "predictions" to exactly {self.prediction_count} if enough evidence exists, otherwise fewer.
- Keep "ideas" to exactly {self.idea_count} if enough evidence exists, otherwise fewer.
- In the opening and interpretation, write fluent continuous prose, not bullet fragments.
- In the signals list, prefer the strongest evidence rather than exhaustive coverage.
- For papers and technical posts, favor TLDR + method/pipeline explanations over vague trend talk.
"""

    @staticmethod
    def _clean_llm_json(raw: str) -> str:
        cleaned = str(raw or "").strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        first_brace = cleaned.find("{")
        last_brace = cleaned.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            cleaned = cleaned[first_brace:last_brace + 1]
        return cleaned.strip()

    @staticmethod
    def _normalize_signal(signal: dict[str, Any]) -> dict[str, str]:
        return {
            "source": str(signal.get("source", "")).strip(),
            "title": str(signal.get("title", "")).strip(),
            "why_it_matters": str(signal.get("why_it_matters", "")).strip(),
            "url": str(signal.get("url", "")).strip(),
        }

    def _fallback_signals(self, filtered_items: list[dict], limit: int = 3) -> list[dict[str, str]]:
        signals = []
        for item in filtered_items[:limit]:
            signals.append(
                {
                    "source": str(item.get("source", "")),
                    "title": str(item.get("title", "")),
                    "why_it_matters": str(item.get("summary", "")),
                    "url": str(item.get("url", "")),
                }
            )
        return signals

    def _normalize_report(self, data: dict[str, Any], filtered_items: list[dict]) -> dict[str, Any]:
        title = str(data.get("report_title", "")).strip() or self.report_title
        subtitle = str(data.get("subtitle", "")).strip()
        opening = str(data.get("opening", "")).strip()
        item_by_url = {
            str(item.get("url", "")).strip(): item
            for item in filtered_items
            if str(item.get("url", "")).strip()
        }
        item_by_title = {
            str(item.get("title", "")).strip(): item
            for item in filtered_items
            if str(item.get("title", "")).strip()
        }

        themes = []
        for theme in data.get("themes") or []:
            if not isinstance(theme, dict):
                continue
            theme_title = str(theme.get("title", "")).strip()
            narrative = str(theme.get("narrative", "")).strip()
            signals = []
            for signal in theme.get("signals") or []:
                if isinstance(signal, dict):
                    normalized_signal = self._normalize_signal(signal)
                    matched_item = None
                    if normalized_signal["url"]:
                        matched_item = item_by_url.get(normalized_signal["url"])
                    if not matched_item and normalized_signal["title"]:
                        matched_item = item_by_title.get(normalized_signal["title"])
                    if matched_item:
                        if not normalized_signal["source"]:
                            normalized_signal["source"] = str(matched_item.get("source", "")).strip()
                        if not normalized_signal["why_it_matters"]:
                            normalized_signal["why_it_matters"] = str(
                                matched_item.get("summary", "")
                            ).strip()
                    if normalized_signal["title"]:
                        signals.append(normalized_signal)
            if theme_title and narrative:
                themes.append(
                    {
                        "title": theme_title,
                        "narrative": narrative,
                        "signals": signals or self._fallback_signals(filtered_items, limit=2),
                    }
                )
        themes = themes[: self.theme_count]

        interpretation_raw = data.get("interpretation") or {}
        if not isinstance(interpretation_raw, dict):
            interpretation_raw = {}
        interpretation = {
            "thesis": str(interpretation_raw.get("thesis", "")).strip(),
            "implications": str(interpretation_raw.get("implications", "")).strip(),
        }

        predictions = []
        for prediction in data.get("predictions") or []:
            if not isinstance(prediction, dict):
                continue
            content = str(prediction.get("prediction", "")).strip()
            if not content:
                continue
            predictions.append(
                {
                    "prediction": content,
                    "time_horizon": str(prediction.get("time_horizon", "")).strip(),
                    "confidence": str(prediction.get("confidence", "")).strip(),
                    "rationale": str(prediction.get("rationale", "")).strip(),
                }
            )
        predictions = predictions[: self.prediction_count]

        ideas = []
        for idea in data.get("ideas") or []:
            if not isinstance(idea, dict):
                continue
            idea_title = str(idea.get("title", "")).strip()
            if not idea_title:
                continue
            ideas.append(
                {
                    "title": idea_title,
                    "detail": str(idea.get("detail", "")).strip(),
                    "why_now": str(idea.get("why_now", "")).strip(),
                    "basis": str(idea.get("basis", "")).strip(),
                }
            )
        ideas = ideas[: self.idea_count]

        watchlist = []
        for watch in data.get("watchlist") or []:
            if not isinstance(watch, dict):
                continue
            item = str(watch.get("item", "")).strip()
            reason = str(watch.get("reason", "")).strip()
            if item:
                watchlist.append({"item": item, "reason": reason})

        return {
            "report_title": title,
            "subtitle": subtitle,
            "opening": opening,
            "themes": themes,
            "interpretation": interpretation,
            "predictions": predictions,
            "ideas": ideas,
            "watchlist": watchlist,
            "metadata": {
                "date": self.run_date,
                "generated_at": self.run_datetime.isoformat(),
                "source_counts": {
                    source_name: len(recs) for source_name, recs in self.all_recs.items()
                },
                "input_item_count": len(filtered_items),
            },
        }

    def generate(self) -> dict[str, Any] | None:
        filtered = self._filter_items()
        if not filtered:
            print("[ReportGenerator] No recommendation items available for report generation.")
            return None

        print(
            f"[ReportGenerator] Building report from {len(filtered)} curated items "
            f"(min_score={self.min_score})."
        )
        prompt = self._build_prompt(filtered)
        raw = self.model.inference(prompt, temperature=self.llm_config.temperature)
        cleaned = self._clean_llm_json(raw)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            print(f"[ReportGenerator] Failed to parse report JSON: {e}")
            print(f"[ReportGenerator] Raw response (first 600 chars): {cleaned[:600]}")
            return None

        if not isinstance(data, dict):
            print("[ReportGenerator] LLM response is not a JSON object.")
            return None

        report = self._normalize_report(data, filtered)
        report["input_items"] = filtered
        return report

    def render_email(self, report: dict[str, Any]) -> str:
        html = render_report_email(report)
        if self.common_config.save:
            os.makedirs(self.save_dir, exist_ok=True)
            with open(self.email_cache_path, "w", encoding="utf-8") as f:
                f.write(html)
        return html

    def save(self, report: dict[str, Any]) -> None:
        if not self.common_config.save:
            print("[ReportGenerator] Save disabled, skipping.")
            return

        os.makedirs(self.save_dir, exist_ok=True)

        json_path = os.path.join(self.save_dir, "report.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        snapshot_json_path = os.path.join(self.save_dir, f"report_{self.run_stamp}.json")
        with open(snapshot_json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"[ReportGenerator] JSON saved to {snapshot_json_path}")

        md_path = os.path.join(self.save_dir, f"report_{self.run_stamp}.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(f"# {report.get('report_title', self.report_title)}\n")
            subtitle = str(report.get("subtitle", "")).strip()
            if subtitle:
                f.write(f"> {subtitle}\n\n")
            f.write(f"- 日期：{self.run_date}\n")
            f.write(
                f"- 覆盖来源："
                f"{', '.join(f'{name}({count})' for name, count in report.get('metadata', {}).get('source_counts', {}).items())}\n\n"
            )

            opening = str(report.get("opening", "")).strip()
            if opening:
                f.write("## 今日主线\n\n")
                f.write(opening + "\n\n")

            themes = report.get("themes") or []
            for index, theme in enumerate(themes, 1):
                f.write(f"### {index}. {theme.get('title', 'Untitled')}\n\n")
                f.write(str(theme.get("narrative", "")).strip() + "\n\n")
                signals = theme.get("signals") or []
                if signals:
                    f.write("关键信号：\n")
                    for signal in signals:
                        title = signal.get("title", "Untitled")
                        url = signal.get("url", "")
                        why = signal.get("why_it_matters", "")
                        source = signal.get("source", "")
                        if url:
                            f.write(f"- [{source}] [{title}]({url})：{why}\n")
                        else:
                            f.write(f"- [{source}] {title}：{why}\n")
                    f.write("\n")

            interpretation = report.get("interpretation") or {}
            thesis = str(interpretation.get("thesis", "")).strip()
            implications = str(interpretation.get("implications", "")).strip()
            if thesis or implications:
                f.write("## 我的判断\n\n")
                if thesis:
                    f.write(thesis + "\n\n")
                if implications:
                    f.write(implications + "\n\n")

            predictions = report.get("predictions") or []
            if predictions:
                f.write("## 短期预测\n\n")
                for prediction in predictions:
                    f.write(
                        f"- **{prediction.get('prediction', '')}**"
                        f"（时间：{prediction.get('time_horizon', '未注明')}，"
                        f"置信度：{prediction.get('confidence', '未注明')}）"
                        f"：{prediction.get('rationale', '')}\n"
                    )
                f.write("\n")

            ideas = report.get("ideas") or []
            if ideas:
                f.write("## 可行动的想法\n\n")
                for idea in ideas:
                    f.write(f"### {idea.get('title', 'Untitled')}\n")
                    if idea.get("detail"):
                        f.write(f"{idea.get('detail')}\n\n")
                    if idea.get("why_now"):
                        f.write(f"- 为什么是现在：{idea.get('why_now')}\n\n")
                    if idea.get("basis"):
                        f.write(f"- 依据：{idea.get('basis')}\n\n")

            watchlist = report.get("watchlist") or []
            if watchlist:
                f.write("## 继续跟踪\n\n")
                for watch in watchlist:
                    f.write(f"- **{watch.get('item', '')}**：{watch.get('reason', '')}\n")
                f.write("\n")
        print(f"[ReportGenerator] Markdown saved to {md_path}")

    def send_email(self, report: dict[str, Any], email_config: EmailConfig):
        html = self.render_email(report)
        BaseSource._send_email_html(html, email_config, self.report_title, self.run_datetime)

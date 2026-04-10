import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import CommonConfig, LLMConfig
from idea_generator import IdeaGenerator


class DummyModel:
    def __init__(self, response: str):
        self.response = response
        self.last_prompt = None

    def inference(self, prompt, temperature=0.7):
        self.last_prompt = prompt
        return self.response


def load_sample_recommendations() -> dict[str, list[dict]]:
    return {
        "github": [
            {
                "title": "AgentLab",
                "repo_name": "openai/agentlab",
                "summary": "TLDR：这是一个面向工具使用 Agent 的实验平台，强调多步决策和任务执行。",
                "url": "https://github.com/openai/agentlab",
                "score": 8.8,
                "stars": 5200,
                "stars_today": 340,
            },
            {
                "title": "DiffusionPolicyX",
                "repo_name": "robot/diffusion-policy-x",
                "summary": "TLDR：把 diffusion policy 用到复杂控制任务，强调稳定训练和部署。",
                "url": "https://github.com/robot/diffusion-policy-x",
                "score": 7.6,
                "stars": 1800,
                "stars_today": 120,
            },
        ],
        "huggingface": [
            {
                "title": "Unified MLLM Reasoner",
                "summary": "TLDR：一个生成-理解统一的 MLLM，兼顾多模态理解和生成。",
                "url": "https://huggingface.co/papers/1234.5678",
                "score": 8.5,
                "upvotes": 91,
                "_hf_type": "paper",
            }
        ],
        "twitter": [
            {
                "title": "@researcher: New RL post-training thread",
                "summary": "TLDR：一条关于 RL 后训练与蒸馏结合的高信息密度线程，强调实践 recipe。",
                "url": "https://x.com/researcher/status/1",
                "score": 7.9,
                "likes": 440,
                "retweets": 88,
            }
        ],
    }


class IdeaGeneratorTest(unittest.TestCase):
    def setUp(self):
        self.all_recs = load_sample_recommendations()
        self.llm_config = LLMConfig(
            provider="openai",
            model="dummy-model",
            base_url="https://example.com/v1",
            api_key="dummy-key",
            temperature=0.2,
        )
        self.common_config = CommonConfig(
            description="Agent / Safety / Trustworthy",
            num_workers=1,
            save=True,
            save_dir="./history",
        )
        self.generator = IdeaGenerator(
            all_recs=self.all_recs,
            profile_path=str(ROOT / "profiles" / "researcher_profile.md"),
            llm_config=self.llm_config,
            common_config=self.common_config,
            min_score=7,
            max_items=6,
            idea_count=3,
        )

    def test_filter_items_keeps_high_scores_and_diversity(self):
        filtered = self.generator._filter_items(self.all_recs)

        self.assertLessEqual(len(filtered), 6)
        self.assertTrue(all(item["score"] >= 7 for item in filtered))
        self.assertGreaterEqual(len({item["_source"] for item in filtered}), 2)

    def test_generate_normalizes_llm_output(self):
        self.generator.model = DummyModel(
            """```json
            [
              {
                "title": "代理记忆安全基准",
                "research_direction": "Benchmark agent memory editing under adversarial task drift",
                "hypothesis": "如果显式建模记忆写入与安全冲突，Agent 的长程任务鲁棒性会更高",
                "hypothesis_en": "Explicitly modeling the conflict between memory writes and safety constraints improves long-horizon robustness.",
                "idea_basis": "来自 GitHub 的 AgentLab、HuggingFace 论文 Unified MLLM Reasoner，以及 X 上关于 RL 后训练的线程。",
                "core_insight": "把 agent memory control、统一多模态推理和 RL 后训练校准放到同一评测框架里，可以更早暴露长期任务中的错误传播。",
                "plan_outline": "先做一个最小评测基准，比较无约束 memory、规则约束 memory 和 RL 后训练 memory 三种方案。",
                "inspired_by": [
                  {"title": "agentscope-ai/ReMe", "source": "github", "url": "https://github.com/agentscope-ai/ReMe"}
                ],
                "connects_to_project": "ATbench_Engine",
                "interest_area": "Safety",
                "novelty_estimate": "medium",
                "feasibility": "high",
                "composite_score": "8.7",
                "min_experiment": "在 ATbench_Engine 上加入记忆污染与任务漂移设置，比较带约束与不带约束的记忆模块。"
              }
            ]
            ```"""
        )

        ideas = self.generator.generate()

        self.assertEqual(len(ideas), 1)
        self.assertEqual(ideas[0]["id"], f"idea-{self.generator.run_date}-001")
        self.assertEqual(ideas[0]["novelty_estimate"], "MEDIUM")
        self.assertEqual(ideas[0]["feasibility"], "HIGH")
        self.assertEqual(ideas[0]["composite_score"], 8.7)
        self.assertIn("ATbench_Engine", ideas[0]["connects_to_project"])
        self.assertIn("AgentLab", ideas[0]["idea_basis"])
        self.assertIn("最小评测基准", ideas[0]["plan_outline"])

    def test_save_and_render_email_write_artifacts(self):
        ideas = [
            {
                "id": "idea-2026-03-06-001",
                "title": "代理记忆安全基准",
                "title_en": "Agent Memory Safety Benchmark",
                "research_direction": "Benchmark agent memory editing under adversarial task drift",
                "hypothesis": "如果显式建模记忆写入与安全冲突，Agent 的长程任务鲁棒性会更高",
                "hypothesis_en": "Explicitly modeling the conflict between memory writes and safety constraints improves long-horizon robustness.",
                "idea_basis": "来自多源日报的 agent、MLLM 与 RL 后训练线索。",
                "core_insight": "把记忆控制和后训练结合进统一评测框架。",
                "plan_outline": "先构建小规模 benchmark，再对比三种 memory 策略。",
                "inspired_by": [
                    {
                        "title": "agentscope-ai/ReMe",
                        "source": "github",
                        "url": "https://github.com/agentscope-ai/ReMe",
                    }
                ],
                "connects_to_project": "ATbench_Engine",
                "interest_area": "Safety",
                "novelty_estimate": "MEDIUM",
                "feasibility": "HIGH",
                "composite_score": 8.7,
                "min_experiment": "在 ATbench_Engine 上加入记忆污染与任务漂移设置。",
            }
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            self.generator.save_dir = tmpdir
            self.generator.email_cache_path = str(Path(tmpdir) / "ideas_email.html")

            self.generator.save(ideas)
            html = self.generator.render_email(ideas)

            self.assertTrue((Path(tmpdir) / "ideas.json").exists())
            self.assertTrue(list(Path(tmpdir).glob("ideas_*.md")))
            self.assertTrue((Path(tmpdir) / "ideas_email.html").exists())
            self.assertIn("/idea-from-daily", html)


if __name__ == "__main__":
    unittest.main()

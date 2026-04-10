import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
GPT_PATH = ROOT / "llm" / "GPT.py"
SPEC = importlib.util.spec_from_file_location("ideer_llm_gpt", GPT_PATH)
GPT_MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(GPT_MODULE)
GPT = GPT_MODULE.GPT


class GPTResponseExtractionTest(unittest.TestCase):
    def test_extract_response_text_from_plain_string(self):
        message = SimpleNamespace(content='{"ok": true}', reasoning_content=None)

        text = GPT._extract_response_text(message)

        self.assertEqual(text, '{"ok": true}')

    def test_extract_response_text_from_content_parts(self):
        message = SimpleNamespace(
            content=[
                {"type": "text", "text": '{"summary": "hello"}'},
                {"type": "input_text", "text": "ignored"},
            ],
            reasoning_content=None,
        )

        text = GPT._extract_response_text(message)

        self.assertEqual(text, '{"summary": "hello"}\nignored')

    def test_extract_response_text_raises_for_empty_message(self):
        message = SimpleNamespace(content=None, reasoning_content=None, refusal=None, tool_calls=None)

        with self.assertRaisesRegex(ValueError, "did not contain assistant text content"):
            GPT._extract_response_text(message)

    def test_call_gpt_eval_falls_back_to_stream_when_non_stream_content_is_empty(self):
        class FakeCompletions:
            def __init__(self):
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                if kwargs.get("stream"):
                    return iter([
                        SimpleNamespace(
                            choices=[SimpleNamespace(delta=SimpleNamespace(content="Hello"))]
                        ),
                        SimpleNamespace(
                            choices=[SimpleNamespace(delta=SimpleNamespace(content=" world"))]
                        ),
                        SimpleNamespace(
                            choices=[SimpleNamespace(delta=SimpleNamespace(content="!"))]
                        ),
                    ])
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=None, reasoning_content=None))]
                )

        gpt = GPT.__new__(GPT)
        fake_completions = FakeCompletions()
        gpt.client = SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))

        text = gpt.call_gpt_eval(
            message=[{"role": "user", "content": "hello"}],
            model_name="gpt-5.4",
            retries=1,
        )

        self.assertEqual(text, "Hello world!")
        self.assertEqual(len(fake_completions.calls), 2)
        self.assertFalse(fake_completions.calls[0].get("stream", False))
        self.assertTrue(fake_completions.calls[1].get("stream", False))


if __name__ == "__main__":
    unittest.main()

"""
Use GPT Series Models
"""

from openai import OpenAI
import time

class GPT():
    def __init__(self, model, base_url, api_key):
        self.model_name = model
        self.base_url = base_url
        self.api_key = api_key

        self._init_model()

    def _init_model(self):
        self.client = OpenAI(base_url= self.base_url, api_key=self.api_key)

    def build_prompt(self, question):
        message = []

        message.append(
            {
                "type": "text",
                "text": question,
            }
        )

        prompt =  [
            {
                "role": "user",
                "content": message
            }
        ]
        return prompt

    def call_gpt_eval(self, message, model_name, retries=10, wait_time=1, temperature=0.0):
        for i in range(retries):
            try:
                request_kwargs = self._build_request_kwargs(message, model_name, temperature)
                result = self.client.chat.completions.create(**request_kwargs)
                try:
                    response_message = self._extract_response_text(result.choices[0].message)
                except ValueError as exc:
                    response_message = self._collect_streaming_text(request_kwargs, exc)
                return response_message
            except Exception as e:
                if i < retries - 1:
                    print(f"Failed to call the API {i+1}/{retries}, will retry after {wait_time} seconds.")
                    print(e)
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"Failed to call the API after {retries} attempts.")
                    print(e)
                    raise

    def inference(self, prompt, temperature=0.7):
        prompt = self.build_prompt(prompt)
        response = self.call_gpt_eval(prompt, self.model_name, temperature=temperature)
        return response

    @staticmethod
    def _build_request_kwargs(message, model_name, temperature):
        request_kwargs = {
            "model": model_name,
            "messages": message,
            "temperature": temperature,
        }
        if str(model_name).startswith("gpt-5"):
            request_kwargs["extra_body"] = {"reasoning_effort": "low"}
        return request_kwargs

    def _collect_streaming_text(self, request_kwargs, original_error):
        stream_kwargs = dict(request_kwargs)
        stream_kwargs["stream"] = True
        stream = self.client.chat.completions.create(**stream_kwargs)
        text = self._extract_stream_text(stream)
        if text:
            return self._normalize_response_text(text)
        raise original_error

    @classmethod
    def _extract_response_text(cls, message):
        candidates = []

        content = getattr(message, "content", None)
        text = cls._content_to_text(content)
        if text:
            return cls._normalize_response_text(text)
        candidates.append(("content", content))

        reasoning_content = getattr(message, "reasoning_content", None)
        text = cls._content_to_text(reasoning_content)
        if text:
            return cls._normalize_response_text(text)
        candidates.append(("reasoning_content", reasoning_content))

        raise ValueError(
            "LLM response did not contain assistant text content. "
            f"Message fields: {candidates}"
        )

    @staticmethod
    def _content_to_text(content):
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return None

        chunks = []
        for part in content:
            text = None
            if isinstance(part, dict):
                text = part.get("text")
            else:
                text = getattr(part, "text", None)

            if isinstance(text, str) and text.strip():
                chunks.append(text)

        if not chunks:
            return None
        return "\n".join(chunks)

    @classmethod
    def _extract_stream_text(cls, stream):
        chunks = []
        for event in stream:
            choices = getattr(event, "choices", None) or []
            for choice in choices:
                delta = getattr(choice, "delta", None)
                if delta is None:
                    continue
                content = getattr(delta, "content", None)
                text = cls._content_to_text(content)
                if text:
                    chunks.append(text)
                    continue
                if isinstance(content, str) and content:
                    chunks.append(content)
        if not chunks:
            return None
        return "".join(chunks)

    @staticmethod
    def _normalize_response_text(text):
        if not isinstance(text, str):
            return text

        stripped = text.strip()
        if not stripped.startswith("```"):
            return stripped

        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()

        return stripped

if __name__ == "__main__":
    # Test GPT
    model = "gpt-3.5-turbo"
    base_url = "https://api.openai.com/v1"
    api_key = "*"

    # Test SiliconFlow
    model = "deepseek-ai/DeepSeek-V3"
    base_url = "https://api.siliconflow.cn/v1"
    api_key = "*"
    gpt = GPT(model, base_url, api_key)
    prompt = "Hello, who are you?"
    response = gpt.inference(prompt, temperature=1)
    print(response)

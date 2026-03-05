from ollama import generate
import json

class Ollama:
    def __init__(self, model):
        self.model_name = model

    def inference(self, prompt, temperature=0.7):
        response = generate(self.model_name, prompt, options={"temperature": temperature})["response"]
        # Handle models that use <think> tags (like deepseek-r1)
        if "</think>" in response:
            response = response.split("</think>")[-1].strip()
        return response

if __name__ == "__main__":
    model = "deepseek-r1:7b"
    ollama = Ollama(model)
    prompt = "Hello, who are you?"
    response = ollama.inference(prompt)
    print(response)

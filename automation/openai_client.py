from __future__ import annotations

import base64
from typing import Any

import requests


class OpenAIClient:
    def __init__(self, api_key: str, model: str = "gpt-4.1-mini", timeout: int = 60) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.base_url = "https://api.openai.com/v1"

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def text(self, system_prompt: str, user_prompt: str, max_output_tokens: int = 450) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
                {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
            ],
            "max_output_tokens": max_output_tokens,
        }
        response = requests.post(
            f"{self.base_url}/responses",
            json=payload,
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        output_text = data.get("output_text", "")
        if output_text:
            return output_text.strip()

        parts: list[str] = []
        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    parts.append(content.get("text", ""))
        return "\n".join(p for p in parts if p).strip()

    def generate_image_b64(self, prompt: str, size: str = "1024x1024") -> str:
        payload = {
            "model": "gpt-image-1",
            "prompt": prompt,
            "size": size,
        }
        response = requests.post(
            f"{self.base_url}/images/generations",
            json=payload,
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        image_data = data.get("data", [])
        if not image_data:
            raise RuntimeError("No image returned from OpenAI")
        b64 = image_data[0].get("b64_json")
        if not b64:
            raise RuntimeError("No b64_json returned from OpenAI image API")
        return b64

    @staticmethod
    def save_b64_image(b64_value: str, output_path: str) -> None:
        with open(output_path, "wb") as f:
            f.write(base64.b64decode(b64_value))


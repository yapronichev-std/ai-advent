import json
from pathlib import Path

SYSTEM_PROMPT_FILE = Path("memory") / "system_prompt.json"
DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant. Answer clearly and concisely."


def load_system_prompt() -> str:
    if SYSTEM_PROMPT_FILE.exists():
        return json.loads(SYSTEM_PROMPT_FILE.read_text(encoding="utf-8")).get("prompt", DEFAULT_SYSTEM_PROMPT)
    return DEFAULT_SYSTEM_PROMPT


def save_system_prompt(prompt: str) -> None:
    SYSTEM_PROMPT_FILE.parent.mkdir(parents=True, exist_ok=True)
    SYSTEM_PROMPT_FILE.write_text(
        json.dumps({"prompt": prompt}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
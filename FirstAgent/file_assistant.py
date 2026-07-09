"""
FileAssistant agent that actively works with project files.

Follows ChatAgent's dynamic tool-calling pattern (_call_api with tool loop),
NOT SupportAgent's hardcoded pattern. Uses the shared MultiMCPClient to
access search_content, write_file, read_file, and other git/project tools.
"""

import asyncio
import json
import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
MAX_TOOL_RESULT_CHARS = 10_000
MAX_HISTORY = 20

FILE_ASSISTANT_SYSTEM_PROMPT = """You are a File Assistant that proactively works with project files.
Your job is to read, search, analyze, create, and modify files — not just chat about them.

You have access to these tools:
- search_content: Search for text/regex patterns across all project files (like grep). Returns file paths, line numbers, and matching lines.
- edit_file: Make a targeted edit to a file by replacing one exact string with another. The best tool for small/surgical changes — you don't need to read the whole file first, just provide the exact old_string to replace and the new_string.
- write_file: Create or overwrite an entire file. Use this for new files or when you need to rewrite the whole content.
- read_file: Read a file's contents (truncated to 500 lines, 200KB max). Use this to understand a file before editing.
- list_project_files: List files in the project, optionally filtered by glob pattern (e.g. '*.py').
- get_git_branch: Get current branch, last commit info, and all branches.
- get_git_status: Get working tree status — staged, unstaged, untracked files.
- get_git_diff: Get git diff of current changes (unstaged or staged).
- set_project_root: Change the project directory all tools operate on.

CRITICAL RULES:
1. BE PROACTIVE — given a goal-level task, decide which tools to call. Do NOT ask the user to open files for you.
2. READ BEFORE WRITING — always read_file() before modifying an existing file.
3. WRITE DIRECTLY — when you need to create or modify a file, call write_file(diff_only=false) and apply the change.
   You can optionally call write_file(diff_only=true) first to preview, but then proceed to apply in the same turn.
   NEVER give the user a script or tell them to edit files manually — YOU have the tools, YOU make the changes.
4. SEARCH EFFICIENTLY — use search_content to find occurrences across the codebase.
5. WORK WITH MULTIPLE FILES — aim to touch 2-3+ files per task where appropriate.
6. SUMMARIZE RESULTS — after completing the task, explain what you found, what you changed, and why.
7. BE CAREFUL — never delete files. When creating new documentation, use .md extension for readability.

EXAMPLES OF GOOD TASKS:
- "Find all usages of the ChatAgent class and summarize"
- "Update README.md to reflect the new /file endpoints"
- "Generate a CHANGELOG.md based on recent git commits"
- "Check all Python files for proper error handling patterns"
- "Find where environment variables are read and document them"

Always respond in the same language the user used for the task.
"""


class FileAssistant:
    """Agent that actively works with project files using dynamic tool calling."""

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-direct/deepseek-chat",
        deepseek_api_key: str = "",
        mcp_client=None,  # MultiMCPClient
    ):
        self.api_key = api_key
        self.deepseek_api_key = deepseek_api_key
        self.model = model
        self.mcp_client = mcp_client
        self._sessions: dict[str, list[dict]] = {}

    def _get_session(self, session_id: str) -> list[dict]:
        if session_id not in self._sessions:
            self._sessions[session_id] = []
        return self._sessions[session_id]

    def _resolve_model_id(self, model_id: str) -> tuple[str, str]:
        """Return (provider, actual_model_name)."""
        if model_id.startswith("deepseek-direct/"):
            return "deepseek", model_id[len("deepseek-direct/"):]
        return "openrouter", model_id

    async def execute(self, task: str, session_id: str = "default") -> dict:
        """Execute a file-related task with dynamic tool calling.

        Returns:
            dict with keys: answer, files_affected, usage, elapsed_ms, error
        """
        t0 = time.monotonic()

        session = self._get_session(session_id)
        session.append({"role": "user", "content": task})

        # Build messages: system prompt + recent history
        messages = [
            {"role": "system", "content": FILE_ASSISTANT_SYSTEM_PROMPT},
        ]
        # Include only the last N messages to stay within context limits
        recent = session[-MAX_HISTORY:]
        messages.extend(recent)

        try:
            answer, usage, files_affected = await self._call_api(messages)
            session.append({"role": "assistant", "content": answer})
            elapsed_ms = round((time.monotonic() - t0) * 1000)
            return {
                "answer": answer,
                "files_affected": files_affected,
                "usage": usage,
                "elapsed_ms": elapsed_ms,
            }
        except Exception as exc:
            logger.exception("[file_assistant] execution failed")
            elapsed_ms = round((time.monotonic() - t0) * 1000)
            return {
                "answer": "",
                "files_affected": [],
                "usage": {},
                "elapsed_ms": elapsed_ms,
                "error": str(exc),
            }

    async def _call_api(self, messages: list[dict]) -> tuple[str, dict, list[str]]:
        """Dynamic tool-calling loop.

        Follows ChatAgent._call_api (agent.py:1027-1106):
        - Send messages + tools to LLM
        - If finish_reason == "tool_calls", dispatch to MCP client
        - Append tool results and re-call LLM
        - Loop until text response

        Returns:
            (response_text, usage_dict, files_affected_list)
        """
        provider, actual_model = self._resolve_model_id(self.model)

        if provider == "deepseek":
            api_url = DEEPSEEK_URL
            auth_key = self.deepseek_api_key
        else:
            api_url = OPENROUTER_URL
            auth_key = self.api_key

        headers = {
            "Authorization": f"Bearer {auth_key}",
            "Content-Type": "application/json",
        }

        tools = self.mcp_client.tools if self.mcp_client else []
        current_messages = list(messages)
        total_usage: dict = {}
        files_affected: list[str] = []

        async with httpx.AsyncClient(timeout=120.0) as client:
            while True:
                payload: dict = {"model": actual_model, "messages": current_messages}
                if tools:
                    payload["tools"] = tools
                    payload["tool_choice"] = "auto"

                for attempt in range(6):
                    response = await client.post(api_url, headers=headers, json=payload)
                    if response.status_code == 429:
                        retry_after = response.headers.get("Retry-After")
                        wait = int(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt
                        wait = min(wait, 60)
                        logger.warning(
                            "[file_assistant] 429 rate limit, retrying in %ds (attempt %d/6)",
                            wait, attempt + 1,
                        )
                        await asyncio.sleep(wait)
                        continue
                    response.raise_for_status()
                    break
                else:
                    raise RuntimeError("Rate limit exceeded after 6 retries")

                data = response.json()
                total_usage = data.get("usage", {})

                if "choices" not in data or not data["choices"]:
                    err_msg = data.get("error", {}).get("message") or str(data)
                    logger.error("[file_assistant] API response missing 'choices': %s", data)
                    raise RuntimeError(f"API error: {err_msg}")

                choice = data["choices"][0]
                message = choice["message"]
                finish_reason = choice.get("finish_reason")

                if finish_reason == "tool_calls" and self.mcp_client:
                    current_messages.append(message)
                    for tool_call in message.get("tool_calls", []):
                        fn = tool_call["function"]
                        arguments = (
                            json.loads(fn["arguments"])
                            if isinstance(fn["arguments"], str)
                            else fn["arguments"]
                        )
                        logger.info(
                            "[file_assistant] tool call: %s(%s)",
                            fn["name"],
                            ", ".join(f"{k}={v!r}" for k, v in arguments.items()),
                        )
                        result = await self.mcp_client.call_tool(fn["name"], arguments)

                        # Track files affected by write operations
                        if fn["name"] == "write_file":
                            file_path = arguments.get("path", "")
                            diff_only = arguments.get("diff_only", False)
                            if not diff_only:
                                try:
                                    result_obj = json.loads(result)
                                    if result_obj.get("ok"):
                                        files_affected.append(file_path)
                                except (json.JSONDecodeError, AttributeError):
                                    pass

                        # Truncate large tool results before sending to LLM
                        if len(result) > MAX_TOOL_RESULT_CHARS:
                            result = result[:MAX_TOOL_RESULT_CHARS] + "\n... [truncated]"

                        current_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "content": result,
                        })
                else:
                    return message["content"], total_usage, files_affected

    async def execute_stream(self, task: str, session_id: str = "default"):
        """Execute a file-related task with SSE streaming of the final response.

        Yields SSE event dicts: {"token": "..."} for content chunks,
        {"tool": "name", "args": {...}} for tool call start,
        {"done": True, "files_affected": [...], "usage": {...}} on completion.
        """
        t0 = time.monotonic()

        session = self._get_session(session_id)
        session.append({"role": "user", "content": task})

        messages = [
            {"role": "system", "content": FILE_ASSISTANT_SYSTEM_PROMPT},
        ]
        recent = session[-MAX_HISTORY:]
        messages.extend(recent)

        full_answer = ""
        total_usage: dict = {}
        files_affected: list[str] = []

        try:
            async for event in self._call_api_stream(messages):
                if "token" in event:
                    full_answer += event["token"]
                if "tool" in event:
                    pass  # tool call events pass through
                if event.get("done"):
                    total_usage = event.get("usage", {})
                    files_affected = event.get("files_affected", [])
                yield event

            session.append({"role": "assistant", "content": full_answer})
        except Exception as exc:
            logger.exception("[file_assistant] streaming execution failed")
            yield {
                "token": f"\n[ERROR] {exc}",
                "done": True,
                "files_affected": [],
                "usage": {},
                "error": str(exc),
            }

    async def _call_api_stream(self, messages: list[dict]):
        """Streaming version of _call_api with tool-calling loop.

        Yields SSE-compatible dicts.
        """
        provider, actual_model = self._resolve_model_id(self.model)

        if provider == "deepseek":
            api_url = DEEPSEEK_URL
            auth_key = self.deepseek_api_key
        else:
            api_url = OPENROUTER_URL
            auth_key = self.api_key

        headers = {
            "Authorization": f"Bearer {auth_key}",
            "Content-Type": "application/json",
        }

        tools = self.mcp_client.tools if self.mcp_client else []
        current_messages = list(messages)
        total_usage: dict = {}
        files_affected: list[str] = []

        async with httpx.AsyncClient(timeout=180.0) as client:
            while True:
                payload = {
                    "model": actual_model,
                    "messages": current_messages,
                    "stream": True,
                }
                if tools:
                    payload["tools"] = tools
                    payload["tool_choice"] = "auto"

                # ── Collect streaming chunks ────────────────────────────────
                full_content = ""
                tool_calls: list[dict] = []  # accumulated tool calls
                finish_reason = None

                for attempt in range(6):
                    try:
                        async with client.stream(
                            "POST", api_url, headers=headers, json=payload
                        ) as resp:
                            if resp.status_code == 429:
                                retry_after = resp.headers.get("Retry-After")
                                wait = int(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt
                                wait = min(wait, 60)
                                logger.warning(
                                    "[file_assistant] 429, retrying in %ds (attempt %d/6)",
                                    wait, attempt + 1,
                                )
                                await asyncio.sleep(wait)
                                break  # break out of the with block, retry
                            resp.raise_for_status()

                            async for line in resp.aiter_lines():
                                if not line.startswith("data: "):
                                    continue
                                data_str = line[6:]
                                if data_str == "[DONE]":
                                    break

                                try:
                                    chunk = json.loads(data_str)
                                except json.JSONDecodeError:
                                    continue

                                total_usage = chunk.get("usage", total_usage)

                                choices = chunk.get("choices", [])
                                if not choices:
                                    continue

                                delta = choices[0].get("delta", {})
                                finish_reason = choices[0].get("finish_reason") or finish_reason

                                # Content token
                                content = delta.get("content", "")
                                if content:
                                    full_content += content
                                    yield {"token": content}

                                # Accumulate tool calls from streaming deltas
                                tc_deltas = delta.get("tool_calls", [])
                                for tc in tc_deltas:
                                    idx = tc.get("index", 0)
                                    while len(tool_calls) <= idx:
                                        tool_calls.append({
                                            "id": "",
                                            "type": "function",
                                            "function": {"name": "", "arguments": ""},
                                        })
                                    if tc.get("id"):
                                        tool_calls[idx]["id"] = tc["id"]
                                    fn = tc.get("function", {})
                                    if fn.get("name"):
                                        tool_calls[idx]["function"]["name"] = fn["name"]
                                    if fn.get("arguments"):
                                        tool_calls[idx]["function"]["arguments"] += fn["arguments"]
                            break  # success, exit retry loop
                    except httpx.HTTPStatusError as e:
                        if e.response.status_code == 429:
                            continue  # retry
                        raise

                # ── Handle tool calls ───────────────────────────────────────
                if finish_reason == "tool_calls" and tool_calls and self.mcp_client:
                    assistant_msg = {
                        "role": "assistant",
                        "content": full_content or None,
                        "tool_calls": tool_calls,
                    }
                    current_messages.append(assistant_msg)

                    for tc in tool_calls:
                        fn = tc["function"]
                        try:
                            arguments = (
                                json.loads(fn["arguments"])
                                if isinstance(fn["arguments"], str)
                                else fn["arguments"]
                            )
                        except json.JSONDecodeError:
                            arguments = {}

                        yield {"tool": fn["name"], "args": arguments}

                        logger.info(
                            "[file_assistant] tool call (stream): %s(%s)",
                            fn["name"],
                            ", ".join(f"{k}={v!r}" for k, v in arguments.items()),
                        )
                        result = await self.mcp_client.call_tool(fn["name"], arguments)

                        # Track files affected
                        if fn["name"] in ("write_file", "edit_file"):
                            file_path = arguments.get("path", "")
                            diff_only = arguments.get("diff_only", False)
                            if not diff_only:
                                try:
                                    result_obj = json.loads(result)
                                    if result_obj.get("ok"):
                                        files_affected.append(file_path)
                                except (json.JSONDecodeError, AttributeError):
                                    pass

                        if len(result) > MAX_TOOL_RESULT_CHARS:
                            result = result[:MAX_TOOL_RESULT_CHARS] + "\n... [truncated]"

                        current_messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result,
                        })
                    # Continue the loop — call LLM again with tool results
                    continue

                # ── Final response ──────────────────────────────────────────
                yield {
                    "done": True,
                    "files_affected": files_affected,
                    "usage": total_usage,
                }
                return

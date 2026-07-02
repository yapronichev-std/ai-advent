"""
MCP server that provides git and project-context tools for the developer assistant.

Transport: stdio (standard MCP pattern).

Available tools:
  - get_git_branch      — current branch name and basic info
  - get_git_status      — working tree status (porcelain)
  - get_git_diff        — diff of unstaged and staged changes
  - list_project_files  — list files in the project directory
  - read_file           — read a file from the project (path-validated)
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)

app = Server("mcp-git-project")

# Project root — can be overridden via env var
PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", Path.cwd())).resolve()

# File extensions to exclude from listing (binary, generated, etc.)
EXCLUDE_EXTENSIONS = {
    ".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib",
    ".exe", ".bin", ".dat", ".db", ".sqlite", ".sqlite3",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg",
    ".mp3", ".mp4", ".avi", ".mov", ".wav",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    ".min.js", ".min.css",
}

EXCLUDE_DIRS = {
    ".git", "__pycache__", ".venv", "venv", ".claude",
    "node_modules", ".idea", ".vscode", ".DS_Store",
    "memory", "diagrams",
}

MAX_FILE_SIZE_READ = 50_000  # 50 KB max for read_file


def _is_safe_path(path_str: str) -> Path:
    """Resolve and validate that the path is inside PROJECT_ROOT."""
    raw = Path(path_str)
    if raw.is_absolute():
        resolved = raw.resolve()
    else:
        resolved = (PROJECT_ROOT / raw).resolve()

    # Must be inside PROJECT_ROOT
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError:
        raise ValueError(f"Path '{path_str}' is outside the project root")

    return resolved


def _run_git(args: list[str], timeout: int = 15) -> dict:
    """Run a git command and return {ok, stdout, stderr}."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "exit_code": result.returncode,
        }
    except FileNotFoundError:
        return {"ok": False, "stdout": "", "stderr": "git executable not found", "exit_code": -1}
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": f"git command timed out after {timeout}s", "exit_code": -1}


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    """Advertise the git and project-context tools."""
    return [
        types.Tool(
            name="get_git_branch",
            description=(
                "Return the current git branch name, along with the latest commit hash, "
                "author, date, and message. Useful for orienting the assistant to the "
                "current development context."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        types.Tool(
            name="get_git_status",
            description=(
                "Return the git working tree status in porcelain v1 format. "
                "Shows staged, unstaged, and untracked files. "
                "Use this to understand what has changed in the project."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        types.Tool(
            name="get_git_diff",
            description=(
                "Return the git diff of current changes. By default returns "
                "unstaged diff. Set staged=true to get staged diff, or "
                "staged=false and path=<file> to diff a specific file."
            ),  
            inputSchema={
                "type": "object",
                "properties": {
                    "staged": {
                        "type": "boolean",
                        "description": "If true, show staged (cached) diff. Default: false (unstaged).",
                        "default": False,
                    },
                    "path": {
                        "type": "string",
                        "description": "Optional: diff only this file path.",
                    },
                },
                "required": [],
            },
        ),
        types.Tool(
            name="set_project_root",
            description=(
                "Change the project root directory that all other git tools operate on. "
                "Call this before using other tools on a different project."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path to the new project root directory.",
                    },
                },
                "required": ["path"],
            },
        ),
        types.Tool(
            name="list_project_files",
            description=(
                "List files in the project directory, optionally filtered by pattern "
                "and limited to a subdirectory. Returns relative paths. "
                "Binary and generated files are excluded."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "subdir": {
                        "type": "string",
                        "description": "Optional subdirectory to list (relative to project root). Default: root.",
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Optional glob pattern to filter files (e.g. '*.py', '*.md').",
                    },
                    "max_files": {
                        "type": "integer",
                        "description": "Maximum number of files to return. Default: 100.",
                        "default": 100,
                    },
                },
                "required": [],
            },
        ),
        types.Tool(
            name="read_file",
            description=(
                "Read the contents of a file from the project directory. "
                "The path must be inside the project root. "
                f"Files larger than {MAX_FILE_SIZE_READ} bytes will be truncated."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file, relative to project root.",
                    },
                    "max_lines": {
                        "type": "integer",
                        "description": "Maximum lines to return. Default: 500.",
                        "default": 500,
                    },
                },
                "required": ["path"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """Dispatch a tool call and return the result as JSON text."""
    logger.info("call_tool: %s  args=%s", name, list(arguments.keys()))

    try:
        if name == "set_project_root":
            result = _handle_set_project_root(arguments)
        elif name == "get_git_branch":
            result = _handle_get_git_branch()
        elif name == "get_git_status":
            result = _handle_get_git_status()
        elif name == "get_git_diff":
            result = _handle_get_git_diff(arguments)
        elif name == "list_project_files":
            result = _handle_list_project_files(arguments)
        elif name == "read_file":
            result = _handle_read_file(arguments)
        else:
            raise ValueError(f"Unknown tool: '{name}'")

        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

    except Exception as exc:
        logger.exception("Error in tool '%s': %s", name, exc)
        return [types.TextContent(type="text", text=json.dumps({"error": str(exc)}))]


# ── Tool handlers ──────────────────────────────────────────────────────────────

def _handle_set_project_root(arguments: dict) -> dict:
    """Change the project root directory."""
    global PROJECT_ROOT
    path_str = arguments.get("path", "")
    if not path_str:
        return {"error": "path is required"}
    p = Path(path_str).resolve()
    if not p.exists():
        return {"error": f"Directory not found: {p}"}
    if not p.is_dir():
        return {"error": f"Not a directory: {p}"}
    PROJECT_ROOT = p
    logger.info("Project root changed to: %s", PROJECT_ROOT)
    return {"ok": True, "project_root": str(PROJECT_ROOT)}


def _handle_get_git_branch() -> dict:
    """Return current branch + last commit info."""
    branch = _run_git(["branch", "--show-current"])
    if not branch["ok"]:
        return {"error": branch["stderr"] or "Could not determine current branch"}

    current_branch = branch["stdout"]

    # Get all local branches for context
    all_branches = _run_git(["branch", "--format=%(refname:short)"])
    branches_list = [
        b.strip() for b in all_branches["stdout"].split("\n") if b.strip()
    ] if all_branches["ok"] else []

    # Last commit info
    log = _run_git([
        "log", "-1", "--format=%H|%an|%ad|%s",
        "--date=relative",
        current_branch,
    ])

    last_commit = None
    if log["ok"] and log["stdout"]:
        parts = log["stdout"].split("|", 3)
        if len(parts) == 4:
            last_commit = {
                "hash": parts[0],
                "author": parts[1],
                "date": parts[2],
                "message": parts[3],
            }

    return {
        "current_branch": current_branch,
        "all_branches": branches_list,
        "last_commit": last_commit,
        "project_root": str(PROJECT_ROOT),
    }


def _handle_get_git_status() -> dict:
    """Return git status in porcelain format."""
    status = _run_git(["status", "--porcelain"])
    if not status["ok"]:
        return {"error": status["stderr"] or "Could not get git status"}

    lines = status["stdout"].split("\n") if status["stdout"] else []

    # Categorize changes
    staged = []
    unstaged = []
    untracked = []

    for line in lines:
        if not line:
            continue
        xy = line[:2]
        filename = line[3:].strip()
        # XY: X=staged status, Y=unstaged status
        if xy[0] != " " and xy[0] != "?":
            staged.append({"status": xy, "file": filename})
        if xy[1] != " ":
            unstaged.append({"status": xy, "file": filename})
        if xy == "??":
            untracked.append(filename)

    return {
        "porcelain": lines,
        "staged_count": len(staged),
        "unstaged_count": len(unstaged),
        "untracked_count": len(untracked),
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "is_clean": len(lines) == 0,
    }


def _handle_get_git_diff(arguments: dict) -> dict:
    """Return git diff."""
    args = ["diff"]
    if arguments.get("staged", False):
        args.append("--cached")
    path = arguments.get("path")
    if path:
        args.append("--")
        args.append(path)

    diff = _run_git(args, timeout=30)
    if not diff["ok"]:
        return {"error": diff["stderr"] or "Could not get git diff"}

    diff_text = diff["stdout"]
    # Truncate very large diffs
    if len(diff_text) > 20_000:
        diff_text = diff_text[:20_000] + "\n... [diff truncated at 20KB]"

    return {
        "diff": diff_text,
        "is_empty": len(diff_text) == 0,
        "staged": arguments.get("staged", False),
        "path": path,
    }


def _handle_list_project_files(arguments: dict) -> dict:
    """List project files with optional filtering."""
    subdir = arguments.get("subdir", "")
    pattern = arguments.get("pattern")
    max_files = arguments.get("max_files", 100)

    base = PROJECT_ROOT
    if subdir:
        base = _is_safe_path(subdir)
        if not base.exists():
            return {"error": f"Directory not found: {subdir}", "files": []}

    files = []
    for root, dirs, filenames in os.walk(base):
        # Skip excluded directories
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".")]

        for fname in filenames:
            fpath = Path(root) / fname
            rel = fpath.relative_to(PROJECT_ROOT)

            # Skip excluded extensions
            if fpath.suffix.lower() in EXCLUDE_EXTENSIONS:
                continue
            if any(fname.endswith(ext) for ext in EXCLUDE_EXTENSIONS):
                continue

            # Pattern filter
            if pattern and not fpath.match(pattern):
                continue

            files.append({
                "path": str(rel),
                "size": fpath.stat().st_size,
                "is_dir": False,
            })

            if len(files) >= max_files:
                break

        if len(files) >= max_files:
            break

    # Also list top-level dirs
    try:
        dirs_list = [
            d for d in os.listdir(base)
            if os.path.isdir(os.path.join(base, d))
            and d not in EXCLUDE_DIRS
            and not d.startswith(".")
        ]
    except OSError:
        dirs_list = []

    return {
        "project_root": str(PROJECT_ROOT),
        "subdir": subdir or ".",
        "file_count": len(files),
        "max_files": max_files,
        "truncated": len(files) >= max_files,
        "files": files,
        "top_level_dirs": dirs_list,
    }


def _handle_read_file(arguments: dict) -> dict:
    """Read a file from the project, with path validation."""
    path_str = arguments["path"]
    max_lines = arguments.get("max_lines", 500)

    try:
        resolved = _is_safe_path(path_str)
    except ValueError as e:
        return {"error": str(e)}

    if not resolved.exists():
        return {"error": f"File not found: {path_str}"}

    if resolved.is_dir():
        # List the directory instead
        try:
            contents = os.listdir(resolved)
            return {
                "path": path_str,
                "is_dir": True,
                "contents": sorted(contents),
            }
        except OSError as e:
            return {"error": f"Cannot read directory: {e}"}

    file_size = resolved.stat().st_size
    if file_size > MAX_FILE_SIZE_READ:
        try:
            text = resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return {"error": f"File '{path_str}' is not a UTF-8 text file", "size": file_size}
        lines = text.split("\n")
        shown = lines[:max_lines]
        return {
            "path": path_str,
            "total_lines": len(lines),
            "shown_lines": len(shown),
            "truncated": True,
            "warning": f"File is {file_size} bytes (max {MAX_FILE_SIZE_READ}). Showing first {max_lines} lines.",
            "content": "\n".join(shown),
            "size": file_size,
        }

    try:
        text = resolved.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"error": f"File '{path_str}' is not a UTF-8 text file", "size": file_size}

    lines = text.split("\n")
    total_lines = len(lines)

    if len(lines) > max_lines:
        shown = lines[:max_lines]
        return {
            "path": path_str,
            "total_lines": total_lines,
            "shown_lines": max_lines,
            "truncated": True,
            "content": "\n".join(shown),
            "size": file_size,
        }

    return {
        "path": path_str,
        "total_lines": total_lines,
        "content": text,
        "size": file_size,
    }


async def main() -> None:
    """Entry point: run the MCP server over stdio."""
    logger.info("Git MCP server starting — project root: %s", PROJECT_ROOT)
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

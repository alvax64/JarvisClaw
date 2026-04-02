"""Tools: local system control — what makes Jarvis useful on Linux."""

import asyncio
import os

from livekit.agents import function_tool, RunContext


@function_tool(
    name="run_command",
    description=(
        "Run a shell command on the user's Linux system. "
        "Use for: opening apps, checking system status, file operations, "
        "package management, etc. Return the command output."
    ),
)
async def run_command(context: RunContext, command: str) -> str:
    """Run a shell command and return its output.

    Args:
        command: The shell command to execute, e.g. 'firefox', 'df -h', 'date'.
    """
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

        output = stdout.decode().strip()
        errors = stderr.decode().strip()

        if proc.returncode != 0:
            return f"Command failed (exit {proc.returncode}): {errors or output}"

        if not output and not errors:
            return "Command executed successfully (no output)."

        # Truncate for voice — LLM will summarize
        result = output[:2000]
        if errors:
            result += f"\nStderr: {errors[:500]}"
        return result

    except asyncio.TimeoutError:
        return "Command timed out after 30 seconds."
    except Exception as e:
        return f"Failed to run command: {e}"


@function_tool(
    name="get_screenshot",
    description="Take a screenshot of the current screen. Returns the file path.",
)
async def get_screenshot(context: RunContext) -> str:
    """Take a screenshot using grim (Wayland)."""
    path = "/tmp/jarvis-screenshot.png"
    try:
        proc = await asyncio.create_subprocess_exec(
            "grim", path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode == 0:
            size = os.path.getsize(path)
            return f"Screenshot saved to {path} ({size} bytes)."
        return f"Screenshot failed: {stderr.decode().strip()}"
    except Exception as e:
        return f"Screenshot failed: {e}"

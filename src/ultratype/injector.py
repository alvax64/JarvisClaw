"""Text injection via wtype for Wayland."""

from __future__ import annotations

import asyncio


class Injector:
    """Inject text into the focused Wayland window using wtype."""

    async def inject(self, text: str) -> None:
        """Type text into the currently focused window."""
        if not text:
            return

        process = await asyncio.create_subprocess_exec(
            "wtype", "--", text,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(
                f"wtype failed (exit {process.returncode}): "
                f"{stderr.decode().strip()}"
            )

    async def inject_via_clipboard(self, text: str) -> None:
        """Copy to clipboard and paste. Fallback for special characters."""
        if not text:
            return

        # Copy to clipboard
        proc = await asyncio.create_subprocess_exec(
            "wl-copy", "--", text,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.wait()

        # Simulate Ctrl+V
        proc = await asyncio.create_subprocess_exec(
            "wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.wait()

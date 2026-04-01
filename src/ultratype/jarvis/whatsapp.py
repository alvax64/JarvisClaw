"""WhatsApp integration via Baileys — managed by Jarvis."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

WHATSAPP_DIR = Path(__file__).resolve().parent.parent.parent.parent / "whatsapp"
API_PORT = 3001
API_BASE = f"http://127.0.0.1:{API_PORT}"


class WhatsAppService:
    """Manages the Baileys Node.js process and provides a Python API."""

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._client: httpx.AsyncClient | None = None
        self._ready = False

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    @property
    def is_ready(self) -> bool:
        return self._ready

    async def start(self) -> None:
        """Start the Baileys Node.js server."""
        self._client = httpx.AsyncClient(timeout=10.0)

        # Check if already running (external service)
        if await self._health_check():
            log.info("WhatsApp service already running on port %d", API_PORT)
            self._ready = True
            return

        server_js = WHATSAPP_DIR / "server.js"
        if not server_js.exists():
            log.warning("WhatsApp server.js not found at %s", server_js)
            return

        log.info("Starting WhatsApp service from %s", WHATSAPP_DIR)
        self._process = await asyncio.create_subprocess_exec(
            "node", "server.js",
            cwd=str(WHATSAPP_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Wait for the server to be ready
        for _ in range(30):
            await asyncio.sleep(1)
            if await self._health_check():
                self._ready = True
                log.info("WhatsApp service ready")
                return
            if self._process.returncode is not None:
                stderr = await self._process.stderr.read()
                log.error("WhatsApp process died: %s", stderr.decode()[:300])
                return

        log.error("WhatsApp service failed to start within 30s")

    async def stop(self) -> None:
        """Stop the Baileys Node.js server."""
        self._ready = False
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
            self._process = None
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _health_check(self) -> bool:
        """Check if the API is responsive."""
        try:
            resp = await self._client.get(f"{API_BASE}/status")
            data = resp.json()
            return data.get("ok") and data.get("connected")
        except Exception:
            return False

    async def send(self, name: str, text: str) -> dict:
        """Send a message by contact name."""
        try:
            resp = await self._client.post(
                f"{API_BASE}/send-to",
                json={"name": name, "text": text},
            )
            return resp.json()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def send_number(self, phone: str, text: str) -> dict:
        """Send a message by phone number."""
        try:
            resp = await self._client.post(
                f"{API_BASE}/send",
                json={"to": phone, "text": text},
            )
            return resp.json()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def search(self, query: str) -> dict:
        """Search contacts."""
        try:
            resp = await self._client.get(
                f"{API_BASE}/contacts",
                params={"q": query},
            )
            return resp.json()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def status(self) -> dict:
        """Get service status."""
        try:
            resp = await self._client.get(f"{API_BASE}/status")
            return resp.json()
        except Exception as e:
            return {"ok": False, "error": str(e), "connected": False}

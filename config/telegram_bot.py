#!/usr/bin/env python3
"""Freeflix Telegram Bot — bridges Telegram messages to the OpenCode AI agent."""

import os
import re
import sys
import asyncio
import logging

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ── Configuration ──
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
OPENCODE_TIMEOUT = 300  # 5 minutes max per request
TELEGRAM_MAX_LEN = 4096

# ── Globals ──
ALLOWED_USERS: set[int] = set()
opencode_lock = asyncio.Lock()

logging.basicConfig(
    format="[telegram] %(asctime)s %(levelname)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)


def parse_allowed_users() -> set[int]:
    raw = os.environ.get("TELEGRAM_ALLOWED_USERS", "")
    if not raw.strip():
        return set()
    return {int(uid.strip()) for uid in raw.split(",") if uid.strip().isdigit()}


def is_authorized(user_id: int) -> bool:
    if not ALLOWED_USERS:
        return False
    return user_id in ALLOWED_USERS


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def split_message(text: str, max_len: int = TELEGRAM_MAX_LEN) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1 or split_at < max_len // 2:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


async def run_opencode(prompt: str) -> str:
    async with opencode_lock:
        log.info("Running: opencode run --attach http://localhost:4096 %r", prompt)
        proc = await asyncio.create_subprocess_exec(
            "opencode", "run", "--attach", "http://localhost:4096", "--continue", prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd="/work",
        )
        try:
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=OPENCODE_TIMEOUT
            )
        except asyncio.TimeoutError:
            log.warning("OpenCode timed out after %ds, killing process", OPENCODE_TIMEOUT)
            proc.kill()
            await proc.wait()
            return "[Timeout] OpenCode did not respond within 5 minutes."

        log.info("OpenCode exited with code %d", proc.returncode)
        output = stdout.decode("utf-8", errors="replace").strip()
        output = strip_ansi(output)
        log.info("Output length: %d chars", len(output))
        if not output:
            return "[No response from OpenCode]"
        return output


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text(
            f"Unauthorized. Your Telegram user ID is: {user_id}\n"
            "Add it to TELEGRAM_ALLOWED_USERS to gain access."
        )
        return
    await update.message.reply_text(
        "Freeflix Bot ready! Send me a message and I'll forward it to the AI agent.\n\n"
        "Examples:\n"
        '  "Find me a good sci-fi movie"\n'
        '  "Download The Matrix 1999"\n'
        '  "What\'s downloading right now?"\n'
        '  "Get me Neuromancer ebook"'
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text(
            f"Unauthorized. Your Telegram user ID is: {user_id}\n"
            "Add it to TELEGRAM_ALLOWED_USERS to gain access."
        )
        return

    prompt = update.message.text
    if not prompt:
        return

    log.info("Message from %s: %s", user_id, prompt[:100])
    await update.message.chat.send_action("typing")

    response = await run_opencode(prompt)

    for chunk in split_message(response):
        await update.message.reply_text(chunk)


def main() -> None:
    global ALLOWED_USERS

    if not BOT_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN not set")
        sys.exit(1)

    ALLOWED_USERS = parse_allowed_users()
    if not ALLOWED_USERS:
        log.warning("TELEGRAM_ALLOWED_USERS is empty — all users will be denied")

    log.info("Starting bot, allowed users: %s", ALLOWED_USERS)

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Bot polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Freeflix Telegram Bot — bridges Telegram messages to the OpenCode AI agent."""

import os
import re
import sys
import asyncio
import logging
import tempfile

import speech_recognition as sr
from pydub import AudioSegment
import telegramify_markdown
from telegram import Update
from telegram.helpers import escape_markdown
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


_TOOL_LINE_RE = re.compile(r"^(\$ |⚙ )")
_STATUS_LINE_RE = re.compile(r"^> \S+ · ")


def format_for_telegram(raw: str) -> str:
    """Separate tool calls from assistant text.

    Tool call blocks become expandable blockquotes in MarkdownV2.
    Assistant text is converted via telegramify_markdown.
    """
    lines = raw.split("\n")
    sections: list[tuple[str, list[str]]] = []  # ("tool"|"text", lines)
    current_type = "text"
    current: list[str] = []

    for line in lines:
        # Strip status lines (e.g. "> build · kimi-k2.5-free")
        if _STATUS_LINE_RE.match(line):
            continue

        is_tool = bool(_TOOL_LINE_RE.match(line))

        if is_tool and current_type != "tool":
            # Flush text section, start tool section
            if current:
                sections.append(("text", current))
            current = [line]
            current_type = "tool"
        elif not is_tool and current_type == "tool":
            # Flush tool section, start text section
            if current:
                sections.append(("tool", current))
            current = [line]
            current_type = "text"
        else:
            current.append(line)

    if current:
        sections.append((current_type, current))

    parts: list[str] = []
    for stype, slines in sections:
        text = "\n".join(slines).strip()
        if not text:
            continue
        if stype == "tool":
            # MarkdownV2 expandable blockquote: **>line\n>line\n>last||
            escaped = escape_markdown(text, version=2)
            bq_lines = escaped.split("\n")
            quoted = "\n".join(
                ("**>" if i == 0 else ">") + l
                for i, l in enumerate(bq_lines)
            )
            quoted += "||"
            parts.append(quoted)
        else:
            parts.append(telegramify_markdown.markdownify(text))

    return "\n\n".join(parts)


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


async def _exec_opencode(prompt: str, use_continue: bool) -> tuple[int, str]:
    cmd = ["opencode", "run", "--attach", "http://localhost:4096"]
    if use_continue:
        cmd.append("--continue")
    cmd.append(prompt)
    log.info("Running: %s", " ".join(cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
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
        return 1, "[Timeout] OpenCode did not respond within 5 minutes."

    output = stdout.decode("utf-8", errors="replace").strip()
    output = strip_ansi(output)
    log.info("OpenCode exited with code %d, output length: %d chars", proc.returncode, len(output))
    return proc.returncode, output


async def run_opencode(prompt: str) -> str:
    async with opencode_lock:
        # Try continuing the last session; if none exists, create a new one
        rc, output = await _exec_opencode(prompt, use_continue=True)
        if rc != 0:
            log.info("--continue failed (rc=%d), retrying without it", rc)
            rc, output = await _exec_opencode(prompt, use_continue=False)
        if not output:
            return "[No response from OpenCode]"
        return output


def transcribe_audio(ogg_path: str) -> str:
    """Convert OGG voice message to text via Google Speech Recognition."""
    wav_path = ogg_path.replace(".ogg", ".wav")
    audio = AudioSegment.from_ogg(ogg_path)
    audio.export(wav_path, format="wav")
    recognizer = sr.Recognizer()
    with sr.AudioFile(wav_path) as source:
        audio_data = recognizer.record(source)
    os.unlink(wav_path)
    return recognizer.recognize_google(audio_data)


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

    # Keep "typing..." indicator alive throughout the entire OpenCode execution
    typing_active = True

    async def keep_typing():
        while typing_active:
            await update.message.chat.send_action("typing")
            await asyncio.sleep(4)

    typing_task = asyncio.create_task(keep_typing())
    try:
        response = await run_opencode(prompt)
    finally:
        typing_active = False
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass

    formatted = format_for_telegram(response)
    for chunk in split_message(formatted):
        await update.message.reply_markdown_v2(chunk)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text(
            f"Unauthorized. Your Telegram user ID is: {user_id}\n"
            "Add it to TELEGRAM_ALLOWED_USERS to gain access."
        )
        return

    voice = update.message.voice
    if not voice:
        return

    log.info("Voice message from %s, duration: %ds", user_id, voice.duration)

    # Download the voice file
    voice_file = await context.bot.get_file(voice.file_id)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        ogg_path = tmp.name
    await voice_file.download_to_drive(ogg_path)

    # Transcribe in a thread to avoid blocking the event loop
    try:
        loop = asyncio.get_event_loop()
        prompt = await loop.run_in_executor(None, transcribe_audio, ogg_path)
    except Exception as e:
        log.error("Transcription failed: %s", e)
        await update.message.reply_text("[Could not transcribe voice message]")
        return
    finally:
        os.unlink(ogg_path)

    log.info("Transcribed: %s", prompt[:100])
    await update.message.reply_text(f"🎤 {prompt}")

    # Keep "typing..." indicator alive throughout the entire OpenCode execution
    typing_active = True

    async def keep_typing():
        while typing_active:
            await update.message.chat.send_action("typing")
            await asyncio.sleep(4)

    typing_task = asyncio.create_task(keep_typing())
    try:
        response = await run_opencode(prompt)
    finally:
        typing_active = False
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass

    formatted = format_for_telegram(response)
    for chunk in split_message(formatted):
        await update.message.reply_markdown_v2(chunk)


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
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    log.info("Bot polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

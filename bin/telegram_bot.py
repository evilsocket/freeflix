#!/usr/bin/env python3
"""Freeflix Telegram Bot — bridges Telegram messages to the OpenCode AI agent."""

import os
import re
import sys
import json
import glob
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
SESSION_DIR = "/data/opencode/storage/session/global"

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

    Tool call blocks (including their output) become expandable blockquotes
    in MarkdownV2. Assistant text is converted via telegramify_markdown.
    """
    lines = raw.split("\n")

    # First pass: find indices of all tool call lines ($ or ⚙)
    tool_line_indices = set()
    for i, line in enumerate(lines):
        if _TOOL_LINE_RE.match(line):
            tool_line_indices.add(i)

    # Second pass: mark each line as "tool", "status" (skip), or "text".
    # Lines between tool calls are tool output. After the LAST tool call,
    # only the final paragraph (after a blank line) is assistant text.
    labels: list[str] = []  # "tool", "text", or "skip"
    in_tool = False

    for i, line in enumerate(lines):
        if _STATUS_LINE_RE.match(line):
            labels.append("skip")
            continue

        if i in tool_line_indices:
            in_tool = True
            labels.append("tool")
        elif in_tool:
            # Check if there are more tool calls ahead
            has_more_tools = any(j > i for j in tool_line_indices)
            if has_more_tools:
                # Between tool calls — this is tool output
                labels.append("tool")
            else:
                # After the last tool call. Tool output continues until
                # we hit a blank line, then the rest is assistant text.
                # Look backwards: was there a blank line between last tool and here?
                last_tool = max(j for j in tool_line_indices if j <= i)
                preceding = lines[last_tool + 1:i]
                if any(l.strip() == "" for l in preceding) and line.strip() != "":
                    # We're past a blank separator after the last tool output
                    in_tool = False
                    labels.append("text")
                else:
                    labels.append("tool")
        else:
            labels.append("text")

    # Third pass: group consecutive same-label lines into sections
    sections: list[tuple[str, list[str]]] = []
    for i, line in enumerate(lines):
        label = labels[i]
        if label == "skip":
            continue
        if sections and sections[-1][0] == label:
            sections[-1][1].append(line)
        else:
            sections.append((label, [line]))

    # Fourth pass: render sections
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


def get_latest_session_id() -> str | None:
    """Find the most recently updated session from OpenCode's storage."""
    session_files = glob.glob(os.path.join(SESSION_DIR, "ses_*.json"))
    if not session_files:
        return None
    best_id, best_time = None, 0
    for path in session_files:
        try:
            with open(path) as f:
                data = json.load(f)
            updated = data.get("time", {}).get("updated", 0)
            if updated > best_time:
                best_time = updated
                best_id = data.get("id")
        except (json.JSONDecodeError, OSError):
            continue
    return best_id


async def _exec_opencode(prompt: str, session_id: str | None = None) -> tuple[int, str]:
    cmd = ["opencode", "run", "--attach", "http://localhost:4096"]
    if session_id:
        cmd.extend(["--session", session_id])
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
        # Find the latest session (shared with TUI)
        session_id = get_latest_session_id()
        if session_id:
            log.info("Using session: %s", session_id)

        rc, output = await _exec_opencode(prompt, session_id=session_id)
        if rc != 0 and session_id:
            # Session might be stale, try without it (creates new)
            log.info("--session failed (rc=%d), creating new session", rc)
            rc, output = await _exec_opencode(prompt, session_id=None)
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

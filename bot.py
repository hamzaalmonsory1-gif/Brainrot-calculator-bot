import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional

import discord
from discord.ext import commands


# ============================================================
# Brainrot Calculator
# PREFIX COMMAND VERSION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = str(BASE_DIR / "brainrot.db")

# PUT YOUR NEW TOKEN HERE


TOKEN = os.getenv("DISCORD_TOKEN")


# ============================================================
# Configuration
# ============================================================

DEFAULT_WORDS = {
    "gyatt",
    "skibidi",
    "rizz",
    "sigma",
    "fanum",
    "ohio",
    "goofy",
    "sus",
    "mewing",
    "aura",
    "cooked",
    "bussin",
    "mog",
}

RANKS = [
    (0, "Normal Human"),
    (100, "Brainrot Enjoyer"),
    (1_000, "Brainrot Addict"),
    (10_000, "Brainrot Lord"),
    (100_000, "Brainrot Final Boss"),
]


# ============================================================
# Discord Intents
# ============================================================

intents = discord.Intents.default()
intents.message_content = True


# ============================================================
# Database
# ============================================================

def get_db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    con = get_db()

    try:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                global_count INTEGER NOT NULL DEFAULT 0,
                streak INTEGER NOT NULL DEFAULT 0,
                last_message INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS guilds (
                guild_id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1,
                total_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS words (
                word TEXT PRIMARY KEY,
                count INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS user_words (
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                word TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(user_id, guild_id, word)
            );
            """
        )

        for word in DEFAULT_WORDS:
            con.execute(
                "INSERT OR IGNORE INTO words(word) VALUES (?)",
                (word,)
            )

        con.commit()

    finally:
        con.close()


def ensure_guild(
    con: sqlite3.Connection,
    guild_id: int
) -> None:

    con.execute(
        "INSERT OR IGNORE INTO guilds(guild_id) VALUES (?)",
        (guild_id,)
    )


# ============================================================
# Word Detection
# ============================================================

def normalize_word(value: str) -> str:
    return value.strip().casefold()


def load_words() -> list[str]:

    con = get_db()

    try:
        rows = con.execute(
            """
            SELECT word
            FROM words
            ORDER BY LENGTH(word) DESC, word ASC
            """
        ).fetchall()

        return [
            normalize_word(row["word"])
            for row in rows
        ]

    finally:
        con.close()


def compile_word_pattern(
    word: str
) -> re.Pattern:

    return re.compile(
        rf"(?<![A-Za-z0-9_])"
        rf"{re.escape(word)}"
        rf"(?![A-Za-z0-9_])",
        re.IGNORECASE
    )


def detect_words(
    content: str,
    words: Optional[list[str]] = None
) -> list[str]:

    if not content:
        return []

    candidates = (
        words
        if words is not None
        else load_words()
    )

    found = []

    for word in candidates:

        pattern = compile_word_pattern(word)

        for _ in pattern.finditer(content):
            found.append(normalize_word(word))

    return found


# ============================================================
# Message Processing
# ============================================================

def process_message(
    guild_id: int,
    user_id: int,
    content: str
) -> list[str]:

    found = detect_words(content)

    if not found:
        return []

    now = int(time.time())

    con = get_db()

    try:

        con.execute(
            """
            INSERT OR IGNORE INTO users(user_id)
            VALUES (?)
            """,
            (user_id,)
        )

        ensure_guild(con, guild_id)

        # One message = one streak increase
        con.execute(
            """
            UPDATE users
            SET streak = streak + 1,
                last_message = ?
            WHERE user_id = ?
            """,
            (now, user_id)
        )

        for found_word in found:

            con.execute(
                """
                UPDATE users
                SET global_count = global_count + 1
                WHERE user_id = ?
                """,
                (user_id,)
            )

            con.execute(
                """
                UPDATE guilds
                SET total_count = total_count + 1
                WHERE guild_id = ?
                """,
                (guild_id,)
            )

            con.execute(
                """
                INSERT OR IGNORE INTO words(word)
                VALUES (?)
                """,
                (found_word,)
            )

            con.execute(
                """
                UPDATE words
                SET count = count + 1
                WHERE word = ?
                """,
                (found_word,)
            )

            con.execute(
                """
                INSERT INTO user_words(
                    user_id,
                    guild_id,
                    word,
                    count
                )
                VALUES (?, ?, ?, 1)

                ON CONFLICT(
                    user_id,
                    guild_id,
                    word
                )
                DO UPDATE SET count = count + 1
                """,
                (
                    user_id,
                    guild_id,
                    found_word
                )
            )

        con.commit()

    finally:
        con.close()

    return found


# ============================================================
# Statistics
# ============================================================

def get_user_stats(
    user_id: int,
    guild_id: int
):

    con = get_db()

    try:

        user = con.execute(
            """
            SELECT *
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        ).fetchone()

        guild = con.execute(
            """
            SELECT total_count
            FROM guilds
            WHERE guild_id = ?
            """,
            (guild_id,)
        ).fetchone()

        top = con.execute(
            """
            SELECT word, SUM(count) AS count
            FROM user_words
            WHERE user_id = ?
            GROUP BY word
            ORDER BY count DESC, word ASC
            LIMIT 1
            """,
            (user_id,)
        ).fetchone()

        return user, guild, top

    finally:
        con.close()


def rank_for(count: int) -> str:

    rank = RANKS[0][1]

    for threshold, name in RANKS:

        if count >= threshold:
            rank = name

    return rank


# ============================================================
# Embeds
# ============================================================

def make_embed(
    title: str,
    description: Optional[str] = None
) -> discord.Embed:

    embed = discord.Embed(
        title=title,
        description=description,
        colour=discord.Colour.blurple()
    )

    embed.set_footer(
        text="Brainrot Calculator"
    )

    return embed


# ============================================================
# Bot
# ============================================================

class BrainrotBot(commands.Bot):

    async def setup_hook(self):

        print("[SETUP] Initializing database...")

        init_db()

        print("[SETUP] Database ready.")

        print("[SETUP] Prefix commands enabled.")
        print("[SETUP] Command prefix: >")


bot = BrainrotBot(
    command_prefix=">",
    intents=intents,
    help_command=None
)


# ============================================================
# Ready
# ============================================================

@bot.event
async def on_ready():
	
    activity = discord.Game(name=">help For Commands :)")
    await bot.change_presence(
        status=discord.Status.idle,
        activity=activity
    )
   

    print(f"Logged in as {bot.user}")

    print(
        f"[READY] Logged in as "
        f"{bot.user} "
        f"(ID: {bot.user.id})"
    )

    print(
        f"[READY] Connected to "
        f"{len(bot.guilds)} server(s)."
    )

    print("[READY] Prefix commands are ready.")
    




# ============================================================
# Automatic Message Detection
# ============================================================

@bot.event
async def on_message(
    message: discord.Message
):

    if message.author.bot:
        return

    if message.guild is None:
        await bot.process_commands(message)
        return

    found = process_message(
        message.guild.id,
        message.author.id,
        message.content
    )

    if found:

        user, guild, _ = get_user_stats(
            message.author.id,
            message.guild.id
        )

        unique = ", ".join(
            sorted(set(found))
        )

        embed = make_embed(
            "Brainrot Detected",
            f"You typed **{len(found)}** "
            "brainrot word(s)."
        )

        embed.add_field(
            name="Detected",
            value=f"`{unique}`",
            inline=False
        )

        embed.add_field(
            name="Your Total",
            value=f"**{user['global_count']:,}**",
            inline=True
        )

        embed.add_field(
            name="Server Total",
            value=f"**{guild['total_count']:,}**",
            inline=True
        )

        embed.add_field(
            name="Rank",
            value=rank_for(
                user["global_count"]
            ),
            inline=True
        )

        await message.reply(
            embed=embed,
            mention_author=False
        )

    # REQUIRED for ! commands
    await bot.process_commands(message)


# ============================================================
# !stats
# ============================================================

@bot.command(name="stats")
@commands.guild_only()
async def stats(ctx: commands.Context):

    user, _, top = get_user_stats(
        ctx.author.id,
        ctx.guild.id
    )

    count = (
        user["global_count"]
        if user
        else 0
    )

    streak = (
        user["streak"]
        if user
        else 0
    )

    embed = make_embed(
        f"{ctx.author.display_name}'s Brainrot Stats"
    )

    embed.add_field(
        name="Global Brainrot",
        value=f"**{count:,}**",
        inline=True
    )

    embed.add_field(
        name="Rank",
        value=rank_for(count),
        inline=True
    )

    embed.add_field(
        name="Streak",
        value=f"**{streak}**",
        inline=True
    )

    embed.add_field(
        name="Most Used",
        value=(
            f"`{top['word']}` — "
            f"{top['count']:,}"
            if top
            else "None"
        ),
        inline=False
    )

    await ctx.reply(embed=embed)


# ============================================================
# !leaderboard
# ============================================================

@bot.command(name="leaderboard")
@commands.guild_only()
async def leaderboard(ctx: commands.Context):

    con = get_db()

    try:

        rows = con.execute(
            """
            SELECT user_id, SUM(count) AS total
            FROM user_words
            WHERE guild_id = ?
            GROUP BY user_id
            ORDER BY total DESC, user_id ASC
            LIMIT 10
            """,
            (ctx.guild.id,)
        ).fetchall()

    finally:
        con.close()

    embed = make_embed(
        f"{ctx.guild.name} Brainrot Leaderboard"
    )

    if not rows:

        embed.description = (
            "No brainrot detected yet."
        )

    else:

        lines = []

        for i, row in enumerate(rows, 1):

            member = ctx.guild.get_member(
                row["user_id"]
            )

            name = (
                member.display_name
                if member
                else f"User {row['user_id']}"
            )

            lines.append(
                f"**#{i}** {name} — "
                f"`{row['total']:,}`"
            )

        embed.description = "\n".join(lines)

    await ctx.reply(embed=embed)


# ============================================================
# !globalleaderboard
# ============================================================

@bot.command(name="globalleaderboard")
async def globalleaderboard(ctx: commands.Context):

    con = get_db()

    try:

        rows = con.execute(
            """
            SELECT user_id, global_count
            FROM users
            ORDER BY global_count DESC, user_id ASC
            LIMIT 10
            """
        ).fetchall()

    finally:
        con.close()

    lines = []

    for i, row in enumerate(rows, 1):

        try:

            user = await bot.fetch_user(
                row["user_id"]
            )

            name = user.display_name

        except (
            discord.NotFound,
            discord.HTTPException
        ):

            name = f"User {row['user_id']}"

        lines.append(
            f"**#{i}** {name} — "
            f"`{row['global_count']:,}`"
        )

    description = (
        "\n".join(lines)
        if lines
        else "No data yet."
    )

    embed = make_embed(
        "Global Brainrot Leaderboard",
        description
    )

    await ctx.reply(embed=embed)


# ============================================================
# !serverstats
# ============================================================

@bot.command(name="serverstats")
@commands.guild_only()
async def serverstats(ctx: commands.Context):

    con = get_db()

    try:

        guild = con.execute(
            """
            SELECT total_count
            FROM guilds
            WHERE guild_id = ?
            """,
            (ctx.guild.id,)
        ).fetchone()

        top = con.execute(
            """
            SELECT word, count
            FROM words
            ORDER BY count DESC, word ASC
            LIMIT 1
            """
        ).fetchone()

    finally:
        con.close()

    total = (
        guild["total_count"]
        if guild
        else 0
    )

    embed = make_embed(
        f"{ctx.guild.name} Stats"
    )

    embed.add_field(
        name="Server Total",
        value=f"**{total:,}**",
        inline=True
    )

    embed.add_field(
        name="Most Used Globally",
        value=(
            f"`{top['word']}` — "
            f"{top['count']:,}"
            if top
            else "None"
        ),
        inline=True
    )

    await ctx.reply(embed=embed)


# ============================================================
# !word
# ============================================================

@bot.command(name="word")
@commands.guild_only()
async def word(
    ctx: commands.Context,
    *,
    word: str
):

    normalized = normalize_word(word)

    con = get_db()

    try:

        row = con.execute(
            """
            SELECT count
            FROM words
            WHERE word = ?
            """,
            (normalized,)
        ).fetchone()

    finally:
        con.close()

    count = (
        row["count"]
        if row
        else 0
    )

    embed = make_embed(
        "Word Statistics",
        f"`{normalized}` has been detected "
        f"**{count:,}** times globally."
    )

    await ctx.reply(embed=embed)


# ============================================================
# !wordleaderboard
# ============================================================

@bot.command(name="wordleaderboard")
async def wordleaderboard(ctx: commands.Context):

    con = get_db()

    try:

        rows = con.execute(
            """
            SELECT word, count
            FROM words
            ORDER BY count DESC, word ASC
            LIMIT 10
            """
        ).fetchall()

    finally:
        con.close()

    description = "\n".join(
        f"**#{i}** `{row['word']}` — "
        f"`{row['count']:,}`"
        for i, row in enumerate(rows, 1)
    )

    if not description:
        description = "No words yet."

    embed = make_embed(
        "Brainrot Words",
        description
    )

    await ctx.reply(embed=embed)


# ============================================================
# !addword
# ============================================================

@bot.command(name="addword")
@commands.guild_only()
@commands.has_permissions(manage_guild=True)
async def addword(
    ctx: commands.Context,
    *,
    word: str
):

    normalized = normalize_word(word)

    if not re.fullmatch(
        r"[a-z0-9_-]{1,32}",
        normalized
    ):

        await ctx.reply(
            "Invalid word. Use 1-32 characters: "
            "letters, numbers, `_`, or `-`."
        )

        return

    con = get_db()

    try:

        cur = con.execute(
            """
            INSERT OR IGNORE INTO words(word)
            VALUES (?)
            """,
            (normalized,)
        )

        con.commit()

        added = cur.rowcount == 1

    finally:
        con.close()

    if added:

        message = (
            f"Added `{normalized}` "
            "to the brainrot list."
        )

    else:

        message = (
            f"`{normalized}` is already "
            "in the brainrot list."
        )

    await ctx.reply(message)


# ============================================================
# !removeword
# ============================================================

@bot.command(name="removeword")
@commands.guild_only()
@commands.has_permissions(manage_guild=True)
async def removeword(
    ctx: commands.Context,
    *,
    word: str
):

    normalized = normalize_word(word)

    con = get_db()

    try:

        cur = con.execute(
            """
            DELETE FROM words
            WHERE word = ?
            """,
            (normalized,)
        )

        con.commit()

        removed = cur.rowcount == 1

    finally:
        con.close()

    if removed:

        message = (
            f"Removed `{normalized}`."
        )

    else:

        message = (
            f"`{normalized}` was not "
            "in the brainrot list."
        )

    await ctx.reply(message)


# ============================================================
# !listwords
# ============================================================

@bot.command(name="listwords")
async def listwords(ctx: commands.Context):

    words = load_words()

    if not words:

        description = "No tracked words."

    else:

        description = ", ".join(
            f"`{word}`"
            for word in words
        )

        if len(description) > 4000:

            description = (
                description[:3990]
                + "..."
            )

    embed = make_embed(
        "Tracked Brainrot Words",
        description
    )

    await ctx.reply(embed=embed)


# ============================================================
# !help
# ============================================================

@bot.command(name="help")
async def help_command(ctx: commands.Context):

    embed = make_embed(
        "Brainrot Calculator",
        "Automatic brainrot detection + statistics."
    )

    embed.add_field(
        name="Statistics",
        value=(
            "`>stats`\n"
            "`>leaderboard`\n"
            "`>globalleaderboard`\n"
            "`>serverstats`"
        ),
        inline=False
    )

    embed.add_field(
        name="Words",
        value=(
            "`>word <word>`\n"
            "`>wordleaderboard`\n"
            "`>listwords`"
        ),
        inline=False
    )

    embed.add_field(
        name="Admin",
        value=(
            "`>addword <word>`\n"
            "`>removeword <word>`"
        ),
        inline=False
    )

    await ctx.reply(embed=embed)


# ============================================================
# Command Error Handler
# ============================================================

@bot.event
async def on_command_error(
    ctx: commands.Context,
    error: commands.CommandError
):

    # Ignore unknown commands
    if isinstance(
        error,
        commands.CommandNotFound
    ):
        return

    print(
        f"[COMMAND ERROR] "
        f"{type(error).__name__}: "
        f"{error!r}"
    )

    if isinstance(
        error,
        commands.MissingPermissions
    ):

        await ctx.reply(
            "You need **Manage Server** permission "
            "to use this command."
        )

    elif isinstance(
        error,
        commands.NoPrivateMessage
    ):

        await ctx.reply(
            "This command can only be used "
            "inside a server."
        )

    elif isinstance(
        error,
        commands.MissingRequiredArgument
    ):

        await ctx.reply(
            "You're missing an argument.\n"
            "Use `!help` to see how to use the commands."
        )

    elif isinstance(
        error,
        commands.BadArgument
    ):

        await ctx.reply(
            "Invalid argument.\n"
            "Use `!help` to see how to use the commands."
        )

    else:

        try:

            await ctx.reply(
                "Something went wrong while "
                "running that command."
            )

        except discord.HTTPException:

            pass


# ============================================================
# Start
# ============================================================

if __name__ == "__main__":

    if TOKEN == "PUT_YOUR_NEW_BOT_TOKEN_HERE":

        raise RuntimeError(
            "Put your NEW bot token in TOKEN first."
        )

    bot.run(TOKEN)

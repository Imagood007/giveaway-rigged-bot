import discord
from discord.ext import commands, tasks
import json
import os
import re
import logging
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

TOKEN = os.environ.get("DISCORD_TOKEN")
PREFIX = "g.f "

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

GIVEAWAYS_FILE = "giveaways.json"
giveaways: dict = {}


# ──────────────────────────────────────────────
#  Storage helpers
# ──────────────────────────────────────────────

def load_giveaways():
    global giveaways
    if os.path.exists(GIVEAWAYS_FILE):
        try:
            with open(GIVEAWAYS_FILE, "r") as f:
                giveaways = json.load(f)
        except Exception:
            giveaways = {}
    else:
        giveaways = {}


def save_giveaways():
    with open(GIVEAWAYS_FILE, "w") as f:
        json.dump(giveaways, f, indent=2)


# ──────────────────────────────────────────────
#  Duration helpers
# ──────────────────────────────────────────────

def parse_duration(duration_str: str):
    """Parse strings like 10s, 5m, 2h, 1d into seconds. Returns None on failure."""
    match = re.fullmatch(r"(\d+)([smhd])", duration_str.strip().lower())
    if not match:
        return None
    value, unit = int(match.group(1)), match.group(2)
    return value * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


# ──────────────────────────────────────────────
#  Embed builders
# ──────────────────────────────────────────────

def make_active_embed(giveaway: dict) -> discord.Embed:
    end_ts = int(giveaway["end_time"])
    embed = discord.Embed(
        title="🎉 GIVEAWAY 🎉",
        color=discord.Color.blue()
    )
    embed.add_field(name="Prize", value=giveaway["prize"], inline=False)
    embed.add_field(name="Ends", value=f"<t:{end_ts}:R>", inline=False)
    embed.add_field(name="Hosted by", value=f"<@{giveaway['host_id']}>", inline=False)
    embed.add_field(name="Entries", value=str(len(giveaway["entries"])), inline=False)
    embed.set_footer(text="Click the button below to join!")
    return embed


def make_ended_embed(giveaway: dict, announce_winner: bool) -> discord.Embed:
    end_ts = int(giveaway["end_time"])
    entries = len(giveaway["entries"])

    embed = discord.Embed(
        title="🎉 GIVEAWAY 🎉",
        color=discord.Color.gold() if announce_winner else discord.Color.greyple()
    )
    embed.add_field(name="Prize", value=giveaway["prize"], inline=False)
    embed.add_field(name="Ended", value=f"<t:{end_ts}:R>", inline=False)
    embed.add_field(name="Hosted by", value=f"<@{giveaway['host_id']}>", inline=False)
    embed.add_field(name="Entries", value=str(entries), inline=False)

    if announce_winner:
        embed.add_field(
            name="🏆 Winner",
            value=f"<@{giveaway['preset_winner_id']}>",
            inline=False
        )

    embed.set_footer(text="Giveaway ended")
    return embed


def make_info_embed(giveaway: dict) -> discord.Embed:
    end_ts = int(giveaway["end_time"])
    entries = giveaway["entries"]
    total = len(entries)
    is_active = giveaway.get("active", False)
    announced = giveaway.get("announced_winner", False)

    status = "🟢 Active" if is_active else "🔴 Ended"

    created_ts = int(giveaway.get("created_at", giveaway["end_time"]))
    created_dt = datetime.fromtimestamp(created_ts, tz=timezone.utc)
    footer_date = created_dt.strftime("%m/%d/%Y %-I:%M %p")

    embed = discord.Embed(
        title=f"🎊 Giveaway Info — {giveaway['prize']}",
        color=discord.Color.blue() if is_active else discord.Color.greyple()
    )
    embed.add_field(name="Status", value=status, inline=False)
    embed.add_field(name="Total Entries", value=str(total), inline=False)
    embed.add_field(name="Hosted by", value=f"<@{giveaway['host_id']}>", inline=False)
    embed.add_field(name="Ends", value=f"<t:{end_ts}:R>", inline=False)
    embed.add_field(name="Preset Winner", value=f"<@{giveaway['preset_winner_id']}>", inline=False)

    if announced:
        announced_winner_val = f"<@{giveaway['preset_winner_id']}>"
    else:
        announced_winner_val = "*Not yet announced*"
    embed.add_field(name="Announced Winner", value=announced_winner_val, inline=False)

    if entries:
        lines = []
        for i, uid in enumerate(entries, start=1):
            lines.append(f"{i}. <@{uid}>")
        participants_text = "\n".join(lines)
        if len(participants_text) > 1024:
            participants_text = participants_text[:1010] + "\n*...and more*"
        embed.add_field(name=f"Participants ({total})", value=participants_text, inline=False)
    else:
        embed.add_field(name=f"Participants (0)", value="*No participants yet.*", inline=False)

    embed.set_footer(
        text=f"Message ID: {giveaway['message_id']} | {footer_date}"
    )
    return embed


# ──────────────────────────────────────────────
#  Button Views
# ──────────────────────────────────────────────

class GiveawayJoinView(discord.ui.View):
    """Active giveaway — blue clickable button."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Join Giveaway",
        style=discord.ButtonStyle.primary,
        custom_id="giveaway:join"
    )
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        message_id = str(interaction.message.id)

        if message_id not in giveaways:
            await interaction.response.send_message(
                "❌ This giveaway no longer exists in the records.",
                ephemeral=True
            )
            return

        giveaway = giveaways[message_id]

        if not giveaway.get("active", False):
            await interaction.response.send_message(
                "❌ This giveaway has already ended!",
                ephemeral=True
            )
            return

        user_id = str(interaction.user.id)
        prize = giveaway["prize"]

        if user_id in giveaway["entries"]:
            await interaction.response.send_message(
                f"⚠️ You have already joined the giveaway of **{prize}**!",
                ephemeral=True
            )
            return

        giveaway["entries"].append(user_id)
        save_giveaways()

        await interaction.response.send_message(
            f"✅ You have joined the giveaway of **{prize}**! 🎉",
            ephemeral=True
        )


class GiveawayEndedView(discord.ui.View):
    """Ended giveaway — gray disabled button."""

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(
            label="Giveaway Ended",
            style=discord.ButtonStyle.secondary,
            custom_id="giveaway:ended",
            disabled=True
        ))


# ──────────────────────────────────────────────
#  Core end-giveaway logic
# ──────────────────────────────────────────────

async def end_giveaway(giveaway: dict, announce_winner: bool):
    message_id = giveaway["message_id"]
    channel_id = giveaway["channel_id"]

    giveaway["active"] = False
    if announce_winner:
        giveaway["announced_winner"] = True
    save_giveaways()

    try:
        channel = bot.get_channel(int(channel_id)) or await bot.fetch_channel(int(channel_id))
        message = await channel.fetch_message(int(message_id))

        ended_embed = make_ended_embed(giveaway, announce_winner=announce_winner)
        await message.edit(embed=ended_embed, view=GiveawayEndedView())

        if announce_winner:
            winner_id = giveaway["preset_winner_id"]
            prize = giveaway["prize"]
            await channel.send(
                f"🎉 Congratulations <@{winner_id}>! You won the **{prize}** giveaway!"
            )

    except discord.NotFound:
        logging.warning(f"Message or channel not found while ending giveaway {message_id}")
    except Exception as e:
        logging.error(f"Error ending giveaway {message_id}: {e}")


# ──────────────────────────────────────────────
#  Background task — auto-end giveaways
# ──────────────────────────────────────────────

@tasks.loop(seconds=5)
async def check_giveaways():
    now = datetime.now(timezone.utc).timestamp()
    to_end = [
        g for g in list(giveaways.values())
        if g.get("active") and g["end_time"] <= now
    ]
    for giveaway in to_end:
        await end_giveaway(giveaway, announce_winner=True)


@check_giveaways.before_loop
async def before_check():
    await bot.wait_until_ready()


# ──────────────────────────────────────────────
#  Bot events
# ──────────────────────────────────────────────

@bot.event
async def on_ready():
    load_giveaways()
    bot.add_view(GiveawayJoinView())
    bot.add_view(GiveawayEndedView())
    check_giveaways.start()
    logging.info(f"Logged in as {bot.user} ({bot.user.id})")
    logging.info(f"Loaded {len(giveaways)} giveaway(s) from storage.")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing argument: `{error.param.name}`. Use `g.f help` for usage.")
        return
    logging.error(f"Command error in '{ctx.command}': {error}")


# ──────────────────────────────────────────────
#  Commands
# ──────────────────────────────────────────────

@bot.group(name="giveaway", invoke_without_command=True)
async def giveaway_group(ctx):
    await ctx.send("❌ Invalid subcommand. Use `g.f help` to see all available commands.")


# ── g.f giveaway start ────────────────────────

@giveaway_group.command(name="start")
async def giveaway_start(ctx, *, args: str = ""):
    """
    Usage: g.f giveaway start <duration> <prize> @winner #channel
    Example: g.f giveaway start 3h Discord Nitro @user #general
    """
    parts = args.split()

    if len(parts) < 4:
        await ctx.send(
            "❌ **Usage:** `g.f giveaway start <duration> <prize> @winner #channel`\n"
            "**Example:** `g.f giveaway start 3h Discord Nitro @user #general`\n"
            "**Duration units:** `s` = seconds, `m` = minutes, `h` = hours, `d` = days"
        )
        return

    duration_str = parts[0]
    duration_seconds = parse_duration(duration_str)

    if duration_seconds is None:
        await ctx.send(
            "❌ **Invalid duration.** Use a number followed by `s`, `m`, `h`, or `d`.\n"
            "**Examples:** `30s`, `10m`, `3h`, `1d`"
        )
        return

    if duration_seconds < 5:
        await ctx.send("❌ Duration must be at least **5 seconds**.")
        return

    mentions = ctx.message.mentions
    channel_mentions = ctx.message.channel_mentions

    if not mentions:
        await ctx.send("❌ Please mention the **preset winner** with `@user`.")
        return

    if not channel_mentions:
        await ctx.send("❌ Please mention the **giveaway channel** with `#channel`.")
        return

    preset_winner = mentions[0]
    giveaway_channel = channel_mentions[0]

    prize = " ".join(parts[1:-2]).strip()

    if not prize:
        await ctx.send("❌ Please provide a **prize name**.")
        return

    now_ts = datetime.now(timezone.utc).timestamp()
    end_time = now_ts + duration_seconds

    placeholder_embed = discord.Embed(
        title="🎉 GIVEAWAY 🎉",
        description="Starting giveaway...",
        color=discord.Color.blue()
    )

    try:
        giveaway_msg = await giveaway_channel.send(
            embed=placeholder_embed,
            view=GiveawayJoinView()
        )
    except discord.Forbidden:
        await ctx.send(f"❌ I don't have permission to send messages in {giveaway_channel.mention}.")
        return

    giveaway_data = {
        "message_id": str(giveaway_msg.id),
        "channel_id": str(giveaway_channel.id),
        "guild_id": str(ctx.guild.id),
        "host_id": str(ctx.author.id),
        "prize": prize,
        "preset_winner_id": str(preset_winner.id),
        "preset_winner_name": preset_winner.display_name,
        "end_time": end_time,
        "created_at": now_ts,
        "entries": [],
        "active": True,
        "announced_winner": False
    }

    giveaways[str(giveaway_msg.id)] = giveaway_data
    save_giveaways()

    active_embed = make_active_embed(giveaway_data)
    await giveaway_msg.edit(embed=active_embed)

    await ctx.send(
        f"✅ Giveaway for **{prize}** started in {giveaway_channel.mention}!\n"
        f"Pre-set winner: {preset_winner.display_name}"
    )


# ── g.f giveaway info ─────────────────────────

@giveaway_group.command(name="info")
async def giveaway_info(ctx, message_id: str = ""):
    """
    Usage: g.f giveaway info <message_id>
    Shows full information about a giveaway.
    """
    if not message_id:
        await ctx.send("❌ **Usage:** `g.f giveaway info <message_id>`")
        return

    giveaway = giveaways.get(message_id)

    if giveaway is None:
        await ctx.send(
            f"❌ No giveaway found with message ID `{message_id}`.\n"
            "Make sure you're using the correct giveaway embed message ID."
        )
        return

    embed = make_info_embed(giveaway)
    await ctx.send(embed=embed)


# ── g.f giveaway end ──────────────────────────

@giveaway_group.command(name="end")
async def giveaway_end(ctx, message_id: str = ""):
    """
    Usage: g.f giveaway end <message_id>
    Ends a running giveaway without announcing a winner.
    """
    if not message_id:
        await ctx.send("❌ **Usage:** `g.f giveaway end <message_id>`")
        return

    giveaway = giveaways.get(message_id)

    if giveaway is None:
        await ctx.send(f"❌ No giveaway found with message ID `{message_id}`.")
        return

    if not giveaway["active"]:
        await ctx.send(f"❌ Giveaway `{message_id}` is already ended.")
        return

    await ctx.send("⏱ Ending that giveaway now...")
    await end_giveaway(giveaway, announce_winner=False)


# ── g.f help ──────────────────────────────────

@bot.command(name="help")
async def help_command(ctx):
    embed = discord.Embed(
        title="🤖 Giveaway Bot — Help",
        description="All commands use the prefix `g.f`.",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="🎉 Start a Giveaway",
        value=(
            "```g.f giveaway start <duration> <prize> @winner #channel```\n"
            "Starts a giveaway in the specified channel.\n"
            "The `@winner` is the **preset winner** — they will always be announced "
            "as the winner when the giveaway ends, no matter how many users join.\n\n"
            "**Duration units:** `s` = seconds · `m` = minutes · `h` = hours · `d` = days\n"
            "**Example:** `g.f giveaway start 3h Discord Nitro @user #general`"
        ),
        inline=False
    )

    embed.add_field(
        name="📋 Giveaway Info",
        value=(
            "```g.f giveaway info <message_id>```\n"
            "Shows full details about a giveaway using its embed message ID.\n"
            "**Example:** `g.f giveaway info 123456789012345678`"
        ),
        inline=False
    )

    embed.add_field(
        name="⛔ End a Giveaway",
        value=(
            "```g.f giveaway end <message_id>```\n"
            "Ends a running giveaway **without** announcing a winner. "
            "The button turns gray and becomes unclickable.\n"
            "**Example:** `g.f giveaway end 123456789012345678`"
        ),
        inline=False
    )

    embed.set_footer(text="Giveaway Bot  •  Preset winner system")
    embed.timestamp = datetime.now(timezone.utc)

    await ctx.send(embed=embed)


# ──────────────────────────────────────────────
#  Entry point
# ──────────────────────────────────────────────

if __name__ == "__main__":
    if not TOKEN:
        logging.error("DISCORD_TOKEN environment variable is not set!")
    else:
        bot.run(TOKEN)

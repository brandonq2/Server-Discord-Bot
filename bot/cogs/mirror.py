import logging
import re
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.mirror_store import MirrorConfig, MirrorStore

logger = logging.getLogger(__name__)

MESSAGE_LINK_PATTERN = re.compile(
    r"https?://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/channels/"
    r"(?P<guild_id>\d+|@me)/(?P<channel_id>\d+)/(?P<message_id>\d+)"
)
CHANNEL_ID_PATTERN = re.compile(r"^(?:<#)?(?P<id>\d+)>?$")


def parse_channel_id(value: str, label: str = "channel ID") -> int:
    match = CHANNEL_ID_PATTERN.fullmatch(value.strip())
    if not match:
        raise ValueError(
            f"Invalid {label}. Enable Developer Mode, then right-click the channel "
            "and choose Copy Channel ID."
        )
    return int(match.group("id"))


def parse_user_id(value: str) -> int:
    cleaned = value.strip()
    if cleaned.startswith("<@") and cleaned.endswith(">"):
        cleaned = cleaned[2:-1].lstrip("!")
    if not cleaned.isdigit():
        raise ValueError("Invalid bot ID. Right-click the bot → Copy User ID.")
    return int(cleaned)


async def resolve_text_channel(
    bot: commands.Bot,
    channel_id: int,
    label: str,
) -> discord.TextChannel:
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except discord.NotFound:
            raise ValueError(
                f"Could not find {label} `{channel_id}`. "
                "Make sure the bot is in that server and the ID is correct."
            ) from None
        except discord.HTTPException:
            raise ValueError(f"Could not access {label} `{channel_id}`.") from None

    if not isinstance(channel, discord.TextChannel):
        raise ValueError(f"{label} must be a text channel.")

    return channel


def parse_message_link(link: str) -> tuple[int, int, int]:
    match = MESSAGE_LINK_PATTERN.fullmatch(link.strip())
    if not match:
        raise ValueError("Invalid message link. Right-click a message and choose Copy Message Link.")

    guild_id_raw, channel_id_raw, message_id_raw = match.groups()
    if guild_id_raw == "@me":
        raise ValueError("DM message links are not supported.")

    return int(guild_id_raw), int(channel_id_raw), int(message_id_raw)


def clone_embeds(embeds: list[discord.Embed]) -> list[discord.Embed]:
    return [discord.Embed.from_dict(embed.to_dict()) for embed in embeds]


async def build_mirror_files(message: discord.Message) -> list[discord.File]:
    files: list[discord.File] = []
    for attachment in message.attachments:
        files.append(await attachment.to_file())
    return files


class Mirror(commands.Cog):
    """Copy embeds from bot messages in one channel to channels in other servers."""

    mirror_group = app_commands.Group(
        name="mirror",
        description="Copy and mirror embeds across servers.",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.store = MirrorStore()
        self._webhook_cache: dict[int, discord.Webhook] = {}

    async def _get_webhook(self, webhook_id: int) -> Optional[discord.Webhook]:
        cached = self._webhook_cache.get(webhook_id)
        if cached is not None:
            return cached

        try:
            webhook = await self.bot.fetch_webhook(webhook_id)
        except discord.HTTPException:
            logger.warning("Could not fetch webhook %s for mirror author check", webhook_id)
            return None

        self._webhook_cache[webhook_id] = webhook
        return webhook

    async def _matches_author_filter(self, message: discord.Message, mirror: MirrorConfig) -> bool:
        if mirror.bots_only and not message.author.bot and not message.webhook_id:
            logger.debug(
                "Mirror %s skipped message %s: author is not a bot or webhook",
                mirror.id,
                message.id,
            )
            return False

        if not mirror.filter_bot_id:
            return True

        if message.author.id == mirror.filter_bot_id:
            return True

        if message.application_id == mirror.filter_bot_id:
            return True

        if message.webhook_id == mirror.filter_bot_id:
            return True

        if message.webhook_id:
            webhook = await self._get_webhook(message.webhook_id)
            if webhook and webhook.user and webhook.user.id == mirror.filter_bot_id:
                return True

        logger.info(
            "Mirror %s skipped message %s: author %s (webhook=%s) does not match filter %s",
            mirror.id,
            message.id,
            message.author.id,
            message.webhook_id,
            mirror.filter_bot_id,
        )
        return False

    async def _process_message(self, message: discord.Message) -> None:
        if message.author.id == self.bot.user.id:
            return
        if not message.embeds and not message.attachments:
            return

        mirrors = self.store.get_for_source(message.channel.id)
        if not mirrors:
            return

        logger.info(
            "Mirror check for message %s in channel %s (%d embed(s), %d attachment(s))",
            message.id,
            message.channel.id,
            len(message.embeds),
            len(message.attachments),
        )

        for mirror in mirrors:
            if not await self._matches_author_filter(message, mirror):
                continue
            await self._mirror_to_config(message, mirror)

    async def _send_mirrored_message(
        self,
        destination: discord.abc.Messageable,
        message: discord.Message,
    ) -> discord.Message:
        embeds = clone_embeds(message.embeds)
        files = await build_mirror_files(message)

        kwargs: dict = {}
        if embeds:
            kwargs["embeds"] = embeds
        if files:
            kwargs["files"] = files

        if not kwargs:
            raise ValueError("That message has no embeds or attachments to mirror.")

        return await destination.send(**kwargs)

    async def _mirror_to_config(self, message: discord.Message, mirror: MirrorConfig) -> None:
        if not message.embeds and not message.attachments:
            return

        destination = self.bot.get_channel(mirror.destination_channel_id)
        if destination is None:
            try:
                destination = await self.bot.fetch_channel(mirror.destination_channel_id)
            except discord.HTTPException:
                logger.warning(
                    "Mirror %s destination channel %s is unavailable",
                    mirror.id,
                    mirror.destination_channel_id,
                )
                return

        if not isinstance(destination, discord.abc.Messageable):
            return

        try:
            mirrored = await self._send_mirrored_message(destination, message)
            logger.info(
                "Mirrored message %s to channel %s (mirror %s): %s",
                message.id,
                mirror.destination_channel_id,
                mirror.id,
                mirrored.jump_url,
            )
        except discord.Forbidden:
            logger.warning(
                "Missing permissions to mirror into channel %s (mirror %s)",
                mirror.destination_channel_id,
                mirror.id,
            )
        except discord.HTTPException:
            logger.exception(
                "Failed to mirror message %s to channel %s (mirror %s)",
                message.id,
                mirror.destination_channel_id,
                mirror.id,
            )

    @mirror_group.command(name="add", description="Auto-mirror new embeds from a source channel.")
    @app_commands.describe(
        source_channel_id="Source channel ID (right-click channel → Copy Channel ID).",
        destination_channel_id="Destination channel ID from any server this bot is in.",
        bot_id="Optional bot/app user ID to mirror only that author.",
    )
    async def mirror_add(
        self,
        interaction: discord.Interaction,
        source_channel_id: str,
        destination_channel_id: str,
        bot_id: Optional[str] = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            source_id = parse_channel_id(source_channel_id, "source channel ID")
            destination_id = parse_channel_id(destination_channel_id, "destination channel ID")
            filter_bot_id = parse_user_id(bot_id) if bot_id else None
            source = await resolve_text_channel(self.bot, source_id, "source channel")
            destination = await resolve_text_channel(self.bot, destination_id, "destination channel")
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        if source.id == destination.id:
            await interaction.followup.send("Source and destination must be different channels.", ephemeral=True)
            return

        existing = self.store.find_duplicate(source.id, destination.id, filter_bot_id)
        if existing:
            await interaction.followup.send(
                f"A matching mirror already exists (`{existing.id}`).",
                ephemeral=True,
            )
            return

        mirror = self.store.add(
            source_channel_id=source.id,
            destination_channel_id=destination.id,
            filter_bot_id=filter_bot_id,
            bots_only=True,
        )

        filter_note = f" from <@{filter_bot_id}>" if filter_bot_id else " from any bot"
        await interaction.followup.send(
            f"Mirror `{mirror.id}` created.\n"
            f"New embeds in {source.mention}{filter_note} will be copied to {destination.mention}.",
            ephemeral=True,
        )

    @mirror_group.command(name="remove", description="Remove an auto-mirror by ID.")
    @app_commands.describe(mirror_id="The mirror ID shown in /mirror list.")
    async def mirror_remove(self, interaction: discord.Interaction, mirror_id: str) -> None:
        removed = self.store.remove(mirror_id.strip())
        if removed is None:
            await interaction.response.send_message(f"No mirror found with ID `{mirror_id}`.", ephemeral=True)
            return

        await interaction.response.send_message(f"Removed mirror `{removed.id}`.", ephemeral=True)

    @mirror_group.command(name="list", description="Show configured auto-mirrors.")
    async def mirror_list(self, interaction: discord.Interaction) -> None:
        mirrors = self.store.list_all()
        if not mirrors:
            await interaction.response.send_message("No mirrors configured yet.", ephemeral=True)
            return

        lines: list[str] = []
        for mirror in mirrors:
            source = f"<#{mirror.source_channel_id}>"
            destination = f"<#{mirror.destination_channel_id}>"
            bot_note = f"bot `<@{mirror.filter_bot_id}>`" if mirror.filter_bot_id else "any bot"
            lines.append(f"`{mirror.id}`: {source} -> {destination} ({bot_note})")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @mirror_group.command(name="copy", description="One-time copy of embeds from a message link.")
    @app_commands.describe(
        message_link="Right-click the source message and choose Copy Message Link.",
        destination_channel_id="Destination channel ID (right-click channel → Copy Channel ID).",
    )
    async def mirror_copy(
        self,
        interaction: discord.Interaction,
        message_link: str,
        destination_channel_id: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            _, channel_id, message_id = parse_message_link(message_link)
            destination_id = parse_channel_id(destination_channel_id, "destination channel ID")
            destination = await resolve_text_channel(self.bot, destination_id, "destination channel")
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        source_channel = self.bot.get_channel(channel_id)
        if source_channel is None:
            try:
                source_channel = await self.bot.fetch_channel(channel_id)
            except discord.HTTPException:
                await interaction.followup.send("Could not access the source channel.", ephemeral=True)
                return

        if not isinstance(source_channel, discord.abc.Messageable):
            await interaction.followup.send("That channel cannot contain messages.", ephemeral=True)
            return

        try:
            source_message = await source_channel.fetch_message(message_id)
        except discord.NotFound:
            await interaction.followup.send("Message not found.", ephemeral=True)
            return
        except discord.Forbidden:
            await interaction.followup.send("Missing permission to read that message.", ephemeral=True)
            return

        if not source_message.embeds and not source_message.attachments:
            await interaction.followup.send("That message has no embeds or attachments to copy.", ephemeral=True)
            return

        try:
            mirrored = await self._send_mirrored_message(destination, source_message)
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except discord.Forbidden:
            await interaction.followup.send(
                f"Missing permission to send messages in {destination.mention}.",
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            logger.exception("Failed to copy message %s to %s", message_id, destination.id)
            await interaction.followup.send("Failed to copy the message.", ephemeral=True)
            return

        await interaction.followup.send(
            f"Copied {len(source_message.embeds)} embed(s) to {destination.mention}: {mirrored.jump_url}",
            ephemeral=True,
        )

    @mirror_group.command(name="test", description="Check why a message would or would not mirror.")
    @app_commands.describe(message_link="Copy Message Link from the source embed.")
    async def mirror_test(self, interaction: discord.Interaction, message_link: str) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            _, channel_id, message_id = parse_message_link(message_link)
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        source_channel = self.bot.get_channel(channel_id)
        if source_channel is None:
            try:
                source_channel = await self.bot.fetch_channel(channel_id)
            except discord.HTTPException:
                await interaction.followup.send("Could not access the source channel.", ephemeral=True)
                return

        if not isinstance(source_channel, discord.abc.Messageable):
            await interaction.followup.send("That channel cannot contain messages.", ephemeral=True)
            return

        try:
            message = await source_channel.fetch_message(message_id)
        except discord.NotFound:
            await interaction.followup.send("Message not found.", ephemeral=True)
            return
        except discord.Forbidden:
            await interaction.followup.send("Missing permission to read that message.", ephemeral=True)
            return

        mirrors = self.store.get_for_source(channel_id)
        lines = [
            f"**Message** `{message.id}`",
            f"Author: `{message.author}` (`{message.author.id}`) bot={message.author.bot}",
            f"Webhook ID: `{message.webhook_id}`",
            f"Application ID: `{message.application_id}`",
            f"Embeds: {len(message.embeds)} | Attachments: {len(message.attachments)}",
        ]

        if not mirrors:
            lines.append("\n**No mirrors** configured for this channel.")
        else:
            lines.append("\n**Mirror checks:**")
            for mirror in mirrors:
                matches = await self._matches_author_filter(message, mirror)
                status = "would mirror" if matches else "would skip"
                lines.append(
                    f"- `{mirror.id}` -> <#{mirror.destination_channel_id}> "
                    f"(filter `<@{mirror.filter_bot_id}>`): **{status}**"
                )

        lines.append(
            "\nAuto-mirror only runs on **new** messages after the mirror is saved. "
            "Use `/mirror copy` for existing messages."
        )
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        await self._process_message(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if before.embeds == after.embeds and before.attachments == after.attachments:
            return
        await self._process_message(after)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Mirror(bot))

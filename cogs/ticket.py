import io
import os
import nextcord
from nextcord.ext import commands
from nextcord import ui
from datetime import datetime, timezone

LOG_CHANNEL_ID = int(os.getenv("CANALE_LOG_ID", "0"))


class TicketCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def generate_transcript(self, channel):
        messages = []
        async for msg in channel.history(limit=2000, oldest_first=True):
            messages.append(msg)
        if not messages:
            return None
        rows = []
        for m in messages:
            time    = m.created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            content = (m.content or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            if m.attachments:
                for att in m.attachments:
                    content += f"<br><i style='color:#6366f1;'>[Allegato: {att.filename}]</i>"
            rows.append(
                f"<tr><td style='padding:8px;border:1px solid #334;'>{time}</td>"
                f"<td style='padding:8px;border:1px solid #334;'><b>{m.author}</b></td>"
                f"<td style='padding:8px;border:1px solid #334;'>{content}</td></tr>"
            )
        html = (
            "<html><body style='font-family:sans-serif;background:#04060f;color:#e8f0ff;padding:20px;'>"
            f"<h2 style='color:#3b8eea;'>Transcript: #{channel.name}</h2>"
            "<table style='width:100%;border-collapse:collapse;'>"
            + "".join(rows) +
            "</table></body></html>"
        )
        return nextcord.File(
            io.BytesIO(html.encode("utf-8")),
            filename=f"transcript-{channel.name}.html",
        )

    @nextcord.slash_command(name="ticket", description="Apri un ticket con la Dirigenza")
    async def ticket_panel(self, interaction: nextcord.Interaction):
        embed = nextcord.Embed(
            title="🎫 Supporto — Polizia d'Estovia",
            description="Seleziona una categoria per aprire un ticket con la Dirigenza.",
            color=0x0052b4,
        )
        await interaction.response.send_message(embed=embed, view=TicketCategoryView(self.bot))

    @nextcord.slash_command(name="close", description="Chiudi il ticket corrente")
    async def close_ticket(self, interaction: nextcord.Interaction):
        if not interaction.channel.name.startswith("ticket-"):
            return await interaction.response.send_message(
                "❌ Questo comando funziona solo nei canali ticket.", ephemeral=True
            )
        await interaction.response.send_message("💾 Chiusura in corso...")
        transcript = await self.generate_transcript(interaction.channel)
        if LOG_CHANNEL_ID:
            log_ch = self.bot.get_channel(LOG_CHANNEL_ID)
            if log_ch and transcript:
                await log_ch.send(
                    content=(
                        f"📑 **Ticket Chiuso**\n"
                        f"**Canale:** {interaction.channel.name}\n"
                        f"**Chiuso da:** {interaction.user.mention}"
                    ),
                    file=transcript,
                )
        await interaction.channel.delete()

    @nextcord.slash_command(name="claim", description="Prendi in carico il ticket")
    async def claim_ticket(self, interaction: nextcord.Interaction):
        if not interaction.channel.name.startswith("ticket-"):
            return await interaction.response.send_message("Solo nei ticket!", ephemeral=True)
        embed = nextcord.Embed(
            description=f"🙋 Ticket preso in carico da {interaction.user.mention}",
            color=0xf59e0b,
        )
        await interaction.response.send_message(embed=embed)

    @nextcord.slash_command(name="add", description="Aggiungi un utente al ticket")
    async def add_user(self, interaction: nextcord.Interaction, user: nextcord.Member):
        if not interaction.channel.name.startswith("ticket-"):
            return
        await interaction.channel.set_permissions(
            user, view_channel=True, send_messages=True, read_message_history=True
        )
        await interaction.response.send_message(f"{user.mention} aggiunto al ticket.")


class TicketCategoryView(ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.add_item(CategorySelect(bot))


class CategorySelect(ui.Select):
    def __init__(self, bot):
        self.bot = bot
        options = [
            nextcord.SelectOption(label="Dirigenza",        value="dirigenza",       emoji="📁"),
            nextcord.SelectOption(label="Segnalazione",     value="segnalazione",    emoji="⚠️"),
            nextcord.SelectOption(label="Richiesta Grado",  value="richiesta_grado", emoji="🎖️"),
            nextcord.SelectOption(label="Altro",            value="altro",           emoji="🛠️"),
        ]
        super().__init__(placeholder="Seleziona la categoria...", options=options)

    async def callback(self, interaction: nextcord.Interaction):
        await interaction.response.send_modal(TicketModal(self.bot, self.values[0]))


class TicketModal(ui.Modal):
    def __init__(self, bot, categoria: str):
        super().__init__(title=f"Ticket — {categoria.replace('_', ' ').title()}")
        self.bot       = bot
        self.categoria = categoria

        self.nome_cognome = ui.TextInput(
            label="Nome e Cognome",
            placeholder="Es. Mario Rossi",
            required=True,
        )
        self.add_item(self.nome_cognome)

        self.cf = ui.TextInput(
            label="Codice Fiscale / Username",
            placeholder="Il tuo CF nel gestionale",
            required=True,
        )
        self.add_item(self.cf)

        self.motivo = ui.TextInput(
            label="Motivo del ticket",
            placeholder="Descrivi brevemente il problema",
            required=True,
            style=nextcord.TextInputStyle.paragraph,
        )
        self.add_item(self.motivo)

    async def callback(self, interaction: nextcord.Interaction):
        guild = interaction.guild
        cat = nextcord.utils.get(guild.categories, name="TICKET") or await guild.create_category("TICKET")

        overwrites = {
            guild.default_role: nextcord.PermissionOverwrite(view_channel=False),
            interaction.user:   nextcord.PermissionOverwrite(view_channel=True, send_messages=True),
        }
        channel = await guild.create_text_channel(
            name=f"ticket-{interaction.user.name}",
            category=cat,
            overwrites=overwrites,
        )

        embed = nextcord.Embed(title="🎫 Ticket Aperto", color=0x10b981)
        embed.add_field(name="Agente",        value=interaction.user.mention, inline=True)
        embed.add_field(name="Categoria",     value=self.categoria,           inline=True)
        embed.add_field(name="\u200b",        value="\u200b",                 inline=True)
        embed.add_field(name="Nome Cognome",  value=self.nome_cognome.value,  inline=True)
        embed.add_field(name="CF / Username", value=self.cf.value,            inline=True)
        embed.add_field(name="Motivo",        value=self.motivo.value,        inline=False)
        embed.set_footer(text="Polizia d'Estovia — usa /close per chiudere il ticket")

        await channel.send(content=f"{interaction.user.mention} Il tuo ticket è stato aperto.", embed=embed)
        await interaction.response.send_message(f"✅ Ticket creato: {channel.mention}", ephemeral=True)


def setup(bot):
    bot.add_cog(TicketCog(bot))

import nextcord
from nextcord.ext import commands
from datetime import datetime, timezone
import os

CITTADINO_ROLE_ID  = int(os.getenv("CITTADINO_ROLE_ID", "0"))
WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID", "0"))


class Benvenuto(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: nextcord.Member):
        # Assegna ruolo cittadino automaticamente
        if CITTADINO_ROLE_ID:
            role = member.guild.get_role(CITTADINO_ROLE_ID)
            if role:
                try:
                    await member.add_roles(role)
                except Exception as e:
                    print(f"[Benvenuto] Errore assegnazione ruolo: {e}")

        # Messaggio di benvenuto
        embed = nextcord.Embed(
            title="🚔 Benvenuto nella Polizia d'Estovia!",
            description=(
                f"Ciao {member.mention}, benvenuto nel server del Dipartimento.\n\n"
                "Leggi le regole e attendi l'assegnazione del tuo ruolo dalla Dirigenza."
            ),
            color=0x0052b4,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text="Polizia d'Estovia — Dipartimento di Polizia")

        if WELCOME_CHANNEL_ID:
            channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
            if channel:
                await channel.send(embed=embed)


def setup(bot):
    bot.add_cog(Benvenuto(bot))

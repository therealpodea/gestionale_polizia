"""
Cog: Candidatura
Slash command /candidatura → pubblica pannello nel canale.
I nuovi candidati compilano il form Discord e la candidatura
viene inviata al canale staff con bottoni Approva/Rifiuta.
All'approvazione: assegna ruolo Tirocinante + cambia nickname.
"""
import os
import nextcord
from nextcord.ext import commands
from datetime import datetime, timezone

TIROCINANTE_ROLE_ID  = int(os.getenv("ROLE_AGENTE",     "0"))   # ruolo assegnato all'approvazione
CANALE_CANDIDATURE   = int(os.getenv("CANALE_CANDIDATURE_ID", "0"))  # canale dove mandare le candidature


class ApprovalView(nextcord.ui.View):
    """Bottoni Approva/Rifiuta sul messaggio della candidatura."""
    def __init__(self):
        super().__init__(timeout=None)

    @nextcord.ui.button(label="✅ Approva", style=nextcord.ButtonStyle.green, custom_id="cand_approva")
    async def approva(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        embed = interaction.message.embeds[0]
        # Recupera l'ID utente dal campo "Utente Discord"
        user_field = next((f.value for f in embed.fields if "Utente" in f.name), "")
        user_id = int("".join(filter(str.isdigit, user_field))) if user_field else None

        if not user_id:
            return await interaction.response.send_message("❌ Impossibile trovare l'utente.", ephemeral=True)

        guild  = interaction.guild
        member = guild.get_member(user_id) or await guild.fetch_member(user_id)
        if not member:
            return await interaction.response.send_message("❌ Utente non trovato nel server.", ephemeral=True)

        # Assegna ruolo Agente/Tirocinante
        if TIROCINANTE_ROLE_ID:
            role = guild.get_role(TIROCINANTE_ROLE_ID)
            if role:
                await member.add_roles(role)

        # Aggiorna nickname con "Tir - Nome"
        nome_field = next((f.value for f in embed.fields if "Nome" in f.name), "")
        if nome_field:
            try:
                await member.edit(nick=f"Tir - {nome_field}")
            except Exception:
                pass  # Mancanza permessi (es. owner)

        # Notifica all'utente
        try:
            await member.send(
                embed=nextcord.Embed(
                    title="✅ Candidatura Approvata",
                    description=f"La tua candidatura alla **Polizia d'Estovia** è stata approvata! Benvenuto nel Dipartimento.",
                    color=0x10b981,
                    timestamp=datetime.now(timezone.utc),
                ).set_footer(text="Polizia d'Estovia")
            )
        except Exception:
            pass

        # Disabilita bottoni
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(
            content=f"✅ Approvata da {interaction.user.mention}",
            view=self,
        )
        await interaction.response.send_message(f"✅ Candidatura di {member.mention} approvata!", ephemeral=True)

    @nextcord.ui.button(label="❌ Rifiuta", style=nextcord.ButtonStyle.red, custom_id="cand_rifiuta")
    async def rifiuta(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        embed = interaction.message.embeds[0]
        user_field = next((f.value for f in embed.fields if "Utente" in f.name), "")
        user_id = int("".join(filter(str.isdigit, user_field))) if user_field else None

        if user_id:
            member = interaction.guild.get_member(user_id)
            if member:
                try:
                    await member.send(
                        embed=nextcord.Embed(
                            title="❌ Candidatura Rifiutata",
                            description="La tua candidatura alla Polizia d'Estovia è stata rifiutata. Puoi riprovare in futuro.",
                            color=0xef4444,
                        ).set_footer(text="Polizia d'Estovia")
                    )
                except Exception:
                    pass

        for item in self.children:
            item.disabled = True
        await interaction.message.edit(
            content=f"❌ Rifiutata da {interaction.user.mention}",
            view=self,
        )
        await interaction.response.send_message("❌ Candidatura rifiutata.", ephemeral=True)


class CandidaturaButton(nextcord.ui.View):
    """Bottone 'Candidati' nel pannello pubblico."""
    def __init__(self):
        super().__init__(timeout=None)

    @nextcord.ui.button(label="📋 Candidati", style=nextcord.ButtonStyle.green, custom_id="apri_form_cand")
    async def candidati(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.response.send_modal(FormCandidatura())


class FormCandidatura(nextcord.ui.Modal):
    def __init__(self):
        super().__init__("Candidatura — Polizia d'Estovia")

        self.nome = nextcord.ui.TextInput(
            label="Nome e Cognome",
            placeholder="Es. Mario Rossi",
            required=True, max_length=60,
        )
        self.add_item(self.nome)

        self.cf = nextcord.ui.TextInput(
            label="Codice Fiscale / Nickname di gioco",
            placeholder="Il tuo CF o nick nel gioco",
            required=True, max_length=30,
        )
        self.add_item(self.cf)

        self.motivazione = nextcord.ui.TextInput(
            label="Perché vuoi entrare nel Dipartimento?",
            placeholder="Motiva la tua candidatura in modo chiaro…",
            required=True,
            style=nextcord.TextInputStyle.paragraph,
            max_length=500,
        )
        self.add_item(self.motivazione)

        self.esperienza = nextcord.ui.TextInput(
            label="Esperienza precedente (opzionale)",
            placeholder="Hai già fatto parte di dipartimenti simili?",
            required=False,
            style=nextcord.TextInputStyle.paragraph,
            max_length=300,
        )
        self.add_item(self.esperienza)

    async def callback(self, interaction: nextcord.Interaction):
        if not CANALE_CANDIDATURE:
            return await interaction.response.send_message(
                "❌ Canale candidature non configurato. Contatta la Dirigenza.", ephemeral=True
            )

        canale = interaction.guild.get_channel(CANALE_CANDIDATURE)
        if not canale:
            return await interaction.response.send_message(
                "❌ Canale candidature non trovato.", ephemeral=True
            )

        embed = nextcord.Embed(
            title="📋 Nuova Candidatura",
            color=0x0052b4,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="👤 Nome e Cognome",  value=self.nome.value,        inline=False)
        embed.add_field(name="🪪 CF / Nickname",   value=self.cf.value,          inline=True)
        embed.add_field(name="🏷️ Utente Discord",  value=interaction.user.mention, inline=True)
        embed.add_field(name="💬 Motivazione",     value=self.motivazione.value, inline=False)
        if self.esperienza.value:
            embed.add_field(name="📌 Esperienza",  value=self.esperienza.value,  inline=False)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text=f"ID: {interaction.user.id} · Polizia d'Estovia")

        await canale.send(embed=embed, view=ApprovalView())
        await interaction.response.send_message(
            "✅ Candidatura inviata! Attendi la valutazione della Dirigenza.", ephemeral=True
        )


class CandidaturaCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @nextcord.slash_command(
        name="candidatura",
        description="Pubblica il pannello candidature nel canale corrente",
    )
    async def candidatura_panel(self, interaction: nextcord.Interaction):
        """Solo per la Dirigenza — pubblica il pannello nel canale."""
        embed = nextcord.Embed(
            title="🚔 Candidature — Polizia d'Estovia",
            description=(
                "Vuoi entrare a far parte del Dipartimento di Polizia d'Estovia?\n\n"
                "Clicca il pulsante qui sotto, compila il modulo e attendi la valutazione della Dirigenza.\n\n"
                "**Requisiti:** leggere il regolamento interno e impegnarsi a rispettarlo."
            ),
            color=0x0052b4,
        )
        embed.set_footer(text="Polizia d'Estovia — Dipartimento di Polizia")

        await interaction.channel.send(embed=embed, view=CandidaturaButton())
        await interaction.response.send_message("✅ Pannello candidature pubblicato!", ephemeral=True)


def setup(bot):
    bot.add_cog(CandidaturaCog(bot))

import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
import json
import os
import locale
import aiohttp

try:
    locale.setlocale(locale.LC_TIME, 'it_IT.UTF-8')
except:
    try:
        locale.setlocale(locale.LC_TIME, 'Italian_Italy.1252')
    except:
        pass

# ============================================================
#  CONFIGURAZIONE SYNC GESTIONALE
#  Imposta queste variabili d'ambiente oppure modificale qui.
# ============================================================
GESTIONALE_URL = os.getenv("GESTIONALE_URL", "https://gestionale-polizia.onrender.com/api/sync")
GESTIONALE_KEY = os.getenv("SYNC_KEY", "estovia_2026_secret")

async def sync_gestionale(discord_nick: str, tipo: str, nuovo: str, motivo: str, eseguito_da: str = ""):
    params = {
        "discord": discord_nick,
        "grado":   nuovo,
        "tipo":    tipo,
        "motivo":  f"{motivo} [da: {eseguito_da}]" if eseguito_da else motivo,
        "key":     GESTIONALE_KEY
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(GESTIONALE_URL, params=params, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                data = await resp.json()
                if resp.status == 200 and data.get("ok"):
                    print(f"✅ Sync gestionale → {discord_nick} | {tipo} → {nuovo}")
                else:
                    print(f"⚠️ Sync gestionale: {data.get('error', resp.status)} per {discord_nick}")
    except Exception as e:
        print(f"⚠️ Sync gestionale non raggiunta ({e}) — azione Discord completata comunque")


intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

CONFIG_FILE = "config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {
        "ruolo_mantenuto_licenziamento": None,
        "ruoli_sanzioni": {},
        "gerarchia_ruoli": []
    }

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

config = load_config()


# ============================================================
#  EVENTI BOT
# ============================================================

@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f'✅ {bot.user} è online!')
        print(f'📋 {len(synced)} comandi sincronizzati')
        print(f'🔧 {len(config.get("gerarchia_ruoli", []))} ruoli gerarchici caricati')
    except Exception as e:
        print(f'❌ Errore sincronizzazione: {e}')

@bot.event
async def on_command_error(ctx, error):
    print(f"❌ Errore comando: {error}")

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    print(f"❌ Errore app command: {error}")
    msg = f"❌ Si è verificato un errore: {str(error)}"
    if not interaction.response.is_done():
        await interaction.response.send_message(msg, ephemeral=True)
    else:
        await interaction.followup.send(msg, ephemeral=True)


# ============================================================
#  COMANDI DI CONFIGURAZIONE
# ============================================================

@bot.tree.command(name="set_ruolo_licenziamento", description="Imposta il ruolo da mantenere durante il licenziamento")
@app_commands.describe(ruolo="Il ruolo che verrà mantenuto quando un utente viene licenziato")
async def set_ruolo_licenziamento(interaction: discord.Interaction, ruolo: discord.Role):
    config["ruolo_mantenuto_licenziamento"] = ruolo.id
    save_config(config)
    await interaction.response.send_message(
        f"✅ **Ruolo licenziamento impostato**\n\nRuolo: {ruolo.mention}\n"
        f"Verrà mantenuto al licenziamento.",
        ephemeral=True
    )

@bot.tree.command(name="set_ruolo_sanzione", description="Imposta un ruolo per un tipo di sanzione")
@app_commands.describe(
    nome_sanzione="Nome della sanzione (es: avviso_formale_1, richiamo_1)",
    ruolo="Il ruolo da assegnare per questa sanzione"
)
async def set_ruolo_sanzione(interaction: discord.Interaction, nome_sanzione: str, ruolo: discord.Role):
    config["ruoli_sanzioni"][nome_sanzione.lower()] = ruolo.id
    save_config(config)
    sanzioni_str = "\n".join([
        f"• `{n}` → {interaction.guild.get_role(rid).mention if interaction.guild.get_role(rid) else 'Ruolo non trovato'}"
        for n, rid in config["ruoli_sanzioni"].items()
    ])
    await interaction.response.send_message(
        f"✅ **Ruolo sanzione configurato**\n\n"
        f"Sanzione: `{nome_sanzione.lower()}`\nRuolo: {ruolo.mention}\n\n"
        f"**Sanzioni attive:**\n{sanzioni_str}",
        ephemeral=True
    )


# ============================================================
#  CONFIGURAZIONE GERARCHIA
# ============================================================

@bot.tree.command(name="configura_gerarchia", description="Configura la gerarchia dei ruoli (dal più alto al più basso)")
async def configura_gerarchia(interaction: discord.Interaction):
    view = GerarchiaConfigView()
    await interaction.response.send_message(
        "📋 **CONFIGURAZIONE GERARCHIA RUOLI**\n\n"
        "Aggiungi i ruoli in ordine dal **più alto** al **più basso**.\n"
        "⚠️ `/promuovi` e `/degrada` rimuoveranno automaticamente i ruoli gerarchici precedenti.",
        view=view, ephemeral=True
    )

class GerarchiaConfigView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.gerarchia = config.get("gerarchia_ruoli", []).copy()

    @discord.ui.button(label="Aggiungi Ruolo", style=discord.ButtonStyle.primary, emoji="➕")
    async def aggiungi_ruolo(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Seleziona un ruolo da aggiungere:", view=RuoloSelectView(self), ephemeral=True
        )

    @discord.ui.button(label="Salva Gerarchia", style=discord.ButtonStyle.success, emoji="✅")
    async def salva_gerarchia(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.gerarchia:
            await interaction.response.send_message("❌ Aggiungi almeno un ruolo!", ephemeral=True)
            return
        config["gerarchia_ruoli"] = self.gerarchia
        save_config(config)
        nomi = [interaction.guild.get_role(r).name for r in self.gerarchia if interaction.guild.get_role(r)]
        await interaction.response.send_message(
            "✅ **Gerarchia salvata!**\n\n**Dal più alto al più basso:**\n" +
            "\n".join([f"`{i+1}.` **{n}**" for i, n in enumerate(nomi)]),
            ephemeral=True
        )
        self.stop()

    @discord.ui.button(label="Mostra Gerarchia", style=discord.ButtonStyle.secondary, emoji="📋")
    async def mostra_gerarchia(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.gerarchia:
            await interaction.response.send_message("📋 Nessun ruolo ancora.", ephemeral=True)
            return
        nomi = [interaction.guild.get_role(r).name for r in self.gerarchia if interaction.guild.get_role(r)]
        await interaction.response.send_message(
            "**📋 Gerarchia attuale:**\n" + "\n".join([f"`{i+1}.` **{n}**" for i, n in enumerate(nomi)]),
            ephemeral=True
        )

    @discord.ui.button(label="Reset", style=discord.ButtonStyle.danger, emoji="🔄")
    async def reset_gerarchia(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.gerarchia = []
        await interaction.response.send_message("✅ Gerarchia resettata.", ephemeral=True)

class RuoloSelectView(discord.ui.View):
    def __init__(self, parent_view):
        super().__init__(timeout=60)
        self.add_item(RuoloSelect(parent_view))

class RuoloSelect(discord.ui.RoleSelect):
    def __init__(self, parent_view):
        super().__init__(placeholder="Seleziona un ruolo...", min_values=1, max_values=1)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        ruolo = self.values[0]
        if ruolo.id in self.parent_view.gerarchia:
            await interaction.response.send_message(f"⚠️ **{ruolo.name}** è già nella gerarchia!", ephemeral=True)
        else:
            self.parent_view.gerarchia.append(ruolo.id)
            await interaction.response.send_message(
                f"✅ **{ruolo.name}** aggiunto in posizione **{len(self.parent_view.gerarchia)}**",
                ephemeral=True
            )


# ============================================================
#  COMANDO /licenzia  ← SYNC AGGIUNTA
# ============================================================

@bot.tree.command(name="licenzia", description="Licenzia un utente rimuovendo tutti i ruoli tranne quello impostato")
@app_commands.describe(utente="L'utente da licenziare", motivazione="Motivo del licenziamento")
async def licenzia(interaction: discord.Interaction, utente: discord.Member, motivazione: str):
    if not config.get("ruolo_mantenuto_licenziamento"):
        await interaction.response.send_message(
            "❌ Imposta prima il ruolo con `/set_ruolo_licenziamento`", ephemeral=True
        )
        return

    ruolo_mantenuto = interaction.guild.get_role(config["ruolo_mantenuto_licenziamento"])
    if not ruolo_mantenuto:
        await interaction.response.send_message(
            "❌ Ruolo non più valido. Reimpostalo con `/set_ruolo_licenziamento`", ephemeral=True
        )
        return

    ruoli_da_rimuovere = [r for r in utente.roles if r != interaction.guild.default_role and r != ruolo_mantenuto]

    try:
        if ruoli_da_rimuovere:
            await utente.remove_roles(*ruoli_da_rimuovere, reason=f"Licenziamento da {interaction.user}")
        if ruolo_mantenuto not in utente.roles:
            await utente.add_roles(ruolo_mantenuto)

        ora = datetime.now().strftime('%H:%M')
        data = datetime.now().strftime("%A %d %B %Y %H:%M")

        embed = discord.Embed(title="⛔ SANZIONI - POLIZIA D'ESTOVIA", color=0xED4245)
        embed.add_field(name="⚠️ TIPO DI SANZIONE", value="**LICENZIAMENTO**", inline=False)
        embed.add_field(name="👤 UTENTE SANZIONATO", value=utente.mention, inline=True)
        embed.add_field(name="👮 SANZIONATO DA", value=interaction.user.mention, inline=True)
        embed.add_field(name="📅 DATA", value=data, inline=True)
        embed.add_field(name="📋 MOTIVAZIONE", value=motivazione, inline=False)
        embed.set_footer(text=f"Polizia D'Estovia - Sistema Sanzionatorio • Oggi alle {ora}")

        await interaction.response.send_message(embed=embed)

        # ── SYNC GESTIONALE ──────────────────────────────────
        await sync_gestionale(
            discord_nick=utente.name,
            tipo="Licenziamento",
            nuovo="Congedato",
            motivo=motivazione,
            eseguito_da=interaction.user.name
        )
        # ─────────────────────────────────────────────────────

    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ Permessi insufficienti. Controlla la posizione del ruolo del bot.", ephemeral=True
        )
    except Exception as e:
        print(f"Errore licenziamento: {e}")
        await interaction.response.send_message(f"❌ Errore: {str(e)}", ephemeral=True)


# ============================================================
#  COMANDO /sanziona  ← SYNC AGGIUNTA
# ============================================================

@bot.tree.command(name="sanziona", description="Sanziona un utente assegnando un ruolo disciplinare")
@app_commands.describe(
    utente="L'utente da sanzionare",
    tipo_sanzione="Il tipo di sanzione da applicare",
    motivazione="Motivo della sanzione",
    durata_giorni="Durata della sanzione in giorni"
)
async def sanziona(interaction: discord.Interaction, utente: discord.Member, tipo_sanzione: str, motivazione: str, durata_giorni: int):
    tipo_lower = tipo_sanzione.lower()
    if tipo_lower not in config["ruoli_sanzioni"]:
        await interaction.response.send_message(
            f"❌ Sanzione `{tipo_sanzione}` non configurata. Usa `/set_ruolo_sanzione`.", ephemeral=True
        )
        return

    ruolo_sanzione = interaction.guild.get_role(config["ruoli_sanzioni"][tipo_lower])
    if not ruolo_sanzione:
        await interaction.response.send_message(
            "❌ Ruolo sanzione non valido. Riconfiguralo con `/set_ruolo_sanzione`.", ephemeral=True
        )
        return

    try:
        await utente.add_roles(ruolo_sanzione, reason=f"Sanzione da {interaction.user}")

        scadenza = datetime.now() + timedelta(days=durata_giorni)
        ora = datetime.now().strftime('%H:%M')
        data = datetime.now().strftime("%A %d %B %Y %H:%M")
        scadenza_str = scadenza.strftime("%A %d %B %Y %H:%M")

        embed = discord.Embed(title="⛔ SANZIONI - POLIZIA D'ESTOVIA", color=0x5865F2)
        embed.add_field(name="⚠️ TIPO DI SANZIONE", value=ruolo_sanzione.mention, inline=False)
        embed.add_field(name="👤 UTENTE SANZIONATO", value=utente.mention, inline=True)
        embed.add_field(name="👮 SANZIONATO DA", value=interaction.user.mention, inline=True)
        embed.add_field(name="📅 DATA", value=data, inline=True)
        embed.add_field(name="📋 MOTIVAZIONE", value=motivazione, inline=False)
        embed.add_field(name="⏱️ DURATA", value=f"**{durata_giorni} giorni** • scadenza {scadenza_str}", inline=False)
        embed.set_footer(text=f"Polizia D'Estovia - Sistema Sanzionatorio • Oggi alle {ora}")

        await interaction.response.send_message(embed=embed)

        # ── SYNC GESTIONALE ──────────────────────────────────
        await sync_gestionale(
            discord_nick=utente.name,
            tipo="Sanzione",
            nuovo=ruolo_sanzione.name,
            motivo=f"{motivazione} (durata: {durata_giorni}gg)",
            eseguito_da=interaction.user.name
        )
        # ─────────────────────────────────────────────────────

    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ Permessi insufficienti. Controlla la posizione del ruolo del bot.", ephemeral=True
        )
    except Exception as e:
        print(f"Errore sanzione: {e}")
        await interaction.response.send_message(f"❌ Errore: {str(e)}", ephemeral=True)


# ============================================================
#  COMANDO /promuovi  ← SYNC AGGIUNTA
# ============================================================

@bot.tree.command(name="promuovi", description="Promuovi un utente ad un grado superiore")
@app_commands.describe(
    utente="L'utente da promuovere",
    nuovo_grado="Il nuovo grado da assegnare",
    motivazione="Motivazione della promozione (opzionale)"
)
async def promuovi(interaction: discord.Interaction, utente: discord.Member, nuovo_grado: discord.Role, motivazione: str = "Promozione per meriti"):
    if not config.get("gerarchia_ruoli"):
        await interaction.response.send_message(
            "❌ Configura prima la gerarchia con `/configura_gerarchia`", ephemeral=True
        )
        return
    if nuovo_grado.id not in config["gerarchia_ruoli"]:
        await interaction.response.send_message(
            f"❌ **{nuovo_grado.name}** non è nella gerarchia. Aggiungilo con `/configura_gerarchia`.",
            ephemeral=True
        )
        return

    try:
        ruoli_da_rimuovere = [r for r in utente.roles if r.id in config["gerarchia_ruoli"]]
        if ruoli_da_rimuovere:
            await utente.remove_roles(*ruoli_da_rimuovere, reason=f"Promozione da {interaction.user}")
        await utente.add_roles(nuovo_grado, reason=f"Promozione da {interaction.user}")

        ora = datetime.now().strftime('%H:%M')
        data = datetime.now().strftime("%A %d %B %Y %H:%M")

        embed = discord.Embed(title="⬆️ PROMOZIONE - POLIZIA D'ESTOVIA", color=0x3BA55D)
        embed.add_field(name="👤 UTENTE PROMOSSO", value=utente.mention, inline=True)
        embed.add_field(name="👮 PROMOSSO DA", value=interaction.user.mention, inline=True)
        embed.add_field(name="📅 DATA", value=data, inline=True)
        embed.add_field(name="🎖️ NUOVO GRADO", value=f"**⬆️ PROMOSSO**\n{nuovo_grado.mention}", inline=False)
        embed.add_field(name="📋 MOTIVAZIONE", value=motivazione, inline=False)
        embed.set_footer(text=f"Polizia D'Estovia - Sistema Gestionale • Oggi alle {ora}")

        await interaction.response.send_message(embed=embed)

        # ── SYNC GESTIONALE ──────────────────────────────────
        await sync_gestionale(
            discord_nick=utente.name,
            tipo="Promozione",
            nuovo=nuovo_grado.name,
            motivo=motivazione,
            eseguito_da=interaction.user.name
        )
        # ─────────────────────────────────────────────────────

    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ Permessi insufficienti. Controlla la posizione del ruolo del bot.", ephemeral=True
        )
    except Exception as e:
        print(f"Errore promozione: {e}")
        await interaction.response.send_message(f"❌ Errore: {str(e)}", ephemeral=True)


# ============================================================
#  COMANDO /degrada  ← SYNC AGGIUNTA
# ============================================================

@bot.tree.command(name="degrada", description="Degrada un utente ad un grado inferiore")
@app_commands.describe(
    utente="L'utente da degradare",
    nuovo_grado="Il grado a cui viene degradato"
)
async def degrada(interaction: discord.Interaction, utente: discord.Member, nuovo_grado: discord.Role):
    if not config.get("gerarchia_ruoli"):
        await interaction.response.send_message(
            "❌ Configura prima la gerarchia con `/configura_gerarchia`", ephemeral=True
        )
        return
    if nuovo_grado.id not in config["gerarchia_ruoli"]:
        await interaction.response.send_message(
            f"❌ **{nuovo_grado.name}** non è nella gerarchia. Aggiungilo con `/configura_gerarchia`.",
            ephemeral=True
        )
        return

    view = DegradaView(utente, nuovo_grado, interaction.user)
    await interaction.response.send_message(
        "🔽 **PROCEDURA DI DEGRADO**\n\n"
        "Seleziona eventuali ruoli aggiuntivi da rimuovere (opzionale), poi conferma.",
        view=view, ephemeral=True
    )

class DegradaView(discord.ui.View):
    def __init__(self, utente, nuovo_grado, moderatore):
        super().__init__(timeout=120)
        self.utente = utente
        self.nuovo_grado = nuovo_grado
        self.moderatore = moderatore
        self.ruoli_extra = []
        self.motivazione = "Degrado disciplinare"
        if len(utente.roles) > 1:
            self.add_item(RuoliDegradaSelect(self))
        self.add_item(MotivazioneButton(self))

    @discord.ui.button(label="Conferma Degrado", style=discord.ButtonStyle.danger, emoji="✅", row=2)
    async def conferma_degrado(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            ruoli_ger = [r for r in self.utente.roles if r.id in config["gerarchia_ruoli"]]
            tutti = list(set(ruoli_ger + self.ruoli_extra))
            if tutti:
                await self.utente.remove_roles(*tutti, reason=f"Degrado da {self.moderatore}")
            await self.utente.add_roles(self.nuovo_grado, reason=f"Degrado da {self.moderatore}")

            ora = datetime.now().strftime('%H:%M')
            data = datetime.now().strftime("%A %d %B %Y %H:%M")

            embed = discord.Embed(title="⬇️ DEGRADO - POLIZIA D'ESTOVIA", color=0xFF9500)
            embed.add_field(name="👤 UTENTE DEGRADATO", value=self.utente.mention, inline=True)
            embed.add_field(name="👮 DEGRADATO DA", value=self.moderatore.mention, inline=True)
            embed.add_field(name="📅 DATA", value=data, inline=True)
            embed.add_field(name="📉 NUOVO GRADO", value=f"**⬇️ DEGRADATO**\n{self.nuovo_grado.mention}", inline=False)
            embed.add_field(name="📋 MOTIVAZIONE", value=self.motivazione, inline=False)
            if self.ruoli_extra:
                embed.add_field(name="🗑️ RUOLI RIMOSSI", value="\n".join([r.mention for r in self.ruoli_extra]), inline=False)
            embed.set_footer(text=f"Polizia D'Estovia - Sistema Gestionale • Oggi alle {ora}")

            await interaction.response.send_message(embed=embed)
            self.stop()

            # ── SYNC GESTIONALE ──────────────────────────────
            await sync_gestionale(
                discord_nick=self.utente.name,
                tipo="Degrado",
                nuovo=self.nuovo_grado.name,
                motivo=self.motivazione,
                eseguito_da=self.moderatore.name
            )
            # ─────────────────────────────────────────────────

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Permessi insufficienti. Controlla la posizione del ruolo del bot.", ephemeral=True
            )
        except Exception as e:
            print(f"Errore degrado: {e}")
            await interaction.response.send_message(f"❌ Errore: {str(e)}", ephemeral=True)

class MotivazioneButton(discord.ui.Button):
    def __init__(self, parent_view):
        super().__init__(label="Aggiungi Motivazione", style=discord.ButtonStyle.secondary, emoji="📝", row=2)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(MotivazioneModal(self.parent_view))

class MotivazioneModal(discord.ui.Modal, title="Motivazione Degrado"):
    motivazione = discord.ui.TextInput(
        label="Motivazione",
        placeholder="Inserisci la motivazione del degrado...",
        style=discord.TextStyle.paragraph,
        max_length=500
    )

    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        self.parent_view.motivazione = self.motivazione.value
        await interaction.response.send_message(
            f"✅ Motivazione impostata: *{self.motivazione.value}*", ephemeral=True
        )

class RuoliDegradaSelect(discord.ui.RoleSelect):
    def __init__(self, parent_view):
        super().__init__(
            placeholder="Ruoli aggiuntivi da rimuovere (opzionale)...",
            min_values=0, max_values=10, row=0
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.ruoli_extra = self.values
        if self.values:
            await interaction.response.send_message(
                f"✅ {len(self.values)} ruoli aggiuntivi selezionati.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "✅ Nessun ruolo aggiuntivo. Verranno rimossi solo i ruoli gerarchici.", ephemeral=True
            )


# ============================================================
#  COMANDO /info_bot
# ============================================================

@bot.tree.command(name="info_bot", description="Mostra informazioni sul bot e la configurazione attuale")
async def info_bot(interaction: discord.Interaction):
    embed = discord.Embed(
        title="ℹ️ Bot - Polizia D'Estovia",
        color=0x5865F2,
        description="Sistema gestione sanzioni, promozioni e degradi con sync gestionale"
    )

    ruolo_lic = config.get("ruolo_mantenuto_licenziamento")
    if ruolo_lic:
        r = interaction.guild.get_role(ruolo_lic)
        embed.add_field(name="🚫 Ruolo Licenziamento", value=r.mention if r else "❌ Non trovato", inline=False)
    else:
        embed.add_field(name="🚫 Ruolo Licenziamento", value="❌ Non configurato", inline=False)

    sanzioni = config.get("ruoli_sanzioni", {})
    if sanzioni:
        s_text = "\n".join([
            f"• `{n}` → {interaction.guild.get_role(rid).mention if interaction.guild.get_role(rid) else '❌'}"
            for n, rid in list(sanzioni.items())[:5]
        ])
        if len(sanzioni) > 5:
            s_text += f"\n... e altre {len(sanzioni)-5}"
    else:
        s_text = "❌ Nessuna configurata"
    embed.add_field(name="⚠️ Sanzioni", value=s_text, inline=False)

    gerarchia = config.get("gerarchia_ruoli", [])
    if gerarchia:
        g_text = "\n".join([
            f"`{i+1}.` {interaction.guild.get_role(rid).mention if interaction.guild.get_role(rid) else '❌'}"
            for i, rid in enumerate(gerarchia[:8])
        ])
        if len(gerarchia) > 8:
            g_text += f"\n... e altri {len(gerarchia)-8}"
    else:
        g_text = "❌ Non configurata"
    embed.add_field(name="📊 Gerarchia", value=g_text, inline=False)

    sync_status = f"✅ Configurato → {GESTIONALE_URL}"
    embed.add_field(name="🔗 Sync Gestionale", value=sync_status, inline=False)

    embed.add_field(
        name="📋 Comandi",
        value=(
            "• `/configura_gerarchia` • `/set_ruolo_licenziamento`\n"
            "• `/set_ruolo_sanzione` • `/promuovi` • `/degrada`\n"
            "• `/licenzia` • `/sanziona` • `/info_bot`"
        ),
        inline=False
    )
    embed.set_footer(text="Polizia D'Estovia — Sistema Gestionale")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ============================================================
#  AVVIO BOT
#  ⚠️ Metti il token in una variabile d'ambiente, non nel codice!
#  Esempio: TOKEN = os.getenv("DISCORD_TOKEN")
# ============================================================

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()  # carica automaticamente il file .env

    TOKEN = os.getenv("DISCORD_TOKEN")

    if not TOKEN:
        print("⚠️ Token non trovato!")
        print("Crea un file .env nella stessa cartella con questo contenuto:")
        print('  DISCORD_TOKEN=il_tuo_token_qui')
    else:
        print("🚀 Avvio bot...")
        bot.run(TOKEN)
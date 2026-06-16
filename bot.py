"""
Discord Build Bot — Allods Online
"""

import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import os
import json
import asyncio
from datetime import datetime
from typing import Optional
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

# ─── Serveur HTTP pour Render ─────────────────────────────────────────────────

class HealthCheck(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *args):
        pass

def run_server():
    HTTPServer(("0.0.0.0", 8080), HealthCheck).serve_forever()

threading.Thread(target=run_server, daemon=True).start()

# ─── Configuration ───────────────────────────────────────────────────────────

TOKEN        = os.getenv("DISCORD_TOKEN", "YOUR_TOKEN_HERE")
DB_PATH      = "builds.db"
DELETE_ADD   = 180   # 3 min pour /build-add
DELETE_GET   = 600   # 10 min pour les résultats dashboard

CONTENUS = ["PvE", "PvP"]
ASPECTS  = ["DPS", "Heal", "Tank", "Support"]

CLASSE_ASPECTS = {
    "Cleric":  ["DPS", "Heal", "Support"],
    "War":     ["DPS", "Tank"],
    "Pally":   ["DPS", "Tank"],
    "Warden":  ["DPS", "Heal", "Support"],
    "Summy":   ["DPS", "Heal", "Support"],
    "Demon":   ["DPS", "Tank"],
    "Engi":    ["DPS", "Support"],
    "Bard":    ["DPS", "Support"],
    "Mage":    ["DPS", "Support"],
    "Scout":   ["DPS", "Tank"],
    "Psi":     ["DPS", "Support"],
}

CLASSES = list(CLASSE_ASPECTS.keys())

CLASSE_EMOJIS = {
    "Cleric": "<:Cleric:1515702932094451773>",
    "Summy":  "<:Summy:1515701932868505680>",
    "Warden": "<:Warden:1515701969929637909>",
    "Scout":  "<:Scout:1515701914791186574>",
    "Psi":    "<:Psi:1515701895069700268>",
    "Pally":  "<:Pally:1515701874958012496>",
    "War":    "<:War:1515701951868702720>",
    "Mage":   "<:Mage:1515701858948091915>",
    "Engi":   "<:Engi:1515701821786820730>",
    "Bard":   "<:Bard:1515701718845751367>",
    "Demon":  "<:Demon:1515701796260151378>",
}

# ─── Base de données ──────────────────────────────────────────────────────────

def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS builds (
            id          TEXT    PRIMARY KEY,
            guild_id    TEXT    NOT NULL,
            author_id   TEXT    NOT NULL,
            author_name TEXT    NOT NULL,
            nom         TEXT    NOT NULL,
            classe      TEXT    NOT NULL,
            aspect      TEXT    NOT NULL,
            contenu     TEXT    NOT NULL,
            description TEXT,
            images      TEXT    NOT NULL DEFAULT '[]',
            patch       TEXT,
            created_at  TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS dashboard (
            guild_id    TEXT PRIMARY KEY,
            channel_id  TEXT NOT NULL,
            message_id  TEXT NOT NULL
        );
    """)
    con.commit()
    con.close()

def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def make_id(nom, classe, aspect, author_name):
    date = datetime.utcnow().strftime("%Y-%m-%d")
    nom_clean = "".join(c if c.isalnum() or c in "-_" else "-" for c in nom).strip("-")
    base = f"{nom_clean}_{classe}_{aspect}_{author_name}_{date}"
    con = get_db()
    existing = con.execute("SELECT id FROM builds WHERE id LIKE ?", (f"{base}%",)).fetchall()
    con.close()
    return base if not existing else f"{base}_{len(existing)+1}"

# ─── Dashboard image (style Prop B) ──────────────────────────────────────────

def generate_dashboard_image(guild_id: str) -> BytesIO:
    con = get_db()
    rows = con.execute(
        "SELECT classe, aspect, contenu, COUNT(*) as nb FROM builds WHERE guild_id = ? GROUP BY classe, aspect, contenu",
        (guild_id,)
    ).fetchall()
    total_row = con.execute("SELECT COUNT(*) as nb FROM builds WHERE guild_id = ?", (guild_id,)).fetchone()
    con.close()

    data: dict = {}
    for r in rows:
        data.setdefault(r["classe"], {}).setdefault(r["aspect"], {})[r["contenu"]] = r["nb"]
    total = total_row["nb"] if total_row else 0

    COLS = 3
    CW = 210
    PAD = 14
    CARD_PAD = 8

    BG2      = (47, 49, 54)
    BG_CARD  = (54, 57, 63)
    BG_HDR   = (64, 68, 75)
    BG_ALT   = (50, 52, 58)
    WHITE    = (220, 222, 225)
    GRAY     = (148, 155, 164)
    GREEN    = (87, 200, 120)
    BLUE     = (130, 140, 255)
    GREEN_BG = (30, 45, 33)
    BLUE_BG  = (28, 32, 65)
    BORDER   = (79, 84, 92)
    ACCENT   = (88, 101, 242)
    MUTED    = (80, 83, 90)

    try:
        fb = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 13)
        fn = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
        fs = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
        ft = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 15)
    except:
        fb = fn = fs = ft = ImageFont.load_default()

    def card_h(cls):
        return 28 + len(CLASSE_ASPECTS[cls]) * 20 + 8

    rows_cards = [CLASSES[i:i+COLS] for i in range(0, len(CLASSES), COLS)]
    row_heights = [max(card_h(c) for c in row) for row in rows_cards]

    W = PAD + COLS*(CW+CARD_PAD) - CARD_PAD + PAD
    H = PAD + 54 + PAD + sum(row_heights) + len(row_heights)*CARD_PAD + PAD

    img = Image.new("RGB", (W, H), (32, 34, 37))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W, H], radius=8, fill=BG2)
    d.rectangle([0, 0, 5, H], fill=ACCENT)

    now = datetime.utcnow().strftime("%d/%m/%Y %H:%M")
    d.text((PAD+8, 12), "Bibliothèque de Builds — Allods Online", font=ft, fill=WHITE)
    d.text((PAD+8, 34), f"{total} builds actifs · Mis à jour le {now}", font=fs, fill=GRAY)
    d.line([(PAD+8, 52), (W-PAD, 52)], fill=BORDER, width=1)

    y = 52 + PAD
    for ri, row in enumerate(rows_cards):
        rh = row_heights[ri]
        for ci, cls in enumerate(row):
            cx = PAD + ci*(CW+CARD_PAD)
            cy = y
            ch = card_h(cls)

            d.rounded_rectangle([cx, cy, cx+CW, cy+ch], radius=6, fill=BG_CARD, outline=BORDER, width=1)
            d.rectangle([cx, cy+6, cx+4, cy+ch-6], fill=ACCENT)
            d.text((cx+12, cy+6), cls, font=fb, fill=WHITE)
            d.line([(cx+1, cy+24), (cx+CW-1, cy+24)], fill=BORDER, width=1)

            for k, asp in enumerate(CLASSE_ASPECTS[cls]):
                ay = cy + 28 + k*20
                if k % 2 == 1:
                    d.rectangle([cx+1, ay-1, cx+CW-1, ay+17], fill=BG_ALT)
                p = data.get(cls, {}).get(asp, {}).get("PvE", 0)
                v = data.get(cls, {}).get(asp, {}).get("PvP", 0)
                d.text((cx+10, ay+2), asp, font=fn, fill=GRAY)
                d.text((cx+CW-82, ay+2), f"PvE:{p}", font=fs, fill=GREEN if p>0 else MUTED)
                d.text((cx+CW-40, ay+2), f"PvP:{v}", font=fs, fill=BLUE if v>0 else MUTED)

        y += rh + CARD_PAD

    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf

# ─── Mise à jour dashboard ────────────────────────────────────────────────────

async def update_dashboard(bot, guild_id: str):
    con = get_db()
    row = con.execute("SELECT * FROM dashboard WHERE guild_id = ?", (guild_id,)).fetchone()
    con.close()
    if not row:
        return
    try:
        channel = bot.get_channel(int(row["channel_id"]))
        if not channel:
            return
        old_msg = await channel.fetch_message(int(row["message_id"]))
        await old_msg.delete()
        buf = generate_dashboard_image(guild_id)
        view = DashboardView(guild_id)
        new_msg = await channel.send(file=discord.File(buf, filename="dashboard.png"), view=view)
        con = get_db()
        con.execute("UPDATE dashboard SET message_id = ? WHERE guild_id = ?", (str(new_msg.id), guild_id))
        con.commit()
        con.close()
    except Exception as e:
        print(f"Dashboard update error: {e}")

# ─── Composants interactifs dashboard ────────────────────────────────────────

class AspectSelect(discord.ui.Select):
    def __init__(self, guild_id: str, classe: str):
        self.guild_id = guild_id
        self.classe = classe
        options = []
        for asp in CLASSE_ASPECTS[classe]:
            for contenu in CONTENUS:
                options.append(discord.SelectOption(
                    label=f"{asp} — {contenu}",
                    value=f"{asp}|{contenu}",
                    emoji="🟢" if contenu == "PvE" else "🔵"
                ))
        super().__init__(placeholder=f"Choisir aspect + contenu pour {classe}…", options=options)

    async def callback(self, interaction: discord.Interaction):
        aspect, contenu = self.values[0].split("|")
        con = get_db()
        rows = con.execute(
            "SELECT * FROM builds WHERE guild_id = ? AND classe = ? AND aspect = ? AND contenu = ? ORDER BY created_at ASC",
            (self.guild_id, self.classe, aspect, contenu)
        ).fetchall()
        con.close()

        if not rows:
            await interaction.response.send_message(
                f"😕 Aucun build trouvé pour **{self.classe} — {aspect} — {contenu}**.", ephemeral=True)
            return

        if len(rows) == 1:
            await send_build_result(interaction, rows[0])
        else:
            # Plusieurs builds : propose un choix
            view = BuildChoiceView(self.guild_id, rows)
            embed = discord.Embed(
                title=f"🔍 {len(rows)} builds trouvés — {self.classe} {aspect} {contenu}",
                description="\n".join([f"`{i+1}.` **{r['nom']}** — *par {r['author_name']}*" for i, r in enumerate(rows)]),
                color=discord.Color.blurple()
            )
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

            async def cleanup():
                await asyncio.sleep(DELETE_GET)
                try:
                    await (await interaction.original_response()).delete()
                except Exception:
                    pass
            asyncio.create_task(cleanup())


class BuildChoiceView(discord.ui.View):
    def __init__(self, guild_id: str, rows):
        super().__init__(timeout=DELETE_GET)
        self.add_item(BuildChoiceSelect(guild_id, rows))


class BuildChoiceSelect(discord.ui.Select):
    def __init__(self, guild_id: str, rows):
        self.guild_id = guild_id
        self.rows = rows
        options = [
            discord.SelectOption(label=f"{i+1}. {r['nom']}", description=f"Par {r['author_name']}", value=str(i))
            for i, r in enumerate(rows)
        ]
        super().__init__(placeholder="Choisir un build…", options=options)

    async def callback(self, interaction: discord.Interaction):
        row = self.rows[int(self.values[0])]
        await send_build_result(interaction, row)


class ClasseButton(discord.ui.Button):
    def __init__(self, guild_id: str, classe: str):
        self.guild_id = guild_id
        emoji = CLASSE_EMOJIS.get(classe)
        super().__init__(label=classe, emoji=emoji, style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        view = discord.ui.View(timeout=DELETE_GET)
        view.add_item(AspectSelect(self.guild_id, self.label))
        await interaction.response.send_message(
            f"Sélectionne un aspect et un contenu pour **{self.label}** :",
            view=view, ephemeral=True
        )
        async def cleanup():
            await asyncio.sleep(DELETE_GET)
            try:
                await (await interaction.original_response()).delete()
            except Exception:
                pass
        asyncio.create_task(cleanup())


class DashboardView(discord.ui.View):
    def __init__(self, guild_id: str):
        super().__init__(timeout=None)
        for cls in CLASSES:
            self.add_item(ClasseButton(guild_id, cls))


async def send_build_result(interaction: discord.Interaction, row):
    labels = {
        "talents":      "🎯 Talents",
        "rubis1":       "💎 Rubis 1",
        "rubis2":       "💎 Rubis 2",
        "rubis3":       "💎 Rubis 3",
        "statistiques": "📊 Statistiques",
    }
    embed = discord.Embed(
        title=f"**{row['nom']}**",
        color=discord.Color.orange(),
        timestamp=datetime.fromisoformat(row["created_at"])
    )
    embed.add_field(name="🧙 Classe",   value=row["classe"],      inline=True)
    embed.add_field(name="⚔️ Aspect",   value=row["aspect"],      inline=True)
    embed.add_field(name="🎯 Contenu",  value=row["contenu"],     inline=True)
    embed.add_field(name="👤 Créateur", value=row["author_name"], inline=True)
    if row["patch"]:
        embed.add_field(name="📅 Patch", value=row["patch"], inline=True)
    if row["description"]:
        embed.add_field(name="📝 Description", value=row["description"], inline=False)
    embed.set_footer(text=f"ID : {row['id']} · Créé le")

    images = json.loads(row["images"])
    has_images = images and isinstance(images, dict)

    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
        if has_images:
            img_embed = discord.Embed(title="🖼️ Screenshots", color=discord.Color.blurple())
            for key, label in labels.items():
                if key in images:
                    e = discord.Embed(title=label, color=discord.Color.blurple())
                    e.set_image(url=images[key])
                    await interaction.followup.send(embed=e, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)
        if has_images:
            for key, label in labels.items():
                if key in images:
                    e = discord.Embed(title=label, color=discord.Color.blurple())
                    e.set_image(url=images[key])
                    await interaction.followup.send(embed=e, ephemeral=True)

    async def cleanup():
        await asyncio.sleep(DELETE_GET)
        try:
            await (await interaction.original_response()).delete()
        except Exception:
            pass
    asyncio.create_task(cleanup())

# ─── Autocomplétion ──────────────────────────────────────────────────────────

async def autocomplete_classe(interaction: discord.Interaction, current: str):
    return [app_commands.Choice(name=c, value=c) for c in CLASSES if current.lower() in c.lower()]

async def autocomplete_aspect_for_class(interaction: discord.Interaction, current: str):
    classe = interaction.namespace.classe
    aspects = CLASSE_ASPECTS.get(classe, ASPECTS)
    return [app_commands.Choice(name=a, value=a) for a in aspects if current.lower() in a.lower()]

async def autocomplete_contenu(interaction: discord.Interaction, current: str):
    return [app_commands.Choice(name=c, value=c) for c in CONTENUS if current.lower() in c.lower()]

async def autocomplete_own_builds(interaction: discord.Interaction, current: str):
    """Affiche uniquement les builds de l'utilisateur (ou tous si modérateur)."""
    is_admin = interaction.user.guild_permissions.manage_messages
    con = get_db()
    if is_admin:
        rows = con.execute(
            "SELECT id, nom, author_name FROM builds WHERE guild_id = ? AND (id LIKE ? OR nom LIKE ?) ORDER BY created_at DESC LIMIT 25",
            (str(interaction.guild_id), f"%{current}%", f"%{current}%")
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT id, nom, author_name FROM builds WHERE guild_id = ? AND author_id = ? AND (id LIKE ? OR nom LIKE ?) ORDER BY created_at DESC LIMIT 25",
            (str(interaction.guild_id), str(interaction.user.id), f"%{current}%", f"%{current}%")
        ).fetchall()
    con.close()
    return [app_commands.Choice(name=f"{r['nom']} (par {r['author_name']})", value=r["id"]) for r in rows]

async def autocomplete_build_id(interaction: discord.Interaction, current: str):
    con = get_db()
    rows = con.execute(
        "SELECT id, nom FROM builds WHERE guild_id = ? AND (id LIKE ? OR nom LIKE ?) ORDER BY created_at DESC LIMIT 25",
        (str(interaction.guild_id), f"%{current}%", f"%{current}%")
    ).fetchall()
    con.close()
    return [app_commands.Choice(name=r["nom"], value=r["id"]) for r in rows]

async def autocomplete_build_sans_images(interaction: discord.Interaction, current: str):
    ns = interaction.namespace
    classe  = getattr(ns, "classe",  None)
    aspect  = getattr(ns, "aspect",  None)
    contenu = getattr(ns, "contenu", None)
    query  = "SELECT id, nom FROM builds WHERE guild_id = ? AND (images = '[]' OR images IS NULL)"
    params = [str(interaction.guild_id)]
    if classe:  query += " AND classe = ?";  params.append(classe)
    if aspect:  query += " AND aspect = ?";  params.append(aspect)
    if contenu: query += " AND contenu = ?"; params.append(contenu)
    if current: query += " AND (id LIKE ? OR nom LIKE ?)"; params += [f"%{current}%", f"%{current}%"]
    query += " ORDER BY created_at DESC LIMIT 25"
    con = get_db()
    rows = con.execute(query, params).fetchall()
    con.close()
    return [app_commands.Choice(name=r["nom"], value=r["id"]) for r in rows]

# ─── Helpers ─────────────────────────────────────────────────────────────────

async def auto_delete(interaction: discord.Interaction, delay: int = DELETE_ADD):
    async def cleanup():
        await asyncio.sleep(delay)
        try:
            await (await interaction.original_response()).delete()
        except Exception:
            pass
    asyncio.create_task(cleanup())

# ─── Bot setup ───────────────────────────────────────────────────────────────

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

@bot.event
async def on_ready():
    init_db()
    bot.add_view(DashboardView("persistent"))
    await tree.sync()
    print(f"✅ Bot connecté en tant que {bot.user} — commandes synchronisées.")

# ─── /build-add ──────────────────────────────────────────────────────────────

@tree.command(name="build-add", description="Enregistre un nouveau build.")
@app_commands.describe(
    nom         = "Nom du build",
    classe      = "Classe du personnage",
    aspect      = "Rôle du build",
    contenu     = "Type de contenu (PvE ou PvP)",
    description = "Description optionnelle",
    patch       = "Version du jeu (ex: 13.1)",
)
@app_commands.autocomplete(classe=autocomplete_classe, aspect=autocomplete_aspect_for_class, contenu=autocomplete_contenu)
async def build_add(
    interaction: discord.Interaction,
    nom: str, classe: str, aspect: str, contenu: str,
    description: Optional[str] = None,
    patch: Optional[str] = None,
):
    if classe not in CLASSES:
        await interaction.response.send_message("❌ Classe invalide.", ephemeral=True); return
    if aspect not in CLASSE_ASPECTS.get(classe, []):
        await interaction.response.send_message(f"❌ Aspect invalide pour {classe}.", ephemeral=True); return
    if contenu not in CONTENUS:
        await interaction.response.send_message("❌ Contenu invalide.", ephemeral=True); return

    build_id = make_id(nom, classe, aspect, interaction.user.display_name)
    con = get_db()
    con.execute(
        "INSERT INTO builds (id, guild_id, author_id, author_name, nom, classe, aspect, contenu, description, images, patch, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (build_id, str(interaction.guild_id), str(interaction.user.id), str(interaction.user.display_name),
         nom, classe, aspect, contenu, description, "[]", patch, datetime.utcnow().isoformat())
    )
    con.commit()
    con.close()

    embed = discord.Embed(title="✅ Build enregistré !", color=discord.Color.green(),
                          description="Utilise `/build-images` pour y associer tes screenshots.")
    embed.add_field(name="🏷️ Nom",     value=nom,     inline=False)
    embed.add_field(name="🆔 ID",      value=f"`{build_id}`", inline=False)
    embed.add_field(name="🧙 Classe",  value=classe,  inline=True)
    embed.add_field(name="⚔️ Aspect",  value=aspect,  inline=True)
    embed.add_field(name="🎯 Contenu", value=contenu, inline=True)

    await interaction.response.send_message(embed=embed, ephemeral=True)
    await update_dashboard(bot, str(interaction.guild_id))
    await auto_delete(interaction, DELETE_ADD)

# ─── /build-images ───────────────────────────────────────────────────────────

@tree.command(name="build-images", description="Associe les 5 screenshots à un build sans images.")
@app_commands.describe(
    classe="Filtrer par classe (optionnel)", aspect="Filtrer par aspect (optionnel)",
    contenu="Filtrer par contenu (optionnel)", build_id="Build auquel associer les images",
    talents="Screenshot Talents", rubis1="Screenshot Rubis 1", rubis2="Screenshot Rubis 2",
    rubis3="Screenshot Rubis 3", statistiques="Screenshot Statistiques",
)
@app_commands.autocomplete(classe=autocomplete_classe, aspect=autocomplete_aspect_for_class,
                           contenu=autocomplete_contenu, build_id=autocomplete_build_sans_images)
async def build_images(
    interaction: discord.Interaction,
    build_id: str, talents: discord.Attachment, rubis1: discord.Attachment,
    rubis2: discord.Attachment, rubis3: discord.Attachment, statistiques: discord.Attachment,
    classe: Optional[str] = None, aspect: Optional[str] = None, contenu: Optional[str] = None,
):
    con = get_db()
    row = con.execute("SELECT * FROM builds WHERE id = ? AND guild_id = ?",
                      (build_id, str(interaction.guild_id))).fetchone()
    if not row:
        await interaction.response.send_message("❌ Build introuvable.", ephemeral=True)
        con.close(); return

    urls = {"talents": talents.url, "rubis1": rubis1.url, "rubis2": rubis2.url,
            "rubis3": rubis3.url, "statistiques": statistiques.url}
    con.execute("UPDATE builds SET images = ? WHERE id = ?", (json.dumps(urls), build_id))
    con.commit()
    con.close()

    embed = discord.Embed(title="🖼️ Images associées !", color=discord.Color.green(),
                          description=f"**{row['nom']}** — 5 screenshots enregistrés.")
    embed.add_field(name="✅ Images", value="Talents · Rubis 1 · Rubis 2 · Rubis 3 · Statistiques", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)
    await auto_delete(interaction, DELETE_ADD)

# ─── /build-list ─────────────────────────────────────────────────────────────

@tree.command(name="build-list", description="Liste tous les builds disponibles par classe.")
async def build_list(interaction: discord.Interaction):
    con = get_db()
    rows = con.execute(
        "SELECT classe, contenu, COUNT(*) as nb FROM builds WHERE guild_id = ? GROUP BY classe, contenu ORDER BY classe",
        (str(interaction.guild_id),)
    ).fetchall()
    con.close()

    if not rows:
        await interaction.response.send_message("📭 Aucun build enregistré.", ephemeral=True); return

    by_class: dict = {}
    for r in rows:
        by_class.setdefault(r["classe"], {})[r["contenu"]] = r["nb"]

    embed = discord.Embed(title="📚 Builds Allods Online", color=discord.Color.blurple())
    for classe in CLASSES:
        if classe in by_class:
            parts = [f"`{c}` : {by_class[classe].get(c, 0)}" for c in CONTENUS if by_class[classe].get(c)]
            embed.add_field(name=f"{CLASSE_EMOJIS.get(classe, '🧙')} {classe}", value=" · ".join(parts), inline=False)
    embed.set_footer(text=f"Total : {sum(r['nb'] for r in rows)} builds")
    await interaction.response.send_message(embed=embed, ephemeral=True)
    await auto_delete(interaction, DELETE_ADD)

# ─── /build-delete ───────────────────────────────────────────────────────────

@tree.command(name="build-delete", description="Supprime un de tes builds.")
@app_commands.describe(build_id="ID du build à supprimer")
@app_commands.autocomplete(build_id=autocomplete_own_builds)
async def build_delete(interaction: discord.Interaction, build_id: str):
    con = get_db()
    row = con.execute("SELECT * FROM builds WHERE id = ? AND guild_id = ?",
                      (build_id, str(interaction.guild_id))).fetchone()
    if not row:
        await interaction.response.send_message("❌ Build introuvable.", ephemeral=True)
        con.close(); return

    is_admin = interaction.user.guild_permissions.manage_messages
    if str(row["author_id"]) != str(interaction.user.id) and not is_admin:
        await interaction.response.send_message("🚫 Tu ne peux supprimer que tes propres builds.", ephemeral=True)
        con.close(); return

    con.execute("DELETE FROM builds WHERE id = ?", (build_id,))
    con.commit()
    con.close()
    await interaction.response.send_message(f"🗑️ Build **{row['nom']}** supprimé.", ephemeral=True)
    await update_dashboard(bot, str(interaction.guild_id))
    await auto_delete(interaction, DELETE_ADD)

# ─── /dashboard-setup ────────────────────────────────────────────────────────

@tree.command(name="dashboard-setup", description="Crée l'interface permanente des builds dans ce salon.")
async def dashboard_setup(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("🚫 Réservé aux modérateurs.", ephemeral=True); return

    buf = generate_dashboard_image(str(interaction.guild_id))
    view = DashboardView(str(interaction.guild_id))
    msg = await interaction.channel.send(file=discord.File(buf, filename="dashboard.png"), view=view)

    con = get_db()
    con.execute("INSERT OR REPLACE INTO dashboard (guild_id, channel_id, message_id) VALUES (?,?,?)",
                (str(interaction.guild_id), str(interaction.channel_id), str(msg.id)))
    con.commit()
    con.close()

    await interaction.response.send_message("✅ Dashboard créé avec les boutons de navigation !", ephemeral=True)

# ─── Lancement ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    bot.run(TOKEN)

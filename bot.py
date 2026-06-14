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

TOKEN       = os.getenv("DISCORD_TOKEN", "YOUR_TOKEN_HERE")
DB_PATH     = "builds.db"
DELETE_DELAY = 180  # 3 minutes

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
            obsolete    INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS votes (
            build_id    TEXT    NOT NULL,
            user_id     TEXT    NOT NULL,
            PRIMARY KEY (build_id, user_id),
            FOREIGN KEY (build_id) REFERENCES builds(id) ON DELETE CASCADE
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
    # Nettoie le nom pour l'ID (espaces → tirets, caractères spéciaux retirés)
    nom_clean = "".join(c if c.isalnum() or c in "-_" else "-" for c in nom).strip("-")
    base = f"{nom_clean}_{classe}_{aspect}_{author_name}_{date}"
    con = get_db()
    existing = con.execute("SELECT id FROM builds WHERE id LIKE ?", (f"{base}%",)).fetchall()
    con.close()
    return base if not existing else f"{base}_{len(existing)+1}"

# ─── Dashboard ───────────────────────────────────────────────────────────────

def generate_dashboard_image(guild_id: str) -> BytesIO:
    con = get_db()
    rows = con.execute(
        "SELECT classe, aspect, contenu, COUNT(*) as nb FROM builds WHERE guild_id = ? AND obsolete = 0 GROUP BY classe, aspect, contenu",
        (guild_id,)
    ).fetchall()
    con.close()

    data: dict = {}
    total = 0
    for r in rows:
        data.setdefault(r["classe"], {}).setdefault(r["aspect"], {})[r["contenu"]] = r["nb"]
        total += r["nb"]

    # ── Dimensions ──────────────────────────────────────────────────────────
    COLS = 3
    CW, CH_BASE = 320, 0
    PAD = 22
    CARD_PAD = 18

    # Calcule la hauteur de chaque carte selon le nombre d'aspects
    def card_height(classe):
        return 50 + len(CLASSE_ASPECTS[classe]) * 38 + 14

    rows_cards = [CLASSES[i:i+COLS] for i in range(0, len(CLASSES), COLS)]
    row_heights = [max(card_height(c) for c in row) for row in rows_cards]

    W = COLS * (CW + CARD_PAD) + PAD * 2 - CARD_PAD
    H = PAD + 50 + PAD + sum(row_heights) + len(row_heights) * CARD_PAD + PAD

    # ── Couleurs ─────────────────────────────────────────────────────────────
    BG       = (30, 31, 34)
    BG2      = (38, 39, 43)
    BG3      = (52, 54, 60)
    WHITE    = (230, 232, 235)
    GRAY     = (120, 125, 135)
    GREEN_BG = (25, 55, 35)
    GREEN    = (70, 190, 110)
    BLUE_BG  = (18, 40, 70)
    BLUE     = (70, 140, 210)
    BORDER   = (58, 60, 68)

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    try:
        font       = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
        font_bold  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
        font_sm    = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
        font_xs    = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15)
    except:
        font = font_bold = font_sm = font_title = font_xs = ImageFont.load_default()

    # ── Header ───────────────────────────────────────────────────────────────
    d.rounded_rectangle([0, 0, W, 64], radius=0, fill=BG3)
    d.text((PAD, 12), "Bibliothèque de Builds — Allods Online", font=font_title, fill=WHITE)
    now = datetime.utcnow().strftime("%d/%m/%Y %H:%M")
    d.text((PAD, 38), f"{total} builds actifs · Mis à jour le {now}", font=font_sm, fill=GRAY)
    d.line([(0, 64), (W, 64)], fill=BORDER, width=1)

    # ── Cartes ───────────────────────────────────────────────────────────────
    y_offset = 64 + PAD
    for row_idx, row in enumerate(rows_cards):
        row_h = row_heights[row_idx]
        for col_idx, classe in enumerate(row):
            cx = PAD + col_idx * (CW + CARD_PAD)
            cy = y_offset
            ch = card_height(classe)

            # Fond carte
            d.rounded_rectangle([cx, cy, cx+CW, cy+ch], radius=10, fill=BG2, outline=BORDER, width=1)
            # Header carte
            d.rounded_rectangle([cx, cy, cx+CW, cy+42], radius=10, fill=BG3)
            d.rectangle([cx, cy+28, cx+CW, cy+42], fill=BG3)
            d.line([(cx+1, cy+42), (cx+CW-1, cy+42)], fill=BORDER, width=1)
            d.text((cx+14, cy+12), classe, font=font_bold, fill=WHITE)

            # Aspects
            for j, aspect in enumerate(CLASSE_ASPECTS[classe]):
                ay = cy + 52 + j * 38
                pve = data.get(classe, {}).get(aspect, {}).get("PvE", 0)
                pvp = data.get(classe, {}).get(aspect, {}).get("PvP", 0)

                d.text((cx+14, ay+5), aspect, font=font_sm, fill=GRAY)

                # Badge PvE
                pve_x = cx + 120
                d.rounded_rectangle([pve_x, ay+2, pve_x+80, ay+26], radius=6, fill=GREEN_BG if pve > 0 else BG3)
                d.text((pve_x+8, ay+6), f"PvE: {pve}", font=font_xs, fill=GREEN if pve > 0 else GRAY)

                # Badge PvP
                pvp_x = cx + 210
                d.rounded_rectangle([pvp_x, ay+2, pvp_x+80, ay+26], radius=6, fill=BLUE_BG if pvp > 0 else BG3)
                d.text((pvp_x+8, ay+6), f"PvP: {pvp}", font=font_xs, fill=BLUE if pvp > 0 else GRAY)

        y_offset += row_h + CARD_PAD

    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf

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
        message = await channel.fetch_message(int(row["message_id"]))
        buf = generate_dashboard_image(guild_id)
        await message.edit(content="", attachments=[discord.File(buf, filename="dashboard.png")], embed=None)
    except Exception as e:
        print(f"Dashboard update error: {e}")

# ─── Autocomplétion ──────────────────────────────────────────────────────────

async def autocomplete_classe(interaction: discord.Interaction, current: str):
    return [app_commands.Choice(name=c, value=c) for c in CLASSES if current.lower() in c.lower()]

async def autocomplete_aspect_for_class(interaction: discord.Interaction, current: str):
    classe = interaction.namespace.classe
    aspects = CLASSE_ASPECTS.get(classe, ASPECTS)
    return [app_commands.Choice(name=a, value=a) for a in aspects if current.lower() in a.lower()]

async def autocomplete_contenu(interaction: discord.Interaction, current: str):
    return [app_commands.Choice(name=c, value=c) for c in CONTENUS if current.lower() in c.lower()]

async def autocomplete_build_id(interaction: discord.Interaction, current: str):
    con = get_db()
    rows = con.execute(
        "SELECT id, nom FROM builds WHERE guild_id = ? AND (id LIKE ? OR nom LIKE ?) ORDER BY created_at DESC LIMIT 25",
        (str(interaction.guild_id), f"%{current}%", f"%{current}%")
    ).fetchall()
    con.close()
    return [app_commands.Choice(name=f"{r['nom']} ({r['id']})", value=r["id"]) for r in rows]

async def autocomplete_build_sans_images(interaction: discord.Interaction, current: str):
    """Autocomplétion filtrée : builds sans images, avec filtres optionnels classe/aspect/contenu."""
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

def build_embed(row, vote_count: int = 0) -> discord.Embed:
    color = discord.Color.orange() if not row["obsolete"] else discord.Color.dark_gray()
    title = f"{'⚠️ [OBSOLÈTE] ' if row['obsolete'] else ''}**{row['nom']}**"
    embed = discord.Embed(title=title, color=color, timestamp=datetime.fromisoformat(row["created_at"]))
    embed.add_field(name="🧙 Classe",  value=row["classe"],       inline=True)
    embed.add_field(name="⚔️ Aspect",  value=row["aspect"],       inline=True)
    embed.add_field(name="🎯 Contenu", value=row["contenu"],      inline=True)
    embed.add_field(name="👤 Créateur", value=row["author_name"], inline=True)
    embed.add_field(name="⭐ Votes",   value=str(vote_count),     inline=True)
    if row["patch"]:
        embed.add_field(name="📅 Patch", value=row["patch"], inline=True)
    if row["description"]:
        embed.add_field(name="📝 Description", value=row["description"], inline=False)
    embed.set_footer(text=f"ID : {row['id']} · Créé le")
    return embed

async def auto_delete(interaction: discord.Interaction):
    async def cleanup():
        await asyncio.sleep(DELETE_DELAY)
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
    await tree.sync()
    print(f"✅ Bot connecté en tant que {bot.user} — commandes synchronisées.")

# ─── /build-add ──────────────────────────────────────────────────────────────

@tree.command(name="build-add", description="Enregistre un nouveau build.")
@app_commands.describe(
    nom         = "Nom du build",
    classe      = "Classe du personnage",
    aspect      = "Rôle du build (filtré selon la classe)",
    contenu     = "Type de contenu (PvE ou PvP)",
    description = "Description optionnelle du build",
    patch       = "Version du jeu (ex: 13.1)",
)
@app_commands.autocomplete(classe=autocomplete_classe, aspect=autocomplete_aspect_for_class, contenu=autocomplete_contenu)
async def build_add(
    interaction: discord.Interaction,
    nom: str,
    classe: str,
    aspect: str,
    contenu: str,
    description: Optional[str] = None,
    patch: Optional[str] = None,
):
    if classe not in CLASSES:
        await interaction.response.send_message("❌ Classe invalide.", ephemeral=True)
        return
    if aspect not in CLASSE_ASPECTS.get(classe, []):
        await interaction.response.send_message(
            f"❌ Aspect invalide pour {classe}. Disponibles : {', '.join(CLASSE_ASPECTS[classe])}", ephemeral=True)
        return
    if contenu not in CONTENUS:
        await interaction.response.send_message("❌ Contenu invalide.", ephemeral=True)
        return

    build_id = make_id(nom, classe, aspect, interaction.user.display_name)
    con = get_db()
    con.execute(
        """INSERT INTO builds (id, guild_id, author_id, author_name, nom, classe, aspect, contenu, description, images, patch, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (build_id, str(interaction.guild_id), str(interaction.user.id),
         str(interaction.user.display_name), nom, classe, aspect, contenu,
         description, "[]", patch, datetime.utcnow().isoformat())
    )
    con.commit()
    con.close()

    embed = discord.Embed(title="✅ Build enregistré !", color=discord.Color.green(),
                          description="Utilise `/build-images` pour y associer tes screenshots.")
    embed.add_field(name="🏷️ Nom",    value=nom,     inline=False)
    embed.add_field(name="🆔 ID",     value=f"`{build_id}`", inline=False)
    embed.add_field(name="🧙 Classe", value=classe,  inline=True)
    embed.add_field(name="⚔️ Aspect", value=aspect,  inline=True)
    embed.add_field(name="🎯 Contenu",value=contenu, inline=True)

    await interaction.response.send_message(embed=embed, ephemeral=True)
    await update_dashboard(bot, str(interaction.guild_id))
    await auto_delete(interaction)

# ─── /build-images ───────────────────────────────────────────────────────────

@tree.command(name="build-images", description="Associe les 5 screenshots obligatoires à un build sans images.")
@app_commands.describe(
    classe       = "Filtrer les builds sans images par classe (optionnel)",
    aspect       = "Filtrer par aspect (optionnel)",
    contenu      = "Filtrer par contenu (optionnel)",
    build_id     = "Build auquel associer les images",
    talents      = "Screenshot de la page Talents",
    rubis1       = "Screenshot Rubis 1",
    rubis2       = "Screenshot Rubis 2",
    rubis3       = "Screenshot Rubis 3",
    statistiques = "Screenshot des Statistiques",
)
@app_commands.autocomplete(
    classe=autocomplete_classe,
    aspect=autocomplete_aspect_for_class,
    contenu=autocomplete_contenu,
    build_id=autocomplete_build_sans_images
)
async def build_images(
    interaction: discord.Interaction,
    build_id:     str,
    talents:      discord.Attachment,
    rubis1:       discord.Attachment,
    rubis2:       discord.Attachment,
    rubis3:       discord.Attachment,
    statistiques: discord.Attachment,
    classe:  Optional[str] = None,
    aspect:  Optional[str] = None,
    contenu: Optional[str] = None,
):
    con = get_db()
    row = con.execute("SELECT * FROM builds WHERE id = ? AND guild_id = ?",
                      (build_id, str(interaction.guild_id))).fetchone()
    if not row:
        await interaction.response.send_message("❌ Build introuvable.", ephemeral=True)
        con.close()
        return

    urls = {
        "talents":      talents.url,
        "rubis1":       rubis1.url,
        "rubis2":       rubis2.url,
        "rubis3":       rubis3.url,
        "statistiques": statistiques.url,
    }

    con.execute("UPDATE builds SET images = ? WHERE id = ?", (json.dumps(urls), build_id))
    con.commit()
    con.close()

    embed = discord.Embed(title="🖼️ Images associées !",
                          description=f"**{row['nom']}** — 5 screenshots enregistrés.",
                          color=discord.Color.green())
    embed.add_field(name="🆔 ID", value=f"`{build_id}`", inline=False)
    embed.add_field(name="✅ Images", value="Talents · Rubis 1 · Rubis 2 · Rubis 3 · Statistiques", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)
    await auto_delete(interaction)

# ─── /build-get ──────────────────────────────────────────────────────────────

@tree.command(name="build-get", description="Recherche des builds par classe, aspect et/ou contenu.")
@app_commands.describe(classe="Classe du personnage", aspect="Rôle du build", contenu="Type de contenu (PvE ou PvP)")
@app_commands.autocomplete(classe=autocomplete_classe, aspect=autocomplete_aspect_for_class, contenu=autocomplete_contenu)
async def build_get(
    interaction: discord.Interaction,
    classe:  str,
    aspect:  str,
    contenu: str,
):
    query = """SELECT b.*, (SELECT COUNT(*) FROM votes v WHERE v.build_id = b.id) as votes
               FROM builds b WHERE b.guild_id = ?"""
    params = [str(interaction.guild_id)]
    query += " AND b.classe = ?";  params.append(classe)
    query += " AND b.aspect = ?";  params.append(aspect)
    query += " AND b.contenu = ?"; params.append(contenu)

    con = get_db()
    rows = con.execute(query, params).fetchall()
    con.close()

    if not rows:
        await interaction.response.send_message("😕 Aucun build trouvé.", ephemeral=True)
        return

    await interaction.response.send_message(
        f"🔍 **{len(rows)} build(s) trouvé(s)** :",
        embeds=[build_embed(r, r["votes"]) for r in rows],
        ephemeral=True
    )

    # Envoie toutes les images d'un build en un seul message groupé (max 10 embeds)
    labels = {
        "talents":      "🎯 Talents",
        "rubis1":       "💎 Rubis 1",
        "rubis2":       "💎 Rubis 2",
        "rubis3":       "💎 Rubis 3",
        "statistiques": "📊 Statistiques",
    }

    for r in rows:
        images = json.loads(r["images"])
        if images and isinstance(images, dict):
            embeds = []
            for key, label in labels.items():
                if key in images:
                    e = discord.Embed(title=label, color=discord.Color.blurple())
                    e.set_image(url=images[key])
                    embeds.append(e)
            if embeds:
                await interaction.followup.send(
                    f"🖼️ **{r['nom']}**",
                    embeds=embeds,
                    ephemeral=True
                )

    await auto_delete(interaction)

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
        await interaction.response.send_message("📭 Aucun build enregistré.", ephemeral=True)
        return

    by_class: dict = {}
    for r in rows:
        by_class.setdefault(r["classe"], {})[r["contenu"]] = r["nb"]

    embed = discord.Embed(title="📚 Builds Allods Online", color=discord.Color.blurple())
    for classe in CLASSES:
        if classe in by_class:
            parts = [f"`{c}` : {by_class[classe].get(c, 0)}" for c in CONTENUS if by_class[classe].get(c)]
            embed.add_field(name=f"🧙 {classe}", value=" · ".join(parts), inline=False)
    embed.set_footer(text=f"Total : {sum(r['nb'] for r in rows)} builds")

    await interaction.response.send_message(embed=embed, ephemeral=True)
    await auto_delete(interaction)

# ─── /build-top ──────────────────────────────────────────────────────────────

@tree.command(name="build-top", description="Affiche les builds les mieux votés.")
async def build_top(interaction: discord.Interaction):
    con = get_db()
    rows = con.execute(
        """SELECT b.*, COUNT(v.user_id) as votes FROM builds b
           LEFT JOIN votes v ON v.build_id = b.id WHERE b.guild_id = ?
           GROUP BY b.id ORDER BY votes DESC, b.created_at DESC LIMIT 5""",
        (str(interaction.guild_id),)
    ).fetchall()
    con.close()

    if not rows:
        await interaction.response.send_message("📭 Aucun build.", ephemeral=True)
        return

    await interaction.response.send_message("🏆 **Top builds :**",
        embeds=[build_embed(r, r["votes"]) for r in rows], ephemeral=True)
    await auto_delete(interaction)

# ─── /build-vote ─────────────────────────────────────────────────────────────

@tree.command(name="build-vote", description="Vote pour un build (toggle).")
@app_commands.describe(build_id="ID du build")
@app_commands.autocomplete(build_id=autocomplete_build_id)
async def build_vote(interaction: discord.Interaction, build_id: str):
    con = get_db()
    row = con.execute("SELECT * FROM builds WHERE id = ? AND guild_id = ?",
                      (build_id, str(interaction.guild_id))).fetchone()
    if not row:
        await interaction.response.send_message("❌ Build introuvable.", ephemeral=True)
        con.close()
        return
    existing = con.execute("SELECT 1 FROM votes WHERE build_id = ? AND user_id = ?",
                           (build_id, str(interaction.user.id))).fetchone()
    if existing:
        con.execute("DELETE FROM votes WHERE build_id = ? AND user_id = ?", (build_id, str(interaction.user.id)))
        msg = f"⭐ Vote retiré du build **{row['nom']}**."
    else:
        con.execute("INSERT INTO votes (build_id, user_id) VALUES (?,?)", (build_id, str(interaction.user.id)))
        msg = f"⭐ Vote ajouté au build **{row['nom']}** !"
    con.commit()
    con.close()
    await interaction.response.send_message(msg, ephemeral=True)
    await auto_delete(interaction)

# ─── /build-delete ───────────────────────────────────────────────────────────

@tree.command(name="build-delete", description="Supprime un build.")
@app_commands.describe(build_id="ID du build à supprimer")
@app_commands.autocomplete(build_id=autocomplete_build_id)
async def build_delete(interaction: discord.Interaction, build_id: str):
    con = get_db()
    row = con.execute("SELECT * FROM builds WHERE id = ? AND guild_id = ?",
                      (build_id, str(interaction.guild_id))).fetchone()
    if not row:
        await interaction.response.send_message("❌ Build introuvable.", ephemeral=True)
        con.close()
        return
    is_admin = interaction.user.guild_permissions.manage_messages
    if str(row["author_id"]) != str(interaction.user.id) and not is_admin:
        await interaction.response.send_message("🚫 Tu ne peux supprimer que tes propres builds.", ephemeral=True)
        con.close()
        return
    con.execute("DELETE FROM builds WHERE id = ?", (build_id,))
    con.commit()
    con.close()
    await interaction.response.send_message(f"🗑️ Build **{row['nom']}** supprimé.", ephemeral=True)
    await update_dashboard(bot, str(interaction.guild_id))
    await auto_delete(interaction)

# ─── /build-obsolete ─────────────────────────────────────────────────────────

@tree.command(name="build-obsolete", description="Marque/démarque un build comme obsolète.")
@app_commands.describe(build_id="ID du build")
@app_commands.autocomplete(build_id=autocomplete_build_id)
async def build_obsolete(interaction: discord.Interaction, build_id: str):
    con = get_db()
    row = con.execute("SELECT * FROM builds WHERE id = ? AND guild_id = ?",
                      (build_id, str(interaction.guild_id))).fetchone()
    if not row:
        await interaction.response.send_message("❌ Build introuvable.", ephemeral=True)
        con.close()
        return
    is_admin = interaction.user.guild_permissions.manage_messages
    if str(row["author_id"]) != str(interaction.user.id) and not is_admin:
        await interaction.response.send_message("🚫 Action réservée à l'auteur ou un modérateur.", ephemeral=True)
        con.close()
        return
    new_state = 0 if row["obsolete"] else 1
    con.execute("UPDATE builds SET obsolete = ? WHERE id = ?", (new_state, build_id))
    con.commit()
    con.close()
    status = "⚠️ marqué comme obsolète" if new_state else "✅ marqué comme actif"
    await interaction.response.send_message(f"Build **{row['nom']}** {status}.", ephemeral=True)
    await update_dashboard(bot, str(interaction.guild_id))
    await auto_delete(interaction)

# ─── /build-random ───────────────────────────────────────────────────────────

@tree.command(name="build-random", description="Affiche un build aléatoire.")
async def build_random(interaction: discord.Interaction):
    con = get_db()
    row = con.execute(
        """SELECT b.*, COUNT(v.user_id) as votes FROM builds b
           LEFT JOIN votes v ON v.build_id = b.id
           WHERE b.guild_id = ? AND b.obsolete = 0
           GROUP BY b.id ORDER BY RANDOM() LIMIT 1""",
        (str(interaction.guild_id),)
    ).fetchone()
    con.close()
    if not row:
        await interaction.response.send_message("📭 Aucun build disponible.", ephemeral=True)
        return
    await interaction.response.send_message("🎲 **Build aléatoire :**",
        embed=build_embed(row, row["votes"]), ephemeral=True)
    images = json.loads(row["images"])
    for url in images:
        await interaction.followup.send(url, ephemeral=True)
    await auto_delete(interaction)

# ─── /dashboard-setup ────────────────────────────────────────────────────────

@tree.command(name="dashboard-setup", description="Crée l'interface permanente des builds dans ce salon.")
async def dashboard_setup(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("🚫 Réservé aux modérateurs.", ephemeral=True)
        return

    buf = generate_dashboard_image(str(interaction.guild_id))
    # Message public et permanent
    msg = await interaction.channel.send(file=discord.File(buf, filename="dashboard.png"))

    con = get_db()
    con.execute(
        "INSERT OR REPLACE INTO dashboard (guild_id, channel_id, message_id) VALUES (?,?,?)",
        (str(interaction.guild_id), str(interaction.channel_id), str(msg.id))
    )
    con.commit()
    con.close()

    await interaction.response.send_message("✅ Dashboard créé !", ephemeral=True)

# ─── Lancement ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    bot.run(TOKEN)

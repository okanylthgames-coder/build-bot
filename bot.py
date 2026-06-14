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
ASPECTS  = ["Assault", "Heal", "Tank", "Support"]

CLASSE_ASPECTS = {
    "Cleric":  ["Assault", "Heal", "Support"],
    "War":     ["Assault", "Tank"],
    "Pally":   ["Assault", "Tank"],
    "Warden":  ["Assault", "Heal", "Support"],
    "Summy":   ["Assault", "Heal", "Support"],
    "Demon":   ["Assault", "Tank"],
    "Engi":    ["Assault", "Support"],
    "Bard":    ["Assault", "Support"],
    "Mage":    ["Assault", "Support"],
    "Scout":   ["Assault", "Tank"],
    "Psi":     ["Assault", "Support"],
}

CLASSES = list(CLASSE_ASPECTS.keys())

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

def make_id(classe, aspect, contenu, author_name):
    date = datetime.utcnow().strftime("%Y-%m-%d")
    base = f"{classe}_{aspect}_{contenu}_{author_name}_{date}"
    con = get_db()
    existing = con.execute("SELECT id FROM builds WHERE id LIKE ?", (f"{base}%",)).fetchall()
    con.close()
    return base if not existing else f"{base}_{len(existing)+1}"

# ─── Dashboard ───────────────────────────────────────────────────────────────

def build_dashboard_embed(guild_id: str) -> discord.Embed:
    con = get_db()
    rows = con.execute(
        "SELECT classe, aspect, contenu, COUNT(*) as nb FROM builds WHERE guild_id = ? AND obsolete = 0 GROUP BY classe, aspect, contenu",
        (guild_id,)
    ).fetchall()
    con.close()

    data: dict = {}
    for r in rows:
        data.setdefault(r["classe"], {}).setdefault(r["aspect"], {})[r["contenu"]] = r["nb"]

    embed = discord.Embed(
        title="📚 Bibliothèque de Builds — Allods Online",
        description="Nombre de builds disponibles par classe, aspect et contenu.",
        color=discord.Color.blurple(),
        timestamp=datetime.utcnow()
    )

    total = 0
    for classe in CLASSES:
        lines = []
        for aspect in CLASSE_ASPECTS[classe]:
            pve = data.get(classe, {}).get(aspect, {}).get("PvE", 0)
            pvp = data.get(classe, {}).get(aspect, {}).get("PvP", 0)
            total += pve + pvp
            if pve or pvp:
                parts = []
                if pve: parts.append(f"`PvE:{pve}`")
                if pvp: parts.append(f"`PvP:{pvp}`")
                lines.append(f"**{aspect}** — " + " ".join(parts))
            else:
                lines.append(f"**{aspect}** — *aucun build*")
        embed.add_field(name=f"🧙 {classe}", value="\n".join(lines), inline=True)

    embed.set_footer(text=f"Total : {total} builds actifs · Mis à jour")
    return embed

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
        await message.edit(embed=build_dashboard_embed(guild_id))
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
    return [app_commands.Choice(name=f"{r['nom']} ({r['id']})", value=r["id"]) for r in rows]

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

    build_id = make_id(classe, aspect, contenu, interaction.user.display_name)
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

@tree.command(name="build-images", description="Associe des screenshots à un build sans images.")
@app_commands.describe(
    classe   = "Filtrer les builds sans images par classe (optionnel)",
    aspect   = "Filtrer par aspect (optionnel)",
    contenu  = "Filtrer par contenu (optionnel)",
    build_id = "Build auquel associer les images",
    image1   = "Screenshot 1",
    image2   = "Screenshot 2 (optionnel)",
    image3   = "Screenshot 3 (optionnel)",
    image4   = "Screenshot 4 (optionnel)",
    image5   = "Screenshot 5 (optionnel)",
)
@app_commands.autocomplete(
    classe=autocomplete_classe,
    aspect=autocomplete_aspect_for_class,
    contenu=autocomplete_contenu,
    build_id=autocomplete_build_sans_images
)
async def build_images(
    interaction: discord.Interaction,
    build_id: str,
    image1: discord.Attachment,
    classe:  Optional[str] = None,
    aspect:  Optional[str] = None,
    contenu: Optional[str] = None,
    image2: Optional[discord.Attachment] = None,
    image3: Optional[discord.Attachment] = None,
    image4: Optional[discord.Attachment] = None,
    image5: Optional[discord.Attachment] = None,
):
    con = get_db()
    row = con.execute("SELECT * FROM builds WHERE id = ? AND guild_id = ?",
                      (build_id, str(interaction.guild_id))).fetchone()
    if not row:
        await interaction.response.send_message("❌ Build introuvable.", ephemeral=True)
        con.close()
        return

    # Collecte les URLs des pièces jointes
    attachments = [a for a in [image1, image2, image3, image4, image5] if a is not None]
    urls = [a.url for a in attachments]

    con.execute("UPDATE builds SET images = ? WHERE id = ?", (json.dumps(urls), build_id))
    con.commit()
    con.close()

    embed = discord.Embed(title="🖼️ Images associées !",
                          description=f"**{row['nom']}** — {len(urls)} image(s) enregistrée(s).",
                          color=discord.Color.green())
    embed.add_field(name="🆔 ID", value=f"`{build_id}`", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)
    await auto_delete(interaction)

# ─── /build-get ──────────────────────────────────────────────────────────────

@tree.command(name="build-get", description="Recherche des builds par classe, aspect et/ou contenu.")
@app_commands.describe(classe="Filtrer par classe", aspect="Filtrer par aspect", contenu="Filtrer par contenu")
@app_commands.autocomplete(classe=autocomplete_classe, aspect=autocomplete_aspect_for_class, contenu=autocomplete_contenu)
async def build_get(
    interaction: discord.Interaction,
    classe:  Optional[str] = None,
    aspect:  Optional[str] = None,
    contenu: Optional[str] = None,
):
    if not classe and not aspect and not contenu:
        await interaction.response.send_message("❌ Précise au moins un critère.", ephemeral=True)
        return

    query = """SELECT b.*, (SELECT COUNT(*) FROM votes v WHERE v.build_id = b.id) as votes
               FROM builds b WHERE b.guild_id = ?"""
    params = [str(interaction.guild_id)]
    if classe:  query += " AND b.classe = ?";  params.append(classe)
    if aspect:  query += " AND b.aspect = ?";  params.append(aspect)
    if contenu: query += " AND b.contenu = ?"; params.append(contenu)
    query += " ORDER BY votes DESC, b.created_at DESC LIMIT 5"

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

    # Envoie les images en éphémère
    for r in rows:
        images = json.loads(r["images"])
        if images:
            await interaction.followup.send(
                f"🖼️ Images — **{r['nom']}** :",
                ephemeral=True
            )
            for url in images:
                await interaction.followup.send(url, ephemeral=True)

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

    embed = build_dashboard_embed(str(interaction.guild_id))
    # Message public et permanent
    msg = await interaction.channel.send(embed=embed)

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

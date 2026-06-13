"""
Discord Build Bot — Allods Online
Enregistre et retrouve des builds par classe et contenu.
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

TOKEN = os.getenv("DISCORD_TOKEN", "YOUR_TOKEN_HERE")
DB_PATH = "builds.db"
DELETE_DELAY = 300  # 5 minutes en secondes

CLASSES  = ["Psi", "Cleric", "Warden", "Summy", "Demon", "Bard", "Engi", "War", "Pally", "Scout", "Mage"]
ASPECTS  = ["Assault", "Heal", "Tank", "Support"]
CONTENUS = ["PvE", "PvP"]

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
            classe      TEXT    NOT NULL,
            aspect      TEXT    NOT NULL,
            contenu     TEXT    NOT NULL,
            description TEXT,
            liens       TEXT    NOT NULL DEFAULT '[]',
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
    """)
    con.commit()
    con.close()


def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def make_id(classe: str, aspect: str, contenu: str, author_name: str) -> str:
    """Génère un ID lisible unique."""
    date = datetime.utcnow().strftime("%Y-%m-%d")
    base = f"{classe}_{aspect}_{contenu}_{author_name}_{date}"
    # Si l'ID existe déjà, ajoute un suffixe numérique
    con = get_db()
    existing = con.execute("SELECT id FROM builds WHERE id LIKE ?", (f"{base}%",)).fetchall()
    con.close()
    if not existing:
        return base
    return f"{base}_{len(existing) + 1}"

# ─── Autocomplétion ──────────────────────────────────────────────────────────

async def autocomplete_classe(interaction: discord.Interaction, current: str):
    return [app_commands.Choice(name=c, value=c) for c in CLASSES if current.lower() in c.lower()]

async def autocomplete_aspect(interaction: discord.Interaction, current: str):
    return [app_commands.Choice(name=a, value=a) for a in ASPECTS if current.lower() in a.lower()]

async def autocomplete_contenu(interaction: discord.Interaction, current: str):
    return [app_commands.Choice(name=c, value=c) for c in CONTENUS if current.lower() in c.lower()]

async def autocomplete_build_id(interaction: discord.Interaction, current: str):
    con = get_db()
    rows = con.execute(
        "SELECT id FROM builds WHERE guild_id = ? AND id LIKE ? ORDER BY created_at DESC LIMIT 25",
        (str(interaction.guild_id), f"%{current}%")
    ).fetchall()
    con.close()
    return [app_commands.Choice(name=r["id"], value=r["id"]) for r in rows]

# ─── Helpers ─────────────────────────────────────────────────────────────────

def build_embed(row, vote_count: int = 0) -> discord.Embed:
    color = discord.Color.orange() if not row["obsolete"] else discord.Color.dark_gray()
    title = f"{'⚠️ [OBSOLÈTE] ' if row['obsolete'] else ''}{row['contenu']} · {row['classe']} · {row['aspect']}"
    embed = discord.Embed(title=title, description=row["description"] or "*Aucune description.*", color=color,
                          timestamp=datetime.fromisoformat(row["created_at"]))
    embed.add_field(name="🧙 Classe",  value=row["classe"],  inline=True)
    embed.add_field(name="⚔️ Aspect",  value=row["aspect"],  inline=True)
    embed.add_field(name="🎯 Contenu", value=row["contenu"], inline=True)
    if row["patch"]:
        embed.add_field(name="📅 Patch", value=row["patch"], inline=True)
    embed.add_field(name="⭐ Votes", value=str(vote_count), inline=True)
    embed.set_footer(text=f"ID : {row['id']} · Ajouté par {row['author_name']}")
    return embed


async def send_and_delete(interaction: discord.Interaction, embeds: list, images: list, ephemeral_info: bool = False):
    """Envoie l'embed + images, puis supprime tout après DELETE_DELAY secondes."""
    # L'embed principal est éphémère si demandé, sinon public
    await interaction.response.send_message(embeds=embeds, ephemeral=ephemeral_info)
    sent_messages = []

    # Envoie les images en messages séparés dans le même salon
    if images and not ephemeral_info:
        for url in images:
            msg = await interaction.channel.send(url)
            sent_messages.append(msg)

    # Suppression après 5 minutes
    if not ephemeral_info:
        await asyncio.sleep(DELETE_DELAY)
        try:
            original = await interaction.original_response()
            await original.delete()
        except Exception:
            pass
        for msg in sent_messages:
            try:
                await msg.delete()
            except Exception:
                pass

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
    classe      = "Classe du personnage",
    aspect      = "Rôle du build",
    contenu     = "Type de contenu visé (PvE ou PvP)",
    description = "Description et explications du build",
    liens       = "Liens ou URLs d'images séparés par des espaces",
    patch       = "Version du jeu (ex: 13.1)",
)
@app_commands.autocomplete(classe=autocomplete_classe, aspect=autocomplete_aspect, contenu=autocomplete_contenu)
async def build_add(
    interaction: discord.Interaction,
    classe: str, aspect: str, contenu: str,
    description: Optional[str] = None,
    liens: Optional[str] = None,
    patch: Optional[str] = None,
):
    if classe not in CLASSES:
        await interaction.response.send_message(f"❌ Classe invalide.", ephemeral=True)
        return
    if aspect not in ASPECTS:
        await interaction.response.send_message(f"❌ Aspect invalide.", ephemeral=True)
        return
    if contenu not in CONTENUS:
        await interaction.response.send_message(f"❌ Contenu invalide.", ephemeral=True)
        return

    liens_list = liens.split() if liens else []
    build_id = make_id(classe, aspect, contenu, interaction.user.display_name)

    con = get_db()
    con.execute(
        """INSERT INTO builds (id, guild_id, author_id, author_name, classe, aspect, contenu, description, liens, patch, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (build_id, str(interaction.guild_id), str(interaction.user.id),
         str(interaction.user.display_name), classe, aspect, contenu,
         description, json.dumps(liens_list), patch, datetime.utcnow().isoformat())
    )
    con.commit()
    con.close()

    embed = discord.Embed(title="✅ Build enregistré !", color=discord.Color.green())
    embed.add_field(name="🆔 ID",      value=f"`{build_id}`", inline=False)
    embed.add_field(name="🧙 Classe",  value=classe,   inline=True)
    embed.add_field(name="⚔️ Aspect",  value=aspect,   inline=True)
    embed.add_field(name="🎯 Contenu", value=contenu,  inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ─── /build-get ──────────────────────────────────────────────────────────────

@tree.command(name="build-get", description="Recherche des builds par classe, aspect et/ou contenu.")
@app_commands.describe(
    classe  = "Filtrer par classe",
    aspect  = "Filtrer par aspect",
    contenu = "Filtrer par contenu (PvE ou PvP)",
)
@app_commands.autocomplete(classe=autocomplete_classe, aspect=autocomplete_aspect, contenu=autocomplete_contenu)
async def build_get(
    interaction: discord.Interaction,
    classe: Optional[str] = None,
    aspect: Optional[str] = None,
    contenu: Optional[str] = None,
):
    if not classe and not aspect and not contenu:
        await interaction.response.send_message("❌ Précise au moins un critère.", ephemeral=True)
        return

    query = "SELECT b.*, (SELECT COUNT(*) FROM votes v WHERE v.build_id = b.id) as votes FROM builds b WHERE b.guild_id = ?"
    params = [str(interaction.guild_id)]
    if classe:
        query += " AND b.classe = ?"; params.append(classe)
    if aspect:
        query += " AND b.aspect = ?"; params.append(aspect)
    if contenu:
        query += " AND b.contenu = ?"; params.append(contenu)
    query += " ORDER BY votes DESC, b.created_at DESC LIMIT 5"

    con = get_db()
    rows = con.execute(query, params).fetchall()
    con.close()

    if not rows:
        await interaction.response.send_message("😕 Aucun build trouvé pour ces critères.", ephemeral=True)
        return

    # Un embed par build
    embeds = [build_embed(r, r["votes"]) for r in rows]
    # Toutes les images de tous les builds
    all_images = []
    for r in rows:
        all_images.extend(json.loads(r["liens"]))

    await interaction.response.send_message(f"🔍 **{len(rows)} build(s) trouvé(s)** :", embeds=embeds)

    # Images en messages séparés
    sent = []
    for url in all_images:
        msg = await interaction.channel.send(url)
        sent.append(msg)

    # Suppression après 5 minutes
    async def cleanup():
        await asyncio.sleep(DELETE_DELAY)
        try:
            await (await interaction.original_response()).delete()
        except Exception:
            pass
        for msg in sent:
            try:
                await msg.delete()
            except Exception:
                pass
    asyncio.create_task(cleanup())

# ─── /build-list ─────────────────────────────────────────────────────────────

@tree.command(name="build-list", description="Liste tous les builds disponibles par classe.")
async def build_list(interaction: discord.Interaction):
    con = get_db()
    rows = con.execute(
        "SELECT classe, contenu, COUNT(*) as nb FROM builds WHERE guild_id = ? GROUP BY classe, contenu ORDER BY classe, contenu",
        (str(interaction.guild_id),)
    ).fetchall()
    con.close()

    if not rows:
        await interaction.response.send_message("📭 Aucun build enregistré pour l'instant.", ephemeral=True)
        return

    by_class: dict[str, dict[str, int]] = {}
    for r in rows:
        by_class.setdefault(r["classe"], {})[r["contenu"]] = r["nb"]

    embed = discord.Embed(title="📚 Builds Allods Online", color=discord.Color.blurple())
    for classe in CLASSES:
        if classe in by_class:
            parts = [f"`{c}` : {by_class[classe].get(c, 0)}" for c in CONTENUS if by_class[classe].get(c)]
            embed.add_field(name=f"🧙 {classe}", value=" · ".join(parts), inline=False)

    embed.set_footer(text=f"Total : {sum(r['nb'] for r in rows)} builds")
    await interaction.response.send_message(embed=embed, ephemeral=True)

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
        await interaction.response.send_message("📭 Aucun build pour l'instant.", ephemeral=True)
        return

    await interaction.response.send_message("🏆 **Top builds :**",
        embeds=[build_embed(r, r["votes"]) for r in rows], ephemeral=True)

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
        msg = f"⭐ Vote retiré du build **{build_id}**."
    else:
        con.execute("INSERT INTO votes (build_id, user_id) VALUES (?,?)", (build_id, str(interaction.user.id)))
        msg = f"⭐ Vote ajouté au build **{build_id}** !"
    con.commit()
    con.close()
    await interaction.response.send_message(msg, ephemeral=True)

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
    await interaction.response.send_message(f"🗑️ Build **{build_id}** supprimé.", ephemeral=True)

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
    await interaction.response.send_message(f"Build **{build_id}** {status}.", ephemeral=True)

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

    liens = json.loads(row["liens"])
    await interaction.response.send_message("🎲 **Build aléatoire :**", embed=build_embed(row, row["votes"]), ephemeral=True)
    for url in liens:
        await interaction.followup.send(url, ephemeral=True)

# ─── Lancement ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    bot.run(TOKEN)

"""
Discord Build Bot
Enregistre et retrouve des builds de jeu vidéo par classe et aspect.
"""

import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import os
import json
from datetime import datetime
from typing import Optional

# ─── Configuration ───────────────────────────────────────────────────────────

TOKEN = os.getenv("DISCORD_TOKEN", "YOUR_TOKEN_HERE")
DB_PATH = "builds.db"

# ─── Base de données ──────────────────────────────────────────────────────────

def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS builds (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id    TEXT    NOT NULL,
            author_id   TEXT    NOT NULL,
            author_name TEXT    NOT NULL,
            classe      TEXT    NOT NULL,
            aspect      TEXT    NOT NULL,
            titre       TEXT    NOT NULL,
            description TEXT,
            liens       TEXT    NOT NULL DEFAULT '[]',  -- JSON array
            patch       TEXT,
            obsolete    INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS votes (
            build_id    INTEGER NOT NULL,
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

# ─── Helpers ─────────────────────────────────────────────────────────────────

def build_embed(row, vote_count: int = 0) -> discord.Embed:
    """Transforme une ligne DB en Embed Discord."""
    color = discord.Color.orange() if not row["obsolete"] else discord.Color.greys()[3]
    
    title = f"{'⚠️ [OBSOLÈTE] ' if row['obsolete'] else ''}**{row['titre']}**"
    embed = discord.Embed(
        title=title,
        description=row["description"] or "*Aucune description.*",
        color=color,
        timestamp=datetime.fromisoformat(row["created_at"])
    )
    embed.add_field(name="🧙 Classe",  value=row["classe"].capitalize(), inline=True)
    embed.add_field(name="✨ Aspect",  value=row["aspect"].capitalize(), inline=True)
    if row["patch"]:
        embed.add_field(name="📅 Patch", value=row["patch"], inline=True)
    embed.add_field(name="⭐ Votes",   value=str(vote_count), inline=True)

    liens = json.loads(row["liens"])
    if liens:
        liens_str = "\n".join(f"[Lien {i+1}]({l})" for i, l in enumerate(liens))
        embed.add_field(name="🔗 Liens / Images", value=liens_str, inline=False)
        # Affiche la première image en aperçu si c'est une URL d'image
        first = liens[0]
        if any(first.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"]):
            embed.set_image(url=first)

    embed.set_footer(text=f"Build #{row['id']} · Ajouté par {row['author_name']}")
    return embed


def autocomplete_from_column(column: str):
    """Génère une fonction d'autocomplétion depuis les valeurs distinctes d'une colonne."""
    async def autocomplete(interaction: discord.Interaction, current: str):
        con = get_db()
        rows = con.execute(
            f"SELECT DISTINCT {column} FROM builds WHERE guild_id = ? AND {column} LIKE ? LIMIT 10",
            (str(interaction.guild_id), f"%{current}%")
        ).fetchall()
        con.close()
        return [app_commands.Choice(name=r[0].capitalize(), value=r[0]) for r in rows]
    return autocomplete

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
    classe      = "Classe du personnage (ex: Sorcier, Barbare…)",
    aspect      = "Aspect / archétype du build (ex: Feu, Tanky, DoT…)",
    titre       = "Nom court du build",
    description = "Description et explications du build",
    liens       = "Liens ou URLs d'images séparés par des espaces",
    patch       = "Version / saison du jeu (ex: S4, 2.1.0)",
)
async def build_add(
    interaction: discord.Interaction,
    classe: str,
    aspect: str,
    titre: str,
    description: Optional[str] = None,
    liens: Optional[str] = None,
    patch: Optional[str] = None,
):
    liens_list = liens.split() if liens else []
    con = get_db()
    cur = con.execute(
        """INSERT INTO builds (guild_id, author_id, author_name, classe, aspect, titre, description, liens, patch, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            str(interaction.guild_id),
            str(interaction.user.id),
            str(interaction.user.display_name),
            classe.lower(), aspect.lower(), titre,
            description,
            json.dumps(liens_list),
            patch,
            datetime.utcnow().isoformat(),
        )
    )
    con.commit()
    build_id = cur.lastrowid
    con.close()

    embed = discord.Embed(
        title="✅ Build enregistré !",
        description=f"**{titre}** ajouté avec l'ID `#{build_id}`.",
        color=discord.Color.green()
    )
    embed.add_field(name="Classe", value=classe.capitalize(), inline=True)
    embed.add_field(name="Aspect", value=aspect.capitalize(), inline=True)
    await interaction.response.send_message(embed=embed)

# ─── /build-get ──────────────────────────────────────────────────────────────

@tree.command(name="build-get", description="Recherche des builds par classe et/ou aspect.")
@app_commands.describe(
    classe = "Filtrer par classe",
    aspect = "Filtrer par aspect",
)
@app_commands.autocomplete(classe=autocomplete_from_column("classe"), aspect=autocomplete_from_column("aspect"))
async def build_get(
    interaction: discord.Interaction,
    classe: Optional[str] = None,
    aspect: Optional[str] = None,
):
    if not classe and not aspect:
        await interaction.response.send_message("❌ Précise au moins une classe ou un aspect.", ephemeral=True)
        return

    query = "SELECT b.*, (SELECT COUNT(*) FROM votes v WHERE v.build_id = b.id) as votes FROM builds b WHERE b.guild_id = ?"
    params = [str(interaction.guild_id)]
    if classe:
        query += " AND b.classe LIKE ?"
        params.append(f"%{classe.lower()}%")
    if aspect:
        query += " AND b.aspect LIKE ?"
        params.append(f"%{aspect.lower()}%")
    query += " ORDER BY votes DESC, b.created_at DESC LIMIT 5"

    con = get_db()
    rows = con.execute(query, params).fetchall()
    con.close()

    if not rows:
        await interaction.response.send_message(
            f"😕 Aucun build trouvé pour {'classe **' + classe + '**' if classe else ''}"
            f"{' + ' if classe and aspect else ''}{'aspect **' + aspect + '**' if aspect else ''}.",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"🔍 **{len(rows)} build(s) trouvé(s)** :",
        embeds=[build_embed(r, r["votes"]) for r in rows]
    )

# ─── /build-list ─────────────────────────────────────────────────────────────

@tree.command(name="build-list", description="Liste toutes les classes et aspects disponibles.")
async def build_list(interaction: discord.Interaction):
    con = get_db()
    rows = con.execute(
        "SELECT classe, aspect, COUNT(*) as nb FROM builds WHERE guild_id = ? GROUP BY classe, aspect ORDER BY classe, aspect",
        (str(interaction.guild_id),)
    ).fetchall()
    con.close()

    if not rows:
        await interaction.response.send_message("📭 Aucun build enregistré pour l'instant.", ephemeral=True)
        return

    # Regrouper par classe
    by_class: dict[str, list[str]] = {}
    for r in rows:
        by_class.setdefault(r["classe"].capitalize(), []).append(
            f"`{r['aspect'].capitalize()}` ({r['nb']})"
        )

    embed = discord.Embed(title="📚 Builds disponibles", color=discord.Color.blurple())
    for classe, aspects in by_class.items():
        embed.add_field(name=f"🧙 {classe}", value=" · ".join(aspects), inline=False)
    embed.set_footer(text=f"Total : {sum(r['nb'] for r in rows)} builds")
    await interaction.response.send_message(embed=embed)

# ─── /build-top ──────────────────────────────────────────────────────────────

@tree.command(name="build-top", description="Affiche les builds les mieux votés.")
async def build_top(interaction: discord.Interaction):
    con = get_db()
    rows = con.execute(
        """SELECT b.*, COUNT(v.user_id) as votes
           FROM builds b LEFT JOIN votes v ON v.build_id = b.id
           WHERE b.guild_id = ?
           GROUP BY b.id ORDER BY votes DESC, b.created_at DESC LIMIT 5""",
        (str(interaction.guild_id),)
    ).fetchall()
    con.close()

    if not rows:
        await interaction.response.send_message("📭 Aucun build pour l'instant.", ephemeral=True)
        return

    await interaction.response.send_message(
        "🏆 **Top builds :**",
        embeds=[build_embed(r, r["votes"]) for r in rows]
    )

# ─── /build-vote ─────────────────────────────────────────────────────────────

@tree.command(name="build-vote", description="Vote pour un build (toggle).")
@app_commands.describe(build_id="ID du build (visible en bas de chaque embed)")
async def build_vote(interaction: discord.Interaction, build_id: int):
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
        con.execute("DELETE FROM votes WHERE build_id = ? AND user_id = ?",
                    (build_id, str(interaction.user.id)))
        msg = f"⭐ Vote retiré du build **{row['titre']}**."
    else:
        con.execute("INSERT INTO votes (build_id, user_id) VALUES (?,?)",
                    (build_id, str(interaction.user.id)))
        msg = f"⭐ Vote ajouté au build **{row['titre']}** !"
    con.commit()
    con.close()
    await interaction.response.send_message(msg, ephemeral=True)

# ─── /build-delete ───────────────────────────────────────────────────────────

@tree.command(name="build-delete", description="Supprime un de tes builds.")
@app_commands.describe(build_id="ID du build à supprimer")
async def build_delete(interaction: discord.Interaction, build_id: int):
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
    await interaction.response.send_message(f"🗑️ Build **#{build_id} — {row['titre']}** supprimé.", ephemeral=True)

# ─── /build-obsolete ─────────────────────────────────────────────────────────

@tree.command(name="build-obsolete", description="Marque/démarque un build comme obsolète.")
@app_commands.describe(build_id="ID du build")
async def build_obsolete(interaction: discord.Interaction, build_id: int):
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
    await interaction.response.send_message(f"Build **#{build_id}** {status}.", ephemeral=True)

# ─── /build-random ───────────────────────────────────────────────────────────

@tree.command(name="build-random", description="Affiche un build aléatoire.")
async def build_random(interaction: discord.Interaction):
    con = get_db()
    row = con.execute(
        """SELECT b.*, COUNT(v.user_id) as votes
           FROM builds b LEFT JOIN votes v ON v.build_id = b.id
           WHERE b.guild_id = ? AND b.obsolete = 0
           GROUP BY b.id ORDER BY RANDOM() LIMIT 1""",
        (str(interaction.guild_id),)
    ).fetchone()
    con.close()

    if not row:
        await interaction.response.send_message("📭 Aucun build disponible.", ephemeral=True)
        return

    await interaction.response.send_message("🎲 **Build aléatoire :**", embed=build_embed(row, row["votes"]))

# ─── Lancement ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    bot.run(TOKEN)

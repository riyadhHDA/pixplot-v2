# Brancher PixPlot sur Claude (ou un autre LLM) — serveur MCP

[English](MCP.md) · **Français**

`pixplot mcp` démarre un serveur [MCP](https://modelcontextprotocol.io) qui donne au LLM un
accès direct au corpus : il cherche, **regarde les images**, explore les groupes et
exporte des Research Packs. Tout reste sur votre PC : le serveur lit vos fichiers locaux
et ne transmet au LLM que ce que ses outils renvoient (textes, vignettes, détails).

> Rôles : PixPlot calcule, observe et organise. Le LLM questionne et propose.
> L'historien vérifie, interprète et construit le savoir.

## Outils fournis

| Outil | Rôle |
|---|---|
| `corpus_overview` | taille, modèles, groupes et leurs métadonnées dominantes |
| `search_by_text` | œuvres correspondant à une description (SigLIP 2, français ou anglais) |
| `similar_artworks` | plus proches voisines d'une œuvre, dans l'espace choisi : `forme` (DINOv3), `sujet` (SigLIP 2), `couleur`, `touche` |
| `search_detail` | zones semblables à un détail (cadre x0, y0, x1, y1 en fractions) |
| `get_artwork` | fiche : métadonnées et leur source, groupe, atypicité, voisines |
| `view_artwork` | **l'image** de l'œuvre (256 à 1024 px) |
| `view_detail` | **un détail recadré** depuis l'original |
| `compare_artworks` | **planche numérotée** de 2 à 12 œuvres + une matrice de similarité par espace |
| `get_group` | un groupe de la carte, œuvres les plus centrales d'abord |
| `find_atypical` | œuvres les plus isolées (exceptions, erreurs de catalogue…) |
| `check_labels` | étiquettes que toutes les voisines contredisent (erreurs possibles ou œuvres singulières) |
| `notebook_add` | ajoute une piste au **carnet de recherche** de l'historien (visible dans l'Atlas) |
| `notebook_list` | relit le carnet (les plus récentes d'abord) |
| `export_research_pack` | dossier .zip traçable (voir README) |

Les consignes données au LLM (méthode, prudence d'interprétation, contre-exemples) sont
dans `pixplot/mcp/server.py` (`INSTRUCTIONS`).

## Claude Code

Créer à la racine du projet un fichier `.mcp.json` :

```json
{
  "mcpServers": {
    "pixplot": {
      "command": ".venv/Scripts/pixplot.exe",
      "args": ["--data", "data", "mcp"]
    }
  }
}
```

Ouvrir une nouvelle session dans ce dossier et approuver le serveur `pixplot`.

## Claude Desktop

Dans `%APPDATA%\Claude\claude_desktop_config.json` (chemins absolus) :

```json
{
  "mcpServers": {
    "pixplot": {
      "command": "C:\\chemin\\vers\\pixplot-v2\\.venv\\Scripts\\pixplot.exe",
      "args": ["--data", "C:\\chemin\\vers\\pixplot-v2\\data", "mcp"]
    }
  }
}
```

Puis redémarrer Claude Desktop.

## Codex (OpenAI)

Dans `.codex/config.toml` à la racine du projet (local, non versionné) ou dans
`%USERPROFILE%\.codex\config.toml`, chemins absolus :

```toml
[mcp_servers.pixplot]
command = 'C:\chemin\vers\pixplot-v2\.venv\Scripts\pixplot.exe'
args = ["--data", 'C:\chemin\vers\pixplot-v2\data', "mcp"]
```

## Gemini (Gemini CLI, Antigravity)

Dans `.gemini/settings.json` à la racine du projet (local, non versionné), chemins absolus :

```json
{
  "mcpServers": {
    "pixplot": {
      "command": "C:\\chemin\\vers\\pixplot-v2\\.venv\\Scripts\\pixplot.exe",
      "args": ["--data", "C:\\chemin\\vers\\pixplot-v2\\data", "mcp"]
    }
  }
}
```

Les consignes du dépôt pour tous les assistants sont dans [`AGENTS.md`](../AGENTS.md).

## Bon à savoir

- Le serveur charge l'analyse la plus récente (`--analysis <dossier>` pour en choisir une).
- La première recherche par texte ou par détail charge le modèle sur le GPU (jusqu'à une
  minute) ; les suivantes sont immédiates.
- Ne pas lancer `pip install` pendant qu'un serveur PixPlot (Atlas ou MCP) tourne : sous
  Windows, `pixplot.exe` est verrouillé et l'installation reste à moitié faite.

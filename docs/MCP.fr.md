# Brancher PixPlot sur Claude (ou un autre LLM) — serveur MCP

[English](MCP.md) · **Français**

`pixplot mcp` démarre un serveur [MCP](https://modelcontextprotocol.io) pour brancher un
assistant directement sur le corpus local : il peut lancer des recherches, afficher les
images, parcourir les groupes, écrire dans le carnet et exporter des *Research Packs*. Les
fichiers restent sur la machine ; le serveur ne renvoie au modèle que le résultat des outils
appelés (textes, vignettes, recadrages).

En pratique, PixPlot calcule les voisinages, l'assistant aide à formuler des pistes et à
comparer, et la vérification reste côté historien.

## Outils fournis

| Outil | Rôle |
|---|---|
| `corpus_overview` | taille, modèles, groupes et leurs métadonnées dominantes |
| `search_by_text` | œuvres correspondant à une description (SigLIP 2, français ou anglais) |
| `similar_artworks` | plus proches voisines d'une œuvre, dans l'espace choisi : `forme` (DINOv3), `sujet` (SigLIP 2), `couleur`, `touche` |
| `search_detail` | zones semblables à un détail (cadre x0, y0, x1, y1 en fractions) |
| `search_zones` | zones d'œuvres correspondant à un détail décrit (« une auréole », « un crâne »), avec le recadrage |
| `get_artwork` | fiche : métadonnées et leur source, groupe, atypicité, voisines |
| `view_artwork` | **l'image** de l'œuvre (256 à 1024 px) |
| `view_detail` | **un détail recadré** depuis l'original |
| `compare_artworks` | **planche numérotée** de 2 à 12 œuvres + une matrice de similarité par espace |
| `why_similar` | **planche des deux œuvres** où les zones qui se répondent (cases 4 × 4, regard forme) portent le même numéro, + leurs cosinus |
| `probe_concepts` | compare **deux concepts textuels** sur tout le corpus (SigLIP 2, façon *2D CLIP* d'Impett & Offert) : corrélation, extrêmes et écarts à la diagonale |
| `measure_artwork` | **mesures visuelles sans GPU** (Stork) : barycentre de luminance/saturation, dispersion locale, symétrie gauche-droite, entropie chromatique et première coupe |
| `get_group` | un groupe de la carte, œuvres les plus centrales d'abord |
| `find_atypical` | œuvres les plus isolées (exceptions, erreurs de catalogue…) |
| `check_labels` | étiquettes que toutes les voisines contredisent (erreurs possibles ou œuvres singulières) |
| `find_duplicates` | œuvres entrées deux fois (même image) et variantes proches (répliques, séries, copies), avec les étiquettes qui se contredisent (`pixplot doublons`) |
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

## Antigravity (Google), sous Windows

**Antigravity → PixPlot.** L'éditeur Antigravity et son outil en ligne de commande (`agy`) lisent la
configuration MCP de l'espace de travail dans `.agents/mcp_config.json` (local, non versionné ; le
script `scripts/nouvelle-tache.ps1 … -Agent gemini` l'écrit dans chaque copie de travail) :

```json
{
  "mcpServers": {
    "pixplot": {
      "command": "C:\chemin\vers\pixplot-v2\.venv\Scripts\pixplot.exe",
      "args": ["--data", "C:\chemin\vers\pixplot-v2\data\wikiart81k", "mcp"]
    }
  }
}
```

Redémarrer Antigravity après l'avoir créée. Les compétences communes (`.agents/skills/`, par exemple
l'accessibilité) sont lues par Antigravity, Codex et Gemini, et par Claude Code par un lien.

**Claude → Antigravity (second avis).** `pixplot antigravity-mcp` est un petit serveur MCP avec un
seul outil, `ask_antigravity` : Claude envoie une question (et des fichiers à lire) à Antigravity et
reçoit sa réponse. Antigravity y est lancé **en lecture seule** (mode `plan`, sans autorisation
automatique) : il ne peut rien modifier. Dans `.mcp.json` (Claude Code) :

```json
"antigravity": {
  "command": "C:\chemin\vers\pixplot-v2\.venv\Scripts\pixplot.exe",
  "args": ["antigravity-mcp"]
}
```

Il faut l'outil `agy` (installateur officiel de Google, dans PowerShell :
`irm https://antigravity.google/cli/install.ps1 | iex`, ou `winget install Google.AntigravityCLI`),
puis lancer une fois `agy` dans un terminal pour se connecter à son compte Google. `agy.exe` est cherché
dans le PATH puis dans `%LOCALAPPDATA%\agy\bin` ; sinon, indiquer son chemin dans `AGY_BIN`.

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

# Connecting PixPlot to Claude (or another LLM) — MCP server

**English** · [Français](MCP.fr.md)

`pixplot mcp` starts an [MCP](https://modelcontextprotocol.io) server that gives the LLM
direct access to the corpus: it searches, **looks at the images**, explores the groups,
writes to your research notebook and exports Research Packs. Everything stays on your PC:
the server reads your local files and only passes to the LLM what its tools return (text,
thumbnails, details).

> Roles: PixPlot computes, observes and organises. The LLM asks and suggests.
> The art historian checks, interprets and builds knowledge.

## Tools

| Tool | Purpose |
|---|---|
| `corpus_overview` | size, models, similarity spaces, groups (with their names) and their dominant metadata |
| `search_by_text` | works matching a description (SigLIP 2, French or English) |
| `similar_artworks` | nearest neighbours of a work in the chosen space: `forme` (DINOv3), `sujet` (SigLIP 2), `couleur`, `touche` |
| `search_detail` | regions similar to a detail (box x0, y0, x1, y1 as fractions) |
| `get_artwork` | record: metadata and their source, group, atypicality, neighbours |
| `view_artwork` | **the image** of the work (256 to 1024 px) |
| `view_detail` | **a cropped detail** from the original |
| `compare_artworks` | **numbered contact sheet** of 2 to 12 works + one similarity matrix per space |
| `get_group` | a group of the map, most central works first |
| `find_atypical` | the most isolated works (exceptions, cataloguing errors…) |
| `check_labels` | labels contradicted by all the neighbours (possible errors or singular works) |
| `notebook_add` | adds a lead to the historian's **research notebook** (visible in the Atlas) |
| `notebook_list` | reads the notebook back (most recent first) |
| `export_research_pack` | traceable .zip dossier (see the README) |

The guidelines given to the LLM (method, interpretive caution, counter-examples) are in
`pixplot/mcp/server.py` (`INSTRUCTIONS`, in French; the LLM reads them as they are).

## Claude Code

Create a `.mcp.json` file at the root of the project:

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

Open a new session in that folder and approve the `pixplot` server.

## Claude Desktop

In `%APPDATA%\Claude\claude_desktop_config.json` (absolute paths):

```json
{
  "mcpServers": {
    "pixplot": {
      "command": "C:\\path\\to\\pixplot-v2\\.venv\\Scripts\\pixplot.exe",
      "args": ["--data", "C:\\path\\to\\pixplot-v2\\data", "mcp"]
    }
  }
}
```

Then restart Claude Desktop.

## Good to know

- The server loads the most recent analysis (`--analysis <folder>` to pick another).
- The first text or detail search loads the model onto the GPU (up to a minute); later
  ones are immediate.
- Do not run `pip install` while a PixPlot server (Atlas or MCP) is running: on Windows,
  `pixplot.exe` is locked and the installation is left half done.

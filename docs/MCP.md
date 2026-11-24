# Connecting PixPlot to Claude (or another LLM) — MCP server

**English** · [Français](MCP.fr.md)

`pixplot mcp` starts an [MCP](https://modelcontextprotocol.io) server to connect an assistant
directly to your local corpus: it can run searches, inspect images, browse groups, add notes
to your notebook and export *Research Packs*. Files stay on your machine; the server only
returns tool outputs (text, thumbnails, crops).

In practice, PixPlot computes neighbourhoods, the assistant helps query and compare, and
verification stays with the historian.

## Tools

| Tool | Purpose |
|---|---|
| `corpus_overview` | size, models, similarity spaces, groups (with their names) and their dominant metadata |
| `search_by_text` | works matching a description (SigLIP 2, French or English) |
| `similar_artworks` | nearest neighbours of a work in the chosen space: `forme` (DINOv3), `sujet` (SigLIP 2), `couleur`, `touche`, `posture` (on trial: figures and gestures, mirror included) |
| `search_detail` | regions similar to a detail (box x0, y0, x1, y1 as fractions) |
| `search_zones` | regions of works matching a described detail ("a halo", "a skull"), with the crop |
| `get_artwork` | record: metadata and their source, group, atypicality, neighbours |
| `view_artwork` | **the image** of the work (256 to 1024 px) |
| `view_detail` | **a cropped detail** from the original |
| `compare_artworks` | **numbered contact sheet** of 2 to 12 works + one similarity matrix per space |
| `why_similar` | **plate of the two works** where the zones that answer each other (4×4 cells, form regard) carry the same number, + their cosines |
| `probe_concepts` | compares **two textual concepts** across the corpus (SigLIP 2, after Impett & Offert's *2D CLIP*): correlation, poles and off-diagonal deviations |
| `measure_artwork` | **neural-free visual measures** (Stork): lightness/saturation barycentre, local spread, left–right symmetry, chromatic entropy and primary compositional split |
| `get_group` | a group of the map, most central works first |
| `find_atypical` | the most isolated works (exceptions, cataloguing errors…) |
| `check_labels` | labels contradicted by all the neighbours (possible errors or singular works) |
| `find_duplicates` | works entered twice (same image) and close variants (replicas, series, copies), with the labels that contradict each other (`pixplot doublons`) |
| `explore_notions` | notions the model learned on its own (objects, motifs, manners): search them by name, or see the works where one is strongest; Iconclass name only when reliable; `space`: `sujet` or `forme` (`pixplot notions`) |
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

## Codex (OpenAI)

In `.codex/config.toml` at the project root (local, not versioned) or in
`%USERPROFILE%\.codex\config.toml`, absolute paths:

```toml
[mcp_servers.pixplot]
command = 'C:\path\to\pixplot-v2\.venv\Scripts\pixplot.exe'
args = ["--data", 'C:\path\to\pixplot-v2\data', "mcp"]
```

## Antigravity (Google), on Windows

**Antigravity → PixPlot.** The Antigravity editor and its command-line tool (`agy`) read the workspace
MCP configuration from `.agents/mcp_config.json` (local, not versioned; `scripts/nouvelle-tache.ps1 …
-Agent gemini` writes it in each worktree):

```json
{
  "mcpServers": {
    "pixplot": {
      "command": "C:\path\to\pixplot-v2\.venv\Scripts\pixplot.exe",
      "args": ["--data", "C:\path\to\pixplot-v2\data\wikiart81k", "mcp"]
    }
  }
}
```

Restart Antigravity after creating it. Shared skills (`.agents/skills/`, e.g. accessibility) are read by
Antigravity, Codex and Gemini, and by Claude Code through a link.

**Claude → Antigravity (second opinion).** `pixplot antigravity-mcp` is a small MCP server with one
tool, `ask_antigravity`: Claude sends a question (and files to read) to Antigravity and gets its answer.
Antigravity runs **read-only** (`plan` mode, no automatic approval): it cannot change anything. In
`.mcp.json` (Claude Code):

```json
"antigravity": {
  "command": "C:\path\to\pixplot-v2\.venv\Scripts\pixplot.exe",
  "args": ["antigravity-mcp"]
}
```

It needs the `agy` tool (Google's official installer, in PowerShell:
`irm https://antigravity.google/cli/install.ps1 | iex`, or `winget install Google.AntigravityCLI`), then
running `agy` once in a terminal to sign in with a Google account. `agy.exe` is looked up on the PATH,
then in `%LOCALAPPDATA%\agy\bin`; otherwise set its path in `AGY_BIN`.

## Gemini (Gemini CLI, Antigravity)

In `.gemini/settings.json` at the project root (local, not versioned), absolute paths:

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

Repository instructions shared by all assistants are in [`AGENTS.md`](../AGENTS.md) (in French).

## Good to know

- The server loads the most recent analysis (`--analysis <folder>` to pick another).
- The first text or detail search loads the model onto the GPU (up to a minute); later
  ones are immediate.
- Do not run `pip install` while a PixPlot server (Atlas or MCP) is running: on Windows,
  `pixplot.exe` is locked and the installation is left half done.

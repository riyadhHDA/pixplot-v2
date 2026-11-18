# CLAUDE.md

Les consignes de ce dépôt sont communes à tous les assistants : elles sont dans `AGENTS.md`.
Lire ensuite `docs/HANDOFF.md`, et le mettre à jour en fin de session.

@AGENTS.md
@docs/HANDOFF.md

## Propre à Claude Code

- Serveurs de prévisualisation : `.claude/launch.json` (local, non versionné).
- Serveur MCP PixPlot : `.mcp.json` à la racine (local), voir `docs/MCP.fr.md`.
- La mémoire automatique de Claude Code ne sert qu'à Claude : tout ce qui doit être connu des autres
  modèles va dans `AGENTS.md` (règles) ou `docs/HANDOFF.md` (état du travail).

"""Relais MCP vers Antigravity (Google) : un second avis, d'une autre famille de modèles.

``pixplot antigravity-mcp`` lance un petit serveur MCP (stdio) avec un seul outil,
``ask_antigravity`` : il transmet une question (et, au besoin, des fichiers ou dossiers à lire) à
l'outil en ligne de commande d'Antigravity, ``agy``, et renvoie sa réponse. Claude peut ainsi
demander une relecture ou un avis à Gemini sans quitter sa session.

Prudence, contrairement au paquet ``antigravity-claude-mcp`` dont il s'inspire :
- **lecture seule** : Antigravity est lancé en mode ``plan``, sans ``--dangerously-skip-permissions`` ;
  en mode non interactif, toute action qui demanderait une autorisation (écrire un fichier, lancer
  une commande) est refusée d'office par ``agy`` ;
- **Windows d'abord** : ``agy.exe`` est cherché dans le PATH, puis dans ``%LOCALAPPDATA%\\agy\\bin``
  (emplacement de l'installateur Windows), puis dans ``~/.local/bin`` (macOS, Linux) ;
- aucune dépendance de plus que le SDK MCP déjà utilisé par PixPlot.

Installer ``agy`` et se connecter à son compte Google reste à faire par l'utilisateur.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

DEFAULT_TIMEOUT = 330          # secondes (agy s'arrête lui-même à 5 min : --print-timeout 5m)
INSTALL_HELP = (
    "L'outil en ligne de commande d'Antigravity (agy) est introuvable.\n"
    "Sous Windows, dans PowerShell (installateur officiel de Google) :\n"
    "  irm https://antigravity.google/cli/install.ps1 | iex\n"
    "ou : winget install Google.AntigravityCLI\n"
    "Puis, une fois, dans un nouveau terminal : agy  (connexion au compte Google dans le navigateur).\n"
    "Ou indiquez son chemin exact dans la variable d'environnement AGY_BIN."
)
READ_ONLY_NOTE = ("Tu fais une relecture en lecture seule pour un autre assistant : ne modifie aucun "
                  "fichier et ne lance aucune commande ; réponds par écrit.\n\n")


def find_agy(env: dict | None = None) -> str | None:
    """Chemin de ``agy`` : AGY_BIN, puis le PATH, puis les emplacements des installateurs."""
    env = os.environ if env is None else env
    if env.get("AGY_BIN"):
        return env["AGY_BIN"] if Path(env["AGY_BIN"]).exists() else None
    found = shutil.which("agy", path=env.get("PATH"))
    if found:
        return found
    candidates = []
    if env.get("LOCALAPPDATA"):
        local = Path(env["LOCALAPPDATA"])
        candidates += [local / "agy" / "bin" / name for name in ("agy.exe", "agy.cmd", "agy")]
        # winget install Google.AntigravityCLI : le dossier n'entre dans le PATH qu'aux nouvelles sessions
        candidates += [local / "Microsoft" / "WinGet" / "Links" / "agy.exe"]
        candidates += sorted((local / "Microsoft" / "WinGet" / "Packages").glob("Google.AntigravityCLI_*/agy.exe"))
    home = env.get("USERPROFILE") or env.get("HOME")
    if home:
        candidates.append(Path(home) / ".local" / "bin" / "agy")
    return next((str(c) for c in candidates if c.exists()), None)


def build_args(agy: str, question: str, paths: list[str] | None = None, model: str | None = None) -> list[str]:
    """Ligne de commande de ``agy`` : non interactive, en mode plan (lecture seule), avec les
    dossiers des chemins donnés ajoutés à l'espace de travail."""
    paths = [p for p in (paths or []) if Path(p).exists()]
    prompt = READ_ONLY_NOTE + (
        "Fichiers et dossiers à lire en entier avant de répondre :\n" + "\n".join(f"- {p}" for p in paths) + "\n\n"
        if paths else "") + question
    args = [agy, "-p", prompt, "--mode", "plan", "--sandbox", "--print-timeout", "5m"]
    if model:
        args += ["--model", model]
    for d in dict.fromkeys(str(Path(p) if Path(p).is_dir() else Path(p).parent) for p in paths):
        args += ["--add-dir", d]
    return args


def ask(question: str, paths: list[str] | None = None, model: str | None = None,
        timeout: int = DEFAULT_TIMEOUT) -> tuple[bool, str]:
    agy = find_agy()
    if agy is None:
        return False, INSTALL_HELP
    try:
        r = subprocess.run(build_args(agy, question, paths, model), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return False, f"Antigravity n'a pas répondu en {timeout} s."
    except OSError as exc:
        return False, f"Impossible de lancer agy ({agy}) : {exc}"
    text = (r.stdout or "").strip() or (r.stderr or "").strip() or f"(aucune réponse ; code de sortie {r.returncode})"
    if r.returncode != 0 and "auth" in text.lower():
        text += "\n\nConnexion nécessaire : lancez une fois « agy » dans un terminal pour vous connecter."
    return r.returncode == 0, text


def create_server():
    from mcp.server.mcpserver import MCPServer

    server = MCPServer(name="antigravity", title="Antigravity (second avis)", log_level="WARNING",
                       instructions="Un second avis d'Antigravity (Google, Gemini), en lecture seule : "
                                    "relecture de code, approche alternative, recherche de bogues. "
                                    "Ses réponses sont des propositions à vérifier, pas des faits.")

    @server.tool()
    def ask_antigravity(question: str, paths: list[str] | None = None, model: str | None = None) -> str:
        """Demande un second avis à Antigravity (Google, modèle Gemini par défaut), une autre famille
        de modèles que Claude. ``paths`` : chemins absolus de fichiers ou dossiers à lui faire lire.
        Lecture seule : Antigravity ne peut rien modifier. Réponse en quelques dizaines de secondes."""
        ok, text = ask(question, paths, model)
        if not ok:
            raise RuntimeError(text)
        return text

    return server


def run() -> None:
    create_server().run("stdio")

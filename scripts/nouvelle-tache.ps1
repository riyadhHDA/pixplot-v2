<#
.SYNOPSIS
  Une copie de travail par tâche, pour faire travailler plusieurs assistants en parallèle
  (Codex, Claude, Gemini…) sans qu'ils se marchent dessus. Voir AGENTS.md, « Travail en parallèle ».

.EXAMPLE
  .\scripts\nouvelle-tache.ps1 paris-musees -Agent codex
    Crée ..\pixplot-paris-musees sur la branche codex/paris-musees, reliée aux données du dossier
    principal, avec le serveur MCP PixPlot configuré pour Codex, Claude et Gemini.

.EXAMPLE
  .\scripts\nouvelle-tache.ps1 paris-musees -Agent codex -Terminer
    Vérifie que tout est commité et que les tests passent, fusionne la branche dans le dossier
    principal (sans push), puis supprime la copie de travail.

.EXAMPLE
  .\scripts\nouvelle-tache.ps1 paris-musees -Agent codex -Abandonner
    Supprime la copie de travail et sa branche, sans rien fusionner.
#>
param(
  [Parameter(Mandatory = $true, Position = 0)][string]$Nom,
  [string]$Agent = "codex",
  [string]$Corpus = "wikiart81k",
  [switch]$Terminer,
  [switch]$Abandonner
)
$ErrorActionPreference = "Stop"

if ($Nom -notmatch '^[a-z0-9][a-z0-9-]*$') { throw "Nom de tâche : minuscules, chiffres et tirets (ex. paris-musees)." }
$Root   = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Dir    = Join-Path (Split-Path $Root -Parent) "pixplot-$Nom"
$Branch = "$Agent/$Nom"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Data   = Join-Path $Root "data\$Corpus"

# git écrit ses avertissements (fins de ligne…) sur la sortie d'erreur : sous PowerShell 5.1, avec
# ErrorActionPreference = Stop, ils deviendraient des erreurs. Seul le code de sortie compte.
function RunGit {
  $ErrorActionPreference = "Continue"
  & git.exe -C $Root @args 2>&1 | ForEach-Object { "$_" }
  if ($LASTEXITCODE) { throw "git $args : échec" }
}
function Utf8($path, $text) { [IO.File]::WriteAllText($path, $text, (New-Object Text.UTF8Encoding $false)) }

# ------------------------------------------------------------------ abandonner
if ($Abandonner) {
  if (Test-Path $Dir) { RunGit worktree remove --force $Dir }
  & git.exe -C $Root branch -D $Branch 2>$null
  Write-Host "Tâche abandonnée : $Dir et la branche $Branch sont supprimés."
  return
}

# ------------------------------------------------------------------ terminer
if ($Terminer) {
  if (-not (Test-Path $Dir)) { throw "Pas de copie de travail $Dir." }
  $ErrorActionPreference = "Continue"; $dirty = & git.exe -C $Dir status --porcelain 2>$null; $ErrorActionPreference = "Stop"
  if ($dirty) { throw "Il reste des modifications non commitées dans $Dir :`n$($dirty -join "`n")" }
  Write-Host "Tests de la branche $Branch…"
  Push-Location $Dir
  try { & $Python -m pytest -q tests; $ok = ($LASTEXITCODE -eq 0) } finally { Pop-Location }
  if (-not $ok) { throw "Les tests ne passent pas : rien n'est fusionné." }
  Write-Host "`nCe qui va être fusionné :"
  RunGit log --oneline "main..$Branch"
  RunGit diff --stat "main...$Branch"
  RunGit merge --no-ff $Branch -m "Fusion de $Branch"
  RunGit worktree remove $Dir
  RunGit branch -d $Branch
  Write-Host "`nFusionné dans main (sans push). Mettre à jour docs/HANDOFF.md avec docs/handoff/$($Branch -replace '/', '-').md."
  return
}

# ------------------------------------------------------------------ créer
if (Test-Path $Dir) { throw "$Dir existe déjà." }
RunGit worktree add $Dir -b $Branch main

# un port libre pour l'Atlas de cette tâche (8770, 8771…) : ni pris en ce moment, ni réservé
# par une autre copie de travail (même si son Atlas ne tourne pas)
$taken = @()
foreach ($f in Get-ChildItem (Split-Path $Root -Parent) -Filter ".pixplot-tache" -Recurse -Depth 1 -Force -ErrorAction SilentlyContinue) {
  $m = Select-String -Path $f.FullName -Pattern '^port\s*=\s*(\d+)'
  if ($m) { $taken += [int]$m.Matches[0].Groups[1].Value }
}
$Port = 8770
while ($true) {
  if ($taken -notcontains $Port) {
    $l = New-Object Net.Sockets.TcpListener ([Net.IPAddress]::Loopback, $Port)
    try { $l.Start(); $l.Stop(); break } catch { }
  }
  $Port++
}

# serveur MCP PixPlot (lecture du corpus) pour Codex, Claude et Gemini : chemins absolus,
# car la copie de travail n'a ni .venv ni data
$exe = Join-Path $Root ".venv\Scripts\pixplot.exe"
New-Item -ItemType Directory -Force (Join-Path $Dir ".codex"), (Join-Path $Dir ".gemini") | Out-Null
Utf8 (Join-Path $Dir ".codex\config.toml") @"
[mcp_servers.pixplot]
command = '$exe'
args = ["--data", '$Data', "mcp"]
"@
$json = @{ mcpServers = @{ pixplot = @{ command = $exe; args = @("--data", $Data, "mcp") } } } | ConvertTo-Json -Depth 5
Utf8 (Join-Path $Dir ".mcp.json") $json
Utf8 (Join-Path $Dir ".gemini\settings.json") $json

# fiche de la tâche, lue par l'agent (non versionnée : .pixplot-tache est dans .gitignore)
Utf8 (Join-Path $Dir ".pixplot-tache") @"
tache   = $Nom
agent   = $Agent
branche = $Branch
dossier = $Dir
donnees = $Data
port    = $Port
python  = $Python
tests   = & '$Python' -m pytest -q tests
atlas   = & '$Python' -m pixplot.cli --data '$Data' serve --port $Port
"@

Write-Host @"

Copie de travail prête.
  dossier : $Dir
  branche : $Branch
  données : $Data   (partagées avec le dossier principal)
  Atlas   : port $Port

Dans ce dossier, toujours lancer PixPlot avec l'interpréteur du dossier principal et « -m »,
pour que ce soit le code de la branche qui tourne :
  tests : & '$Python' -m pytest -q tests
  Atlas : & '$Python' -m pixplot.cli --data '$Data' serve --port $Port

Ouvrir $Agent dans $Dir. Quand la tâche est finie et commitée :
  .\scripts\nouvelle-tache.ps1 $Nom -Agent $Agent -Terminer
"@

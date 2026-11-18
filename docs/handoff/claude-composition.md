# Compte rendu — claude/composition (18/11/2026)

**Tâche.** Étape 0.15 de la feuille de route : un regard « composition ». Lancée de ma propre
initiative pendant l'absence de l'utilisateur, avec son accord pour un calcul GPU.

**Fait.**
- Encodeur PE-Spatial B/16 (`pixplot/encoders/pe_spatial.py`, par `timm`, Apache 2.0) ; vecteurs
  pour les 80 716 œuvres : `data/wikiart81k/runs/features/pe_spatial_b16_20261118-115825`.
- Banc d'essai `pixplot composition` (`pixplot/analysis/composition.py`) : regards existants,
  PE-Spatial, dispositions 4 × 4, variantes « œuvre seule » et « cases communes ».
- Relecture du code par Codex (plugin Codex de Claude Code) : résultat jugé crédible, deux variantes
  proposées, mesurées.
- Tests : `test_composition_layout_ranks`, `test_composition_common_cells` ; 57 tests passent.
- ARCHITECTURE § 24 (FR + EN), note dans la ROADMAP (FR + EN).

**Résultat.** Non retenu : sur les 14 paires « même composition », DINOv3 reste le meilleur (rang
médian 8 ; PE-Spatial 286 au mieux). Les vecteurs PE-Spatial sont masqués dans l'Atlas et le MCP
(`NOT_KEPT`), gardés pour les bancs d'essai. `timm` ajouté aux dépendances `ml`.

**Pour l'intégrateur.** Pas de changement de version sur la branche. Une version 0.15.0 (« résultat
négatif documenté », comme la 0.13.0 pour TIPSv2) est possible : à décider avec l'utilisateur.

**Pour l'utilisateur.** Valider plus de paires « même composition » rendrait la mesure plus solide
(14 aujourd'hui).

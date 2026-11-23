# Compte rendu — Réparation du bouton « Pourquoi ? » (pourquoi-v2)

*Date : 23/11/2026 · Assistant : Gemini 4 Neon · Branche : `gemini/pourquoi-v2`*

## Ce qui est fait

- **Réglage séparé de la vérification** : exploration de l'Option 1 (sans GPU à la requête) uniquement sur 104 paires « voisines proches » de graine 1 (strictement disjointes des paires validées et des voisines de graine 0 ; 100/104 avec ≥ 4 correspondances). La variante retenue (**centrage par case $\mu_c$ + pondération par alignement avec le vecteur global** : $\max(0, \text{sim}_{\text{centré}}) \cdot \max(0, c_a \cdot g_a) \cdot \max(0, c_b \cdot g_b)$) passe le critère dès le réglage (`one`, `mean` : ratio **4,18**, chute médiane +0,0963 vs +0,0231 au hasard, coins 52,8 % → 3,9 %, centre 5,8 % → 59,0 %). L'Option 2 (occultation GPU à la demande) n'a donc pas été nécessaire.
- **Code modifié** :
  - `pixplot/analysis/correspondences.py` : ajout de `compute_cell_means` et `load_or_compute_cell_means` (cache `cell_means_4x4.npy` dans le dossier du run de vecteurs, 48 Ko, calculé une fois en 11,4 s sur 81k) ; centrage par position et pondération par `global_a`/`global_b` dans `match` et `correspondences` (rétrocompatible si ces arguments ne sont pas passés).
  - `pixplot/api/spaces.py` : cache thread-safe `Spaces.cell_means(key)`.
  - `pixplot/api/app.py` (`/api/correspond`) et `pixplot/mcp/server.py` (`why_similar`) : branchement du nouveau classement avec les mêmes champs de sortie et une note mise à jour.
  - `pixplot/analysis/whytest.py` : utilisation du nouveau classement (avec étiquette `v2_center_align` dans la signature de reprise).
  - `web/atlas-panneaux.js` : mise en garde explicite sous les zones du comparateur (« Zones qui se ressemblent le plus … une piste à regarder, pas une explication »).
  - `tests/test_research.py` : ajout de `test_correspondences_centered_and_global_aligned` (centrage, alignement global, cache disque).
- **Documentation** : section **§ 40** ajoutée dans `ARCHITECTURE.fr.md` et `ARCHITECTURE.md`.
- **Fichiers générés hors git** (dans `C:\Users\Riyadh\Documents\Pixplot V2\data\wikiart81k\`) :
  - `runs/features/dinov3_vitb16_20261116-102419/cell_means_4x4.npy` (48 Ko)
  - `bench/whytest_report_s39.json` (sauvegarde du rapport § 39), `bench/whytest_report.json` (vérification finale § 40), `bench/whytest_avant_apres.jpg` (planche avant / après sur 6 paires de vérification).

## Chiffres clés (vérification finale unique, `pixplot whytest`)

- **Temps** : calcul du cache `cell_means_4x4.npy` **11,4 s** (une seule fois sur CPU, puis < 1 ms par paire à la requête) ; vérification finale `pixplot whytest` **128,4 s** sur RX 7900 GRE (8 273 images encodées ; vérification sans occultation : écart max 0,000663, auto-cos min 0,999998 → OK).
- **Verdict : RÉUSSI en mode une image (`one`) sur les deux groupes et les deux remplissages (`mean` et `blur`)** :

| Groupe et mode (`mean`) | n | (a) Pourquoi [IC 95 %] | (b) Hasard | (c) Centre | Ratio `a / b` | (a − b) [IC 95 %] · p | Verdict |
|---|---|---|---|---|---|---|---|
| **Validées · 1 image (`one`)** | 73/108 | **+0,0112** [+0,0041 ; +0,0220] | +0,0027 | +0,0129 | **4,20** | +0,0138 [+0,0072 ; +0,0203] · <0,001 | **Réussi** |
| **Voisines · 1 image (`one`)** | 93/108 | **+0,0710** [+0,0603 ; +0,0968] | +0,0186 | +0,0960 | **3,82** | +0,0541 [+0,0465 ; +0,0682] · <0,001 | **Réussi** |
| Validées · 2 images (`both`) | 73/108 | +0,0045 [−0,0029 ; +0,0109] | −0,0116 | −0,0451 | — | +0,0136 [+0,0087 ; +0,0233] · 0,001 | Échec *(artefact)* |
| Voisines · 2 images (`both`) | 93/108 | +0,0612 [+0,0511 ; +0,0767] | +0,0270 | +0,0182 | 2,26 | +0,0331 [+0,0229 ; +0,0439] · <0,001 | Échec *(2,26 < 3)* |

- **Contrôle `blur` (`one`)** : Validées ratio **5,69** (+0,0184 vs +0,0032, p < 0,001, **Réussi**) ; Voisines ratio **3,71** (+0,0731 vs +0,0197, p < 0,001, **Réussi**).
- **Répartition spatiale (avant → après)** :
  - Validées : coins **63,0 % → 17,5 %**, bords **95,8 % → 63,7 %**, centre **4,2 % → 36,3 %**, même case **92,8 % → 46,2 %**.
  - Voisines : coins **57,5 % → 4,8 %**, bords **93,6 % → 42,7 %**, centre **6,4 % → 57,3 %**, même case **93,0 % → 56,2 %**.
- **Vérification dans l'Atlas (port 8770)** : 0 erreur console, 0 erreur réseau. Sur *Le Semeur* (`#79406 ↔ #41274`), les 4 cadres se posent sur le semeur (`+0,107` contre `−0,017` avant) ; sur les deux portraits ovales de Rembrandt (`#32834 ↔ #33077`), sur le visage et le buste (`+0,515` contre `+0,001`) ; sur Pissarro/Levitan (`#4261 ↔ #15620`), sur la bande de rivière (`+0,139` contre `−0,004`). Mise en garde vérifiée dans le DOM.

## Ce qui reste / Ce que l'utilisateur doit décider

1. **Intégration** : relire la planche `data/wikiart81k/bench/whytest_avant_apres.jpg`, puis fusionner la branche `gemini/pourquoi-v2` dans `main` (`.\scripts\nouvelle-tache.ps1 pourquoi-v2 -Agent gemini -Terminer`), et mettre à jour `docs/HANDOFF.md` et les CHANGELOG.
2. **Cas des paires à moins de 4 correspondances** : 35/108 paires validées (surtout `meme_palette` et `meme_facture`) produisent désormais 1 à 3 zones (au lieu de 4 fausses correspondances de coins). Le comparateur les affiche déjà proprement ; décider si ce comportement plus honnête convient tel quel.

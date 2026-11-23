# Exemples du regard « posture », pour illustrer le projet

*Mis de côté le 23/11/2026 à la demande de l'utilisateur, qui veut s'en servir pour illustrer
PixPlot sur GitHub (README, site). Regard décrit dans ARCHITECTURE § 35 ; compte rendu de Neon :
[`gemini-postures.md`](gemini-postures.md).*

Ce que le regard fait : il détecte les figures, estime leur squelette (17 points), et compare les
poses **en tenant compte du miroir** (une figure tournée à gauche répond à la même pose tournée à
droite). Il retrouve ainsi des **formules gestuelles** (les *Pathosformeln* d'Aby Warburg) d'un
siècle, d'un médium et d'un artiste à l'autre, là où les autres regards ne voient rien : sur les
paires « même geste », forme, sujet et touche placent l'œuvre jumelle vers le rang 10 000 en médiane ;
la posture, avec le miroir, au rang 38.

**État de la relecture** (`data/wikiart81k/bench/pairs.csv`, type `meme_geste`) : sur 37 paires
proposées par le modèle, l'utilisateur en a **validé 25**, rejeté 7 ; 5 restent à relire.
Le chiffre « pos » est la ressemblance de pose (cosinus, 1 = même pose).

## Exemples à montrer en premier

Œuvres toutes dans le domaine public (artistes morts avant 1956) : on peut les reproduire sur GitHub.

| Pose | Œuvre A | Œuvre B | n° (A ↔ B) | pos |
|---|---|---|---|---|
| Figure allongée en diagonale, bras replié (miroir) | Titien, *Vénus* (1565) | Mantegna, *Le Christ au jardin des Oliviers* (1455) | 66184 ↔ 56885 | 0,93 |
| Torsion du torse, bras tendu, jambes en fente (miroir) | Michel-Ange, *Ignudo*, Sixtine (1509) | Burne-Jones, *L'Amour guidant le pèlerin* (1896) | 24419 ↔ 71616 | 0,9 |
| Corps à quatre pattes, dos horizontal (miroir) | Caillebotte, *Les Raboteurs de parquet* (1876) | Raphael Kirchner, *Ivory sculpture* | 12088 ↔ 32407 | — |
| Figure pliée en deux vers le sol | Károly Ferenczy, *Garçons jetant des cailloux* (1890) | Van Gogh, *Paysans plantant des pommes de terre* (dessin, 1885) | 40978 ↔ 80238 | 0,94 |
| Deux bras levés en Y vers le ciel (miroir) | Raphael Kirchner (1903) | Goya, *Le Naufrage* (1794) | 32761 ↔ 10854 | 0,98 |
| Debout, penchée en avant, bras vers un appui (miroir) | Tintoret, *La Présentation au Temple* (1555) | Berthe Morisot, *La Petite Servante* (1886) | 35248 ↔ 2828 | 0,93 |
| Debout, inclinée en avant, jambe d'appui tendue (miroir) | Fra Angelico, *Mise au tombeau* (1440) | Hogarth, *Prospero et Miranda* (1728) | 10561 ↔ 60538 | 0,92 |
| Enfant allongé de biais sur les genoux (miroir) | Mabuse, *Sainte Famille* (1527) | Murillo, *Vierge à l'Enfant et anges musiciens* (1675) | 50560 ↔ 2506 | 0,90 |

**Filiations connues, retrouvées au premier rang** (paires « filiation » déjà validées, § 35) :

| | Œuvre A | Œuvre B | n° | Rang |
|---|---|---|---|---|
| *Le Semeur* | Van Gogh, d'après Millet (1881) | Millet (1850) | 79406 ↔ 41274 | 1 (pos 0,98) |
| *L'Enlèvement d'Europe* | Rubens, copie | Titien | 64269 ↔ 67405 | 1 (pos 0,95) |
| *Olympia* | Manet (1863) | Titien, *Vénus d'Urbin* (1538) | 8038 ↔ 75363 | 13 (pos 0,95) |

## Autres paires validées (domaine public)

Petrov-Vodkine ↔ Dürer, dessin de 1506 (21394 ↔ 233, nu allongé, bras derrière la tête) ;
Doré, gravure ↔ Monet, *Méditation* (12663 ↔ 5729, figure semi-allongée) ;
Spencer Stanhope ↔ frères Le Nain (44927 ↔ 38152, figure agenouillée penchée) ;
Bosch ↔ Tissot, eau-forte (14757 ↔ 18018, profil incliné) ;
Roerich, dessin ↔ Gallen-Kallela (25918 ↔ 60408, deux bras levés vers la tête) ;
Karl Bodmer, gravure ↔ George Morland (66792 ↔ 38819, mouvement, bras levés) ;
Kirchner ↔ Koustodiev, fusain (32550 ↔ 3475, bras tendu haut, buste renversé) ;
Rembrandt, dessin ↔ Bilibine (32820 ↔ 66703, bras levé en adresse).

## À ne pas reproduire sur GitHub (droits ou auteur inconnus)

- Léonard de Vinci ↔ **André Bauchant** (21617 ↔ 59150) : Bauchant est mort en 1958, encore protégé
  jusqu'en 2029. Très bel exemple, à citer sans l'image.
- Generalić ↔ Pemba (56448 ↔ 64261) : artistes du XXᵉ siècle, protégés.
- Paires avec une œuvre « Unknown Artist » (Titien ↔ affiche Art Nouveau 74414 ↔ 71882,
  Goya ↔ Art Nouveau 69113 ↔ 56766) : auteur et date à établir avant toute reproduction.

## Pour faire l'illustration

- Les vignettes sont dans `data/wikiart81k/thumbs/` (hors git) : composer une planche (par exemple
  3 paires, squelettes dessinés, mention du miroir) et ne mettre dans le dépôt (`docs/images/`) que
  l'image finale, avec les seules œuvres du domaine public.
- Les squelettes sont dans le run `features/vitpose_base_20261121-182701` (`poses_kpts.npy`) ;
  `pixplot/encoders/posture.py` sait les dessiner.
- Dire sous l'image ce que dit toujours PixPlot : une pose semblable est une piste, pas la preuve
  qu'un artiste a vu l'autre.
- Note : la paire 3550 ↔ 27814 est décrite par Neon comme « Dürer ↔ Picasso », mais le catalogue
  donne Corot (n° 3550) : erreur de la note, paire rejetée de toute façon.

# Feuille de route

[English](ROADMAP.md) · **Français** · Mise à jour : 16/11/2026 · Version actuelle : **0.13.3**

Ce qui est fait est dans l'[historique des versions](CHANGELOG.fr.md). Ce document dit ce
qui vient ensuite, dans quel ordre, et à quelle condition une étape est réussie.

## La règle : mesurer avant d'ajouter

PixPlot n'empile pas les modèles. Un nouveau modèle ou une nouvelle méthode n'entre dans le
projet que s'il **gagne sur un banc d'essai** (paires annotées, étiquettes, RichArt…) et
s'il apporte un signal que les regards existants n'ont pas. Sinon, le résultat négatif est
documenté et l'on n'y revient pas. Chaque étape réussie devient une version mineure.

## Prochaines étapes

### 0.11 — Groupes Leiden, emboîtés, par regard · *fait*

> **Résultat** (ARCHITECTURE § 15) : critère rempli pour la forme, le sujet et la touche (plus
> stables, aussi bons ou meilleurs sur les étiquettes), pas pour la couleur. Reste à porter les
> noms, le panneau des groupes et les étiquettes à vérifier sur Leiden avant d'en faire les
> groupes principaux de l'Atlas.

- **Pourquoi** : le nombre de groupes vient d'une règle arbitraire (k = √N / 2, soit 142
  groupes pour 80 716 œuvres) et HDBSCAN échoue sur un continuum sans vides.
- **Quoi** : communautés Leiden sur le graphe des voisines déjà calculé ; la finesse
  devient un réglage ; groupes emboîtés (groupes, puis sous-groupes au zoom dans l'Atlas) ;
  groupes pour chaque regard, pas seulement la forme.
- **Réussi si** : stable d'un calcul à l'autre (indice de Rand ajusté), et au moins aussi
  bon qu'e-means sur les étiquettes et les paires. Sinon, e-means reste.

### 0.12 — Les désaccords entre regards, et la relecture des paires · *outils faits*

> Le panneau « Désaccords », l'onglet « Paires de référence » et la relecture rapide façon Anki
> (touche R, 0.12.1) sont dans l'Atlas (ARCHITECTURE § 16 et 17). **104 paires validées** (§ 18) :
> critère atteint en nombre ; « même main » (1) et « même motif » (2) restent à étoffer. Reste le critère : la relecture des paires par l'historien.

- **Pourquoi** : le résultat le plus parlant pour un historien est souvent qu'un regard
  rapproche deux œuvres et qu'un autre les sépare. Et le banc d'essai a besoin de paires
  validées.
- **Quoi** : dans l'Atlas, un panneau « Désaccords » (œuvres proches selon la forme mais
  lointaines selon le sujet, etc.) et un panneau « Paires à relire » pour valider ou
  rejeter les paires proposées.
- **Réussi si** : les 11 paires proposées sont relues, et l'on atteint environ 100 paires
  validées couvrant les huit types, dont « même composition » et « même palette ».
  *Ce travail-là revient à l'historien.*

### 0.13 — Chercher une zone avec des mots (TIPSv2) · *mesuré, TIPSv2 non retenu*

> **Résultat** (ARCHITECTURE § 19, `pixplot zonebench`) : sur RichArt, SigLIP 2 appliqué aux zones
> découpées bat TIPSv2 (phrase : 28 % contre 20 % en première position) ; le pointage de TIPSv2
> dépasse à peine « toujours le centre » (51 %). **Index de zones SigLIP 2 fait en 0.13.3** : 1,6 million de
> zones, recherche « Zone décrite » dans l'Atlas (ARCHITECTURE § 22).

- **Pourquoi** : aujourd'hui, on compare une zone à une zone (DINOv3) ou une phrase à une
  image entière (SigLIP 2). Rien ne compare une phrase à une zone : « auréole », « main qui
  bénit », « crâne ».
- **Quoi** : pilote de [TIPSv2](https://gdm-tipsv2.github.io/) (Google DeepMind, B/14) sur
  1 000 œuvres, évalué sur [RichArt](https://huggingface.co/datasets/MihaiBogdanBindila/RichArt)
  (20 882 zones décrites, usage local seulement), puis index de zones complet s'il convainc.
- **Réussi si** : il retrouve les zones de RichArt nettement mieux que SigLIP 2 appliqué
  aux zones découpées. Licence vérifiée avant tout téléchargement.

### 0.14 — Nommer les groupes avec Iconclass

- **Pourquoi** : le lexique actuel (101 termes écrits à la main, enrichis d'après Honour et
  Fleming) est petit. [Iconclass](https://github.com/iconclass/data) est la classification
  iconographique de référence des musées, avec des libellés en français, sous licence CC0.
- **Quoi** : noms de groupes proposés à partir des notions Iconclass, avec leur code
  (par ex. « 73A5 Annonciation ») comme source vérifiable ; puis un banc d'essai de 100 à
  200 requêtes en français.
- **Réussi si** : les noms sont jugés plus justes que les actuels, sur un échantillon relu.

### 0.15 — La composition : STELLAR et PE-Spatial

- **Pourquoi** : le banc d'essai montre qu'aucun regard ne suit une filiation dès que
  l'artiste transforme son modèle (Picasso d'après El Greco ou Delacroix).
- **Quoi** : [STELLAR](https://huggingface.co/microsoft/STELLAR) (ce qui est représenté
  *et* où) comme regard « composition » ; [PE-Spatial](https://huggingface.co/facebook/PE-Spatial-B16-512)
  comme candidat pour la recherche par détail.
- **Réussi si** : il gagne sur les paires « même composition » et « filiation » validées
  à l'étape 0.12. Sinon, c'est documenté et abandonné.

## Plus tard, ou à surveiller

- **Entropie et complexité** (Sigaki, Perc et Ribeiro, PNAS 2018) : un regard « ordre et
  complexité » calculé sans GPU, et un axe possible pour la chronologie.
- **ArtEmis** (CVPR 2021) : 455 000 annotations d'émotion sur les œuvres de WikiArt ; les
  regards captent-ils l'effet ressenti ou seulement le sujet ?
- **« Pourquoi ces deux œuvres se ressemblent ? »** : montrer, dans le comparateur, quelles zones
  de l'une répondent à quelles zones de l'autre (réponse au biais perceptif décrit par Wasielewski).
- **Collection Space Navigator** (Ohm et al., 2023) : filtres multidimensionnels et export de
  sélection pour l'Atlas.

- **SAM 3** : découper précisément un motif, à la demande sur une sélection. Licence Meta à
  accepter par l'utilisateur ; compatibilité ROCm à vérifier.
- **MMArt** : apporterait titres et dates à notre WikiArt (rapprochement des images par
  empreinte visuelle). Ses descriptions sont générées par un modèle de langage : banc
  d'essai pour la recherche par texte, jamais source de noms.
- **Corpus hors d'Europe** par IIIF (Asie, Islam, Afrique), et des corpus avec lieux pour
  la vue géographique.
- **PE-Core** : seulement comme concurrent de SigLIP 2 pour le regard « sujet ».

## Écarté

- **Fusionner les classements des regards** : contraire au principe des regards séparés.
- **V-JEPA 2.1, AIMv2** : conçus pour la vidéo ou sans apport attendu sur des œuvres fixes.
- **HDBSCAN** à grande échelle : documenté comme inadapté (ARCHITECTURE § 11).

## Vers la 1.0

La 1.0 viendra quand : les commandes et les formats de fichiers seront stables ; le banc
d'essai aura au moins 100 paires validées ; l'installation aura été testée sur une machine
neuve ; et la documentation sera complète dans les deux langues.

# Compte rendu — lectures utiles et solidité du banc de paires

*Date : 22/11/2026 · Assistant : DeepSeek · Tâche : expériences et ouvrages utiles au projet*

But : dire quelles lectures changeraient quelque chose dans PixPlot v2, et lesquelles ne sont que
du décor. Rien n'a été ajouté au code ni aux dépendances.

## 1. Un résultat de méthode avant les lectures

Le banc de paires décide de garder ou d'écarter un modèle (ARCHITECTURE §§ 27–32). Il est petit.

| Catégorie annotée | Paires validées | Recherches (2 sens) | Conclusion possible ? |
|---|---|---|---|
| Même sujet | 36 | 72 | oui, pour de gros écarts |
| Même palette | 26 | 52 | oui, pour de gros écarts |
| Même facture | 16 | 32 | à la marge |
| Même composition | 14 | 28 | à la marge |
| Filiation attestée | 9 | 18 | non |
| Même motif | 2 | 4 | non |
| Même main | 1 | 2 | non |

Source : `bench/wikiart81k_pairs.csv` (105 lignes, 104 validées, 1 rejetée).

### 1.1 Intervalles de confiance, recalculés depuis les chiffres publiés

Intervalles exacts (Clopper–Pearson) sur les pourcentages de ARCHITECTURE § 27 :

| Mesure | Chiffre publié | Comptage | IC 95 % |
|---|---|---|---|
| Sujet, R@10, filiation | 38,9 % | 7/18 | 17 – 64 % |
| Forme, R@10, filiation | 38,9 % | 7/18 | 17 – 64 % |
| SSCD, R@10, filiation | 33,3 % | 6/18 | 13 – 59 % |
| Forme, R@10, même composition | 53,6 % | 15/28 | 34 – 72 % |
| SSCD, R@10, même composition | 3,6 % | 1/28 | 0 – 18 % |
| Sujet, R@10, même motif | 50,0 % | 2/4 | 7 – 93 % |

Deux lectures opposées, à séparer nettement :

- **Sujet et Forme contre SSCD sur la filiation** (38,9 % contre 33,3 %) : une recherche d'écart sur
  18, intervalles qui se recouvrent presque entièrement. Le classement des trois modèles n'est pas
  établi par ce chiffre ; ce qui le porte, c'est le **rang médian** (25 et 26 contre 216), et là
  l'écart est réel.
- **Forme contre SSCD sur « même composition »** (53,6 % contre 3,6 %) : 15 recherches contre 1,
  intervalles disjoints. Conclusion solide, elle ne bougera pas avec plus de paires.

### 1.2 Test apparié sur le rapport de banc déjà sur disque

`data/wikiart81k/bench/pairs_report_dinov3_vitb16_20261116-111508.json`, catégorie `filiation`
(20 recherches, 10 paires dont une depuis rejetée) :

| Regard | R@10 | Rang médian |
|---|---|---|
| Forme (DINOv3) | 45,0 % | 20 |
| Sujet (SigLIP 2) | 45,0 % | 17 |
| Touche (DINOv3, couche 6) | 25,0 % | 480 |
| Posture | 11,1 % (n = 18) | 4 366 |
| Couleur (CIELAB) | 0,0 % | 27 795 |

- Wilcoxon signé Forme contre Sujet : **p = 0,177**.
- 30 % des recherches donnent le **même rang** exact pour les deux regards.
- ΔR@10 = 0 point, IC 95 % **[−15 ; +15]** (bootstrap apparié, 10 000 tirages).

Conséquence : sur la filiation, Forme et Sujet sont **indépartageables**, et c'est normal — une
copie fidèle se ressemble par la forme *et* par le sujet. Le signal qui distingue vraiment les
regards est ailleurs (« même composition », « même palette »). Toute phrase du type « Forme est
meilleur que Sujet » sur la filiation est à retirer.

### 1.3 Règle proposée par défaut

1. Aucune décision de modèle sur moins de 30 recherches (15 paires).
2. Tout R@k publié avec son IC 95 %.
3. Comparer deux modèles par un test apparié sur les rangs des mêmes paires, jamais par deux
   pourcentages côte à côte.
4. Une catégorie à moins de 10 paires est une anecdote, pas un banc.

## 2. Lectures, classées par ce qu'elles changent

### 2.1 Ce que « semblable » veut dire

| Référence | Apport | Où ça sert |
|---|---|---|
| A. Tversky, *Features of similarity*, Psychological Review 84(4), 1977, p. 327–352 | La similarité n'est pas une distance : elle est asymétrique, dépend du contexte et des traits retenus. | Justifie les **regards séparés** (et interdit de comparer des cosinus entre modèles). À citer dans le Guide. |
| L. Wittgenstein, *Investigations philosophiques*, 1953, § 66–67 | « Air de famille » : un groupe se tient par un réseau de ressemblances, sans critère unique. | Formule juste pour expliquer les groupes de l'Atlas sans les présenter comme des classes. |
| E. Rosch, *Cognitive representations of semantic categories*, J. Exp. Psychol. 104, 1975 | Catégories à prototype, dégradé d'appartenance. | Pourquoi un groupe a un centre et des marges ; pourquoi une œuvre peut être « baroque » à 60 %. |

### 2.2 Lire une carte sans se raconter d'histoires

| Référence | Apport | Où ça sert |
|---|---|---|
| T. Chari & L. Pachter, *The specious art of single-cell genomics*, PLOS Comput. Biol. 19(8), 2023, e1011288 | UMAP et t-SNE créent des séparations et des densités qui ne sont pas dans les données. | Le guide de l'historien : un îlot n'est pas une école. Argument chiffré, pas une prudence de principe. |
| D. Kobak & P. Berens, *The art of using t-SNE for single-cell transcriptomics*, Nature Communications 10, 2019, 5416 | Protocole de réglage et de **mesure** de la conservation du voisinage. | Donne la forme savante du « voisines gardées 7,4 % » déjà mesuré pour UMAP/LocalMAP. |
| J. Venna & S. Kaski, *Neighborhood preservation in nonlinear projection methods*, ICANN 2001 | Métriques *trustworthiness* et *continuity*, comparables entre méthodes. | Le chiffre à mettre à côté de chaque variante de carte (UMAP, LocalMAP, cartes d'essai). |
| L. Manovich, *Cultural Analytics*, MIT Press, 2020 | Précédent et vocabulaire de l'analyse d'image à l'échelle du corpus. | Positionnement du projet, et ce qu'il ne fait pas (pas de lecture d'œuvres). |
| T. Arnold & L. Tilton, *Distant Viewing: Computational Exploration of Digital Images*, MIT Press, 2023 | Cadre méthodologique « distant viewing » : ce qu'une mesure d'image peut affirmer. | La caution à citer quand une mesure visuelle est présentée à un historien. |

### 2.3 Ce que « influence » veut dire (méthode d'histoire de l'art)

| Référence | Apport | Où ça sert |
|---|---|---|
| M. Baxandall, *Patterns of Intention: On the Historical Explanation of Pictures*, Yale UP, 1985 | L'influence est une relation à expliquer (peintre, objet, spectateur), pas une distance à mesurer. | La phrase de garde-fou du README ; et le panneau « Désaccords » : un écart n'est pas un verdict. |
| A. Warburg, *Bilderatlas Mnemosyne*, 1924–1929 (inachevé ; éd. Warnke & Brink, 2000) | L'atlas de motifs comme forme de recherche : planches d'hypothèses, pas de preuves. | Légitime « où revient ce motif » comme geste savant, et le carnet comme son équivalent. |
| H. Wölfflin, *Kunstgeschichtliche Grundbegriffe*, 1915 (trad. *Principles of Art History*, 1932) | Cinq couples d'oppositions : linéaire/pictural, plan/profondeur, forme fermée/ouverte, multiplicité/unité, clarté/non-clarté. | **Dix pôles prêts à l'emploi** pour les axes conceptuels (Impett & Offert) : testables sans GPU avec SigLIP 2 déjà installé. |
| E. Panofsky, *Iconographie et iconologie*, 1939/1955 | Sépare le pré-iconographique (ce qu'on voit) de l'iconologique (ce qu'il faut savoir). | Limite honnête des noms Iconclass proposés par un modèle : ils décrivent, ils n'interprètent pas. |
| G. Kubler, *The Shape of Time*, Yale UP, 1962 | Séries, « primes » et répliques : la temporalité des objets, non des styles. | La vue chronologique : une date par œuvre ne fait pas une chronologie. |

### 2.4 Mesurer et publier

| Référence | Apport | Où ça sert |
|---|---|---|
| M. Smucker, J. Allan, B. Carterette, *A comparison of statistical significance tests for IR evaluation*, CIKM 2007, p. 623–632 | Bootstrap apparié et randomisation sont les bons tests pour R@k ; Wilcoxon et signe sont moins fiables. | § 1.2 ci-dessus : la façon de publier chaque écart de modèle. |
| K. Krippendorff, *Content Analysis*, 4e éd., SAGE, 2019 | Alpha de Krippendorff : accord entre codeurs, avec des données manquantes. | Les 104 paires ont été relues par **une** personne : sans second passage, on ne sait pas si elles sont fiables. |
| N. Z. Da, *The computational case against computational literary studies*, Critical Inquiry 45(3), 2019 | Critique des tests de signification mal appliqués aux corpus culturels. | Confirme la règle « tester avant d'adopter », et évite le mauvais genre de test. |
| D. G. Stork, *Pixels & Paintings*, Wiley, 2024 | Déjà intégré (§ 26) : mesures visuelles sans GPU. | Sert de référence pour E1 (voir § 3). |

### 2.5 Copies, couleur, corpus

| Référence | Apport | Où ça sert |
|---|---|---|
| M. Douze et al., *The 2021 Image Similarity Dataset and Challenge*, arXiv:2106.09672, 2021 (DISC21) | Un million d'images de référence, copies transformées avec vérité terrain. | **Calibrer** les seuils 0,85 / 0,65 des doublons sur des transformations contrôlées, au lieu de les choisir à l'œil sur WikiArt. |
| G. Luo, M. R. Cui, B. Rigg, *The development of the CIE 2000 colour-difference formula*, Color Research & Application 26(5), 2001, p. 340–350 | CIEDE2000 : distance chromatique perceptuelle. | Le regard couleur et l'axe couleur : comparer en Lab, pas sur des moyennes RVB. |
| T. Gebru et al., *Datasheets for Datasets*, Communications of the ACM 64(12), 2021, p. 86–92 | Fiche de données : provenance, droits, limites, biais. | Ce qui manque à côté des fiches de modèles : une fiche de WikiArt 81k dans le Research Pack. |

## 3. Quatre expériences faisables sur ce PC

Aucune ne demande d'intervention de l'utilisateur ni de choix de sa part.

1. **Le « Pourquoi ? » explique-t-il vraiment ?** (répond au biais perceptif de Wasielewski)
   Sur les 104 paires, comparer la similarité avant/après occultation : (a) des 4 zones mises en
   avant, (b) de 4 zones tirées au hasard, (c) de 4 zones de même surface au centre. Test apparié
   sur les chutes de cosinus. *Réussi si* la chute des zones mises en avant dépasse celle du hasard
   d'un facteur 3 et p < 0,01. *Coût* : CPU, quelques minutes, DINOv3 déjà calculé.
2. **Les paires relues sont-elles fiables ?** Faire relire 30 paires tirées au sort, deux fois, à
   deux semaines d'écart, et calculer l'alpha de Krippendorff. *Réussi si* α ≥ 0,80 (à défaut
   ≥ 0,67). *Coût* : aucun calcul ; c'est du temps de relecture, et c'est le seul point qui demande
   un humain — donc à grouper avec la prochaine séance de relecture, sans nouvelle question.
3. **IC et tests appariés dans `pixplot pairs bench`.** Une fonction de 30 lignes : IC 95 % de
   chaque R@k, p apparié contre un regard de référence, et la mention du nombre de recherches.
   *Réussi si* chaque ligne du rapport porte son IC et que les tableaux des §§ 27–32 sont relus.
   *Coût* : une soirée, aucun GPU.
4. **Calibration des doublons sur DISC21.** Reprendre les seuils 0,85 / 0,65 sur des copies
   transformées (recadrage, rotation, filigrane, compression), tracer précision/rappel, garder le
   seuil qui maximise F1. *Réussi si* les seuils actuels restent à ±0,05 de l'optimum ; sinon, mise
   à jour documentée. *Coût* : téléchargement de quelques milliers d'images, CPU.

## 4. Décisions prises par défaut (à corriger si désaccord, sans nouvelle question)

1. Le banc reste à 104 paires ; l'effort d'annotation va à « même composition » (14) et « même
   palette » (26) — les porter à 40 chacune —, pas à « même main » (1) ni « même motif » (2).
2. Aucune évaluation de nouveau modèle avant l'expérience 3 : publier l'IC peut changer les
   conclusions des §§ 27–32, et il serait absurde d'empiler un modèle de plus sur des écarts non
   testés.
3. Les cinq couples de Wölfflin sont proposés comme axes conceptuels (dix pôles) : c'est du texte,
   SigLIP 2 est déjà là, aucun modèle à télécharger.
4. Aucune nouvelle dépendance : numpy et scipy du `.venv` suffisent aux expériences 1 à 3.

## 5. Ce que je n'ai pas fait, et ce qui reste

- Je n'ai **pas** relancé le banc : les IC viennent des comptages publiés et du rapport de banc du
  16/11 déjà sur disque, pas d'un nouveau calcul de rangs.
- Les expériences 1 et 2 ne sont pas codées ; l'expérience 1 demande l'accès aux zones et aux
  images déjà indexées.
- Je n'ai pas vérifié les licences des corpus DISC21 (usage recherche) : à contrôler avant tout
  téléchargement, comme pour TIPSv2.

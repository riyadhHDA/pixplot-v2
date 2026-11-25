# Banc d'essai « influence » — Compte rendu (`gemini/banc-influence`)

Date : 25/11/2026 · Agent : Gemini 4 Neon

## 1. Enquête sur WIB-100 (*M-ArtAgent*, arXiv:2604.07468)

Source consultée : *M-ArtAgent: Evidence-Based Multimodal Agent for Implicit Art Influence Discovery*, par Hanyi Liu, Zhonghao Jiu, Minghao Wang, Yuhang Xie et Heran Yang (`arXiv:2604.07468v1`, 8 avril 2026, 13 pages, soumis à *IEEE Access* ; lu en version HTML sur `arxiv.org`, aucun jeu de données téléchargé).

- **Disponibilité** : **WIB-100 n'est pas publié.** Le préprint complet ne contient aucun lien vers un dépôt de code ou de données (ni GitHub, ni Hugging Face, ni Zenodo, ni OSF, ni IEEE DataPort, ni fichiers annexes sur arXiv). Ni la liste des 100 artistes ni les 2 000 paires ne figurent dans l'article (seuls deux exemples sont nommés : *Hokusai → Van Gogh* en positif et *Dalí → Escher* en négatif difficile).
- **Licence et taille** : aucune licence n'est indiquée pour le jeu de données (seul le texte du préprint porte la licence arXiv non exclusive) ; la taille est inconnue.
- **Contenu décrit par l'article** (§ III-C, § IV-A1, Tableau V) :
  - **Des paires d'artistes** (et non des paires d'œuvres) : **100 artistes** choisis parmi les **129 artistes nommés de WikiArt** (`huggan/wikiart`), rééquilibrés en régions et époques (Impressionnisme / Post-impressionnisme ramenés de 66 % à 38 % ; Renaissance et Baroque portés de 0 % à 23 %).
  - **2 000 paires dirigées d'artistes** ($A_i \to A_j$), équilibrées 50/50 :
    - **1 000 liens positifs** : recueillis « dans la littérature d'histoire de l'art et des registres d'influence curatés », recoupés quand plusieurs sources existent (ni les registres ni les annotateurs ne sont nommés).
    - **1 000 paires négatives stratifiées**, vérifiées activement : **300 difficiles** (même époque et même mouvement, sans influence directe), **300 moyennes** (même époque, mouvements différents), **200 faciles** et **200 chronologiquement impossibles**.
- **Suite décidée par l'utilisateur** : ne pas contacter les auteurs ; construire un banc d'essai « influence entre artistes » inspiré du protocole de WIB-100 à partir de **Wikidata** (licence **CC0 1.0**, domaine public), rattaché à notre corpus WikiArt 81k.

---

## 2. Collecte Wikidata et rattachement à WikiArt 81k

- **Accès** : service SPARQL public de Wikidata (`https://query.wikidata.org/sparql`), licence **CC0 1.0**, User-Agent générique `PixPlot-v2-research/0.1 (https://riyadhhda.github.io/pixplot-v2/)` (sans nom ni adresse électronique), requêtes par lots avec pauses de 1,2 s.
- **Réponses brutes conservées hors git** dans `<données>/bench/influence/` (date : `2026-11-25`) :
  - `raw_p6002_20261125.json` (5 702 éléments Wikidata portant la propriété **`P6002` = WikiArt ID** ; vérification faite que `P6599` correspond en fait à *HCA Red List of Endangered Crafts ID* et non à WikiArt),
  - `raw_names_20261125.json` (recherche par nom + profession artistique pour les 21 artistes sans `P6002`),
  - `raw_links_20261125.json` (liens `P737` et `P1066` avec leurs références `P248`, `P854`, `P4656`, `P143`, `P813`).
- **Rattachement des 1 089 artistes connus** (œuvres `status = 'ok'`, hors `Unknown Artist` ; 999 artistes avec ≥ 5 œuvres) :
  - **1 072 rattachements sûrs (98,4 %)** : **1 068** par identifiant exact **`P6002`**, **4** par **nom + cohérence de dates** (`andrea-del-verrocchio` `Q183458`, `m.-h.-maxy` `Q983833`, `martiros-saryan` `Q718409`, `william-h.-johnson` `Q1883000`).
  - **0 ambigu** (tout cas à plusieurs QID candidats est écarté par construction).
  - **17 absents** : principalement des slugs avec initiales collées (`m.c.-escher`, `n.c.-wyeth`, `a.y.-jackson`, `r.-b.-kitaj`, `t.-c.-steele`), accents ou apostrophes (`joaquin-sorolla`, `pierre-paul-prud'hon`, `allan-d'arcangelo`, `georgia-o'keeffe`), parenthèses (`marevna-(marie-vorobieff)`) ou variante de slug (`jacob-isaakszoon-van-ruisdael`, déjà présent sous `jacob-van-ruisdael`).
- **Liens collectés entre artistes rattachés ayant ≥ 5 œuvres** (`984` artistes éligibles) :
  - **`P737` (« influencé par », source A → cible B)** : **302 liens** (0 chronologiquement impossible). Ventilation : **74** même époque (≤ 30 ans d'écart de naissance) et même style dominant, **99** même époque et autre style, **129** époque différente.
  - **`P1066` (« élève de », maître A → élève B)** : **152 liens** (0 chronologiquement impossible). Ventilation : **52** même époque et même style, **46** même époque et autre style, **54** époque différente.
  - **Références Wikidata** : **243 liens sur 454 (53,5 %)** portent au moins une référence sur Wikidata (National Gallery of Art, Musée d'Orsay, Smithsonian, Tretyakov Gallery Magazine, TheArtStory, articles Wikipédia…). Les autres (211 liens) n'ont pas de référence renseignée sur Wikidata : une affirmation Wikidata reste une donnée à sourcer, jamais une preuve.
- **Groupes témoins** (paires sans lien `P737` ni `P1066` connu dans aucun sens, ≥ 5 œuvres, 500 paires tirées par niveau, graine 0) :
  - **`difficiles`** (500) : même époque (≤ 30 ans) et même style dominant, chronologiquement possibles ;
  - **`moyens`** (500) : même époque (≤ 30 ans) et style dominant différent, chronologiquement possibles ;
  - **`faciles`** (500) : source ≥ 80 ans plus ancienne et style dominant différent ;
  - **`impossibles`** (500, **mis à part, hors mesure principale**) : source née après la mort de la cible.

---

## 3. Mesure par artistes et résultats sur les cinq regards

**Méthode (`pixplot influence`, `pixplot/analysis/influence.py`)** : pour une paire dirigée $A \to B$ dans un regard (`forme`, `sujet`, `couleur`, `touche`, `posture`), pour chaque œuvre $b$ de $B$, on classe tout le corpus hors œuvres de $B$ et hors **doublons exacts** de `doublons.json` (1 674 œuvres concernées), et l'on relève le **rang médian des œuvres de $A$** parmi les voisines de $b$. Le score de la paire est la médiane sur $b \in B$, exprimée en **centile** ($0{,}5$ = hasard, $1$ = tout en tête). Cette mesure est **invariante au nombre d'œuvres de $A$**. Pour `posture`, la mesure utilise `PostureIndex` (multi-figures + miroir) sur les 39 043 œuvres figurées (paires ayant ≥ 3 œuvres figurées de chaque côté). Les intervalles de confiance à 95 % et les écarts appariés entre regards sont calculés par bootstrap sur les paires (2 000 tirages).

### A. Tous les liens contre les trois niveaux de témoins (hors impossibles)

| Comparaison | Forme (DINOv3) | Sujet (SigLIP 2) | Couleur (CIELAB) | Touche (DINOv3 L6) | Posture (ViTPose) | Écarts appariés sûrs (IC 95 % exclut 0) |
|---|---|---|---|---|---|---|
| **`P737` (302) vs `difficiles` (500)** | **0,503** [0,465–0,541] | 0,435 [0,394–0,476] | 0,455 [0,414–0,493] | 0,483 [0,443–0,526] | 0,531 [0,483–0,578] *(277/281)* | Forme > Sujet (+0,068), Forme > Couleur (+0,049), Touche > Sujet (+0,048) |
| **`P737` (302) vs `moyens` (500)** | **0,659** [0,621–0,697] | 0,561 [0,520–0,602] | 0,525 [0,485–0,565] | 0,627 [0,590–0,665] | 0,523 [0,471–0,578] *(277/201)* | **Forme** > Sujet (+0,097), > Couleur (+0,134), > Posture (+0,187) ; Touche > Sujet (+0,066), > Couleur (+0,102), > Posture (+0,154) ; Sujet > Posture (+0,111) |
| **`P737` (302) vs `faciles` (500)** | 0,837 [0,807–0,866] | **0,906** [0,884–0,926] | 0,670 [0,633–0,705] | 0,764 [0,730–0,796] | 0,395 [0,350–0,441] *(277/286)* | **Sujet** > Forme (+0,069) > Touche (+0,073) > Couleur (+0,094) > Posture (+0,210) (tous sûrs) |
| **`P1066` (152) vs `difficiles` (500)** | 0,525 [0,466–0,577] | 0,544 [0,483–0,600] | 0,535 [0,478–0,586] | 0,494 [0,437–0,547] | **0,611** [0,551–0,666] *(132/281)* | Sujet > Touche (+0,051) seulement |
| **`P1066` (152) vs `moyens` (500)** | **0,663** [0,614–0,712] | 0,647 [0,589–0,700] | 0,602 [0,550–0,655] | 0,628 [0,576–0,676] | 0,599 [0,539–0,661] *(132/201)* | Forme > Couleur (+0,061) ; Forme, Sujet, Touche > Posture |
| **`P1066` (152) vs `faciles` (500)** | 0,828 [0,787–0,862] | **0,911** [0,884–0,936] | 0,718 [0,673–0,758] | 0,749 [0,701–0,792] | 0,493 [0,432–0,553] *(132/286)* | **Sujet** > Forme (+0,083) > Touche (+0,079) > Couleur (+0,031 n.s.) > Posture |

*(Annexe, hors mesure principale : contre les 500 témoins `impossibles`, les AUC atteignent 0,881 en `forme` et 0,896 en `sujet` pour `P737`, et 0,876 / 0,906 pour `P1066` — ce qui confirme pourquoi ils rendraient la mesure artificiellement facile.)*

### B. Contrôle essentiel : à époque et style égaux (positifs même époque + même style vs `difficiles`)

Dans le tableau A, `P737 vs difficiles` donne 0,435 en `sujet` et 0,503 en `forme` pour une raison structurelle : **75,5 % des liens `P737` traversent les styles ou les siècles** (*Hokusai → Van Gogh*, *Bosch → Goya*, *Cézanne → Picasso*), alors que 100 % des témoins `difficiles` partagent exactement la même époque et le même style. Si l'on compare **à époque et style égaux** :

| Sous-ensemble (même époque et même style) | Forme | Sujet | Couleur | Touche | Posture | Écarts appariés sûrs |
|---|---|---|---|---|---|---|
| **`P737` (74) vs `difficiles` (500)** | **0,588** [0,521–0,651] | 0,567 [0,499–0,639] | 0,565 [0,493–0,635] | 0,575 [0,509–0,639] | 0,542 [0,471–0,614] *(67/281)* | Forme, Sujet, Touche > Posture ; **aucun des 4 principaux ne bat les 3 autres** |
| **`P1066` (52) vs `difficiles` (500)** | 0,635 [0,553–0,720] | **0,727** [0,650–0,798] | 0,622 [0,527–0,713] | 0,643 [0,562–0,721] | 0,640 [0,549–0,724] *(47/281)* | **Sujet bat sûrement tous les autres regards** (+0,084 à +0,209) |

### Lecture des résultats

1. **La proximité visuelle seule ne distingue pas une influence générale (`P737`) de deux contemporains du même style.** Globalement, `P737 vs difficiles` plafonne autour du hasard (0,435 à 0,531). Même en contrôlant à époque et style égaux, l'AUC reste modeste (**0,588** en `forme`, **0,575** en `touche`), sans qu'aucun des quatre regards principaux ne l'emporte sûrement sur les autres. Cela rejoint la thèse centrale de *M-ArtAgent* : la ressemblance visuelle est un indice, jamais une preuve d'influence.
2. **La filiation d'atelier (`P1066`, « élève de ») se voit nettement mieux que l'influence diffuse (`P737`)**, surtout à époque et style égaux : **`sujet` atteint 0,727 [0,650–0,798]** et bat de façon sûre `forme`, `touche`, `couleur` et `posture`. L'élève partage plus durablement le répertoire iconographique et les genres de son maître.
3. **À travers les styles d'une même époque (`vs moyens`), `forme` (0,659) et `touche` (0,627) devancent sûrement `sujet` (0,561) et `couleur` (0,525) sur `P737`** : quand une influence franchit la frontière d'un mouvement, elle se lit davantage dans la mise en page et la facture que dans les mots du sujet.
4. **Attention à la métrique « meilleure œuvre » (`best_centile`)** : enregistrée dans le rapport JSON en complément, elle affiche des AUC beaucoup plus élevées sur `P737 vs difficiles` (0,745 en `forme`, 0,818 en `couleur`), **mais cette hausse est en grande partie un biais de taille de corpus** (les grands maîtres cités comme sources `P737` ont beaucoup plus d'œuvres dans WikiArt que les artistes moyens des témoins, ce qui abaisse mécaniquement le rang du minimum). C'est pourquoi le **rang médian** (invariant au nombre d'œuvres) reste notre mesure principale.

---

## 4. Examen à l'œil : réussites et échecs

Vérifié sur les vignettes de `data/wikiart81k/thumbs/256/` :

- **Réussites (même médium, reprise directe de cadrage ou d'école)** :
  - `edouard-cortes → antoine-blanchard` (`P737`, `forme` centile 0,998, rang médian 127) : `#7980` (*Boulevard de la Madeleine 7*) ↔ `#2143` (*Boulevard de la Madeleine 2*), rang 1, cos 0,913 — cadrage, arbre de gauche, fiacre blanc et façade de la Madeleine quasi identiques.
  - `jan-steen → pieter-de-hooch` (`P737`, `forme` 0,993, `sujet` 0,996) et `gerard-terborch → pieter-de-hooch` (`forme` 0,990, `sujet` 0,997) : intérieurs hollandais du XVIIᵉ siècle.
  - `katsushika-hokusai → hiroshige` (`P737`, `forme` 0,984, `sujet` 0,992) et la lignée `utagawa-toyokuni → utagawa-toyokuni-ii / kuniyoshi / kunisada` (`P1066`, `forme` 0,996–0,997) : même tradition ukiyo-e.
- **Échecs très instructifs (médium différent ou emprunt ponctuel noyé dans la médiane)** :
  - `katsushika-hokusai → claude-monet` (`P737`, `forme` centile **0,162**, rang médian 66 514) : l'estampe japonaise et l'huile impressionniste occupent deux régions opposées du corpus, ce qui fait échouer la médiane globale ; **pourtant**, la paire d'œuvres la plus proche retrouvée par `forme` est **`#67058` (Hokusai, *Irises and Grasshopper*) ↔ `#6527` (Monet, *Yellow Irises*, 1917)**, au **rang 3** (cos 0,646) ! Même phénomène pour `hokusai → courbet` (`forme` 0,181, mais `#75302` *Grande Vague* ↔ `#74188` *La Vague*, 1866).
  - `constantin-brancusi → amedeo-modigliani` (`P737` & `P1066`, `forme` **0,178**) : échec global parce que Brâncuși est sculpteur et Modigliani surtout peintre ; **pourtant**, la paire la plus proche est **`#75151` (Brâncuși, *Muse*, 1912) ↔ `#70965` (Modigliani, *Head*, 1912)**, deux têtes sculptées de 1912 au **rang 8** (cos 0,530).
  - `donatello → domenico-veneziano` (`P1066`, `forme` **0,107**, mais `sujet` **0,877**) : médaillon en bronze sombre (`#76484`) contre panneau peint coloré et encadré (`#45500`) — le changement de médium brise la ressemblance de `forme`, tandis que `sujet` retrouve la Vierge à l'Enfant florentine.

---

## 5. Fichiers modifiés / ajoutés et tests

- **Code** :
  - `pixplot/analysis/influence.py` : collecte Wikidata SPARQL (`P6002`, nom + dates, `P737` et `P1066` avec références), rattachement sûr/ambigu/absent, témoins stratifiés, mesure par artistes (vectorielle + `PostureIndex`, exclusion des doublons), AUC + bootstrap apparié, export CSV de relecture.
  - `pixplot/cli.py` : nouvelle commande `pixplot influence`.
- **Documentation** : `docs/COMMANDS.fr.md`, `docs/COMMANDS.md`, `docs/FORMATS.fr.md`, `docs/FORMATS.md`.
- **Tests** : `tests/test_influence.py` (rattachement, chronologie/témoins, AUC/bootstrap apparié, mesure avec doublons et export CSV sur `atlas_env`, exécution CLI hors ligne).
- **Données hors git** (`<données>/bench/influence/`) : réponses brutes datées, `artists.json`, `links.json`, `controls.json`, `relecture_p737_30.csv`, `report_dinov3_vitb16_20261116-111508.json`.

---

## 6. Limites et points à décider / relire par l'utilisateur

- **Limites** :
  1. Les liens `P737` et `P1066` de Wikidata sont inégaux et incomplets (46,5 % sans référence explicite sur Wikidata ; certains sens sont discutables, ex. `alexandre-benois → ilya-repin` où Benois est plus jeune de 26 ans) ; de vrais liens absents de Wikidata peuvent se glisser dans les témoins.
  2. La mesure par médiane globale manque les influences ponctuelles ou trans-médiums (*Hokusai → Monet*, *Brâncuși → Modigliani*) ; une mesure par « quantile supérieur contrôlé pour la taille $|W_A|$ » (par exemple sous-échantillonner à $m = 5$ œuvres de $A$) pourrait les capter sans biais de taille.
  3. 17 artistes sur 1 089 (dont Sorolla et Escher) ne sont pas rattachés automatiquement faute de `P6002` ou à cause d'accents/initiales dans le slug.
  4. Le corpus WikiArt 81k surreprésente les XIXᵉ–XXᵉ siècles et la peinture occidentale.
- **À relire / décider** :
  - **Relecture des 30 liens `P737`** : `<données>/bench/influence/relecture_p737_30.csv` (colonnes `verdict` et `note` vides, rien marqué validé). Cela permettra de mesurer la fiabilité réelle des liens `P737` de Wikidata avant d'en faire une référence stable.
  - **Éventuel contact des auteurs de WIB-100** : laissé entièrement à l'initiative de l'utilisateur.
  - **Intégration dans `ARCHITECTURE.fr.md` / `.md`** : à rédiger ou reprendre par l'intégrateur lors de la fusion de la branche `gemini/banc-influence`.

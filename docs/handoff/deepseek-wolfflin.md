# Compte rendu — les cinq couples de Wölfflin comme axes SigLIP 2

*Mesure : DeepSeek, 22/11/2026 (session multi-agent). Note rédigée par Claude d'après le résultat,
le 22/11/2026. Script et chiffres : `data/wikiart81k/bench/wolfflin/` (`wolfflin_bench.py`,
`wolfflin_result.json`), hors git.*

## Question

Wölfflin (*Principes fondamentaux de l'histoire de l'art*, 1915) oppose la Renaissance au Baroque par
cinq couples de notions : linéaire / pictural, plan / profondeur, forme fermée / ouverte,
multiplicité / unité, clarté absolue / relative. Si l'on traduit chaque couple en phrases et qu'on
projette les œuvres sur l'axe qui va d'un pôle à l'autre dans l'espace de SigLIP 2 (comme les axes
conceptuels d'Impett et Offert, ARCHITECTURE § 26), l'axe sépare-t-il les œuvres Renaissance des
œuvres baroques de WikiArt ?

## Méthode

- **Œuvres** : 2 729 « Renaissance » (Early + High Renaissance) et 4 211 « Baroque » (étiquettes de
  style WikiArt), sur les 80 716 œuvres ; vecteurs SigLIP 2 du regard « sujet ».
- **Axes** : pour chaque pôle, 3 phrases en anglais, moyennées ; score d'une œuvre = sa
  projection sur la différence des deux pôles. Aucun apprentissage.
- **Mesure** : AUC (probabilité qu'une œuvre baroque tirée au hasard soit plus « baroque » sur l'axe
  qu'une œuvre Renaissance ; 0,5 = hasard), IC 95 % par bootstrap (2 000 tirages).
- **Contrôles** : à genre égal (portrait, peinture religieuse, paysage, nu) ; peintures seules ;
  chaque phrase seule ; trois axes témoins sans rapport (« un bol de fruits », « un ciel nuageux »,
  « un cheval ») ; et l'axe qui nomme directement les styles.
- Temps : 52 s au total, sur ce PC.

## Résultats

| Couple | AUC [IC 95 %] | Peintures seules | Portrait | Peinture religieuse | Une phrase seule |
|---|---|---|---|---|---|
| **Linéaire / pictural** | **0,743** [0,731–0,755] | 0,737 | 0,768 | 0,861 | 0,67 – 0,73 |
| Plan / profondeur | 0,679 [0,666–0,691] | 0,676 | 0,673 | 0,735 | **0,40** – 0,74 |
| Clarté / non-clarté | 0,629 [0,615–0,642] | 0,637 | 0,678 | 0,740 | **0,47** – 0,74 |
| Multiplicité / unité | 0,619 [0,605–0,633] | 0,623 | 0,746 | 0,735 | 0,57 – 0,61 |
| Forme fermée / ouverte | 0,613 [0,599–0,626] | 0,634 | **0,463** | 0,590 | 0,50 – 0,64 |
| *Témoin : un bol de fruits* | *0,417* | | *0,428* | *0,387* | |
| *Témoin : un ciel nuageux* | *0,542* | | *0,484* | *0,633* | |
| *Témoin : un cheval* | *0,456* | | *0,256* | *0,423* | |
| *Nommer le style* (« Baroque » / « Renaissance ») | *0,986* | | *0,987* | *0,987* | |

**Lecture.**
- **Le bruit est plus grand qu'il n'y paraît.** Des axes sans aucun rapport s'écartent déjà du hasard
  de 0,04 à 0,08 sur tout le corpus, et jusqu'à 0,24 à genre égal (« un cheval » sur les
  portraits : 0,256). Un écart de cet ordre ne prouve rien : les deux styles diffèrent par
  beaucoup de choses (sujets, supports, état des reproductions).
- **Seul linéaire / pictural tient** : nettement au-dessus des témoins sur tout le corpus (+0,24),
  dans le bon sens dans chaque genre, en peintures seules, et quelle que soit la phrase choisie.
- **Les quatre autres couples ne tiennent pas** : une phrase de « plan / profondeur » donne 0,40,
  une phrase de « clarté » 0,47 (le sens s'inverse ou disparaît selon les mots) ; « forme fermée /
  ouverte » s'inverse sur les portraits (0,46) et s'effondre sur les nus.
- **Nommer le style fait bien mieux (0,986)** : le modèle sait ce qu'est « une peinture baroque »,
  mais ce savoir ne passe pas par les concepts de Wölfflin, sauf en partie le premier.
- **Ce que l'axe linéaire / pictural lit vraiment.** Sur tout le corpus, il range les styles dans
  l'ordre attendu (Renaissance du Nord −0,90, Renaissance −0,55 / −0,45, Baroque +0,33, Rococo +0,54,
  Impressionnisme +0,80, score moyen centré-réduit), mais le Minimalisme va au pôle « linéaire »
  (−1,16) et l'Expressionnisme abstrait au pôle « pictural » (+0,84). Ses extrêmes sont des œuvres
  modernes : il oppose surtout **une surface nette ou graphique à une peinture à touche visible**,
  plus que la vision de Wölfflin. Les extrêmes sont aussi pollués par des reproductions encadrées
  ou légendées (voir la notion n° 88, ARCHITECTURE § 37).

## Limites

- Les étiquettes de style de WikiArt sont des étiquettes de bénévoles ; « Renaissance » réunit ici
  Early et High Renaissance, sans la Renaissance du Nord.
- Les phrases sont en anglais, écrites une fois, sans relecture par un historien.
- Une AUC dit qu'un axe *sépare* deux groupes, pas qu'il mesure la notion de Wölfflin.
- Les AUC par genre sur peu d'œuvres (paysage : 7 Renaissance ; nu : 54 œuvres) ne valent rien.

## Proposition (à décider par l'utilisateur)

- **Ne rien ajouter au code pour l'instant.** La vue « Axes conceptuels (2 mots) » de l'Atlas
  permet déjà d'essayer linéaire / pictural avec ses propres mots.
- Si l'on veut aller plus loin : proposer « linéaire / pictural » comme **axe d'essai préréglé** dans
  cette vue, avec la mise en garde ci-dessus (touche visible contre surface nette, pas la vision de
  Wölfflin), et ne pas proposer les quatre autres couples.
- Si ce résultat est publié, en faire une section d'ARCHITECTURE (après la fusion du § 39 de Neon,
  pour éviter les conflits).

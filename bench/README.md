# Paires de référence · Reference pairs

**Français**

`wikiart81k_pairs.csv` : les paires d'œuvres annotées par Riyadh HADJBA pour le banc d'essai
de PixPlot v2 (`pixplot pairs bench`), sur le corpus WikiArt de 80 716 œuvres
([huggan/wikiart](https://huggingface.co/datasets/huggan/wikiart)). Chaque ligne : les deux
œuvres (`a`, `b`), la sorte de ressemblance (`type`), le statut (validée / rejetée), la source
(page de Honour et Fleming, filiation connue, ou relecture d'un désaccord entre regards), une
note, et les étiquettes WikiArt des deux œuvres (artiste · style · genre) pour les retrouver.

`wikiart81k_review_log.csv` : les candidates écartées pendant la relecture (« pas de lien »).

Les numéros d'œuvres sont ceux du catalogue local de PixPlot, attribués à l'ingestion : ils ne
désignent les mêmes œuvres que pour une ingestion du même jeu de données dans le même ordre.
Aucune image n'est stockée ici. Résultats : ARCHITECTURE.fr.md § 18.

Pour s'en servir : copier le fichier vers `<données>/bench/pairs.csv` (seules les colonnes
`a, b, type, status, source, note` sont lues ; les autres sont ignorées).

`wikiart81k_pairs_travail.csv` : copie exacte du fichier de travail (`<données>/bench/pairs.csv`),
toutes les paires, proposées comprises, écrite par `pixplot sauvegarde`. En cas de perte du
dossier de données, la recopier telle quelle vers `<données>/bench/pairs.csv`.

**English**

`wikiart81k_pairs.csv`: the pairs of works annotated by Riyadh HADJBA for the PixPlot v2
benchmark (`pixplot pairs bench`), on the 80,716-work WikiArt corpus. Each row: the two works,
the kind of resemblance, the status (validated / rejected), the source (a page of Honour and
Fleming, a known filiation, or the review of a disagreement between ways of seeing), a note,
and the WikiArt labels of both works (artist · style · genre). `wikiart81k_review_log.csv`:
candidates dismissed during review ("no link"). Artwork numbers are those of PixPlot's local
catalogue, assigned at ingestion. No image is stored here. Results: ARCHITECTURE.md § 18.
`wikiart81k_pairs_travail.csv`: exact copy of the working file (`<data>/bench/pairs.csv`), every
pair including proposed ones, written by `pixplot sauvegarde`; if the data folder is lost, copy it
back as is to `<data>/bench/pairs.csv`.

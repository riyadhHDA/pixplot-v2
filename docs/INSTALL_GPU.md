# Installer le calcul GPU (RX 7900 GRE, Windows 11 + WSL2)

Objectif : que `pixplot doctor` affiche le GPU, puis lancer DINOv3 sur 1 000 images.

> Les commandes exactes d'AMD changent d'une version de ROCm à l'autre. **Suivez la
> documentation officielle** (rocm.docs.amd.com → *Radeon* → *Install on WSL*) pour le
> pilote et ROCm ; ce guide ne fait que l'encadrer et dire quoi vérifier.

## 0. Sans GPU, tout de suite

Le pipeline complet se teste déjà sur n'importe quel PC, avec l'encodeur de couleurs :

```bash
pixplot ingest "D:/MesImages"
pixplot embed --encoder colorhist
pixplot similar 1 --html planche.html
```

## 1. WSL2 + Ubuntu 24.04

PowerShell (administrateur) :

```powershell
wsl --install -d Ubuntu-24.04
```

Avec 16 Go de RAM, limitez WSL dans `C:\Users\<vous>\.wslconfig` :

```ini
[wsl2]
memory=9GB
swap=16GB
```

puis `wsl --shutdown`.

## 2. Pilote AMD + ROCm pour WSL

1. Installer le pilote Adrenalin récent côté Windows.
2. Dans Ubuntu, installer ROCm pour WSL **selon la page officielle AMD**.
3. Vérifier : `rocminfo | grep gfx` doit afficher **gfx1100**.

## 3. Projet et PyTorch ROCm

```bash
git clone https://github.com/riyadhHDA/pixplot-v2.git ~/pixplot-v2
cd ~/pixplot-v2
python3.12 -m venv .venv && source .venv/bin/activate
pip install -U pip
```

Installer **les roues PyTorch/torchvision fournies par AMD** pour votre version de ROCm
(page *Install PyTorch for Radeon* de la doc AMD, section WSL — elle inclut une étape
spécifique à WSL sur la bibliothèque `libhsa-runtime64`). Puis :

```bash
pip install -e ".[dev,ml]"
pixplot doctor        # doit afficher le GPU et « Calcul GPU ok »
```

**Si `doctor` échoue, on s'arrête là et on corrige avant d'aller plus loin.**
Solutions de secours si ROCm sous WSL ne veut rien savoir : ONNX Runtime + DirectML
sous Windows (à ajouter), ou le CPU (lent mais fonctionnel pour 1 000 images).

## 4. DINOv3 (via Hugging Face)

1. Sur https://huggingface.co/facebook/dinov3-vitb16-pretrain-lvd1689m, accepter la
   licence de Meta. **La demande est validée manuellement par Meta** : attendre que la
   page indique que l'accès est accordé. Chaque taille (S, B, L) a sa propre demande.
2. Se connecter depuis Ubuntu (jeton « read » créé dans les réglages Hugging Face) :

```bash
hf auth login
```

Les poids (~340 Mo pour le ViT-B) se téléchargent automatiquement au premier `embed`,
dans le cache Hugging Face (`~/.cache/huggingface`), jamais dans le dépôt.

**Secours, format Meta :** cloner `facebook/dinov3` dans `vendor/dinov3`, télécharger le
fichier `.pth` et passer `--weights weights/dinov3_vitb16.pth` à `pixplot embed`.
`vendor/` et `weights/` sont exclus de git : les poids ne doivent jamais être publiés.

## 5. Premier essai : 1 000 images

Conseil performance : sous WSL, lire des images sur `/mnt/c` ou `/mnt/d` est lent.
Pour de gros corpus, copiez-les dans le système de fichiers Linux (`~/corpus`), et gardez
le dossier `data/` côté Linux aussi (SQLite y est plus fiable).

```bash
pixplot ingest ~/corpus
pixplot embed --limit 1000 --batch-size 16
pixplot similar 1 --html planche.html
pixplot status
```

Notez dans le résultat de `embed` : **images/s** et **VRAM maximale**. Ce sont les
chiffres qui permettent d'estimer le temps pour 100 000 à 500 000 œuvres.

Si la mémoire GPU déborde : `--batch-size 8`, ou `--input-size 224`.
Un `embed` interrompu (Ctrl+C, plantage) reprend là où il s'était arrêté.

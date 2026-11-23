# Installer le calcul GPU (RX 7900 GRE, Windows 11)

[English](INSTALL_GPU.md) · **Français**

Objectif : que `pixplot doctor` affiche le GPU, puis calculer les vecteurs de 1 000 images.

**Ordre recommandé :**
1. **Windows natif** (ce guide) : AMD prend désormais en charge PyTorch sous Windows 11
   pour les Radeon RX 7000 (puce gfx1100, dont la 7900 GRE).
2. **WSL2** en secours si la carte n'est pas reconnue (section 7).
3. **CPU** en dernier recours (lent mais fonctionnel).

> Les commandes exactes d'AMD changent d'une version de ROCm à l'autre. **Suivez la
> documentation officielle** (rocm.docs.amd.com → *Radeon* → *Install PyTorch on
> Windows*) pour le pilote et les roues PyTorch ; ce guide l'encadre et dit quoi vérifier.

## 0. Sans GPU, tout de suite

Le pipeline complet se teste déjà, avec l'encodeur de couleurs :

```powershell
pixplot ingest "D:\MesImages"
pixplot embed --encoder colorhist
pixplot similar 1 --html planche.html
```

## 1. Pilote AMD

Installer le pilote Adrenalin récent **dans la version demandée par la page PyTorch
pour Windows d'AMD** (elle impose souvent une version minimale).

## 2. Environnement Python du projet (Python 3.12)

Dans PowerShell, à la racine du projet :

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -U pip
```

## 3. PyTorch ROCm pour Windows — AVANT le reste

Installer **les roues PyTorch fournies par AMD pour Windows** (page officielle ci-dessus),
dans le `.venv` activé. Les installer en premier évite que pip installe à la place la
version CPU de PyTorch. Exemple utilisé pour ce projet (ROCm 10.1, gfx1100) :

```powershell
pip install --index-url https://stable.repo.amd.com/rocm/whl-next/ "torch[device-gfx1100]==2.14.0+rocm10.1.0" "torchvision[device-gfx1100]==0.29.0a0+rocm10.1.0"
```

Puis le projet :

```powershell
pip install -e ".[dev,ml]"
pixplot doctor
```

`doctor` doit afficher la 7900 GRE et « Calcul GPU ok ». Vérifiez aussi que la ligne
PyTorch mentionne ROCm/HIP : si elle dit « non », c'est la version CPU qui a été installée.

**Si `doctor` échoue, on s'arrête là et on corrige avant d'aller plus loin.**

## 4. Les modèles

| Modèle | Accès | Commande |
|---|---|---|
| **DINOv2** ViT-B/14 (registres) | libre, Apache 2.0 | `--encoder dinov2_vitb14_reg` |
| **DINOv3** ViT-B/16 (principal) | licence Meta, **validée à la main** | `--encoder dinov3_vitb16` (défaut) |

Les poids se téléchargent tout seuls au premier `embed`, dans le cache Hugging Face
(`%USERPROFILE%\.cache\huggingface`), jamais dans le dépôt.

Pour DINOv3 :
1. Sur https://huggingface.co/facebook/dinov3-vitb16-pretrain-lvd1689m, accepter la
   licence, puis **attendre la validation de Meta** (e-mail de Hugging Face).
   Chaque taille (S, B, L) a sa propre demande.
2. Se connecter (jeton « read » créé dans les réglages Hugging Face) :

```powershell
hf auth login
```

**Secours, format Meta :** le README du dépôt `facebookresearch/dinov3` renvoie vers un
formulaire de Meta qui envoie des liens `.pth` par e-mail. Cloner le dépôt dans
`vendor\dinov3`, placer le fichier dans `weights\`, puis
`pixplot embed --weights weights\dinov3_vitb16.pth`. `vendor/` et `weights/` sont exclus de
git : les poids ne doivent jamais être publiés.

## 5. Premier essai : 1 000 images

Gardez de préférence les images et le dossier `data\` sur un SSD.

```powershell
pixplot ingest "D:\MesImages"
pixplot embed --limit 1000 --batch-size 16
pixplot similar 1 --html planche.html
pixplot status
```

Notez dans le résultat de `embed` : **images/s** et **VRAM maximale**. Ce sont les
chiffres qui permettent d'estimer le temps pour 100 000 à 500 000 œuvres (sur la RX 7900 GRE :
DINOv3 B/16 à 448 px ≈ 97 images/s, SigLIP 2 ≈ 73 images/s).

Si la mémoire GPU déborde : `--batch-size 8`, ou `--input-size 224`.
Un `embed` interrompu (Ctrl+C, plantage) reprend là où il s'était arrêté.

## 6. Résolution : 448 ou 224 ?

Par défaut, les œuvres sont analysées à 448 px (meilleurs détails), ce qui coûte environ
2,5 fois plus de temps qu'à 224 px. Sur WikiArt, le banc d'essai donne +3 points sur l'artiste
à 448 px. Pour le vérifier sur votre propre corpus : `pixplot bench`.

## 7. Secours : WSL2

Si la carte n'est pas reconnue sous Windows :

1. `wsl --install -d Ubuntu-24.04` (PowerShell administrateur).
2. Avec 16 Go de RAM, limiter WSL dans `C:\Users\<vous>\.wslconfig` :
   ```ini
   [wsl2]
   memory=9GB
   swap=16GB
   ```
   puis `wsl --shutdown`.
3. Installer ROCm pour WSL et les roues PyTorch d'AMD **selon la doc AMD, section WSL**
   (elle inclut une étape propre à WSL sur la bibliothèque `libhsa-runtime64`).
   Vérifier `rocminfo | grep gfx` → **gfx1100**.
4. Cloner le projet côté Linux (`~/pixplot-v2`), créer le venv, `pip install -e ".[dev,ml]"`,
   `pixplot doctor`.
5. Sous WSL, lire des images sur `/mnt/c` ou `/mnt/d` est lent : copier le corpus et
   garder `data/` dans le système de fichiers Linux.

Dernier recours : le CPU, avec `--input-size 224`.

# Setting up GPU computation (RX 7900 GRE, Windows 11)

**English** · [Français](INSTALL_GPU.fr.md)

Goal: `pixplot doctor` shows the GPU, then embeddings are computed for 1,000 images.

**Recommended order:**
1. **Native Windows** (this guide): AMD now supports PyTorch on Windows 11 for Radeon
   RX 7000 cards (gfx1100 chip, including the 7900 GRE).
2. **WSL2** as a fallback if the card is not recognised (section 7).
3. **CPU** as a last resort (slow but works).

> AMD's exact commands change from one ROCm release to the next. **Follow the official
> documentation** (rocm.docs.amd.com → *Radeon* → *Install PyTorch on Windows*) for the
> driver and the PyTorch wheels; this guide frames it and says what to check.

## 0. Without a GPU, right away

The whole pipeline can already be tested with the colour encoder:

```powershell
pixplot ingest "D:\MyImages"
pixplot embed --encoder colorhist
pixplot similar 1 --html sheet.html
```

## 1. AMD driver

Install a recent Adrenalin driver **in the version required by AMD's PyTorch-for-Windows
page** (it often sets a minimum version).

## 2. The project's Python environment (Python 3.12)

In PowerShell, at the root of the project:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -U pip
```

## 3. PyTorch ROCm for Windows — BEFORE anything else

Install **the PyTorch wheels provided by AMD for Windows** (official page above) into the
activated `.venv`. Installing them first prevents pip from installing the CPU build of
PyTorch instead. Example used for this project (ROCm 10.1, gfx1100):

```powershell
pip install --index-url https://stable.repo.amd.com/rocm/whl-next/ "torch[device-gfx1100]==2.14.0+rocm10.1.0" "torchvision[device-gfx1100]==0.29.0a0+rocm10.1.0"
```

Then the project:

```powershell
pip install -e ".[dev,ml]"
pixplot doctor
```

`doctor` must show the 7900 GRE and "Calcul GPU ok". Also check that the PyTorch line
mentions ROCm/HIP: if it says "non" (no), the CPU build was installed.

**If `doctor` fails, stop there and fix it before going further.**

## 4. The models

| Model | Access | Command |
|---|---|---|
| **DINOv3** ViT-B/16 (main, "form") | Meta licence, **approved by hand** | `--encoder dinov3_vitb16` (default) |
| **DINOv3** "touch" space | same weights | `--encoder dinov3_vitb16_texture` |
| **SigLIP 2** So400m ("subject", text search) | open, Apache 2.0 | `--encoder siglip2_so400m` |
| Colour space (CIELAB) | no model, no GPU | `--encoder color_lab` |
| **DINOv2** ViT-B/14 (registers) | open, Apache 2.0 | `--encoder dinov2_vitb14_reg` |

The weights are downloaded automatically at the first `embed`, into the Hugging Face cache
(`%USERPROFILE%\.cache\huggingface`), never into the repository.

For DINOv3:
1. On https://huggingface.co/facebook/dinov3-vitb16-pretrain-lvd1689m, accept the licence,
   then **wait for Meta's approval** (email from Hugging Face). Each size (S, B, L) has its
   own request.
2. Log in (a "read" token created in your Hugging Face settings):

```powershell
hf auth login
```

**Fallback, Meta format:** the README of the `facebookresearch/dinov3` repository points to
a Meta form that emails `.pth` links. Clone the repository into `vendor\dinov3`, put the
file in `weights\`, then `pixplot embed --weights weights\dinov3_vitb16.pth`. `vendor/` and
`weights/` are excluded from git: the weights must never be published.

## 5. First trial: 1,000 images

Keep the images and the `data\` folder on an SSD if possible.

```powershell
pixplot ingest "D:\MyImages"
pixplot embed --limit 1000 --batch-size 16
pixplot similar 1 --html sheet.html
pixplot status
```

Note from the `embed` output: **images/s** and **peak VRAM**. These are the figures that
let you estimate the time for 100,000 to 500,000 works (on the RX 7900 GRE: DINOv3 B/16
at 448 px ≈ 97 img/s, SigLIP 2 ≈ 73 img/s).

If GPU memory overflows: `--batch-size 8`, or `--input-size 224`.
An interrupted `embed` (Ctrl+C, crash) resumes where it stopped.

## 6. Resolution: 448 or 224?

By default, works are analysed at 448 px (better details), which takes about 2.5 times
longer than 224 px. On WikiArt, the benchmark gives +3 points on artist at 448 px. To check
on your own corpus: `pixplot bench`.

## 7. Fallback: WSL2

If the card is not recognised on Windows:

1. `wsl --install -d Ubuntu-24.04` (administrator PowerShell).
2. With 16 GB of RAM, limit WSL in `C:\Users\<you>\.wslconfig`:
   ```ini
   [wsl2]
   memory=9GB
   swap=16GB
   ```
   then `wsl --shutdown`.
3. Install ROCm for WSL and AMD's PyTorch wheels **following AMD's documentation, WSL
   section** (it includes a WSL-specific step about the `libhsa-runtime64` library).
   Check `rocminfo | grep gfx` → **gfx1100**.
4. Clone the project on the Linux side (`~/pixplot-v2`), create the venv,
   `pip install -e ".[dev,ml]"`, `pixplot doctor`.
5. Under WSL, reading images from `/mnt/c` or `/mnt/d` is slow: copy the corpus and keep
   `data/` in the Linux file system.

Last resort: the CPU, with `--input-size 224`.

"""Espaces de ressemblance : un même corpus vu par plusieurs « regards ».

Chaque run ``features`` terminé est un espace : DINOv3 (forme, composition), SigLIP 2
(sujet et style, tels qu'on les décrit avec des mots), couleur (palette), touche
(texture de la surface peinte). Les voisines d'une œuvre changent selon l'espace : c'est
voulu, chacun répond à une question différente.

Les vecteurs restent sur disque (memmap) ; un espace n'est ouvert qu'à sa première
utilisation.
"""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

from ..analysis.critique import card
from ..features.extract import OK
from ..features.store import FeatureStore
from ..index.faiss_index import GlobalIndex, find_index_for
from ..runs import Run, list_runs

# (préfixe d'encodeur, nom court, libellé, ce que l'espace « regarde »)
KINDS = [
    ("_texture", "touche", "Touche",
     "texture de la surface : facture, trait, grain — indépendamment du sujet"),
    ("color_lab", "couleur", "Couleur", "palette : proportions des teintes, clartés et saturations"),
    ("colorhist", "couleur_rvb", "Couleur (RVB)", "palette approximative (encodeur de test)"),
    ("siglip2", "sujet", "Sujet et style (SigLIP 2)",
     "ce que l'on décrirait avec des mots : sujet, genre, école, manière"),
    ("dinov3", "forme", "Forme et composition (DINOv3)",
     "ressemblance visuelle : formes, composition, motifs"),
    ("pe_spatial", "composition", "Composition (PE-Spatial)",
     "ce qui est représenté et où : la disposition des formes dans l'œuvre (en essai)"),
    ("sscd", "copie", "Copie (SSCD)",
     "empreinte de détection de copies : répliques, gravures d'après, reprises proches (en essai)"),
    ("depth_anything", "profondeur", "Profondeur (Depth Anything V2)",
     "agencement des plans en profondeur (premier plan, fond) sur une grille 8 × 8 (en essai)"),
    ("pe_core", "sujet_pe", "Sujet (PE-Core)",
     "ce que l'on décrirait avec des mots : sujet, genre, école, manière (PE-Core, en essai)"),
    ("csd", "touche_csd", "Style / touche (CSD)",
     "descripteur contrastif de style (CSD ViT-L/14, entraîné sur LAION-Styles, en essai)"),
    ("vitpose", "posture", "Posture (ViTPose)",
     "formules gestuelles et postures des figures (squelette 50 d avec miroir gauche-droite, en essai)"),
    ("dinov2", "forme_v2", "Forme (DINOv2)", "ancien modèle, pour comparaison"),
]
# Modèles évalués mais non retenus comme regards : leurs vecteurs restent sur le disque pour
# les bancs d'essai, mais l'Atlas et le serveur MCP ne les proposent pas (ARCHITECTURE § 24).
NOT_KEPT = ("pe_spatial", "sscd", "depth_anything", "pe_core", "csd", "vitpose")
ORDER = ["forme", "sujet", "couleur", "touche", "composition", "profondeur", "posture", "copie",
         "sujet_pe", "touche_csd", "forme_v2", "couleur_rvb"]


def describe_encoder(encoder: str) -> tuple[str, str, str]:
    for prefix, key, label, about in KINDS:
        if encoder.startswith(prefix) or (prefix.startswith("_") and encoder.endswith(prefix)):
            return key, label, about
    return encoder, encoder, ""


class Spaces:
    include_not_kept = False   # True pour les bancs d'essai (``pixplot composition``)

    def __init__(self, data):
        self.data = data
        self._lock = threading.Lock()
        self._stores: dict[str, FeatureStore] = {}
        self._indexes: dict[str, GlobalIndex | None] = {}
        self._rows: dict[str, dict[int, int]] = {}
        self.runs = self._discover()

    def _discover(self) -> dict[str, Run]:
        """Le dernier run complet de chaque espace ; celui de l'analyse est prioritaire."""
        out: dict[str, Run] = {}
        for run in list_runs("features", runs_dir=self.data.settings.runs_dir):
            if run.manifest.get("status") != "complete" or run.manifest["params"].get("limit"):
                continue
            if str(run.manifest["params"].get("encoder", "")).startswith(NOT_KEPT) and not self.include_not_kept:
                continue
            key = describe_encoder(run.manifest["params"].get("encoder", run.manifest["name"]))[0]
            out[key] = run
        main = describe_encoder(self.data.features.manifest["params"].get("encoder", ""))[0]
        out[main] = self.data.features
        return out

    @property
    def main(self) -> str:
        return describe_encoder(self.data.features.manifest["params"].get("encoder", ""))[0]

    def list(self) -> list[dict]:
        order = {k: n for n, k in enumerate(ORDER)}
        out = []
        for key, run in sorted(self.runs.items(), key=lambda kv: order.get(kv[0], 99)):
            enc = run.manifest["params"].get("encoder", "")
            _, label, about = describe_encoder(enc)
            out.append({"key": key, "label": label, "about": about, "encoder": enc,
                        "features": run.id, "main": key == self.main, "card": card(key)})
        return out

    # ------------------------------------------------------------------ accès
    def _open(self, key: str) -> FeatureStore:
        if key not in self.runs:
            raise KeyError(f"Espace inconnu : {key} (disponibles : {', '.join(self.runs)})")
        with self._lock:
            if key not in self._stores:
                run = self.runs[key]
                store = FeatureStore.open(run)
                self._stores[key] = store
                p_cnt = Path(run.path) / "poses_count.npy"
                if p_cnt.exists():
                    cnt = np.load(p_cnt, mmap_mode="r")
                    self._rows[key] = {int(i): r for r, i in enumerate(store.ids) if store.status[r] == OK and cnt[r] > 0}
                else:
                    self._rows[key] = {int(i): r for r, i in enumerate(store.ids) if store.status[r] == OK}
                idx = find_index_for(run, runs_dir=self.data.settings.runs_dir)
                self._indexes[key] = GlobalIndex.open(idx) if idx else None
        return self._stores[key]

    def vectors(self, key: str, ids: list[int]) -> np.ndarray:
        store = self._open(key)
        rows = self._rows[key]
        out = np.zeros((len(ids), store.global_vectors.shape[1]), dtype=np.float32)
        for n, i in enumerate(ids):
            if i in rows:
                v = store.global_vectors[rows[i]].astype(np.float32)
                out[n] = v / max(float(np.linalg.norm(v)), 1e-12)
        return out

    def region_spaces(self) -> list[str]:
        """Regards qui gardent des vecteurs par zone (``regions.npy``) : ceux où l'on peut montrer
        quelles zones de deux œuvres se répondent."""
        return [k for k, run in self.runs.items() if (Path(run.path) / "regions.npy").exists()]

    def regions(self, key: str, artwork_id: int):
        """Vecteurs par zone d'une œuvre (R, D), grilles et patchs par côté du run, ou None."""
        self._open(key)
        run = self.runs[key]
        p = Path(run.path) / "regions.npy"
        if not p.exists() or artwork_id not in self._rows[key]:
            return None
        R = np.load(p, mmap_mode="r")
        grids = tuple(run.manifest["params"].get("region_grids") or (1, 2, 4))
        from ..index.regions import patches_per_side
        return (np.asarray(R[self._rows[key][artwork_id]], dtype=np.float32), grids,
                patches_per_side(run.manifest["params"]))

    def neighbors(self, key: str, artwork_id: int, k: int = 20) -> list[tuple[int, float]]:
        """Les ``k`` plus proches voisines dans cet espace, limitées aux œuvres de l'analyse."""
        store = self._open(key)
        if artwork_id not in self._rows[key]:
            return []
        q = self.vectors(key, [artwork_id])[0]
        index = self._indexes[key]
        want = k + 10
        if index is not None:
            found, scores = index.search(q, k=want)
            pairs = list(zip(found[0].tolist(), scores[0].tolist()))
        else:
            pairs = store.search(q, k=want, exclude_row=self._rows[key][artwork_id])
        allowed = self.data.row_of
        return [(int(i), float(s)) for i, s in pairs if i >= 0 and i != artwork_id and i in allowed][:k]

    def pairwise(self, ids: list[int]) -> dict[str, list[list[float | None]]]:
        """Similarité cosinus entre les œuvres données, dans chaque espace (None si absente)."""
        out = {}
        for key in self.runs:
            self._open(key)
            V = self.vectors(key, ids)
            present = np.array([i in self._rows[key] for i in ids])
            S = V @ V.T
            out[key] = [[round(float(S[a, b]), 4) if present[a] and present[b] else None for b in range(len(ids))]
                        for a in range(len(ids))]
        return out

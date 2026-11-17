// Décodage des vignettes hors du fil principal de l'Atlas.
// Reçoit un lot : { job, url, dims: [[largeur, hauteur], …] } ; télécharge les vignettes en une
// requête (/api/thumbs/…, fichiers bout à bout, tailles dans l'en-tête X-Lengths), les décode
// et les met directement à la taille de leur case, puis renvoie les images (transférées, sans
// copie). Une vignette absente revient à null.
self.onmessage = async (e) => {
  const { job, url, dims } = e.data;
  try {
    const r = await fetch(url);
    if (!r.ok) throw new Error(String(r.status));
    const lengths = (r.headers.get("X-Lengths") || "").split(",").map(Number);
    const buf = await r.arrayBuffer();
    let at = 0;
    const images = await Promise.all(lengths.map((n, k) => {
      const part = buf.slice(at, at + n);
      at += n;
      if (!n) return null;
      const [w, h] = dims[k];
      return createImageBitmap(new Blob([part], { type: "image/webp" }),
        { resizeWidth: w, resizeHeight: h, resizeQuality: "high" }).catch(() => null);
    }));
    self.postMessage({ job, images }, images.filter(Boolean));
  } catch (err) {
    self.postMessage({ job, images: null, error: String(err) });
  }
};

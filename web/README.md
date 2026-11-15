# Atlas (interface web)

Carte interactive du corpus, servie par `pixplot serve` sur http://127.0.0.1:8765.

- `index.html`, `atlas.css`, `atlas.js` : l'interface, en JavaScript simple, sans compilation.
- `vendor/deck.gl-9.4.1.min.js` : deck.gl (licence MIT), rangé ici pour fonctionner hors ligne.

L'interface ne lit que l'API (`/api/...`, voir `pixplot/api/app.py`) ; elle n'accède jamais
directement aux fichiers. Pour la modifier : éditer les fichiers puis recharger la page.

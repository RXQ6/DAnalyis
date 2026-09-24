# Brand asset entry

`mark.svg` is the single source for the in-app mark and the derived Windows
`icon.ico`. The current geometric mark is a **working placeholder**, not an
approved final brand identity. Replace it with the reviewed vector artwork and
run `desktop/scripts/build-brand-icon.py` before a future release.

The Renderer copies the SVG and ICO from this directory; BrowserWindow and
electron-builder both use the derived ICO. Do not add separate ad hoc logo
copies or treat a generated placeholder as final artwork.

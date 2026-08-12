# Third-party notices

This project is licensed under **AGPL-3.0** (see `LICENSE`). It orchestrates and, at
install time, downloads the following third-party components. None of their source is
vendored into this repository except where noted; the managed installer
(`scripts/bootstrap.py`) fetches pinned versions onto the user's machine.

| Component | Version / pin | License | Role |
|---|---|---|---|
| PDFMathTranslate (pdf2zh) | 1.9.11, commit `44c4d5b332705797c1df17fadde2022e7c49f5de` | AGPL-3.0 | Translation engine, installed into the managed runtime from the pinned GitHub archive |
| BabelDOC | 0.2.33 | AGPL-3.0 | Document translation library used by pdf2zh |
| PyMuPDF (fitz) | 1.25.2 | AGPL-3.0 (dual-licensed; commercial licenses available from Artifex) | PDF parsing/rendering, imported directly by this project's scripts |
| PaddlePaddle | 3.3.1 | Apache-2.0 | OCR runtime (optional, installed on demand) |
| PaddleOCR | 3.7.0 | Apache-2.0 | OCR pipeline (PP-OCRv5 mobile models, English) |
| PaddleX | 3.7.2 | Apache-2.0 | OCR pipeline dependency |
| pdf.js (pdfjs-dist) | 6.1.200 | Apache-2.0 | **Vendored** browser-side PDF rendering for the local workbench; file identity and hashes recorded in `references/frontend-runtime-lock.json` |
| tencentcloud-sdk-python-tmt / -common | 3.0.1000 | Apache-2.0 | Transitive import dependency of pdf2zh's translator module (not used for translation by this project) |
| Python (python-build-standalone via uv) | 3.12 | PSF-2.0 and component licenses | Managed interpreter, installed per-user |
| Source Han Serif CN / Go Noto fonts | prefetched by installer | OFL-1.1 | CJK rendering fonts, downloaded to the user cache |

Exact pins and asset hashes: `references/runtime-lock.json`,
`references/ocr-runtime-lock.json`, `references/frontend-runtime-lock.json`.

Because this project imports PyMuPDF and orchestrates pdf2zh/BabelDOC (all AGPL-3.0),
the project as distributed is licensed AGPL-3.0. If you need to embed it in a
closed-source product, you must obtain commercial licenses for the AGPL components
(e.g., PyMuPDF from Artifex) and replace or relicense the others.

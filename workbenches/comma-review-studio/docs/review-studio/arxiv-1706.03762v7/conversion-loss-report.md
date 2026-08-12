# arXiv 1706.03762v7 conversion loss report

- Converter: `scripts/convert_attention_arxiv.py` 0.4.0
- Runtime: Python 3.13.12
- Scope: one-paper spike for Attention Is All You Need, not a generic TeX importer.
- Input chain: official arXiv abs HTML, e-print TeX source, official PDF.

## Element Status

- Sections: preserved as Markdown headings; count=23.
- Equations: transformed to Markdown display math with raw TeX bodies retained; count=3.
- Inline math: single-dollar spans are protected before prose cleanup; guard verified zero token-count delta for `\sqrt`, `\frac`, `\sum`, `\mathrm`, `\cdot`.
- Tables: transformed from LaTeX tabular to Markdown pipe tables when parseable; count=4.
- Figures: source package assets copied and referenced by relative paths; count=5, assets=8, rasterized_pdf_assets=5.
- PDF figure rasterizer: `sips` sips-316; Markdown references the generated PNG while the copied source PDF remains listed in the manifest.
- Footnotes: detected and listed in manifest; count=5.
- References: bibliography keys preserved; count=40.

## Known Losses And Downgrades

- TeX macro expansion is partial; unknown macros are preserved or simplified and require manual check.
- The math-token guard checks command counts, not semantic equivalence of rendered mathematics.
- LaTeX labels/cross-references are not resolved to final section, table, equation, or figure numbers.
- Table typography from `booktabs`, `multirow`, `multicolumn`, spacing, and alignment is downgraded to Markdown table text.
- Figure layout options, subfigure grouping, page placement, and original PDF pagination are not preserved.
- PDF vector figure assets are rasterized to PNG for browser display; vector editability and exact PDF-level rendering are not preserved in Markdown.
- Bibliography is flattened to Markdown list entries; citation links are not resolved bidirectionally.
- Author affiliation layout and title footnote markers are simplified.

## Redaction

This committed report excludes manuscript body text and long captions. Full source locators and samples are in the private data manifest under `apps/review-studio/data/`.

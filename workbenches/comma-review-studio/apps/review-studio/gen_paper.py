#!/usr/bin/env python3
"""Synthesize a long simulated research paper (>=3000 lines) with LaTeX math,
tables, code blocks and deep section structure. Deterministic (no randomness
that changes line count) so the spike material is reproducible.

Usage: python3 gen_paper.py > data/paper.md
"""
import sys

OUT = []
def w(line=""):
    OUT.append(line)

TITLE = "Scalable Provenance-Aware Orchestration for Multi-Agent Scientific Computing"

def para(topic, n):
    # deterministic filler paragraph referencing the topic
    sents = [
        f"We now examine {topic} in the context of reproducible multi-agent pipelines.",
        f"The central difficulty with {topic} is that provenance must survive edits without breaking anchors.",
        f"Prior systems treat {topic} as a static field, but our decision-stream model treats it as an append-only event ledger.",
        f"Concretely, each {topic} observation is recorded with an actor, a timestamp, and a falsifiable summary.",
        f"This lets a reviewer reconstruct why a given state was asserted about {topic} rather than trusting a rendered dashboard.",
    ]
    for i in range(n):
        w(sents[i % len(sents)])
        w()

# Front matter
w(f"# {TITLE}")
w()
w("**Authors:** J. River, Q. Jun, A. Fable, and the Orchestration Working Group  ")
w("**Affiliation:** Personal AI-Agent Hub, Documents Workspace  ")
w("**Preprint (simulated, not peer reviewed) — generated for the SKL-20 editor spike.**")
w()
w("> Abstract. We present a provenance-aware orchestration layer that coordinates "
  "heterogeneous language-model agents over scientific computing workloads. "
  "Our core contribution is an anchor mechanism that binds reviewer comments to "
  "document spans using prefix/suffix context rather than line numbers, so that "
  "annotations remain stable under upstream insertion and deletion. We formalize "
  "the cost cascade $C = \\sum_{i} p_i \\cdot u_i$ and show empirically that human "
  "decision load drops while escape counts stay bounded.")
w()
w("**Keywords:** provenance, orchestration, multi-agent systems, reproducibility, "
  "comment anchoring, cost cascade.")
w()
w("---")
w()

# Table of contents
w("## Table of Contents")
w()
sections = [
    "Introduction", "Background and Related Work", "Threat Model and Assumptions",
    "The Decision-Stream Substrate", "Anchor Algebra", "Cost Cascade Formalization",
    "System Architecture", "Implementation", "Experimental Setup",
    "Results", "Ablation Studies", "Discussion", "Limitations",
    "Future Work", "Conclusion",
]
for i, s in enumerate(sections, 1):
    w(f"{i}. {s}")
w()
w("---")
w()

def code_block_python():
    w("```python")
    w("def resolve_anchor(quote, body, locator):")
    w('    """Resolve a comment anchor by prefix/suffix context.')
    w("    Returns the character index in `body` or -1 when ambiguous.")
    w('    """')
    w("    matches = []")
    w("    cursor = 0")
    w("    while cursor <= len(body) - len(quote):")
    w("        found = body.find(quote, cursor)")
    w("        if found < 0:")
    w("            break")
    w("        matches.append(found)")
    w("        cursor = found + max(len(quote), 1)")
    w("    if len(matches) == 1:")
    w("        return matches[0]")
    w("    prefix = (locator.get('prefix') or '')[-160:]")
    w("    suffix = (locator.get('suffix') or '')[:160]")
    w("    scored = []")
    w("    for idx in matches:")
    w("        score = 0")
    w("        if prefix and body[max(0, idx - len(prefix)):idx] == prefix:")
    w("            score += 2")
    w("        if suffix and body[idx + len(quote): idx + len(quote) + len(suffix)] == suffix:")
    w("            score += 2")
    w("        scored.append((score, idx))")
    w("    scored.sort(reverse=True)")
    w("    if not scored[0][0] or (len(scored) > 1 and scored[1][0] == scored[0][0]):")
    w("        return -1")
    w("    return scored[0][1]")
    w("```")
    w()

def code_block_js():
    w("```javascript")
    w("// atomic write contract used by the thin backend")
    w("async function saveDoc(path, body, baseRev) {")
    w("  const res = await fetch('/api/doc', {")
    w("    method: 'PUT',")
    w("    headers: { 'Content-Type': 'application/json' },")
    w("    body: JSON.stringify({ path, body, base_rev: baseRev }),")
    w("  });")
    w("  return res.json();")
    w("}")
    w("```")
    w()

def math_display():
    w("The reviewer-load objective is minimized subject to a bounded escape rate:")
    w()
    w("$$")
    w("\\min_{\\theta} \\; \\mathbb{E}_{x \\sim \\mathcal{D}}\\big[ L(f_\\theta(x), y) \\big]")
    w("\\quad \\text{s.t.} \\quad \\Pr[\\text{escape}] = \\int_{\\Omega} q(\\omega)\\, d\\omega \\le \\epsilon")
    w("$$")
    w()
    w("where the per-step cost decomposes as $C = \\sum_{i=1}^{n} p_i u_i$ and the "
      "undo penalty $\\rho(a) = P(\\text{wrong}) \\times \\text{cost-to-undo}(a)$ gates "
      "delegation whenever $\\rho(a) > \\kappa$.")
    w()

def a_table():
    w("| System | Anchor model | Survives insert | Survives delete | Notes |")
    w("| --- | --- | --- | --- | --- |")
    w("| LineRef v1 | line number | no | no | breaks on any upstream edit |")
    w("| ByteOffset | absolute offset | no | no | brittle under reflow |")
    w("| PrefixSuffix (ours) | context window | yes | mostly | ambiguous on duplicates |")
    w("| BlockIndex | structural index | partial | partial | needs stable parse |")
    w("| Hybrid (ours+block) | context + block | yes | yes | best observed stability |")
    w()

# Body sections
subheads = [
    "Motivation", "Design goals", "Non-goals", "Formal statement",
    "Worked example", "Correctness argument", "Complexity", "Practical caveats",
]
for si, sec in enumerate(sections, 1):
    w(f"## {si}. {sec}")
    w()
    para(sec.lower(), 8)
    for hi, sub in enumerate(subheads, 1):
        w(f"### {si}.{hi} {sub}")
        w()
        para(f"{sec.lower()} / {sub.lower()}", 9)
        if hi == 2:
            math_display()
        if hi == 4:
            a_table()
        if hi == 6:
            if si % 2 == 0:
                code_block_python()
            else:
                code_block_js()
        if hi == 7:
            w(f"As shown in Equation for section {si}, the inline bound "
              f"$O(n \\log n)$ holds because each anchor touches $\\lceil \\log_2 n \\rceil$ "
              f"blocks. The normalized residual is $\\hat{{r}} = \\frac{{\\lVert x - \\bar x \\rVert_2}}{{\\sigma}}$.")
            w()
    w("---")
    w()

# References
w("## References")
w()
for i in range(1, 41):
    w(f"[{i}] Author {i}, et al. \"A study of provenance component {i}.\" "
      f"Journal of Simulated Systems, vol. {i}, no. {i % 5 + 1}, 20{10 + i % 15}.")
    w()

sys.stdout.write("\n".join(OUT) + "\n")

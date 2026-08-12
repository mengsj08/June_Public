# Scalable Provenance-Aware Orchestration for Multi-Agent Scientific Computing

**Authors:** J. River, Q. Jun, A. Fable, and the Orchestration Working Group

**Affiliation:** Synthetic Systems Lab

**Preprint (simulated, not peer reviewed) — generated for workbench validation.**

> Abstract. We present a provenance-aware orchestration layer that coordinates heterogeneous language-model agents over scientific computing workloads. Our core contribution is an anchor mechanism that binds reviewer comments to document spans using prefix/suffix context rather than line numbers, so that annotations remain stable under upstream insertion and deletion. We formalize the cost cascade $C = \sum_{i} p_i \cdot u_i$ and show empirically that human decision load drops while escape counts stay bounded.

**Keywords:** provenance, orchestration, multi-agent systems, reproducibility, comment anchoring, cost cascade.

---

## Table of Contents

1. Introduction
2. Background and Related Work
3. Threat Model and Assumptions
4. The Decision-Stream Substrate
5. Anchor Algebra
6. Cost Cascade Formalization
7. System Architecture
8. Implementation
9. Experimental Setup
10. Results
11. Ablation Studies
12. Discussion
13. Limitations
14. Future Work
15. Conclusion

---

## 1. Introduction

We now examine introduction in the context of reproducible multi-agent pipelines.

The central difficulty with introduction is that provenance must survive edits without breaking anchors.

Prior systems treat introduction as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each introduction observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about introduction rather than trusting a rendered dashboard.

We now examine introduction in the context of reproducible multi-agent pipelines.

The central difficulty with introduction is that provenance must survive edits without breaking anchors.

Prior systems treat introduction as a static field, but our decision-stream model treats it as an append-only event ledger.

### 1.1 Motivation

We now examine introduction / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with introduction / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat introduction / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each introduction / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about introduction / motivation rather than trusting a rendered dashboard.

We now examine introduction / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with introduction / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat introduction / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each introduction / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 1.2 Design goals

We now examine introduction / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with introduction / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat introduction / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each introduction / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about introduction / design goals rather than trusting a rendered dashboard.

We now examine introduction / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with introduction / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat introduction / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each introduction / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

The reviewer-load objective is minimized subject to a bounded escape rate:

$$
\min_{\theta} \; \mathbb{E}_{x \sim \mathcal{D}}\big[ L(f_\theta(x), y) \big]
\quad \text{s.t.} \quad \Pr[\text{escape}] = \int_{\Omega} q(\omega)\, d\omega \le \epsilon
$$

where the per-step cost decomposes as $C = \sum_{i=1}^{n} p_i u_i$ and the undo penalty $\rho(a) = P(\text{wrong}) \times \text{cost-to-undo}(a)$ gates delegation whenever $\rho(a) > \kappa$.

### 1.3 Non-goals

We now examine introduction / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with introduction / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat introduction / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each introduction / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about introduction / non-goals rather than trusting a rendered dashboard.

We now examine introduction / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with introduction / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat introduction / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each introduction / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 1.4 Formal statement

We now examine introduction / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with introduction / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat introduction / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each introduction / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about introduction / formal statement rather than trusting a rendered dashboard.

We now examine introduction / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with introduction / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat introduction / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each introduction / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

| System | Anchor model | Survives insert | Survives delete | Notes |
| --- | --- | --- | --- | --- |
| LineRef v1 | line number | no | no | breaks on any upstream edit |
| ByteOffset | absolute offset | no | no | brittle under reflow |
| PrefixSuffix (ours) | context window | yes | mostly | ambiguous on duplicates |
| BlockIndex | structural index | partial | partial | needs stable parse |
| Hybrid (ours+block) | context + block | yes | yes | best observed stability |

### 1.5 Worked example

We now examine introduction / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with introduction / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat introduction / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each introduction / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about introduction / worked example rather than trusting a rendered dashboard.

We now examine introduction / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with introduction / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat introduction / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each introduction / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 1.6 Correctness argument

We now examine introduction / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with introduction / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat introduction / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each introduction / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about introduction / correctness argument rather than trusting a rendered dashboard.

We now examine introduction / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with introduction / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat introduction / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each introduction / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

```javascript
// atomic write contract used by the thin backend
async function saveDoc(path, body, baseRev) {
  const res = await fetch('/api/doc', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, body, base_rev: baseRev }),
  });
  return res.json();
}
```

### 1.7 Complexity

We now examine introduction / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with introduction / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat introduction / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each introduction / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about introduction / complexity rather than trusting a rendered dashboard.

We now examine introduction / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with introduction / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat introduction / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each introduction / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

As shown in Equation for section 1, the inline bound $O(n \log n)$ holds because each anchor touches $\lceil \log_2 n \rceil$ blocks. The normalized residual is $\hat{r} = \frac{\lVert x - \bar x \rVert_2}{\sigma}$.

### 1.8 Practical caveats

We now examine introduction / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with introduction / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat introduction / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each introduction / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about introduction / practical caveats rather than trusting a rendered dashboard.

We now examine introduction / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with introduction / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat introduction / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each introduction / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

---

## 2. Background and Related Work

We now examine background and related work in the context of reproducible multi-agent pipelines.

The central difficulty with background and related work is that provenance must survive edits without breaking anchors.

Prior systems treat background and related work as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each background and related work observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about background and related work rather than trusting a rendered dashboard.

We now examine background and related work in the context of reproducible multi-agent pipelines.

The central difficulty with background and related work is that provenance must survive edits without breaking anchors.

Prior systems treat background and related work as a static field, but our decision-stream model treats it as an append-only event ledger.

### 2.1 Motivation

We now examine background and related work / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with background and related work / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat background and related work / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each background and related work / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about background and related work / motivation rather than trusting a rendered dashboard.

We now examine background and related work / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with background and related work / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat background and related work / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each background and related work / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 2.2 Design goals

We now examine background and related work / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with background and related work / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat background and related work / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each background and related work / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about background and related work / design goals rather than trusting a rendered dashboard.

We now examine background and related work / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with background and related work / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat background and related work / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each background and related work / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

The reviewer-load objective is minimized subject to a bounded escape rate:

$$
\min_{\theta} \; \mathbb{E}_{x \sim \mathcal{D}}\big[ L(f_\theta(x), y) \big]
\quad \text{s.t.} \quad \Pr[\text{escape}] = \int_{\Omega} q(\omega)\, d\omega \le \epsilon
$$

where the per-step cost decomposes as $C = \sum_{i=1}^{n} p_i u_i$ and the undo penalty $\rho(a) = P(\text{wrong}) \times \text{cost-to-undo}(a)$ gates delegation whenever $\rho(a) > \kappa$.

### 2.3 Non-goals

We now examine background and related work / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with background and related work / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat background and related work / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each background and related work / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about background and related work / non-goals rather than trusting a rendered dashboard.

We now examine background and related work / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with background and related work / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat background and related work / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each background and related work / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 2.4 Formal statement

We now examine background and related work / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with background and related work / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat background and related work / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each background and related work / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about background and related work / formal statement rather than trusting a rendered dashboard.

We now examine background and related work / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with background and related work / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat background and related work / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each background and related work / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

| System | Anchor model | Survives insert | Survives delete | Notes |
| --- | --- | --- | --- | --- |
| LineRef v1 | line number | no | no | breaks on any upstream edit |
| ByteOffset | absolute offset | no | no | brittle under reflow |
| PrefixSuffix (ours) | context window | yes | mostly | ambiguous on duplicates |
| BlockIndex | structural index | partial | partial | needs stable parse |
| Hybrid (ours+block) | context + block | yes | yes | best observed stability |

### 2.5 Worked example

We now examine background and related work / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with background and related work / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat background and related work / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each background and related work / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about background and related work / worked example rather than trusting a rendered dashboard.

We now examine background and related work / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with background and related work / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat background and related work / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each background and related work / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 2.6 Correctness argument

We now examine background and related work / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with background and related work / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat background and related work / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each background and related work / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about background and related work / correctness argument rather than trusting a rendered dashboard.

We now examine background and related work / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with background and related work / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat background and related work / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each background and related work / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

```python
def resolve_anchor(quote, body, locator):
    """Resolve a comment anchor by prefix/suffix context.
    Returns the character index in `body` or -1 when ambiguous.
    """
    matches = []
    cursor = 0
    while cursor <= len(body) - len(quote):
        found = body.find(quote, cursor)
        if found < 0:
            break
        matches.append(found)
        cursor = found + max(len(quote), 1)
    if len(matches) == 1:
        return matches[0]
    prefix = (locator.get('prefix') or '')[-160:]
    suffix = (locator.get('suffix') or '')[:160]
    scored = []
    for idx in matches:
        score = 0
        if prefix and body[max(0, idx - len(prefix)):idx] == prefix:
            score += 2
        if suffix and body[idx + len(quote): idx + len(quote) + len(suffix)] == suffix:
            score += 2
        scored.append((score, idx))
    scored.sort(reverse=True)
    if not scored[0][0] or (len(scored) > 1 and scored[1][0] == scored[0][0]):
        return -1
    return scored[0][1]
```

### 2.7 Complexity

We now examine background and related work / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with background and related work / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat background and related work / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each background and related work / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about background and related work / complexity rather than trusting a rendered dashboard.

We now examine background and related work / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with background and related work / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat background and related work / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each background and related work / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

As shown in Equation for section 2, the inline bound $O(n \log n)$ holds because each anchor touches $\lceil \log_2 n \rceil$ blocks. The normalized residual is $\hat{r} = \frac{\lVert x - \bar x \rVert_2}{\sigma}$.

### 2.8 Practical caveats

We now examine background and related work / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with background and related work / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat background and related work / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each background and related work / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about background and related work / practical caveats rather than trusting a rendered dashboard.

We now examine background and related work / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with background and related work / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat background and related work / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each background and related work / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

---

## 3. Threat Model and Assumptions

We now examine threat model and assumptions in the context of reproducible multi-agent pipelines.

The central difficulty with threat model and assumptions is that provenance must survive edits without breaking anchors.

Prior systems treat threat model and assumptions as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each threat model and assumptions observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about threat model and assumptions rather than trusting a rendered dashboard.

We now examine threat model and assumptions in the context of reproducible multi-agent pipelines.

The central difficulty with threat model and assumptions is that provenance must survive edits without breaking anchors.

Prior systems treat threat model and assumptions as a static field, but our decision-stream model treats it as an append-only event ledger.

### 3.1 Motivation

We now examine threat model and assumptions / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with threat model and assumptions / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat threat model and assumptions / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each threat model and assumptions / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about threat model and assumptions / motivation rather than trusting a rendered dashboard.

We now examine threat model and assumptions / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with threat model and assumptions / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat threat model and assumptions / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each threat model and assumptions / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 3.2 Design goals

We now examine threat model and assumptions / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with threat model and assumptions / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat threat model and assumptions / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each threat model and assumptions / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about threat model and assumptions / design goals rather than trusting a rendered dashboard.

We now examine threat model and assumptions / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with threat model and assumptions / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat threat model and assumptions / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each threat model and assumptions / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

The reviewer-load objective is minimized subject to a bounded escape rate:

$$
\min_{\theta} \; \mathbb{E}_{x \sim \mathcal{D}}\big[ L(f_\theta(x), y) \big]
\quad \text{s.t.} \quad \Pr[\text{escape}] = \int_{\Omega} q(\omega)\, d\omega \le \epsilon
$$

where the per-step cost decomposes as $C = \sum_{i=1}^{n} p_i u_i$ and the undo penalty $\rho(a) = P(\text{wrong}) \times \text{cost-to-undo}(a)$ gates delegation whenever $\rho(a) > \kappa$.

### 3.3 Non-goals

We now examine threat model and assumptions / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with threat model and assumptions / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat threat model and assumptions / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each threat model and assumptions / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about threat model and assumptions / non-goals rather than trusting a rendered dashboard.

We now examine threat model and assumptions / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with threat model and assumptions / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat threat model and assumptions / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each threat model and assumptions / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 3.4 Formal statement

We now examine threat model and assumptions / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with threat model and assumptions / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat threat model and assumptions / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each threat model and assumptions / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about threat model and assumptions / formal statement rather than trusting a rendered dashboard.

We now examine threat model and assumptions / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with threat model and assumptions / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat threat model and assumptions / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each threat model and assumptions / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

| System | Anchor model | Survives insert | Survives delete | Notes |
| --- | --- | --- | --- | --- |
| LineRef v1 | line number | no | no | breaks on any upstream edit |
| ByteOffset | absolute offset | no | no | brittle under reflow |
| PrefixSuffix (ours) | context window | yes | mostly | ambiguous on duplicates |
| BlockIndex | structural index | partial | partial | needs stable parse |
| Hybrid (ours+block) | context + block | yes | yes | best observed stability |

### 3.5 Worked example

We now examine threat model and assumptions / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with threat model and assumptions / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat threat model and assumptions / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each threat model and assumptions / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about threat model and assumptions / worked example rather than trusting a rendered dashboard.

We now examine threat model and assumptions / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with threat model and assumptions / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat threat model and assumptions / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each threat model and assumptions / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 3.6 Correctness argument

We now examine threat model and assumptions / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with threat model and assumptions / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat threat model and assumptions / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each threat model and assumptions / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about threat model and assumptions / correctness argument rather than trusting a rendered dashboard.

We now examine threat model and assumptions / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with threat model and assumptions / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat threat model and assumptions / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each threat model and assumptions / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

```javascript
// atomic write contract used by the thin backend
async function saveDoc(path, body, baseRev) {
  const res = await fetch('/api/doc', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, body, base_rev: baseRev }),
  });
  return res.json();
}
```

### 3.7 Complexity

We now examine threat model and assumptions / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with threat model and assumptions / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat threat model and assumptions / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each threat model and assumptions / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about threat model and assumptions / complexity rather than trusting a rendered dashboard.

We now examine threat model and assumptions / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with threat model and assumptions / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat threat model and assumptions / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each threat model and assumptions / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

As shown in Equation for section 3, the inline bound $O(n \log n)$ holds because each anchor touches $\lceil \log_2 n \rceil$ blocks. The normalized residual is $\hat{r} = \frac{\lVert x - \bar x \rVert_2}{\sigma}$.

### 3.8 Practical caveats

We now examine threat model and assumptions / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with threat model and assumptions / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat threat model and assumptions / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each threat model and assumptions / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about threat model and assumptions / practical caveats rather than trusting a rendered dashboard.

We now examine threat model and assumptions / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with threat model and assumptions / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat threat model and assumptions / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each threat model and assumptions / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

---

## 4. The Decision-Stream Substrate

We now examine the decision-stream substrate in the context of reproducible multi-agent pipelines.

The central difficulty with the decision-stream substrate is that provenance must survive edits without breaking anchors.

Prior systems treat the decision-stream substrate as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each the decision-stream substrate observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about the decision-stream substrate rather than trusting a rendered dashboard.

We now examine the decision-stream substrate in the context of reproducible multi-agent pipelines.

The central difficulty with the decision-stream substrate is that provenance must survive edits without breaking anchors.

Prior systems treat the decision-stream substrate as a static field, but our decision-stream model treats it as an append-only event ledger.

### 4.1 Motivation

We now examine the decision-stream substrate / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with the decision-stream substrate / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat the decision-stream substrate / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each the decision-stream substrate / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about the decision-stream substrate / motivation rather than trusting a rendered dashboard.

We now examine the decision-stream substrate / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with the decision-stream substrate / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat the decision-stream substrate / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each the decision-stream substrate / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 4.2 Design goals

We now examine the decision-stream substrate / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with the decision-stream substrate / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat the decision-stream substrate / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each the decision-stream substrate / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about the decision-stream substrate / design goals rather than trusting a rendered dashboard.

We now examine the decision-stream substrate / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with the decision-stream substrate / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat the decision-stream substrate / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each the decision-stream substrate / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

The reviewer-load objective is minimized subject to a bounded escape rate:

$$
\min_{\theta} \; \mathbb{E}_{x \sim \mathcal{D}}\big[ L(f_\theta(x), y) \big]
\quad \text{s.t.} \quad \Pr[\text{escape}] = \int_{\Omega} q(\omega)\, d\omega \le \epsilon
$$

where the per-step cost decomposes as $C = \sum_{i=1}^{n} p_i u_i$ and the undo penalty $\rho(a) = P(\text{wrong}) \times \text{cost-to-undo}(a)$ gates delegation whenever $\rho(a) > \kappa$.

### 4.3 Non-goals

We now examine the decision-stream substrate / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with the decision-stream substrate / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat the decision-stream substrate / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each the decision-stream substrate / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about the decision-stream substrate / non-goals rather than trusting a rendered dashboard.

We now examine the decision-stream substrate / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with the decision-stream substrate / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat the decision-stream substrate / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each the decision-stream substrate / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 4.4 Formal statement

We now examine the decision-stream substrate / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with the decision-stream substrate / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat the decision-stream substrate / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each the decision-stream substrate / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about the decision-stream substrate / formal statement rather than trusting a rendered dashboard.

We now examine the decision-stream substrate / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with the decision-stream substrate / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat the decision-stream substrate / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each the decision-stream substrate / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

| System | Anchor model | Survives insert | Survives delete | Notes |
| --- | --- | --- | --- | --- |
| LineRef v1 | line number | no | no | breaks on any upstream edit |
| ByteOffset | absolute offset | no | no | brittle under reflow |
| PrefixSuffix (ours) | context window | yes | mostly | ambiguous on duplicates |
| BlockIndex | structural index | partial | partial | needs stable parse |
| Hybrid (ours+block) | context + block | yes | yes | best observed stability |

### 4.5 Worked example

We now examine the decision-stream substrate / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with the decision-stream substrate / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat the decision-stream substrate / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each the decision-stream substrate / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about the decision-stream substrate / worked example rather than trusting a rendered dashboard.

We now examine the decision-stream substrate / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with the decision-stream substrate / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat the decision-stream substrate / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each the decision-stream substrate / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 4.6 Correctness argument

We now examine the decision-stream substrate / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with the decision-stream substrate / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat the decision-stream substrate / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each the decision-stream substrate / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about the decision-stream substrate / correctness argument rather than trusting a rendered dashboard.

We now examine the decision-stream substrate / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with the decision-stream substrate / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat the decision-stream substrate / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each the decision-stream substrate / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

```python
def resolve_anchor(quote, body, locator):
    """Resolve a comment anchor by prefix/suffix context.
    Returns the character index in `body` or -1 when ambiguous.
    """
    matches = []
    cursor = 0
    while cursor <= len(body) - len(quote):
        found = body.find(quote, cursor)
        if found < 0:
            break
        matches.append(found)
        cursor = found + max(len(quote), 1)
    if len(matches) == 1:
        return matches[0]
    prefix = (locator.get('prefix') or '')[-160:]
    suffix = (locator.get('suffix') or '')[:160]
    scored = []
    for idx in matches:
        score = 0
        if prefix and body[max(0, idx - len(prefix)):idx] == prefix:
            score += 2
        if suffix and body[idx + len(quote): idx + len(quote) + len(suffix)] == suffix:
            score += 2
        scored.append((score, idx))
    scored.sort(reverse=True)
    if not scored[0][0] or (len(scored) > 1 and scored[1][0] == scored[0][0]):
        return -1
    return scored[0][1]
```

### 4.7 Complexity

We now examine the decision-stream substrate / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with the decision-stream substrate / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat the decision-stream substrate / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each the decision-stream substrate / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about the decision-stream substrate / complexity rather than trusting a rendered dashboard.

We now examine the decision-stream substrate / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with the decision-stream substrate / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat the decision-stream substrate / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each the decision-stream substrate / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

As shown in Equation for section 4, the inline bound $O(n \log n)$ holds because each anchor touches $\lceil \log_2 n \rceil$ blocks. The normalized residual is $\hat{r} = \frac{\lVert x - \bar x \rVert_2}{\sigma}$.

### 4.8 Practical caveats

We now examine the decision-stream substrate / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with the decision-stream substrate / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat the decision-stream substrate / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each the decision-stream substrate / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about the decision-stream substrate / practical caveats rather than trusting a rendered dashboard.

We now examine the decision-stream substrate / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with the decision-stream substrate / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat the decision-stream substrate / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each the decision-stream substrate / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

---

## 5. Anchor Algebra

We now examine anchor algebra in the context of reproducible multi-agent pipelines.

The central difficulty with anchor algebra is that provenance must survive edits without breaking anchors.

Prior systems treat anchor algebra as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each anchor algebra observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about anchor algebra rather than trusting a rendered dashboard.

We now examine anchor algebra in the context of reproducible multi-agent pipelines.

The central difficulty with anchor algebra is that provenance must survive edits without breaking anchors.

Prior systems treat anchor algebra as a static field, but our decision-stream model treats it as an append-only event ledger.

### 5.1 Motivation

We now examine anchor algebra / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with anchor algebra / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat anchor algebra / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each anchor algebra / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about anchor algebra / motivation rather than trusting a rendered dashboard.

We now examine anchor algebra / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with anchor algebra / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat anchor algebra / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each anchor algebra / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 5.2 Design goals

We now examine anchor algebra / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with anchor algebra / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat anchor algebra / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each anchor algebra / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about anchor algebra / design goals rather than trusting a rendered dashboard.

We now examine anchor algebra / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with anchor algebra / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat anchor algebra / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each anchor algebra / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

The reviewer-load objective is minimized subject to a bounded escape rate:

$$
\min_{\theta} \; \mathbb{E}_{x \sim \mathcal{D}}\big[ L(f_\theta(x), y) \big]
\quad \text{s.t.} \quad \Pr[\text{escape}] = \int_{\Omega} q(\omega)\, d\omega \le \epsilon
$$

where the per-step cost decomposes as $C = \sum_{i=1}^{n} p_i u_i$ and the undo penalty $\rho(a) = P(\text{wrong}) \times \text{cost-to-undo}(a)$ gates delegation whenever $\rho(a) > \kappa$.

### 5.3 Non-goals

We now examine anchor algebra / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with anchor algebra / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat anchor algebra / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each anchor algebra / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about anchor algebra / non-goals rather than trusting a rendered dashboard.

We now examine anchor algebra / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with anchor algebra / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat anchor algebra / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each anchor algebra / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 5.4 Formal statement

We now examine anchor algebra / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with anchor algebra / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat anchor algebra / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each anchor algebra / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about anchor algebra / formal statement rather than trusting a rendered dashboard.

We now examine anchor algebra / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with anchor algebra / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat anchor algebra / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each anchor algebra / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

| System | Anchor model | Survives insert | Survives delete | Notes |
| --- | --- | --- | --- | --- |
| LineRef v1 | line number | no | no | breaks on any upstream edit |
| ByteOffset | absolute offset | no | no | brittle under reflow |
| PrefixSuffix (ours) | context window | yes | mostly | ambiguous on duplicates |
| BlockIndex | structural index | partial | partial | needs stable parse |
| Hybrid (ours+block) | context + block | yes | yes | best observed stability |

### 5.5 Worked example

We now examine anchor algebra / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with anchor algebra / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat anchor algebra / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each anchor algebra / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about anchor algebra / worked example rather than trusting a rendered dashboard.

We now examine anchor algebra / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with anchor algebra / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat anchor algebra / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each anchor algebra / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 5.6 Correctness argument

We now examine anchor algebra / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with anchor algebra / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat anchor algebra / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each anchor algebra / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about anchor algebra / correctness argument rather than trusting a rendered dashboard.

We now examine anchor algebra / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with anchor algebra / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat anchor algebra / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each anchor algebra / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

```javascript
// atomic write contract used by the thin backend
async function saveDoc(path, body, baseRev) {
  const res = await fetch('/api/doc', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, body, base_rev: baseRev }),
  });
  return res.json();
}
```

### 5.7 Complexity

We now examine anchor algebra / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with anchor algebra / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat anchor algebra / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each anchor algebra / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about anchor algebra / complexity rather than trusting a rendered dashboard.

We now examine anchor algebra / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with anchor algebra / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat anchor algebra / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each anchor algebra / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

As shown in Equation for section 5, the inline bound $O(n \log n)$ holds because each anchor touches $\lceil \log_2 n \rceil$ blocks. The normalized residual is $\hat{r} = \frac{\lVert x - \bar x \rVert_2}{\sigma}$.

### 5.8 Practical caveats

We now examine anchor algebra / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with anchor algebra / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat anchor algebra / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each anchor algebra / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about anchor algebra / practical caveats rather than trusting a rendered dashboard.

We now examine anchor algebra / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with anchor algebra / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat anchor algebra / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each anchor algebra / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

---

## 6. Cost Cascade Formalization

We now examine cost cascade formalization in the context of reproducible multi-agent pipelines.

The central difficulty with cost cascade formalization is that provenance must survive edits without breaking anchors.

Prior systems treat cost cascade formalization as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each cost cascade formalization observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about cost cascade formalization rather than trusting a rendered dashboard.

We now examine cost cascade formalization in the context of reproducible multi-agent pipelines.

The central difficulty with cost cascade formalization is that provenance must survive edits without breaking anchors.

Prior systems treat cost cascade formalization as a static field, but our decision-stream model treats it as an append-only event ledger.

### 6.1 Motivation

We now examine cost cascade formalization / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with cost cascade formalization / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat cost cascade formalization / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each cost cascade formalization / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about cost cascade formalization / motivation rather than trusting a rendered dashboard.

We now examine cost cascade formalization / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with cost cascade formalization / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat cost cascade formalization / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each cost cascade formalization / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 6.2 Design goals

We now examine cost cascade formalization / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with cost cascade formalization / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat cost cascade formalization / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each cost cascade formalization / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about cost cascade formalization / design goals rather than trusting a rendered dashboard.

We now examine cost cascade formalization / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with cost cascade formalization / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat cost cascade formalization / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each cost cascade formalization / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

The reviewer-load objective is minimized subject to a bounded escape rate:

$$
\min_{\theta} \; \mathbb{E}_{x \sim \mathcal{D}}\big[ L(f_\theta(x), y) \big]
\quad \text{s.t.} \quad \Pr[\text{escape}] = \int_{\Omega} q(\omega)\, d\omega \le \epsilon
$$

where the per-step cost decomposes as $C = \sum_{i=1}^{n} p_i u_i$ and the undo penalty $\rho(a) = P(\text{wrong}) \times \text{cost-to-undo}(a)$ gates delegation whenever $\rho(a) > \kappa$.

### 6.3 Non-goals

We now examine cost cascade formalization / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with cost cascade formalization / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat cost cascade formalization / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each cost cascade formalization / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about cost cascade formalization / non-goals rather than trusting a rendered dashboard.

We now examine cost cascade formalization / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with cost cascade formalization / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat cost cascade formalization / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each cost cascade formalization / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 6.4 Formal statement

We now examine cost cascade formalization / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with cost cascade formalization / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat cost cascade formalization / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each cost cascade formalization / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about cost cascade formalization / formal statement rather than trusting a rendered dashboard.

We now examine cost cascade formalization / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with cost cascade formalization / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat cost cascade formalization / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each cost cascade formalization / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

| System | Anchor model | Survives insert | Survives delete | Notes |
| --- | --- | --- | --- | --- |
| LineRef v1 | line number | no | no | breaks on any upstream edit |
| ByteOffset | absolute offset | no | no | brittle under reflow |
| PrefixSuffix (ours) | context window | yes | mostly | ambiguous on duplicates |
| BlockIndex | structural index | partial | partial | needs stable parse |
| Hybrid (ours+block) | context + block | yes | yes | best observed stability |

### 6.5 Worked example

We now examine cost cascade formalization / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with cost cascade formalization / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat cost cascade formalization / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each cost cascade formalization / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about cost cascade formalization / worked example rather than trusting a rendered dashboard.

We now examine cost cascade formalization / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with cost cascade formalization / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat cost cascade formalization / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each cost cascade formalization / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 6.6 Correctness argument

We now examine cost cascade formalization / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with cost cascade formalization / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat cost cascade formalization / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each cost cascade formalization / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about cost cascade formalization / correctness argument rather than trusting a rendered dashboard.

We now examine cost cascade formalization / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with cost cascade formalization / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat cost cascade formalization / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each cost cascade formalization / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

```python
def resolve_anchor(quote, body, locator):
    """Resolve a comment anchor by prefix/suffix context.
    Returns the character index in `body` or -1 when ambiguous.
    """
    matches = []
    cursor = 0
    while cursor <= len(body) - len(quote):
        found = body.find(quote, cursor)
        if found < 0:
            break
        matches.append(found)
        cursor = found + max(len(quote), 1)
    if len(matches) == 1:
        return matches[0]
    prefix = (locator.get('prefix') or '')[-160:]
    suffix = (locator.get('suffix') or '')[:160]
    scored = []
    for idx in matches:
        score = 0
        if prefix and body[max(0, idx - len(prefix)):idx] == prefix:
            score += 2
        if suffix and body[idx + len(quote): idx + len(quote) + len(suffix)] == suffix:
            score += 2
        scored.append((score, idx))
    scored.sort(reverse=True)
    if not scored[0][0] or (len(scored) > 1 and scored[1][0] == scored[0][0]):
        return -1
    return scored[0][1]
```

### 6.7 Complexity

We now examine cost cascade formalization / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with cost cascade formalization / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat cost cascade formalization / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each cost cascade formalization / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about cost cascade formalization / complexity rather than trusting a rendered dashboard.

We now examine cost cascade formalization / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with cost cascade formalization / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat cost cascade formalization / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each cost cascade formalization / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

As shown in Equation for section 6, the inline bound $O(n \log n)$ holds because each anchor touches $\lceil \log_2 n \rceil$ blocks. The normalized residual is $\hat{r} = \frac{\lVert x - \bar x \rVert_2}{\sigma}$.

### 6.8 Practical caveats

We now examine cost cascade formalization / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with cost cascade formalization / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat cost cascade formalization / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each cost cascade formalization / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about cost cascade formalization / practical caveats rather than trusting a rendered dashboard.

We now examine cost cascade formalization / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with cost cascade formalization / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat cost cascade formalization / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each cost cascade formalization / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

---

## 7. System Architecture

We now examine system architecture in the context of reproducible multi-agent pipelines.

The central difficulty with system architecture is that provenance must survive edits without breaking anchors.

Prior systems treat system architecture as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each system architecture observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about system architecture rather than trusting a rendered dashboard.

We now examine system architecture in the context of reproducible multi-agent pipelines.

The central difficulty with system architecture is that provenance must survive edits without breaking anchors.

Prior systems treat system architecture as a static field, but our decision-stream model treats it as an append-only event ledger.

### 7.1 Motivation

We now examine system architecture / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with system architecture / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat system architecture / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each system architecture / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about system architecture / motivation rather than trusting a rendered dashboard.

We now examine system architecture / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with system architecture / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat system architecture / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each system architecture / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 7.2 Design goals

We now examine system architecture / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with system architecture / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat system architecture / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each system architecture / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about system architecture / design goals rather than trusting a rendered dashboard.

We now examine system architecture / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with system architecture / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat system architecture / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each system architecture / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

The reviewer-load objective is minimized subject to a bounded escape rate:

$$
\min_{\theta} \; \mathbb{E}_{x \sim \mathcal{D}}\big[ L(f_\theta(x), y) \big]
\quad \text{s.t.} \quad \Pr[\text{escape}] = \int_{\Omega} q(\omega)\, d\omega \le \epsilon
$$

where the per-step cost decomposes as $C = \sum_{i=1}^{n} p_i u_i$ and the undo penalty $\rho(a) = P(\text{wrong}) \times \text{cost-to-undo}(a)$ gates delegation whenever $\rho(a) > \kappa$.

### 7.3 Non-goals

We now examine system architecture / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with system architecture / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat system architecture / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each system architecture / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about system architecture / non-goals rather than trusting a rendered dashboard.

We now examine system architecture / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with system architecture / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat system architecture / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each system architecture / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 7.4 Formal statement

We now examine system architecture / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with system architecture / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat system architecture / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each system architecture / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about system architecture / formal statement rather than trusting a rendered dashboard.

We now examine system architecture / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with system architecture / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat system architecture / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each system architecture / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

| System | Anchor model | Survives insert | Survives delete | Notes |
| --- | --- | --- | --- | --- |
| LineRef v1 | line number | no | no | breaks on any upstream edit |
| ByteOffset | absolute offset | no | no | brittle under reflow |
| PrefixSuffix (ours) | context window | yes | mostly | ambiguous on duplicates |
| BlockIndex | structural index | partial | partial | needs stable parse |
| Hybrid (ours+block) | context + block | yes | yes | best observed stability |

### 7.5 Worked example

We now examine system architecture / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with system architecture / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat system architecture / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each system architecture / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about system architecture / worked example rather than trusting a rendered dashboard.

We now examine system architecture / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with system architecture / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat system architecture / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each system architecture / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 7.6 Correctness argument

We now examine system architecture / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with system architecture / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat system architecture / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each system architecture / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about system architecture / correctness argument rather than trusting a rendered dashboard.

We now examine system architecture / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with system architecture / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat system architecture / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each system architecture / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

```javascript
// atomic write contract used by the thin backend
async function saveDoc(path, body, baseRev) {
  const res = await fetch('/api/doc', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, body, base_rev: baseRev }),
  });
  return res.json();
}
```

### 7.7 Complexity

We now examine system architecture / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with system architecture / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat system architecture / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each system architecture / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about system architecture / complexity rather than trusting a rendered dashboard.

We now examine system architecture / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with system architecture / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat system architecture / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each system architecture / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

As shown in Equation for section 7, the inline bound $O(n \log n)$ holds because each anchor touches $\lceil \log_2 n \rceil$ blocks. The normalized residual is $\hat{r} = \frac{\lVert x - \bar x \rVert_2}{\sigma}$.

### 7.8 Practical caveats

We now examine system architecture / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with system architecture / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat system architecture / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each system architecture / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about system architecture / practical caveats rather than trusting a rendered dashboard.

We now examine system architecture / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with system architecture / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat system architecture / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each system architecture / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

---

## 8. Implementation

We now examine implementation in the context of reproducible multi-agent pipelines.

The central difficulty with implementation is that provenance must survive edits without breaking anchors.

Prior systems treat implementation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each implementation observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about implementation rather than trusting a rendered dashboard.

We now examine implementation in the context of reproducible multi-agent pipelines.

The central difficulty with implementation is that provenance must survive edits without breaking anchors.

Prior systems treat implementation as a static field, but our decision-stream model treats it as an append-only event ledger.

### 8.1 Motivation

We now examine implementation / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with implementation / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat implementation / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each implementation / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about implementation / motivation rather than trusting a rendered dashboard.

We now examine implementation / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with implementation / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat implementation / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each implementation / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 8.2 Design goals

We now examine implementation / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with implementation / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat implementation / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each implementation / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about implementation / design goals rather than trusting a rendered dashboard.

We now examine implementation / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with implementation / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat implementation / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each implementation / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

The reviewer-load objective is minimized subject to a bounded escape rate:

$$
\min_{\theta} \; \mathbb{E}_{x \sim \mathcal{D}}\big[ L(f_\theta(x), y) \big]
\quad \text{s.t.} \quad \Pr[\text{escape}] = \int_{\Omega} q(\omega)\, d\omega \le \epsilon
$$

where the per-step cost decomposes as $C = \sum_{i=1}^{n} p_i u_i$ and the undo penalty $\rho(a) = P(\text{wrong}) \times \text{cost-to-undo}(a)$ gates delegation whenever $\rho(a) > \kappa$.

### 8.3 Non-goals

We now examine implementation / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with implementation / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat implementation / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each implementation / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about implementation / non-goals rather than trusting a rendered dashboard.

We now examine implementation / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with implementation / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat implementation / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each implementation / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 8.4 Formal statement

We now examine implementation / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with implementation / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat implementation / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each implementation / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about implementation / formal statement rather than trusting a rendered dashboard.

We now examine implementation / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with implementation / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat implementation / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each implementation / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

| System | Anchor model | Survives insert | Survives delete | Notes |
| --- | --- | --- | --- | --- |
| LineRef v1 | line number | no | no | breaks on any upstream edit |
| ByteOffset | absolute offset | no | no | brittle under reflow |
| PrefixSuffix (ours) | context window | yes | mostly | ambiguous on duplicates |
| BlockIndex | structural index | partial | partial | needs stable parse |
| Hybrid (ours+block) | context + block | yes | yes | best observed stability |

### 8.5 Worked example

We now examine implementation / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with implementation / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat implementation / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each implementation / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about implementation / worked example rather than trusting a rendered dashboard.

We now examine implementation / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with implementation / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat implementation / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each implementation / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 8.6 Correctness argument

We now examine implementation / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with implementation / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat implementation / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each implementation / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about implementation / correctness argument rather than trusting a rendered dashboard.

We now examine implementation / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with implementation / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat implementation / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each implementation / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

```python
def resolve_anchor(quote, body, locator):
    """Resolve a comment anchor by prefix/suffix context.
    Returns the character index in `body` or -1 when ambiguous.
    """
    matches = []
    cursor = 0
    while cursor <= len(body) - len(quote):
        found = body.find(quote, cursor)
        if found < 0:
            break
        matches.append(found)
        cursor = found + max(len(quote), 1)
    if len(matches) == 1:
        return matches[0]
    prefix = (locator.get('prefix') or '')[-160:]
    suffix = (locator.get('suffix') or '')[:160]
    scored = []
    for idx in matches:
        score = 0
        if prefix and body[max(0, idx - len(prefix)):idx] == prefix:
            score += 2
        if suffix and body[idx + len(quote): idx + len(quote) + len(suffix)] == suffix:
            score += 2
        scored.append((score, idx))
    scored.sort(reverse=True)
    if not scored[0][0] or (len(scored) > 1 and scored[1][0] == scored[0][0]):
        return -1
    return scored[0][1]
```

### 8.7 Complexity

We now examine implementation / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with implementation / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat implementation / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each implementation / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about implementation / complexity rather than trusting a rendered dashboard.

We now examine implementation / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with implementation / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat implementation / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each implementation / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

As shown in Equation for section 8, the inline bound $O(n \log n)$ holds because each anchor touches $\lceil \log_2 n \rceil$ blocks. The normalized residual is $\hat{r} = \frac{\lVert x - \bar x \rVert_2}{\sigma}$.

### 8.8 Practical caveats

We now examine implementation / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with implementation / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat implementation / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each implementation / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about implementation / practical caveats rather than trusting a rendered dashboard.

We now examine implementation / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with implementation / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat implementation / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each implementation / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

---

## 9. Experimental Setup

We now examine experimental setup in the context of reproducible multi-agent pipelines.

The central difficulty with experimental setup is that provenance must survive edits without breaking anchors.

Prior systems treat experimental setup as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each experimental setup observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about experimental setup rather than trusting a rendered dashboard.

We now examine experimental setup in the context of reproducible multi-agent pipelines.

The central difficulty with experimental setup is that provenance must survive edits without breaking anchors.

Prior systems treat experimental setup as a static field, but our decision-stream model treats it as an append-only event ledger.

### 9.1 Motivation

We now examine experimental setup / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with experimental setup / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat experimental setup / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each experimental setup / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about experimental setup / motivation rather than trusting a rendered dashboard.

We now examine experimental setup / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with experimental setup / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat experimental setup / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each experimental setup / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 9.2 Design goals

We now examine experimental setup / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with experimental setup / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat experimental setup / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each experimental setup / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about experimental setup / design goals rather than trusting a rendered dashboard.

We now examine experimental setup / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with experimental setup / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat experimental setup / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each experimental setup / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

The reviewer-load objective is minimized subject to a bounded escape rate:

$$
\min_{\theta} \; \mathbb{E}_{x \sim \mathcal{D}}\big[ L(f_\theta(x), y) \big]
\quad \text{s.t.} \quad \Pr[\text{escape}] = \int_{\Omega} q(\omega)\, d\omega \le \epsilon
$$

where the per-step cost decomposes as $C = \sum_{i=1}^{n} p_i u_i$ and the undo penalty $\rho(a) = P(\text{wrong}) \times \text{cost-to-undo}(a)$ gates delegation whenever $\rho(a) > \kappa$.

### 9.3 Non-goals

We now examine experimental setup / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with experimental setup / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat experimental setup / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each experimental setup / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about experimental setup / non-goals rather than trusting a rendered dashboard.

We now examine experimental setup / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with experimental setup / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat experimental setup / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each experimental setup / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 9.4 Formal statement

We now examine experimental setup / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with experimental setup / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat experimental setup / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each experimental setup / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about experimental setup / formal statement rather than trusting a rendered dashboard.

We now examine experimental setup / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with experimental setup / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat experimental setup / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each experimental setup / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

| System | Anchor model | Survives insert | Survives delete | Notes |
| --- | --- | --- | --- | --- |
| LineRef v1 | line number | no | no | breaks on any upstream edit |
| ByteOffset | absolute offset | no | no | brittle under reflow |
| PrefixSuffix (ours) | context window | yes | mostly | ambiguous on duplicates |
| BlockIndex | structural index | partial | partial | needs stable parse |
| Hybrid (ours+block) | context + block | yes | yes | best observed stability |

### 9.5 Worked example

We now examine experimental setup / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with experimental setup / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat experimental setup / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each experimental setup / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about experimental setup / worked example rather than trusting a rendered dashboard.

We now examine experimental setup / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with experimental setup / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat experimental setup / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each experimental setup / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 9.6 Correctness argument

We now examine experimental setup / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with experimental setup / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat experimental setup / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each experimental setup / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about experimental setup / correctness argument rather than trusting a rendered dashboard.

We now examine experimental setup / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with experimental setup / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat experimental setup / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each experimental setup / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

```javascript
// atomic write contract used by the thin backend
async function saveDoc(path, body, baseRev) {
  const res = await fetch('/api/doc', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, body, base_rev: baseRev }),
  });
  return res.json();
}
```

### 9.7 Complexity

We now examine experimental setup / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with experimental setup / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat experimental setup / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each experimental setup / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about experimental setup / complexity rather than trusting a rendered dashboard.

We now examine experimental setup / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with experimental setup / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat experimental setup / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each experimental setup / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

As shown in Equation for section 9, the inline bound $O(n \log n)$ holds because each anchor touches $\lceil \log_2 n \rceil$ blocks. The normalized residual is $\hat{r} = \frac{\lVert x - \bar x \rVert_2}{\sigma}$.

### 9.8 Practical caveats

We now examine experimental setup / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with experimental setup / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat experimental setup / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each experimental setup / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about experimental setup / practical caveats rather than trusting a rendered dashboard.

We now examine experimental setup / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with experimental setup / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat experimental setup / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each experimental setup / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

---

## 10. Results

We now examine results in the context of reproducible multi-agent pipelines.

The central difficulty with results is that provenance must survive edits without breaking anchors.

Prior systems treat results as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each results observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about results rather than trusting a rendered dashboard.

We now examine results in the context of reproducible multi-agent pipelines.

The central difficulty with results is that provenance must survive edits without breaking anchors.

Prior systems treat results as a static field, but our decision-stream model treats it as an append-only event ledger.

### 10.1 Motivation

We now examine results / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with results / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat results / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each results / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about results / motivation rather than trusting a rendered dashboard.

We now examine results / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with results / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat results / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each results / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 10.2 Design goals

We now examine results / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with results / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat results / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each results / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about results / design goals rather than trusting a rendered dashboard.

We now examine results / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with results / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat results / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each results / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

The reviewer-load objective is minimized subject to a bounded escape rate:

$$
\min_{\theta} \; \mathbb{E}_{x \sim \mathcal{D}}\big[ L(f_\theta(x), y) \big]
\quad \text{s.t.} \quad \Pr[\text{escape}] = \int_{\Omega} q(\omega)\, d\omega \le \epsilon
$$

where the per-step cost decomposes as $C = \sum_{i=1}^{n} p_i u_i$ and the undo penalty $\rho(a) = P(\text{wrong}) \times \text{cost-to-undo}(a)$ gates delegation whenever $\rho(a) > \kappa$.

### 10.3 Non-goals

We now examine results / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with results / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat results / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each results / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about results / non-goals rather than trusting a rendered dashboard.

We now examine results / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with results / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat results / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each results / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 10.4 Formal statement

We now examine results / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with results / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat results / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each results / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about results / formal statement rather than trusting a rendered dashboard.

We now examine results / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with results / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat results / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each results / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

| System | Anchor model | Survives insert | Survives delete | Notes |
| --- | --- | --- | --- | --- |
| LineRef v1 | line number | no | no | breaks on any upstream edit |
| ByteOffset | absolute offset | no | no | brittle under reflow |
| PrefixSuffix (ours) | context window | yes | mostly | ambiguous on duplicates |
| BlockIndex | structural index | partial | partial | needs stable parse |
| Hybrid (ours+block) | context + block | yes | yes | best observed stability |

### 10.5 Worked example

We now examine results / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with results / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat results / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each results / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about results / worked example rather than trusting a rendered dashboard.

We now examine results / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with results / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat results / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each results / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 10.6 Correctness argument

We now examine results / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with results / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat results / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each results / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about results / correctness argument rather than trusting a rendered dashboard.

We now examine results / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with results / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat results / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each results / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

```python
def resolve_anchor(quote, body, locator):
    """Resolve a comment anchor by prefix/suffix context.
    Returns the character index in `body` or -1 when ambiguous.
    """
    matches = []
    cursor = 0
    while cursor <= len(body) - len(quote):
        found = body.find(quote, cursor)
        if found < 0:
            break
        matches.append(found)
        cursor = found + max(len(quote), 1)
    if len(matches) == 1:
        return matches[0]
    prefix = (locator.get('prefix') or '')[-160:]
    suffix = (locator.get('suffix') or '')[:160]
    scored = []
    for idx in matches:
        score = 0
        if prefix and body[max(0, idx - len(prefix)):idx] == prefix:
            score += 2
        if suffix and body[idx + len(quote): idx + len(quote) + len(suffix)] == suffix:
            score += 2
        scored.append((score, idx))
    scored.sort(reverse=True)
    if not scored[0][0] or (len(scored) > 1 and scored[1][0] == scored[0][0]):
        return -1
    return scored[0][1]
```

### 10.7 Complexity

We now examine results / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with results / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat results / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each results / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about results / complexity rather than trusting a rendered dashboard.

We now examine results / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with results / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat results / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each results / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

As shown in Equation for section 10, the inline bound $O(n \log n)$ holds because each anchor touches $\lceil \log_2 n \rceil$ blocks. The normalized residual is $\hat{r} = \frac{\lVert x - \bar x \rVert_2}{\sigma}$.

### 10.8 Practical caveats

We now examine results / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with results / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat results / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each results / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about results / practical caveats rather than trusting a rendered dashboard.

We now examine results / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with results / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat results / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each results / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

---

## 11. Ablation Studies

We now examine ablation studies in the context of reproducible multi-agent pipelines.

The central difficulty with ablation studies is that provenance must survive edits without breaking anchors.

Prior systems treat ablation studies as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each ablation studies observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about ablation studies rather than trusting a rendered dashboard.

We now examine ablation studies in the context of reproducible multi-agent pipelines.

The central difficulty with ablation studies is that provenance must survive edits without breaking anchors.

Prior systems treat ablation studies as a static field, but our decision-stream model treats it as an append-only event ledger.

### 11.1 Motivation

We now examine ablation studies / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with ablation studies / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat ablation studies / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each ablation studies / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about ablation studies / motivation rather than trusting a rendered dashboard.

We now examine ablation studies / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with ablation studies / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat ablation studies / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each ablation studies / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 11.2 Design goals

We now examine ablation studies / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with ablation studies / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat ablation studies / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each ablation studies / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about ablation studies / design goals rather than trusting a rendered dashboard.

We now examine ablation studies / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with ablation studies / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat ablation studies / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each ablation studies / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

The reviewer-load objective is minimized subject to a bounded escape rate:

$$
\min_{\theta} \; \mathbb{E}_{x \sim \mathcal{D}}\big[ L(f_\theta(x), y) \big]
\quad \text{s.t.} \quad \Pr[\text{escape}] = \int_{\Omega} q(\omega)\, d\omega \le \epsilon
$$

where the per-step cost decomposes as $C = \sum_{i=1}^{n} p_i u_i$ and the undo penalty $\rho(a) = P(\text{wrong}) \times \text{cost-to-undo}(a)$ gates delegation whenever $\rho(a) > \kappa$.

### 11.3 Non-goals

We now examine ablation studies / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with ablation studies / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat ablation studies / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each ablation studies / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about ablation studies / non-goals rather than trusting a rendered dashboard.

We now examine ablation studies / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with ablation studies / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat ablation studies / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each ablation studies / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 11.4 Formal statement

We now examine ablation studies / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with ablation studies / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat ablation studies / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each ablation studies / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about ablation studies / formal statement rather than trusting a rendered dashboard.

We now examine ablation studies / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with ablation studies / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat ablation studies / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each ablation studies / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

| System | Anchor model | Survives insert | Survives delete | Notes |
| --- | --- | --- | --- | --- |
| LineRef v1 | line number | no | no | breaks on any upstream edit |
| ByteOffset | absolute offset | no | no | brittle under reflow |
| PrefixSuffix (ours) | context window | yes | mostly | ambiguous on duplicates |
| BlockIndex | structural index | partial | partial | needs stable parse |
| Hybrid (ours+block) | context + block | yes | yes | best observed stability |

### 11.5 Worked example

We now examine ablation studies / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with ablation studies / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat ablation studies / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each ablation studies / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about ablation studies / worked example rather than trusting a rendered dashboard.

We now examine ablation studies / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with ablation studies / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat ablation studies / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each ablation studies / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 11.6 Correctness argument

We now examine ablation studies / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with ablation studies / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat ablation studies / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each ablation studies / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about ablation studies / correctness argument rather than trusting a rendered dashboard.

We now examine ablation studies / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with ablation studies / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat ablation studies / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each ablation studies / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

```javascript
// atomic write contract used by the thin backend
async function saveDoc(path, body, baseRev) {
  const res = await fetch('/api/doc', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, body, base_rev: baseRev }),
  });
  return res.json();
}
```

### 11.7 Complexity

We now examine ablation studies / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with ablation studies / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat ablation studies / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each ablation studies / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about ablation studies / complexity rather than trusting a rendered dashboard.

We now examine ablation studies / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with ablation studies / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat ablation studies / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each ablation studies / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

As shown in Equation for section 11, the inline bound $O(n \log n)$ holds because each anchor touches $\lceil \log_2 n \rceil$ blocks. The normalized residual is $\hat{r} = \frac{\lVert x - \bar x \rVert_2}{\sigma}$.

### 11.8 Practical caveats

We now examine ablation studies / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with ablation studies / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat ablation studies / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each ablation studies / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about ablation studies / practical caveats rather than trusting a rendered dashboard.

We now examine ablation studies / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with ablation studies / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat ablation studies / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each ablation studies / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

---

## 12. Discussion

We now examine discussion in the context of reproducible multi-agent pipelines.

The central difficulty with discussion is that provenance must survive edits without breaking anchors.

Prior systems treat discussion as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each discussion observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about discussion rather than trusting a rendered dashboard.

We now examine discussion in the context of reproducible multi-agent pipelines.

The central difficulty with discussion is that provenance must survive edits without breaking anchors.

Prior systems treat discussion as a static field, but our decision-stream model treats it as an append-only event ledger.

### 12.1 Motivation

We now examine discussion / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with discussion / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat discussion / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each discussion / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about discussion / motivation rather than trusting a rendered dashboard.

We now examine discussion / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with discussion / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat discussion / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each discussion / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 12.2 Design goals

We now examine discussion / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with discussion / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat discussion / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each discussion / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about discussion / design goals rather than trusting a rendered dashboard.

We now examine discussion / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with discussion / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat discussion / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each discussion / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

The reviewer-load objective is minimized subject to a bounded escape rate:

$$
\min_{\theta} \; \mathbb{E}_{x \sim \mathcal{D}}\big[ L(f_\theta(x), y) \big]
\quad \text{s.t.} \quad \Pr[\text{escape}] = \int_{\Omega} q(\omega)\, d\omega \le \epsilon
$$

where the per-step cost decomposes as $C = \sum_{i=1}^{n} p_i u_i$ and the undo penalty $\rho(a) = P(\text{wrong}) \times \text{cost-to-undo}(a)$ gates delegation whenever $\rho(a) > \kappa$.

### 12.3 Non-goals

We now examine discussion / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with discussion / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat discussion / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each discussion / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about discussion / non-goals rather than trusting a rendered dashboard.

We now examine discussion / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with discussion / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat discussion / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each discussion / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 12.4 Formal statement

We now examine discussion / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with discussion / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat discussion / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each discussion / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about discussion / formal statement rather than trusting a rendered dashboard.

We now examine discussion / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with discussion / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat discussion / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each discussion / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

| System | Anchor model | Survives insert | Survives delete | Notes |
| --- | --- | --- | --- | --- |
| LineRef v1 | line number | no | no | breaks on any upstream edit |
| ByteOffset | absolute offset | no | no | brittle under reflow |
| PrefixSuffix (ours) | context window | yes | mostly | ambiguous on duplicates |
| BlockIndex | structural index | partial | partial | needs stable parse |
| Hybrid (ours+block) | context + block | yes | yes | best observed stability |

### 12.5 Worked example

We now examine discussion / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with discussion / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat discussion / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each discussion / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about discussion / worked example rather than trusting a rendered dashboard.

We now examine discussion / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with discussion / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat discussion / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each discussion / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 12.6 Correctness argument

We now examine discussion / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with discussion / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat discussion / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each discussion / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about discussion / correctness argument rather than trusting a rendered dashboard.

We now examine discussion / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with discussion / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat discussion / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each discussion / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

```python
def resolve_anchor(quote, body, locator):
    """Resolve a comment anchor by prefix/suffix context.
    Returns the character index in `body` or -1 when ambiguous.
    """
    matches = []
    cursor = 0
    while cursor <= len(body) - len(quote):
        found = body.find(quote, cursor)
        if found < 0:
            break
        matches.append(found)
        cursor = found + max(len(quote), 1)
    if len(matches) == 1:
        return matches[0]
    prefix = (locator.get('prefix') or '')[-160:]
    suffix = (locator.get('suffix') or '')[:160]
    scored = []
    for idx in matches:
        score = 0
        if prefix and body[max(0, idx - len(prefix)):idx] == prefix:
            score += 2
        if suffix and body[idx + len(quote): idx + len(quote) + len(suffix)] == suffix:
            score += 2
        scored.append((score, idx))
    scored.sort(reverse=True)
    if not scored[0][0] or (len(scored) > 1 and scored[1][0] == scored[0][0]):
        return -1
    return scored[0][1]
```

### 12.7 Complexity

We now examine discussion / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with discussion / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat discussion / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each discussion / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about discussion / complexity rather than trusting a rendered dashboard.

We now examine discussion / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with discussion / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat discussion / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each discussion / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

As shown in Equation for section 12, the inline bound $O(n \log n)$ holds because each anchor touches $\lceil \log_2 n \rceil$ blocks. The normalized residual is $\hat{r} = \frac{\lVert x - \bar x \rVert_2}{\sigma}$.

### 12.8 Practical caveats

We now examine discussion / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with discussion / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat discussion / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each discussion / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about discussion / practical caveats rather than trusting a rendered dashboard.

We now examine discussion / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with discussion / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat discussion / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each discussion / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

---

## 13. Limitations

We now examine limitations in the context of reproducible multi-agent pipelines.

The central difficulty with limitations is that provenance must survive edits without breaking anchors.

Prior systems treat limitations as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each limitations observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about limitations rather than trusting a rendered dashboard.

We now examine limitations in the context of reproducible multi-agent pipelines.

The central difficulty with limitations is that provenance must survive edits without breaking anchors.

Prior systems treat limitations as a static field, but our decision-stream model treats it as an append-only event ledger.

### 13.1 Motivation

We now examine limitations / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with limitations / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat limitations / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each limitations / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about limitations / motivation rather than trusting a rendered dashboard.

We now examine limitations / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with limitations / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat limitations / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each limitations / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 13.2 Design goals

We now examine limitations / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with limitations / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat limitations / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each limitations / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about limitations / design goals rather than trusting a rendered dashboard.

We now examine limitations / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with limitations / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat limitations / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each limitations / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

The reviewer-load objective is minimized subject to a bounded escape rate:

$$
\min_{\theta} \; \mathbb{E}_{x \sim \mathcal{D}}\big[ L(f_\theta(x), y) \big]
\quad \text{s.t.} \quad \Pr[\text{escape}] = \int_{\Omega} q(\omega)\, d\omega \le \epsilon
$$

where the per-step cost decomposes as $C = \sum_{i=1}^{n} p_i u_i$ and the undo penalty $\rho(a) = P(\text{wrong}) \times \text{cost-to-undo}(a)$ gates delegation whenever $\rho(a) > \kappa$.

### 13.3 Non-goals

We now examine limitations / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with limitations / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat limitations / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each limitations / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about limitations / non-goals rather than trusting a rendered dashboard.

We now examine limitations / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with limitations / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat limitations / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each limitations / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 13.4 Formal statement

We now examine limitations / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with limitations / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat limitations / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each limitations / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about limitations / formal statement rather than trusting a rendered dashboard.

We now examine limitations / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with limitations / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat limitations / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each limitations / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

| System | Anchor model | Survives insert | Survives delete | Notes |
| --- | --- | --- | --- | --- |
| LineRef v1 | line number | no | no | breaks on any upstream edit |
| ByteOffset | absolute offset | no | no | brittle under reflow |
| PrefixSuffix (ours) | context window | yes | mostly | ambiguous on duplicates |
| BlockIndex | structural index | partial | partial | needs stable parse |
| Hybrid (ours+block) | context + block | yes | yes | best observed stability |

### 13.5 Worked example

We now examine limitations / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with limitations / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat limitations / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each limitations / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about limitations / worked example rather than trusting a rendered dashboard.

We now examine limitations / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with limitations / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat limitations / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each limitations / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 13.6 Correctness argument

We now examine limitations / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with limitations / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat limitations / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each limitations / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about limitations / correctness argument rather than trusting a rendered dashboard.

We now examine limitations / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with limitations / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat limitations / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each limitations / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

```javascript
// atomic write contract used by the thin backend
async function saveDoc(path, body, baseRev) {
  const res = await fetch('/api/doc', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, body, base_rev: baseRev }),
  });
  return res.json();
}
```

### 13.7 Complexity

We now examine limitations / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with limitations / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat limitations / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each limitations / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about limitations / complexity rather than trusting a rendered dashboard.

We now examine limitations / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with limitations / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat limitations / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each limitations / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

As shown in Equation for section 13, the inline bound $O(n \log n)$ holds because each anchor touches $\lceil \log_2 n \rceil$ blocks. The normalized residual is $\hat{r} = \frac{\lVert x - \bar x \rVert_2}{\sigma}$.

### 13.8 Practical caveats

We now examine limitations / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with limitations / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat limitations / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each limitations / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about limitations / practical caveats rather than trusting a rendered dashboard.

We now examine limitations / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with limitations / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat limitations / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each limitations / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

---

## 14. Future Work

We now examine future work in the context of reproducible multi-agent pipelines.

The central difficulty with future work is that provenance must survive edits without breaking anchors.

Prior systems treat future work as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each future work observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about future work rather than trusting a rendered dashboard.

We now examine future work in the context of reproducible multi-agent pipelines.

The central difficulty with future work is that provenance must survive edits without breaking anchors.

Prior systems treat future work as a static field, but our decision-stream model treats it as an append-only event ledger.

### 14.1 Motivation

We now examine future work / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with future work / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat future work / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each future work / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about future work / motivation rather than trusting a rendered dashboard.

We now examine future work / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with future work / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat future work / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each future work / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 14.2 Design goals

We now examine future work / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with future work / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat future work / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each future work / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about future work / design goals rather than trusting a rendered dashboard.

We now examine future work / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with future work / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat future work / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each future work / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

The reviewer-load objective is minimized subject to a bounded escape rate:

$$
\min_{\theta} \; \mathbb{E}_{x \sim \mathcal{D}}\big[ L(f_\theta(x), y) \big]
\quad \text{s.t.} \quad \Pr[\text{escape}] = \int_{\Omega} q(\omega)\, d\omega \le \epsilon
$$

where the per-step cost decomposes as $C = \sum_{i=1}^{n} p_i u_i$ and the undo penalty $\rho(a) = P(\text{wrong}) \times \text{cost-to-undo}(a)$ gates delegation whenever $\rho(a) > \kappa$.

### 14.3 Non-goals

We now examine future work / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with future work / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat future work / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each future work / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about future work / non-goals rather than trusting a rendered dashboard.

We now examine future work / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with future work / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat future work / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each future work / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 14.4 Formal statement

We now examine future work / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with future work / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat future work / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each future work / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about future work / formal statement rather than trusting a rendered dashboard.

We now examine future work / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with future work / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat future work / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each future work / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

| System | Anchor model | Survives insert | Survives delete | Notes |
| --- | --- | --- | --- | --- |
| LineRef v1 | line number | no | no | breaks on any upstream edit |
| ByteOffset | absolute offset | no | no | brittle under reflow |
| PrefixSuffix (ours) | context window | yes | mostly | ambiguous on duplicates |
| BlockIndex | structural index | partial | partial | needs stable parse |
| Hybrid (ours+block) | context + block | yes | yes | best observed stability |

### 14.5 Worked example

We now examine future work / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with future work / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat future work / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each future work / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about future work / worked example rather than trusting a rendered dashboard.

We now examine future work / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with future work / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat future work / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each future work / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 14.6 Correctness argument

We now examine future work / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with future work / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat future work / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each future work / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about future work / correctness argument rather than trusting a rendered dashboard.

We now examine future work / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with future work / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat future work / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each future work / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

```python
def resolve_anchor(quote, body, locator):
    """Resolve a comment anchor by prefix/suffix context.
    Returns the character index in `body` or -1 when ambiguous.
    """
    matches = []
    cursor = 0
    while cursor <= len(body) - len(quote):
        found = body.find(quote, cursor)
        if found < 0:
            break
        matches.append(found)
        cursor = found + max(len(quote), 1)
    if len(matches) == 1:
        return matches[0]
    prefix = (locator.get('prefix') or '')[-160:]
    suffix = (locator.get('suffix') or '')[:160]
    scored = []
    for idx in matches:
        score = 0
        if prefix and body[max(0, idx - len(prefix)):idx] == prefix:
            score += 2
        if suffix and body[idx + len(quote): idx + len(quote) + len(suffix)] == suffix:
            score += 2
        scored.append((score, idx))
    scored.sort(reverse=True)
    if not scored[0][0] or (len(scored) > 1 and scored[1][0] == scored[0][0]):
        return -1
    return scored[0][1]
```

### 14.7 Complexity

We now examine future work / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with future work / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat future work / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each future work / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about future work / complexity rather than trusting a rendered dashboard.

We now examine future work / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with future work / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat future work / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each future work / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

As shown in Equation for section 14, the inline bound $O(n \log n)$ holds because each anchor touches $\lceil \log_2 n \rceil$ blocks. The normalized residual is $\hat{r} = \frac{\lVert x - \bar x \rVert_2}{\sigma}$.

### 14.8 Practical caveats

We now examine future work / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with future work / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat future work / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each future work / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about future work / practical caveats rather than trusting a rendered dashboard.

We now examine future work / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with future work / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat future work / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each future work / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

---

## 15. Conclusion

We now examine conclusion in the context of reproducible multi-agent pipelines.

The central difficulty with conclusion is that provenance must survive edits without breaking anchors.

Prior systems treat conclusion as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each conclusion observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about conclusion rather than trusting a rendered dashboard.

We now examine conclusion in the context of reproducible multi-agent pipelines.

The central difficulty with conclusion is that provenance must survive edits without breaking anchors.

Prior systems treat conclusion as a static field, but our decision-stream model treats it as an append-only event ledger.

### 15.1 Motivation

We now examine conclusion / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with conclusion / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat conclusion / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each conclusion / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about conclusion / motivation rather than trusting a rendered dashboard.

We now examine conclusion / motivation in the context of reproducible multi-agent pipelines.

The central difficulty with conclusion / motivation is that provenance must survive edits without breaking anchors.

Prior systems treat conclusion / motivation as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each conclusion / motivation observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 15.2 Design goals

We now examine conclusion / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with conclusion / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat conclusion / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each conclusion / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about conclusion / design goals rather than trusting a rendered dashboard.

We now examine conclusion / design goals in the context of reproducible multi-agent pipelines.

The central difficulty with conclusion / design goals is that provenance must survive edits without breaking anchors.

Prior systems treat conclusion / design goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each conclusion / design goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

The reviewer-load objective is minimized subject to a bounded escape rate:

$$
\min_{\theta} \; \mathbb{E}_{x \sim \mathcal{D}}\big[ L(f_\theta(x), y) \big]
\quad \text{s.t.} \quad \Pr[\text{escape}] = \int_{\Omega} q(\omega)\, d\omega \le \epsilon
$$

where the per-step cost decomposes as $C = \sum_{i=1}^{n} p_i u_i$ and the undo penalty $\rho(a) = P(\text{wrong}) \times \text{cost-to-undo}(a)$ gates delegation whenever $\rho(a) > \kappa$.

### 15.3 Non-goals

We now examine conclusion / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with conclusion / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat conclusion / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each conclusion / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about conclusion / non-goals rather than trusting a rendered dashboard.

We now examine conclusion / non-goals in the context of reproducible multi-agent pipelines.

The central difficulty with conclusion / non-goals is that provenance must survive edits without breaking anchors.

Prior systems treat conclusion / non-goals as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each conclusion / non-goals observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 15.4 Formal statement

We now examine conclusion / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with conclusion / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat conclusion / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each conclusion / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about conclusion / formal statement rather than trusting a rendered dashboard.

We now examine conclusion / formal statement in the context of reproducible multi-agent pipelines.

The central difficulty with conclusion / formal statement is that provenance must survive edits without breaking anchors.

Prior systems treat conclusion / formal statement as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each conclusion / formal statement observation is recorded with an actor, a timestamp, and a falsifiable summary.

| System | Anchor model | Survives insert | Survives delete | Notes |
| --- | --- | --- | --- | --- |
| LineRef v1 | line number | no | no | breaks on any upstream edit |
| ByteOffset | absolute offset | no | no | brittle under reflow |
| PrefixSuffix (ours) | context window | yes | mostly | ambiguous on duplicates |
| BlockIndex | structural index | partial | partial | needs stable parse |
| Hybrid (ours+block) | context + block | yes | yes | best observed stability |

### 15.5 Worked example

We now examine conclusion / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with conclusion / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat conclusion / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each conclusion / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about conclusion / worked example rather than trusting a rendered dashboard.

We now examine conclusion / worked example in the context of reproducible multi-agent pipelines.

The central difficulty with conclusion / worked example is that provenance must survive edits without breaking anchors.

Prior systems treat conclusion / worked example as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each conclusion / worked example observation is recorded with an actor, a timestamp, and a falsifiable summary.

### 15.6 Correctness argument

We now examine conclusion / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with conclusion / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat conclusion / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each conclusion / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about conclusion / correctness argument rather than trusting a rendered dashboard.

We now examine conclusion / correctness argument in the context of reproducible multi-agent pipelines.

The central difficulty with conclusion / correctness argument is that provenance must survive edits without breaking anchors.

Prior systems treat conclusion / correctness argument as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each conclusion / correctness argument observation is recorded with an actor, a timestamp, and a falsifiable summary.

```javascript
// atomic write contract used by the thin backend
async function saveDoc(path, body, baseRev) {
  const res = await fetch('/api/doc', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, body, base_rev: baseRev }),
  });
  return res.json();
}
```

### 15.7 Complexity

We now examine conclusion / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with conclusion / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat conclusion / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each conclusion / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about conclusion / complexity rather than trusting a rendered dashboard.

We now examine conclusion / complexity in the context of reproducible multi-agent pipelines.

The central difficulty with conclusion / complexity is that provenance must survive edits without breaking anchors.

Prior systems treat conclusion / complexity as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each conclusion / complexity observation is recorded with an actor, a timestamp, and a falsifiable summary.

As shown in Equation for section 15, the inline bound $O(n \log n)$ holds because each anchor touches $\lceil \log_2 n \rceil$ blocks. The normalized residual is $\hat{r} = \frac{\lVert x - \bar x \rVert_2}{\sigma}$.

### 15.8 Practical caveats

We now examine conclusion / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with conclusion / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat conclusion / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each conclusion / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

This lets a reviewer reconstruct why a given state was asserted about conclusion / practical caveats rather than trusting a rendered dashboard.

We now examine conclusion / practical caveats in the context of reproducible multi-agent pipelines.

The central difficulty with conclusion / practical caveats is that provenance must survive edits without breaking anchors.

Prior systems treat conclusion / practical caveats as a static field, but our decision-stream model treats it as an append-only event ledger.

Concretely, each conclusion / practical caveats observation is recorded with an actor, a timestamp, and a falsifiable summary.

---

## References

[1] Author 1, et al. "A study of provenance component 1." Journal of Simulated Systems, vol. 1, no. 2, 2011.

[2] Author 2, et al. "A study of provenance component 2." Journal of Simulated Systems, vol. 2, no. 3, 2012.

[3] Author 3, et al. "A study of provenance component 3." Journal of Simulated Systems, vol. 3, no. 4, 2013.

[4] Author 4, et al. "A study of provenance component 4." Journal of Simulated Systems, vol. 4, no. 5, 2014.

[5] Author 5, et al. "A study of provenance component 5." Journal of Simulated Systems, vol. 5, no. 1, 2015.

[6] Author 6, et al. "A study of provenance component 6." Journal of Simulated Systems, vol. 6, no. 2, 2016.

[7] Author 7, et al. "A study of provenance component 7." Journal of Simulated Systems, vol. 7, no. 3, 2017.

[8] Author 8, et al. "A study of provenance component 8." Journal of Simulated Systems, vol. 8, no. 4, 2018.

[9] Author 9, et al. "A study of provenance component 9." Journal of Simulated Systems, vol. 9, no. 5, 2019.

[10] Author 10, et al. "A study of provenance component 10." Journal of Simulated Systems, vol. 10, no. 1, 2020.

[11] Author 11, et al. "A study of provenance component 11." Journal of Simulated Systems, vol. 11, no. 2, 2021.

[12] Author 12, et al. "A study of provenance component 12." Journal of Simulated Systems, vol. 12, no. 3, 2022.

[13] Author 13, et al. "A study of provenance component 13." Journal of Simulated Systems, vol. 13, no. 4, 2023.

[14] Author 14, et al. "A study of provenance component 14." Journal of Simulated Systems, vol. 14, no. 5, 2024.

[15] Author 15, et al. "A study of provenance component 15." Journal of Simulated Systems, vol. 15, no. 1, 2010.

[16] Author 16, et al. "A study of provenance component 16." Journal of Simulated Systems, vol. 16, no. 2, 2011.

[17] Author 17, et al. "A study of provenance component 17." Journal of Simulated Systems, vol. 17, no. 3, 2012.

[18] Author 18, et al. "A study of provenance component 18." Journal of Simulated Systems, vol. 18, no. 4, 2013.

[19] Author 19, et al. "A study of provenance component 19." Journal of Simulated Systems, vol. 19, no. 5, 2014.

[20] Author 20, et al. "A study of provenance component 20." Journal of Simulated Systems, vol. 20, no. 1, 2015.

[21] Author 21, et al. "A study of provenance component 21." Journal of Simulated Systems, vol. 21, no. 2, 2016.

[22] Author 22, et al. "A study of provenance component 22." Journal of Simulated Systems, vol. 22, no. 3, 2017.

[23] Author 23, et al. "A study of provenance component 23." Journal of Simulated Systems, vol. 23, no. 4, 2018.

[24] Author 24, et al. "A study of provenance component 24." Journal of Simulated Systems, vol. 24, no. 5, 2019.

[25] Author 25, et al. "A study of provenance component 25." Journal of Simulated Systems, vol. 25, no. 1, 2020.

[26] Author 26, et al. "A study of provenance component 26." Journal of Simulated Systems, vol. 26, no. 2, 2021.

[27] Author 27, et al. "A study of provenance component 27." Journal of Simulated Systems, vol. 27, no. 3, 2022.

[28] Author 28, et al. "A study of provenance component 28." Journal of Simulated Systems, vol. 28, no. 4, 2023.

[29] Author 29, et al. "A study of provenance component 29." Journal of Simulated Systems, vol. 29, no. 5, 2024.

[30] Author 30, et al. "A study of provenance component 30." Journal of Simulated Systems, vol. 30, no. 1, 2010.

[31] Author 31, et al. "A study of provenance component 31." Journal of Simulated Systems, vol. 31, no. 2, 2011.

[32] Author 32, et al. "A study of provenance component 32." Journal of Simulated Systems, vol. 32, no. 3, 2012.

[33] Author 33, et al. "A study of provenance component 33." Journal of Simulated Systems, vol. 33, no. 4, 2013.

[34] Author 34, et al. "A study of provenance component 34." Journal of Simulated Systems, vol. 34, no. 5, 2014.

[35] Author 35, et al. "A study of provenance component 35." Journal of Simulated Systems, vol. 35, no. 1, 2015.

[36] Author 36, et al. "A study of provenance component 36." Journal of Simulated Systems, vol. 36, no. 2, 2016.

[37] Author 37, et al. "A study of provenance component 37." Journal of Simulated Systems, vol. 37, no. 3, 2017.

[38] Author 38, et al. "A study of provenance component 38." Journal of Simulated Systems, vol. 38, no. 4, 2018.

[39] Author 39, et al. "A study of provenance component 39." Journal of Simulated Systems, vol. 39, no. 5, 2019.

[40] Author 40, et al. "A study of provenance component 40." Journal of Simulated Systems, vol. 40, no. 1, 2020.

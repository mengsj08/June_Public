<!--
Bundled compatibility copy for portable Comma Review Studio alpha runs.
Source identity: Deer Flow academic-paper-review compatibility reference
Original sha256: sha256:3b247cac76feb8508445cb3b1eaa8d68f4bbb57a8eed74f47e4c512185352a48
-->

---
name: academic-paper-review
description: Use this skill when the user asks to review, analyze, critique, summarize, assess, or peer-review a single academic paper, preprint, or scientific article. Trigger on paper URLs, arXiv links, uploaded PDFs, DOI links, or requests like "review this paper", "analyze this research", "summarize this study", or "write a peer review".
---

# Academic Paper Review

## Overview

This skill produces a structured, peer-review-style analysis of a single academic paper.

It is designed for depth on one paper, not breadth across many papers.

Source note:
- Imported for ResearchLab from Deer Flow public skills
- Upstream repository: `https://github.com/bytedance/deer-flow`
- Installed as a project-local compatibility copy for `ResearchLab`

## When To Use

Use this skill when:

- the user provides one paper URL or PDF
- the user asks to review or critique one paper
- the user wants a structured academic analysis
- the user wants strengths, weaknesses, novelty, rigor, and improvement suggestions

Do not use it for multi-paper literature surveys; use `systematic-literature-review` for those.

## Review Workflow

### Phase 1: Paper Comprehension

Read the paper carefully before judging it.

Extract:

- title
- authors
- venue or status
- year
- domain
- paper type

Then understand:

1. abstract and introduction
2. related work
3. methodology
4. experiments and results
5. limitations and discussion
6. conclusion and whether it matches the evidence

### Phase 2: Key Claims

List the major claims and the evidence supporting them.

For each claim, assess whether support is:

- strong
- moderate
- weak

### Phase 3: Critical Analysis

Assess:

- soundness
- novelty
- reproducibility
- experimental design
- statistical rigor
- scalability or practicality

If appropriate, do targeted literature lookup to position the paper relative to nearby work.

### Phase 4: Structured Review

The final review should usually include:

1. Paper metadata
2. Executive summary
3. Summary of contributions
4. Strengths
5. Weaknesses
6. Methodology assessment
7. Questions for the authors
8. Minor issues
9. Literature positioning
10. Recommendations

## Review Principles

- Be specific and evidence-based
- Distinguish fatal flaws from fixable issues
- Give credit where it is due
- Suggest how weaknesses could be addressed
- Evaluate the submitted work, not the paper you wish existed

## Output Template

```markdown
# Paper Review: <Paper Title>

## Paper Metadata
- Authors:
- Venue:
- Year:
- Domain:
- Paper Type:

## Executive Summary

<2-3 paragraph review summary>

## Summary of Contributions

1. ...
2. ...
3. ...

## Strengths

### S1: <title>
...

## Weaknesses

### W1: <title>
...

## Methodology Assessment

| Criterion | Rating (1-5) | Assessment |
|-----------|:---:|------------|
| Soundness | X | ... |
| Novelty | X | ... |
| Reproducibility | X | ... |
| Experimental Design | X | ... |
| Statistical Rigor | X | ... |
| Scalability | X | ... |

## Questions for the Authors

1. ...
2. ...
3. ...

## Minor Issues

- ...

## Literature Positioning

...

## Recommendations

**Overall Assessment**: Accept / Weak Accept / Borderline / Weak Reject / Reject

**Confidence**: High / Medium / Low

**Contribution Level**: Landmark / Significant / Moderate / Marginal / Below threshold

### Actionable Suggestions for Improvement
1. ...
2. ...
3. ...
```

## Important Note

If the user asks for a broader topic survey rather than a one-paper critique, switch to `systematic-literature-review` instead of forcing a single-paper template.

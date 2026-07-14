# AI Governance Skills

- [`skill-ecosystem-adapters/`](skill-ecosystem-adapters/) - Cross-ecosystem Skill inventory and runtime-state adapters for Codex, Claude, WorkBuddy, BigApple, and generic filesystem-backed tools. The package keeps asset identity, native runtime state, and verification evidence separate; mutation is limited to capabilities verified by the target ecosystem.
- [`skill-governance-methodology.md`](skill-governance-methodology.md) - Methodology article (中文): how to turn a pile of AI skills into a governable system. Covers separating intent / runtime state / execution evidence, asset-vs-deployment identity, capability evidence tiers, human-only decision boundaries, and independently verified "success". Pairs with `skill-ecosystem-adapters/` as the runnable companion.

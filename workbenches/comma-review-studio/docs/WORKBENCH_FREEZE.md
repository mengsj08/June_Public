# Academic Paper Review Workbench Freeze

Status: feature frozen as of SKL-102 Gate 0.

`academic-paper-review-workbench` remains available during the Comma Review
Agent migration, but it is no longer a target for new product functionality.
Do not add new upload-page, result-page, run-list, or legacy editing-workbench
features there while this freeze is in effect.

The canonical Skill, historical runs, and BigApple entry remain usable. This
freeze does not delete, move, rewrite, or automatically migrate historical
Workbench data, and it does not change the Workbench runtime behavior.

Basis: SKL-102 Gate 0, which keeps the old Workbench runnable while Comma Review
Studio is prepared to host Academic Paper Review as a Review Agent.

Release condition: the freeze can be replaced by the thin-launcher/archive plan
only after SKL-102 Gate 4 passes and June accepts the migration.

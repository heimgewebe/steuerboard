# Neuer Masterplan: steuerboard

## Leitidee

steuerboard ist eine lokale Action-Control-Surface und ein Sicherheitsmechanismus
für Arbeitsgeräte-Operationen.

Git-Repositoriesynchronisation ist die erste Action-Domain.
Omnipull bleibt ein Integrationspfad, aber nicht das ganze Produkt.

Es erzeugt keine kanonische Wahrheit, aber es erzeugt prüfbare operative Ableitungen.

Daher gilt:

> Beobachtung ≠ Ableitung ≠ Entscheidung ≠ Aktion

Das ist der wichtigste Satz des Plans.

steuerboard darf Beobachtung, Assessment, Plan, Approval, Execution und Record
nicht zu einem Schritt zusammenziehen.

## Action Classes

- Git-Aktionen:
  erste Action-Domain; umfasst künftig fetch-only Refresh, switch-main Planning
  und gated fast-forward pull.
- File-Aktionen:
  künftig gated, redaction-aware, ohne breite Home-Folder-Mutation als Default.
- Service-Aktionen:
  künftig gated, mit expliziter Service-Identität und verpflichtendem Postcheck.
- Runbook-/Netzwerkchecks:
  künftig zunächst überwiegend read-only; Mutation erst nach Capability-Gates.

## Canonical Action Chain

Observe
→ Assess
→ Plan
→ Approve
→ Execute
→ Record
→ Explain

- `git pull --ff-only` ist der erste mutierende Pilotkandidat.
- Git pull darf kein Shortcut werden.
- Pull ist nur nach Assessment, Plan, Approval, Execution Trace, Run-Result und
  Postcheck-Evidence zulässig.
- Diese Kette gilt für Single-Repo-Pull und für spätere Fleet-/Omnipull-Flows.

---

## 1. Kernprinzipien

### 1. Falsifikation vor Taxonomie

Nicht zuerst Statusnamen erfinden.

Zuerst sammeln:

- Was kann lokal schiefgehen?
- Welche Fälle hat omnipull bisher übersprungen?
- Welche Repos liegen mehrfach?
- Welche Git-Zustände sind gefährlich?
- Welche Rechte-/Owner-Probleme treten auf?
- Welche Evidence könnte sensible Daten enthalten?

Erst daraus entstehen Statusnamen.

---

### 2. Source-bound statt „steuerboard sagt“

Jede Aussage braucht Herkunft:

```json
{
  "claim": "repo_is_on_feature_branch",
  "observed_from": "git branch --show-current",
  "source_freshness": "fresh",
  "confidence": 0.98
}
```

Kein Source-Ref, kein Urteil.

---

### 3. Freshness-bound statt alte Wahrheit

Eine Quelle kann korrekt und trotzdem veraltet sein.

Beispiel:

- lokales metarepo/fleet/repos.yml ist 14 Tage alt
- letzter omnipull-Lauf war gestern
- origin/main wurde nicht frisch gefetcht
- GitHub ist nicht erreichbar

steuerboard muss sagen:

> Aussage möglich, aber Quelle veraltet. Für Aktion nicht ausreichend.

---

### 4. Evidence mit Redaction

Evidence ist nur gut, wenn sie nicht nebenbei private Daten einsammelt.

Also:

- keine Tokens
- keine Secrets
- keine vollständigen Diffs ungeprüft
- keine endlosen stdout/stderr-Dumps
- absolute private Pfade nur kontrolliert
- Redaction-Policy vor Evidence-Archiv

Eine Evidence-Sammlung ohne Redaction ist ein aufgeräumtes Datenleck. Sehr deutsch, aber trotzdem ein Datenleck.

---

### 5. Simulation vor Aktion

Jede mutierende Aktion braucht zuerst:

```bash
steuerboard plan <aktion>
```

Nicht:

```bash
steuerboard do <aktion>
```

Der Plan ist ein begrenztes Preview-/Derivationsartefakt, keine
Command-Empfehlung, keine Ausführung und keine Autorisierung.

Der Plan muss zeigen:

- welche Aktion und welches Zielobjekt bewertet wurden
- welche Blocker und fehlende Evidenz vorliegen
- welche Entscheidung im Preview-Kontrakt resultiert

---

## 2. Zielbild

steuerboard beantwortet:

- Welche Repos existieren lokal?
- Welche davon sind canonical, shadow, backup, unknown?
- Welche Repos gehören zur Fleet?
- Welche Repos sind dirty?
- Welche Repos sind auf Nicht-Default-Branches?
- Welche Repos sind ahead / behind / diverged?
- Welche Repos sind wegen Ownership/Rechten nicht sicher prüfbar?
- Welche Quellen sind frisch genug?
- Warum würde omnipull skippen?
- Welche Aktion wäre sicher?
- Welche Aktion ist blockiert?
- Welche Evidence existiert?
- Welche Evidence ist redacted und verifizierbar?

steuerboard ersetzt nicht:

- Git
- GitHub
- omnipull
- wgx
- metarepo
- infra
- Runbooks
- server-facts

steuerboard verbindet sie lokal, prüfend, begrenzt.

---

## 3. Architekturmodell

### Ebenen

```text
steuerboard
├─ 1. Falsification Layer
│    └─ reale / konstruierte Bruchfälle
├─ 2. Observation Layer
│    └─ Git, Filesystem, Logs, Config, Commands read-only
├─ 3. Source Layer
│    └─ Herkunft, Frische, Autorität
├─ 4. Assessment Layer
│    └─ Status, Risiko, Skip-Grund, Kohärenz
├─ 5. Planning Layer
│    └─ Simulation sicherer Aktionen
├─ 6. Evidence Layer
│    └─ redacted traces, run index, retention
├─ 7. Action Layer
│    └─ gated capabilities, später
└─ 8. UI Layer
     └─ reine Darstellung / Bedienadapter
```

Wichtig: Die UI steht ganz unten, nicht weil sie unwichtig ist, sondern weil sie sonst so tut, als wäre Darstellung schon Wahrheit.

---

## 4. Repo-Startstruktur

```text
steuerboard/
├─ README.md
├─ docs/
│  ├─ vision.md
│  ├─ architecture.md
│  ├─ falsification-cases.md
│  ├─ source-of-truth-model.md
│  ├─ freshness-model.md
│  ├─ local-scope-model.md
│  ├─ observation-model.md
│  ├─ assessment-model.md
│  ├─ action-model.md
│  ├─ approval-model.md
│  ├─ planning-model.md
│  ├─ evidence-model.md
│  ├─ redaction-model.md
│  ├─ retention-model.md
│  ├─ security-model.md
│  ├─ omnipull-integration.md
│  ├─ git-pull-ff-only-contract.md
│  ├─ remote-refresh-model.md
│  └─ roadmap.md
├─ schemas/
│  ├─ falsification-case.v1.schema.json
│  ├─ source-ref.v1.schema.json
│  ├─ local-config.v1.schema.json
│  ├─ repo-observation.v1.schema.json
│  ├─ repo-assessment.v1.schema.json
│  ├─ action-plan.v1.schema.json
│  ├─ action-approval.v1.schema.json
│  ├─ action-capability.v1.schema.json
│  ├─ command-trace.v1.schema.json
│  ├─ run-result.v1.schema.json
│  ├─ run-index.v1.schema.json
│  ├─ redaction-policy.v1.schema.json
│  └─ remote-refresh-result.v1.schema.json
├─ examples/
│  ├─ failure-cases/
│  ├─ observations/
│  ├─ assessments/
│  ├─ action-plans/
│  ├─ action-approvals/
│  ├─ evidence/
│  └─ remote-refresh-results/
│     ├─ fetch-origin-prune-success.json
│     └─ fetch-origin-prune-network-failed.json
├─ cli/
├─ backend/
├─ frontend/
├─ scripts/
└─ tests/
```

---

## 5. Phasenplan

### Phase -3 — Falsifikationskorpus

#### Ziel

Vor jedem Statusmodell echte oder konstruierte Bruchfälle sammeln.

#### Pflichtfälle

- duplicate_repo
- gdrive_shadow_repo
- backup_repo_accidentally_used
- dubious_ownership
- foreign_owner_present
- wrong_remote
- remote_missing
- remote_unreachable
- stale_metarepo
- stale_omnipull_log
- unknown_default_branch
- missing_upstream
- detached_head
- dirty_worktree
- dirty_submodule
- feature_branch_unmerged
- feature_branch_merged
- branch_local_only
- branch_remote_deleted
- ff_only_not_possible
- origin_main_stale
- omnipull_skip_unknown_reason
- evidence_contains_secret_like_pattern

#### Artefakte

- `docs/falsification-cases.md`
- `schemas/falsification-case.v1.schema.json`
- `examples/failure-cases/*.json`

#### Stop-Kriterium

Mindestens 12 Failure-Cases sind beschrieben, mit:

- Name
- Auslöser
- Erwartete Beobachtung
- Risiko
- Soll-Status
- Blockierte Aktionen
- Sichere Aktionen
- Benötigte Evidence

---

### Phase -2 — Quellen- und Scope-Modell

#### Ziel

steuerboard weiß, welche Quellen es lesen darf und wie autoritativ sie sind.

#### Dokumente

- `docs/source-of-truth-model.md`
- `docs/freshness-model.md`
- `docs/local-scope-model.md`

#### Zentrale Trennung

```text
canonical source      = metarepo, Git remote, wgx, omnipull JSON
local observation     = gemessener Zustand auf Gerät
derived assessment    = steuerboard-Ableitung
decision              = erlauben / blockieren / warnen
```

#### Beispiel: Source-Ref

```json
{
  "source_id": "git.current_branch",
  "authority": "observational",
  "command": "git branch --show-current",
  "freshness": "fresh",
  "usable_for_decision": true
}
```

#### Stop-Kriterium

Jedes geplante Statusfeld hat eine definierte Quelle oder ist explizit als Ableitung markiert.

---

### Phase -1 — Minimaler Schema-Kern

#### Ziel

Nur die Schemas bauen, die wirklich früh tragen.

#### Startschemas

- `falsification-case.v1`
- `source-ref.v1`
- `local-config.v1`
- `repo-observation.v1`
- `repo-assessment.v1`
- `action-plan.v1`
- `command-trace.v1`
- `run-result.v1`
- `redaction-policy.v1`

#### Noch nicht bauen

- UI-Schemas
- komplexe Runbook-Schemas
- Branch-Delete-Schemas
- Daemon-Schemas
- Remote-Action-Schemas

#### Stop-Kriterium

Alle Examples validieren gegen Schemas.

---

### Phase 0 — Repo anlegen

#### Erster Commit

Nur:

- `README.md`
- `docs/*`
- `schemas/*`
- `examples/*`
- `tests/schema_validation*`

Noch kein produktiver Scanner.

#### README-Kernsatz

> steuerboard is a local diagnostics and planning surface for workstation repository state, source freshness, omnipull reports, evidence snapshots, and gated local actions. It is not a canonical source of truth.

#### Stop-Kriterium

Der erste Commit definiert Grenzen, nicht Verhalten.

Code ohne Grenze ist Verhalten mit Sonnenbrille.

---

### Phase 1 — Read-only Observation CLI

#### Ziel

Nur beobachten. Nichts bewerten, nichts verändern.

#### Befehle

```bash
steuerboard observe --json
steuerboard observe repo heimgewebe/infra --json
```

#### Beobachtet

- path
- is_git_repo
- current_branch
- head
- dirty
- upstream
- ahead
- behind
- remote_url
- default_branch_candidate
- worktree_status
- submodule_status
- ownership_status
- git_status_exit

#### Wichtig

Noch kein `safe_actions`, noch kein `risk_level`.

Phase 1 sagt nur:

> Was wurde gemessen?

Nicht:

> Was bedeutet es?

#### Stop-Kriterium

Mindestens diese Zustände werden read-only erkannt:

- clean main
- dirty main
- feature branch
- missing upstream
- wrong remote
- dubious ownership
- detached head

---

### Phase 2 — Inventory & Scope

#### Ziel

steuerboard erkennt, ob ein Repo am richtigen Ort liegt.

#### Befehle

```bash
steuerboard inventory --json
steuerboard inventory duplicates
steuerboard scope explain heimgewebe/infra
```

#### Klassifikation

- scope_canonical
- scope_shadow
- scope_backup
- scope_gdrive
- scope_unknown
- scope_excluded

#### Local Config

```toml
[host]
name = "heim-pc"

[paths]
canonical_repo_roots = ["/home/alex/repos"]
excluded_repo_roots = [
  "/home/alex/GDrive/repos",
  "/home/alex/GDrive/backups",
  "/home/alex/_rollout_wgx_baseline"
]

[policy]
allow_mutating_actions = false
allow_branch_switch = false
allow_network_fetch = true
```

#### Stop-Kriterium

steuerboard kann zwischen echtem Arbeitsrepo, Backup, GDrive-Kopie und unbekanntem Klon unterscheiden.

---

### Phase 3 — Assessment Engine

#### Ziel

Aus Beobachtungen werden begründete Bewertungen.

#### Befehl

```bash
steuerboard assess --json
steuerboard assess repo heimgewebe/infra --json
```

#### Ausgabe trennt strikt

```json
{
  "observation_ref": "obs-20260508-001",
  "derived_status": "clean_feature_branch",
  "risk_level": "medium",
  "skip_reasons": ["non_default_branch"],
  "confidence": 0.91,
  "source_refs": ["git.current_branch", "git.status", "git.upstream"],
  "missing_evidence": ["branch_merge_status"]
}
```

#### Statusgruppen

- repo_cleanliness
- branch_position
- remote_health
- scope_health
- ownership_health
- freshness_health
- omnipull_compatibility

#### Stop-Kriterium

Jeder Assessment-Status verweist auf:

- Observation
- Source
- Freshness
- Regel
- Failure-Case

---

### Phase 4 — Explain

#### Ziel

Maschinenbewertung verständlich machen.

#### Befehle

```bash
steuerboard explain heimgewebe/infra
steuerboard explain heimgewebe/infra --source-trace
steuerboard explain heimgewebe/infra --why-skipped
```

#### Beispiel

```text
Repo: heimgewebe/infra
Status: clean_feature_branch
Beobachtung:
- aktueller Branch: docs/runtime-...
- working tree: clean
- upstream: vorhanden
Ableitung:
- Repo steht nicht auf Default Branch.
- omnipull würde skippen.
Warum:
- automatischer Pull auf Nicht-Default-Branch könnte lokale Arbeit gefährden.
Fehlender Beweis:
- Ob der Branch bereits gemerged ist, wurde nicht nachgewiesen.
Sicher:
- fetch --all --prune
- diff gegen origin/main anzeigen
Blockiert:
- switch main ohne Branch-Lifecycle-Prüfung
- pull --ff-only ohne Default-Branch-Gate
```

#### Stop-Kriterium

Jeder Skip-Reason hat eine Erklärung, eine sichere Aktion und einen fehlenden Beweis oder eine klare Blockade.

---

### Phase 5 — Plan Preview

#### Ziel

Aktionen werden simuliert, bevor sie erlaubt werden.

#### Befehle

```bash
steuerboard plan fetch heimgewebe/infra
steuerboard plan switch-main heimgewebe/infra
steuerboard plan pull-main-ff-only heimgewebe/infra
steuerboard plan omnipull --scope fleet
```

#### Action-Plan

```json
{
  "schema_version": "action-plan.v1",
  "plan_id": "plan-example-switch-main",
  "action": "switch-main",
  "assessment_ref": "examples/assessments/repo.sample.json",
  "decision": "blocked",
  "blocked_because": ["branch_merge_status_unknown"],
  "missing_evidence": ["branch_contains_origin_main_or_pr_merged"],
  "source_refs": ["assessment.repo.sample"],
  "rule_refs": ["action.switch-main.requires_branch_lifecycle_proof"],
  "freshness_refs": ["freshness.local_git_status.current_invocation"],
  "falsification_refs": ["failure-case.feature_branch_unmerged"],
  "boundary": {
    "does_not_execute": true,
    "does_not_mutate": true,
    "does_not_authorise_actions": true
  }
}
```

Historische Platzhalter wie `would_run`, `would_mutate`, `required_evidence`
oder `safe_alternatives` gehören nicht mehr zur aktuellen
`action-plan.v1`-Kontraktform. Contract-Beispiele dürfen keine Felder
außerhalb des aktuellen Schemas einführen.
Die aktuellen Beispiel-Feldnamen sind `plan_id`, `action`, `assessment_ref`,
`decision`, `blocked_because`, `missing_evidence`, `source_refs`, `rule_refs`,
`freshness_refs`, `falsification_refs` und `boundary`; `action_id`, `target`
und `blocked_by` sind keine aktuellen Felder.

#### Stop-Kriterium

Keine Aktion kann ohne Action-Plan ausgeführt werden.

---

### Phase 6 — Omnipull JSON Integration

#### Ziel

omnipull erzeugt strukturierte Reports, steuerboard erklärt sie.

#### Struktur

```text
/home/alex/logs/omnipull/<run-id>/
├─ summary.json
├─ repos/
│  ├─ heimgewebe__infra.json
│  └─ heimgewebe__wgx.json
└─ evidence/
   ├─ command-trace.jsonl
   ├─ status-before.txt
   └─ status-after.txt
```

#### Wichtig

omnipull und steuerboard dürfen keine konkurrierenden Statussprachen erzeugen.

Gemeinsames Vokabular:

- non_default_branch
- dirty_worktree
- no_upstream
- remote_unreachable
- ff_only_not_possible
- default_branch_unknown
- repo_not_in_scope
- permission_denied

#### Stop-Kriterium

```bash
steuerboard omnipull-report latest <run-index-json> --json
```

arbeitet auf genau einem expliziten `omnipull-run-index.v1`-Artefakt.

Boundaries:

- kein Filesystem-Discovery
- kein Glob
- keine Suche unter `/home/alex/logs/omnipull`
- kein Auto-Load des referenzierten Reports
- kein Git-Subprocess
- kein Netzwerk
- keine Action-Autorisierung

---

### Phase 7 — Evidence, Redaction, Retention

#### Ziel

Nachweise speichern, aber kontrolliert.

#### Befehle

```bash
steuerboard runs list
steuerboard runs latest
steuerboard evidence show <run-id>
steuerboard evidence verify <run-id>
steuerboard evidence gc --dry-run
```

#### Regeln

- stdout/stderr begrenzen
- Secret-Patterns redakten
- keine vollständigen Diffs ohne explizite Policy
- Run-Index führen
- Retention definieren
- fehlgeschlagene Runs länger behalten

#### Stop-Kriterium

Jeder Run ist auffindbar, verifizierbar und redacted.

---

### Phase 8 — Sichere Read-only Aktionen

#### Erlaubt (current read-only)

- git status
- git diff
- omnipull dry-run
- make validate --dry-compatible, falls vorhanden

#### Nicht erlaubt

- git switch
- git pull
- git reset
- git clean
- branch delete
- force push
- freie shell
- sudo

#### Stop-Kriterium

Jede Aktion erzeugt:

- `action-plan.json`
- `command-trace.jsonl`
- `run-result.json`
- redacted evidence

Mutierende Git-Aktionen gehören nicht in diese Phase und bleiben future-gated.

---

### Phase 9 — Gated Mutating Actions

#### Status (Phase 9A vs 9B)

Phase 9 ist in eine Beweis- und eine Ausführungshälfte geteilt:

- **Phase 9A (umgesetzt, nicht-mutierend):** reine Readiness-/Proof-Schicht für
  `switch-main`. Sie bildet das untenstehende Gate artefaktisch ab
  (`switch-main-preflight-proof.v1` → `switch-main-readiness.v1`,
  CLI `action validate-switch-main-readiness`, klassifiziert `derivation_only`),
  führt aber keinen Switch aus, mutiert nicht und autorisiert nicht. Details:
  `docs/switch-main-readiness-contract.md`.
- **Phase 9B (umgesetzt, mutierend, eng gegatet):** der gegatete
  `switch-main`-Executor (`action run-switch-main`, klassifiziert
  `mutating_stage_d`). Er konsumiert eine `ready` `switch-main-readiness.v1` und
  eine `binding_valid` `action-approval-validation.v1`, reproduziert die
  mutationskritischen Live-Gates (Toplevel, aktueller Branch, sauberer
  Worktree, Branch-Lifecycle bei Nicht-main-Branch), fetcht **nicht** und führt
  genau einen Branchwechsel auf `main` aus, gefolgt von einem Postcheck.
  `pull --ff-only auf main` ist der erste Stage-D-Pilot (Phase 8E,
  `action run-git-pull-ff-only`). Stage D enthält damit genau **zwei** gegatete
  Executor.

`plan switch-main` bleibt Preview/`derivation_only`.

#### Erlaubt mit Gate

- switch main
- pull --ff-only auf main (geplanter Pilot)

#### Gate: switch-main

Preflight:

- Repo im canonical scope
- Working tree clean
- aktueller Branch bekannt
- Default Branch bekannt
- origin/main frisch
- Branch-Lifecycle bewertet
- kein ownership problem
- Action-Plan erlaubt

Postcheck:

- branch == main
- working tree clean
- HEAD bekannt
- Evidence geschrieben

#### Gate: pull-main-ff-only

Preflight:

- branch == main
- working tree clean
- origin/main frisch
- fast-forward möglich
- remote korrekt

Postcheck:

- HEAD == origin/main
- working tree clean
- Evidence geschrieben

#### Stop-Kriterium

Das Kernproblem wird sicher lösbar:

```text
Repo auf Feature-Branch
→ steuerboard erkennt es
→ erklärt omnipull-Skip
→ prüft Branch-Lifecycle
→ plant switch-main
→ führt nur bei erfülltem Gate aus
→ plant und gate't main ff-only
→ führt erst nach Approval + Trace + Run-Result + Postcheck aus
→ weist HEAD == origin/main nach
```

---

### Phase 10 — Read-only UI

#### Ziel

Darstellung, keine eigene Logik.

#### Status (Phase 10A umgesetzt)

Phase 10A ist die erste, contract-first Scheibe dieser Phase: ein **read-only
Darstellungsvertrag**, kein Bedienpult. Sie führt `docs/ui-readonly-contract.md`,
das strikte Schema `ui-view-model.v1`, abgeleitete Beispiel-View-Models
(`examples/ui-view-models/`) und ein minimales, abhängigkeitsfreies statisches
Read-only-Scaffold (`frontend/index.html`) ein.

Ein UI-View-Model ist Navigations-/Darstellungsmaterial, nicht kanonischer
Repo-Zustand und keine Action-Freigabe. Jedes View-Model trägt eine const-true
Boundary (`does_not_execute`, `does_not_mutate`, `does_not_authorise_actions`,
`display_only`). Phase 10A fügt **keine** Action-Buttons, **kein** Backend,
**keinen** Server, **kein** Live-Git und **keine** mutierende Fähigkeit hinzu;
Stage D bleibt bei genau zwei Executoren (`run-git-pull-ff-only`,
`run-switch-main`).

Die untenstehenden Module, die Server-Sicherheitsgrenze und UI-getriggerte
Actions (Stage E in `docs/action-model.md`) bleiben **future-gated** und sind
nicht Teil von Phase 10A. Jede dieser Erweiterungen erfordert einen eigenen
Vertrag.

#### Module (Zielbild, future)

- Repo-Übersicht
- Inventory / Scope
- Drift-Panel
- Omnipull-Report
- Skip-Erklärungen
- Source-Trace
- Evidence-Viewer
- Action-Plan-Viewer

#### Sicherheitsgrenze (future: lokaler Server)

Gilt erst, wenn ein späterer Vertrag einen lokalen Server einführt; in Phase 10A
gibt es keinen Server.

- bind 127.0.0.1
- kein LAN-Bind
- keine freie Shell
- kein GET für mutierende Aktionen
- CSRF-Schutz
- Origin-Prüfung
- ephemeres Local-Token
- Actions standardmäßig deaktiviert

#### Stop-Kriterium

UI zeigt exakt dieselben Ergebnisse wie CLI-JSON.

Phase 10A erfüllt dies bereits für statische `ui-view-model.v1`-Artefakte:
`docs/ui-readonly-contract.md` (Parity-Regel) plus
`tests/test_ui_view_models.py`.

---

### Phase 11 — Runbook-Starter

Status: Phase 11A implemented.

Phase 11A introduces the first read-only runbook starter, repo-sync-gate.
It adds contracts, schemas, examples, CLI runner, and tests.
It remains read-only/dry-run-only and does not add Stage-D actions, backend, server, or UI trigger.

#### Ziel

Wiederholbare lokale Prüfabläufe starten.

#### Beispiele

- Repo-Sync-Gate
- DNS-Gate
- SSH-Gate
- Tailscale-Preflight
- server-facts Snapshot
- Heimserver-Service-Gate

#### Regel

Runbooks dürfen in v1 nur lesen oder explizit dry-run ausführen.

#### Stop-Kriterium

Ein Runbook erzeugt:

- `result.json`
- `command-trace.jsonl`
- kurze Bewertung
- Evidence-Pfad

---

### Phase 12 — Komfortschicht

Erst jetzt:

- Favoriten
- letzte Problem-Repos
- Warnung bei vielen Nicht-main-Repos
- manuelle PR-Links
- Verlauf pro Repo
- Desktop Notification
- TUI optional

Keine Automagie. Automagie ist nur Magie, die später ein Issue öffnet.

---

## 6. Statusmodell v3

### Dreiteilung

- observed_state
- derived_assessment
- decision_state

### Observed State

Direkt gemessen:

- branch_name
- dirty
- ahead
- behind
- upstream_exists
- remote_url
- head_sha
- git_status_exit_code

### Derived Assessment

Aus Regeln abgeleitet:

- clean_default_current
- clean_default_behind
- clean_feature_branch
- dirty_feature_branch
- no_upstream
- remote_mismatch
- scope_shadow
- stale_source
- ownership_problem

### Decision State

Handlungsurteil:

- action_allowed
- action_blocked
- action_warn
- evidence_missing
- source_stale_for_action

---

## 7. Capability-Modell v3

```json
{
  "action": "git.fetch_all_prune",
  "description": "Fetch all remotes and prune deleted refs.",
  "mutates_worktree": false,
  "mutates_refs": true,
  "mutates_remote": false,
  "requires_clean_tree": false,
  "requires_canonical_scope": true,
  "risk_level": "low",
  "allowed_in_phase": 8,
  "preflight_checks": [
    "repo_exists",
    "scope_canonical",
    "remote_reachable"
  ],
  "post_checks": [
    "fetch_exit_zero",
    "command_trace_written"
  ]
}
```

### Blockiert in v1

- git reset --hard
- git clean -fd
- force push
- branch delete
- free shell
- sudo
- automatic conflict resolution

---

## 8. Minimaler erster Commit

### Enthält

- `README.md`
- `docs/vision.md`
- `docs/architecture.md`
- `docs/falsification-cases.md`
- `docs/source-of-truth-model.md`
- `docs/freshness-model.md`
- `docs/local-scope-model.md`
- `docs/security-model.md`
- `docs/redaction-model.md`
- `docs/roadmap.md`
- `schemas/falsification-case.v1.schema.json`
- `schemas/source-ref.v1.schema.json`
- `schemas/local-config.v1.schema.json`
- `examples/failure-cases/*.json`

### Enthält nicht

- Scanner
- UI
- Backend
- Actions
- omnipull-Integration

Absichtlich.

Der erste Commit ist der Zaun, nicht die Kuh.

---

## 9. Zweiter Commit

### Ziel

Schema-Validierung und Failure-Cases.

```bash
steuerboard validate-examples
```

Oder zunächst nur:

```bash
python scripts/validate_examples.py
```

#### Stop-Kriterium

Alle Examples validieren.

---

## 10. Dritter Commit

### Ziel

Read-only Observation CLI.

```bash
steuerboard observe --json
```

Noch keine Bewertung.

---

## 11. Vierter Commit

### Ziel

Assessment Engine.

```bash
steuerboard assess --json
```

Jetzt erst Statusnamen.

---

## 12. Fünfter Commit

### Ziel

Explain.

```bash
steuerboard explain heimgewebe/infra
```

---

## 13. Sechster Commit

### Ziel

Plan Preview.

```bash
steuerboard plan switch-main heimgewebe/infra
```

Noch keine Ausführung.

---

## 14. Entscheidung: Eigenes Repo oder nicht?

Eigenes Repo ist gerechtfertigt, wenn steuerboard mindestens drei Dinge tut:

- Inventory / Scope
- Source / Freshness
- Evidence / Retention
- Action Planning
- spätere UI

Kein eigenes Repo nötig, wenn es nur wird:

- omnipull-report anzeigen
- Git status hübscher ausgeben
- ein paar Branches erklären

Dann besser omnipull oder wgx erweitern.

---

## 15. Belegt / plausibel / spekulativ

**Belegt:** Dein bisheriger Plan braucht Falsifikation, weil „keine neue Wahrheit“ funktional nicht ganz stimmt: Assessments sind operative Ableitungen.

**Plausibel:** Der größte Hebel ist nicht UI, sondern die Trennung von Observation, Assessment, Decision und Action.

**Spekulativ:** Python-first bleibt wahrscheinlich gut für die frühe CLI. Für spätere mutierende Actions könnte Rust oder ein besonders gehärteter Executor sinnvoller werden.

---

## 16. Risiko- und Nutzenabschätzung

### Nutzen

- weniger lokale Drift
- bessere omnipull-Erklärbarkeit
- weniger falsche Repo-Orte
- bessere Evidence
- sicherere Actions
- klare UI-Grundlage

### Risiken

- mehr Anfangsaufwand
- Schema-Overhead
- zu spätes sichtbares Ergebnis
- Gefahr von Overengineering
- steuerboard kann trotz Grenze operative Autorität bekommen
- Evidence kann sensible Daten sammeln

### Gegenmaßnahmen

- maximal 12–15 Failure-Cases am Anfang
- minimaler Schema-Kern
- keine mutierenden Actions bis Phase 9
- Redaction vor Evidence-Archiv
- UI erst nach CLI-Parität
- Source/Freshness für jede Entscheidung

---

## 17. Alternativpfade

### Pfad A — Kleines steuerboard

Nur:

- observe
- inventory
- assess
- explain
- omnipull-report

Keine Actions, keine UI.

Denkt anders: steuerboard bleibt Diagnosewerkzeug, nicht Bedienbrett.

### Pfad B — omnipull zuerst

Erst:

- omnipull --json
- omnipull explain
- omnipull dry-run

Danach steuerboard.

Denkt anders: Nicht neues Repo, sondern bestehendes Werkzeug härtet seine Ausgabe.

### Pfad C — TUI statt Web-UI

Später Terminal-Oberfläche statt SvelteKit.

Denkt anders: Weniger Angriffsfläche, weniger Frontend-Logik, schneller kontrollierbar.

Meine Empfehlung: steuerboard v3 als eigenes Repo vorbereiten, aber die ersten Commits streng docs/schema/failure-case-first.

---

## 18. Für Dummies

steuerboard soll nicht zuerst Knöpfe bauen.

Es soll zuerst eine Liste machen:

> Was kann bei meinen Repos alles schiefgehen?

Dann misst es:

> Was ist gerade wirklich da?

Dann bewertet es:

> Was bedeutet das?

Dann plant es:

> Was wäre eine sichere nächste Aktion?

Erst ganz am Ende darf es etwas ausführen.

Also: erst Arztbericht, dann Diagnose, dann Therapieplan, dann Behandlung. Nicht: Patient sieht blass aus, also schnell mal git pull.

---

## 19. Optimierungsgrad

Was wird optimiert: Architekturrobustheit, Semantik, Sicherheit, Evidence-Qualität, spätere UI-Fähigkeit.

Wie: Falsifikationskorpus vor Taxonomie, Observation/Assessment/Decision/Action-Trennung, Source/Freshness, Redaction, Plan Preview.

Wodurch: Der Plan entsteht aus Bruchfällen statt aus Idealzuständen.

Wirkung: hoch.

Optimierungsgrad: 0.91 gegenüber v2.1 bei ca. 0.88.

Nebenwirkungen: mehr Vorarbeit, langsamerer sichtbarer Fortschritt, etwas mehr Dokumentationsgewicht. Aber das ist hier sinnvoll: Ein Werkzeug, das lokale Wahrheit prüfen soll, darf am Anfang ruhig etwas bürokratisch wirken. Der Amtsschimmel wiehert, aber diesmal trägt er einen Helm.

---

## 20. Epistemische Leere

- aktueller omnipull-Code fehlt, nötig für exakte JSON-Hook-Punkte.
- aktueller steuerboard-Repozustand fehlt, nötig für konkrete Datei-/Commitplanung.
- aktuelle lokale Repo-Statusliste fehlt, nötig für reale Failure-Cases.
- metarepo/fleet/repos.yml fehlt live, nötig für Source-of-Truth-Abgleich.
- finale Sprache offen, nötig für konkrete pyproject.toml/Rust/Cargo-Struktur.

---

## 21. Unsicherheit und Interpolation

Unsicherheitsgrad: 0.25

Ursachen: Planarbeit ohne Live-Repo, ohne aktuellen omnipull-Code, ohne aktuelle Repo-Dumps.

Interpolationsgrad: 0.32

Hauptquellen: Ableitung aus deinem Heimgewebe-Muster, lokalen Git-/Repo-Problemen, v2/v2.1-Falsifikation und typischen Risiken lokaler Bedienwerkzeuge.

---

## Essenz

**Hebel:** Nicht Dashboard bauen, sondern lokale Kohärenz falsifizierbar machen.

**Entscheidung:** steuerboard v3 startet mit Failure-Cases, Source/Freshness, Observation/Assessment-Trennung und Redaction.

**Nächste Aktion:** Repo mit Phase -3 bis -1 anlegen: `falsification-cases.md`, minimale Schemas, Examples. Kein Scanner im ersten Commit.

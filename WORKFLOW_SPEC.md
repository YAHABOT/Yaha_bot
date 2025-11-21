# YAHA DEVELOPMENT WORKFLOW (OPERATOR ↔ ARCHITECT ↔ ANTIGRAVITY)
This is the permanent development workflow for the YAHA system.
It ensures all dev sessions proceed consistently with zero drift.

There are 6 phases executed in order:

==============================================
PHASE 1 — SESSION START (Operator → Architect)
==============================================
At the start of every new dev session:

1. Operator pastes 3 core files:
   - YAHA_DEV_SUPERPROMPT.md
   - YAHA_SYSTEM_MEMORY.md
   - ENGINEERING_CONTROL_BOARD.md

2. Operator writes:
   “Load everything and continue as developer assistant.”

3. Architect reads all files and responds with:
   - Current roadmap step
   - Next required task
   - Clarifications if needed

No work begins until Architect confirms alignment.

=========================================================
PHASE 2 — TASK PREP & EXECUTION SETUP (Architect → Antig)
=========================================================
After alignment:

The Architect generates:

1. **Antigravity Refresh Prompt**  
   This tells Antigravity:
   - What the project is  
   - What files exist  
   - How the repo is structured  
   - Which branch to operate on  
   - How to behave (strict rules)

2. **Antigravity Task Pack**  
   A precise set of operations:
   - FILE ops (edit/create/delete)
   - CMD ops (install, run, build)
   - TEST ops (what to run after deploy)
   - EXPECTED output

3. Operator pastes both into Antigravity.

The Architect waits for execution results.

==============================================
PHASE 3 — ANTIG EXECUTION (Antigravity → Operator)
==============================================
Antigravity:

1. Executes file edits
2. Runs commands
3. Commits changes
4. Pushes to GitHub
5. Render auto-deploys
6. Returns log/output/errors

Operator pastes the results back to the Architect.

===================================================
PHASE 4 — ARCHITECT ANALYSIS & CORRECTION (Operator → Architect)
===================================================
The Architect:

- Reviews Antigravity logs
- Traces the pipeline
- Diagnoses broken hops
- Creates new Task Packs
- Prepares preliminary changelog notes

This loop continues until:
- The feature is finished
- The build is stable
- No further work is required today

===============================
PHASE 5 — SESSION CLOSE (Architect → Operator)
===============================
Once daily work is complete, the Architect generates:

1. **Daily Operator Master Prompt**  
   This is the state snapshot used tomorrow.
   Contains:
   - Summary of today’s work  
   - Updated system memory  
   - Updated control board  
   - Known issues  
   - Architect operating rules  
   - Operator workflow rules  
   - Everything needed to rehydrate tomorrow's session

2. **Updated SYSTEM_MEMORY and CONTROL_BOARD files (if needed)**  
   Only when structural changes occurred.

Operator copies these into GitHub or stores them locally.

======================================
PHASE 6 — NEXT DAY RESTART (Operator)
======================================
Tomorrow:

1. Operator pastes:
   - YAHA_DEV_SUPERPROMPT.md
   - Updated YAHA_SYSTEM_MEMORY.md
   - Updated ENGINEERING_CONTROL_BOARD.md
   - Daily Operator Master Prompt

2. Operator writes:
   “Load everything and continue as developer assistant.”

Cycle repeats.

======================================
END OF WORKFLOW_SPEC.md
======================================

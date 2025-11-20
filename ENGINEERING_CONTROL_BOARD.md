# ENGINEERING_CONTROL_BOARD.md

This file controls the development roadmap, sequencing, and progress for the YAHA system.  
It ensures we never drift, never forget tasks, and always complete steps in the correct order.

Every new dev chat must load:

1. YAHA_DEV_SUPERPROMPT.md  
2. YAHA_SYSTEM_MEMORY.md  
3. ENGINEERING_CONTROL_BOARD.md  

Then the operator writes:  
“Load everything and continue as developer assistant.”

---

# 🔧 CURRENT STATUS

**Current Step:** Step 1 — Backend Architecture  
**Next Step After Completion:** Step 2 — Parser Engine  
**Last Completed Step:** Step 0 — Project Setup

This board is updated ONLY by the developer assistant at the end of each major step, based on operator confirmation.

---

# 📌 MASTER ROADMAP (A → G)

This is the non-negotiable sequence.  
We only move to the next step after the previous one is completed **and locked**.

---

## ✅ STEP 0 — PROJECT SETUP (Completed)

### Definition of DONE:
- SUPERPROMPT created  
- SYSTEM MEMORY validated  
- CONTROL BOARD created  
- Startup procedure defined  
- Development flow stabilized  

✔ Completed  
✔ Locked  

---

## 🧱 STEP 1 — BACKEND ARCHITECTURE (IN PROGRESS)

### Goal:
Transform the backend from a single-file fragile structure into a clean, stable, modular architecture.

### Definition of DONE:
- Clean folder structure created
- main.py minimized and stable
- Routing modularized
- Parser isolated into its own file/module
- Supabase service created
- Telegram service created
- Error handling centralized
- Logging cleaned up
- Requirements.txt validated
- Render deploy succeeds without regression

### Status:
✔ Completed  
✔ Locked  

---

## 🧠 STEP 2 — PARSER ENGINE (Locked until Step 1 completes)

### Goal:
Make the GPT parser deterministic, schema-safe, and version-controlled.

### Definition of DONE:
- Parser returns deterministic JSON
- No fallback to list/text mode
- Strict container schemas enforced
- Versioned parser logic (Parser Packs)
- Classification rules validated
- Error recovery built-in
- Integration-tested with Supabase inserts

### Status:
🔄 In Progress  
(Do not proceed to Step 3 until operator confirms Step 2 is LOCKED.)

---

## 🤖 STEP 3 — TELEGRAM UX & MEDIA INGESTION PIPELINE (Locked)

### Goal:
Transform the bot from a text-only logger into a multimedia ingestion interface supporting images, screenshots, barcodes, and voice notes — while providing polished, guided Telegram UX with confirmations and recovery flows.

---

### 3A — Media Ingestion Pipeline (Images, Screenshots, Voice Notes)

#### Definition of DONE:
- Telegram file download implemented for:
  - Photos (JPG/PNG)
  - Screenshots
  - Barcodes (photo-based)
  - Voice notes (OGG/MP3/OPUS)
- OCR layer integrated (OpenAI Vision or Tesseract/Turbo OCR)
  - Extract structured text from meal photos, nutrition labels, screenshots
  - Extract layout-aware text blocks for better container mapping
- ASR layer integrated (OpenAI Whisper or server-side STT)
  - Convert voice notes into clean text
  - Normalize filler words, timing words, conversational phrases
- Barcode to nutrition lookup path created
- Pre-parser sanitization layer created to clean OCR/ASR outputs
- Confidence scoring integrated (low confidence → ask user)
- Error/fallback path for:
  - Blurry photos
  - Partial OCR
  - Unclear voice transcriptions
  - Empty or short results
- Raw media links stored in entries for audit/recovery

---

### 3B — Telegram Conversational UX

#### Definition of DONE:
- Inline buttons for Food / Sleep / Workouts / More
- Multi-step guided flows
- Shortcut actions for frequent logs
- Clear confirmation messages (“Log this?” → Yes/No)
- Error recovery flows for media ingestion failures
- Consistent message formatting
- UX smoothing across all containers
- Optional strict-mode paths (Food Bank lookups, raw paste validations)

---

### Status:
🔒 Locked until Step 2 (Parser Engine) is completed.


---

## 🛡 STEP 4 — DEVOPS SAFETY NET (Locked)

### Goal:
Prevent broken builds forever.

### Definition of DONE:
- CI checks added
- Parser validation tests
- Supabase schema validation
- Pre-deploy checks
- requirements.txt consistency checks
- Linting
- Minimal automated test coverage

### Status:
⏳ Locked

---

## 🗄 STEP 5 — SUPABASE SCHEMA OPTIMIZATION (Locked)

### Goal:
Clean, future-proof, analytics-ready schema.

### Definition of DONE:
- Tables normalized
- Indexes created
- Clear constraints
- Future containers integrated
- Schema document updated

### Status:
⏳ Locked

---

## 📊 STEP 6 — DASHBOARD UI (Locked)

### Goal:
Create a full web dashboard for users.

### Definition of DONE:
- Authenticated login
- Per-container journals
- Calendar view
- Stats, charts, analytics
- Clean UI
- Render or Vercel deploy

### Status:
⏳ Locked

---

## 📘 STEP 7 — ARCHITECTURE BLUEPRINT (Locked)

### Goal:
Produce an investor-ready architecture document.

### Definition of DONE:
- System overview diagram
- Container flow
- Parser engine flow
- Database model
- Ingestion pipeline
- UX architecture
- Future roadmap
- Competitive moat analysis

### Status:
⏳ Locked

---

# 📝 CHECKPOINT LOG

This section will store short summaries after each step is fully completed.  
(These are written by the assistant based on operator confirmation.)

---

### 📌 Checkpoint — Step 0 (Completed)
- SUPERPROMPT created  
- SYSTEM MEMORY loaded  
- CONTROL BOARD established  
- Development process structured  

---

# 🧭 OPERATING RULE

The developer assistant MUST begin every session by reading this file and stating:

“According to the Engineering Control Board, we are currently on Step X.  
The next required task is: ________.”

This prevents drift, confusion, or skipping steps.

---

# END OF FILE

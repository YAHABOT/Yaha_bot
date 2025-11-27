# Build 019 — Media Ingestion Architecture (Master Plan)

This document defines the complete sub-build structure for the Media Ingestion Foundation.  
Every 019.x sub-build is recorded here to ensure continuity across sessions and to prevent context loss.

---

## 1. Purpose of Build 019

Introduce a unified media ingestion layer capable of handling:

- Images (photos, screenshots)
- Audio (voice notes)
- Text-based files (TXT, CSV, simple PDFs)

All media inputs must be routed through:

```
media → extraction → GPT fallback → normalized dict
```

This build **does not change schemas**, **does not modify existing flows**, and focuses purely on infrastructure.

---

## 2. Constraints

- No schema changes for Food, Sleep, or Exercise.
- No modifications to the Logging Engine.
- GPT Fallback API signature must remain unchanged.
- Only Telegram is supported in 019; WhatsApp + Webapp arrive in later builds.
- All ingestion logic must sit inside `app/media/`.

---

## 3. Build 019.x Sub-Build Roadmap

### **019.1 — Media Layer Scaffolding**

Create empty modules:

- `app/media/models.py`
- `app/media/storage.py`
- `app/media/ocr.py`
- `app/media/stt.py`
- `app/media/file_parser.py`
- `app/media/pipeline.py`

Implement:

- `MediaJob` dataclass  
- No logic; structure only.

**Purpose:** Establish the foundation with zero risk.

---

### **019.2 — OCR/STT/File Parser Interface Definitions**

Implement *mock* (dummy) versions of:

- `perform_ocr()`
- `perform_stt()`
- `parse_file()`

No real OCR or STT integrations yet.

**Purpose:** Define exact inputs/outputs to remove all architectural ambiguity.

---

### **019.3 — Media Pipeline Assembly (Mock Extractors)**

Implement the pipeline logic:

```
media → extraction → GPT fallback → normalized dict
```

Using mock extractors only.

**Purpose:** Build and test the ingestion spine without external APIs.

---

### **019.4 — Telegram Integration (Food Only)**

Add handlers:

- `handle_photo`
- `handle_voice`
- `handle_document`

Route extracted text to Food Flow:

- Pre-fill macros when possible  
- Jump to confirm when complete  
- Ask follow-up questions when partial  
- Fall back to manual input when unusable  

**Purpose:** First functional end-to-end use-case.

---

### **019.5 — Real OCR + Real STT Integration**

Replace mock extractors with:

- Real OCR provider (cloud/local)
- Real STT provider (cloud/local)
- Real file text extraction

**Purpose:** Production-ready ingestion.

---

### **019.6 — Expand to Sleep & Exercise**

Attach ingestion to:

- Sleep Flow (screenshot or voice input)  
- Exercise Flow (watch summary screenshots, HR data, calories)  

**Purpose:** Extend ingestion to all core containers.

---

### **019.7 — Cleanup, Error Handling, QA**

Finalize:

- Error messages  
- Bad image detection  
- Confidence thresholds  
- Timeout handling  
- Regeneration paths  
- Regression QA  
- Integration QA  
- ChangeLog updates  

**Purpose:** Hardening and stabilization.

---

## 4. QA Requirements Per Sub-Build

Each sub-build must include:

- Unit tests  
- Integration tests  
- Regression safety checks  
- Guarantees that existing flows remain unchanged  

---

## 5. Changelog Expectations

Each 019.x sub-build must:

- Append to `CHANGELOG.md`
- Record exactly what changed
- State clearly whether existing flows were impacted  
  (Default answer should always be: **No**)  

---

## 6. Completion Criteria

Build 019 is considered complete when:

- Food, Sleep, and Exercise flows all support ingestion of:
  - Images/screenshots  
  - Voice notes  
  - Text-based files  

- Normalized dicts from media map cleanly into existing flows  
- All fallback & error modes handled  
- All sub-builds 019.1 → 019.7 are marked complete  

---

# End of Build 019 Master Plan

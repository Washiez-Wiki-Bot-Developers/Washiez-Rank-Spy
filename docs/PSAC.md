# Plan for Software Aspects of Certification (PSAC)

**Project:** `Washiez-Rank-Spy`<br/>
**Target DAL:** DAL E (Training Baseline) $\rightarrow$ Path to DAL A<br/>
**Doc ID:** `PSAC-001`

---

## 1. System & Software Overview

* **Function:** `[SYSTEM_FUNCTION_DESCRIPTION]`
* **Architecture:** Monolithic Python package. Static typing enforced.
* **Target Environment:** Standard CPython (DAL E). Future qualification / C-transpilation target (DAL A).

---

## 2. Software Assurance Level (DAL) Allocation

* **Current Allocation:** **DAL E**
* * Failure condition effect: No safety impact.
* * Compliance objective: Baseline process setup, zero formal ED-12C audit requirements.


* **Future Target:** **DAL A**
* * Failure condition effect: Catastrophic.
* * Mandatory future upgrades: Tool qualification (ED-215), full MC/DC structural coverage, deterministic runtime.



---

## 3. Software Life Cycle Environment (Toolchain)

| Tool / Environment | Component / Version | Purpose |
| --- | --- | --- |
| **IDE** | VS Code | Development environment |
| **Language** | Python 3.12+ (3.14[t] preferred) | Implementation language |
| **Static Analysis** | `mypy --strict` | Type check + static error catch |
| **Documentation** | Sphinx + `myst-parser` | Doc rendering (Markdown $\rightarrow$ HTML/PDF) |
| **Traceability** | `sphinx-needs` | Bi-directional requirement tracing |
| **Test Engine** | `pytest` + `pytest-cov` | Requirement testing + coverage analysis |

---

## 4. Development & Verification Standards

```markdown
# Software Coding Standard (SCS-001)

1. Typing:
   - `Any` type = BANNED !
   - Strict function signature typing mandatory.
2. Dynamic Features:
   - `eval()`, `exec()`, dynamic `__import__` = BANNED !
   - Dynamic class/attribute modification = BANNED !
3. Docstrings:
   - Sphinx format required (`:param:`, `:returns:`).
   - Traceability tag required (`.. satisfies:: REQ_XXX`).
4. Error Handling:
   - Bare `except:` = BANNED !
   - Explicit exception catching required.

```

```markdown
# Requirements Standard (SRS-001)

1. Format:
   - Written in MyST Markdown (`.md`).
   - Defined via `sphinx-needs` directive `{need}`.
2. Naming Convention:
   - High-Level Requirement: `REQ_HLR_[MODULE]_[ID]`
   - Low-Level Requirement: `REQ_LLR_[MODULE]_[ID]`
3. Verifiability:
   - Each requirement must contain clear pass/fail criterion.

```

---

## 5. Life Cycle Deliverables (Artifacts)

* **Plan:** PSAC (`PSAC-001`), Coding Standard (`SCS-001`), Requirements Standard (`SRS-001`)
* **Requirements:** High-Level Requirements (`HLR.md`), Low-Level Requirements (`LLR.md`)
* **Code:** Source code (`src/`), API docs (`docs/`)
* **Verification:** Test cases (`tests/`), Coverage report, Traceability Matrix (`traceability.md`)

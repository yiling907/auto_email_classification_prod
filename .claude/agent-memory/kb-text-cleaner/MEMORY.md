# KB Text Cleaner — Agent Memory

## Key File Locations
- Source KB files: `tests/test_data/knowledge_base/` (175 files: 173 .txt + 2 PDFs)
- Output: `tests/test_data/knowledge_base_clean.txt`
- Cleaning script: `scripts/clean_knowledge_base.py`

## Confirmed Patterns in This KB

### Raw File Format
All Laya Healthcare .txt files follow this structure:
```
PAGE TITLE: ...
============================================================
DESCRIPTION: ...

SOURCE URL: https://...

## Section heading
### Sub-heading
#### Sub-sub-heading
  - bullet item
  | pipe-cell table item  (same content as bullet, causes duplicates)
Standalone text (same content as pipe-cell, causes 3x duplication)
```

### Critical Issues Found (and fixed)
1. **Duplicate content** from 3 renderings: pipe-cell `|`, bullet `-`, standalone heading - requires global per-document dedup
2. **Price table duplicates**: bullet "Item €190" + heading "Item" / next-line "€190" - requires price-table-split dedup
3. **Curly apostrophes** (`\u2019`) in raw files break ASCII startswith matching - normalize quotes before any comparison
4. **Trailing link artifacts**: "Find out more about X here. Find out more ." (double suffix) - needs iterative cleanup loop
5. **Orphaned "on"**: after stripping phone numbers, "call us on " + stripped number leaves dangling "on"
6. **130 plan files** all contain identical JS-placeholder content - collapse to single "AVAILABLE PLANS" section

### Plan Files
All 130 `productsandservices__plan__scheme__*.txt` files contain only boilerplate JS placeholder content. They should be collapsed into one consolidated "AVAILABLE LAYA HEALTHCARE INSURANCE PLANS" section listing plan names.

### Files to Skip Entirely (boilerplate only)
checkcover, contactus, coverchecker, create, find, login, memberarea, memberarea__howtousememberarea, questions, webclaims, writetous

### Brand Normalization
Normalize "laya", "LAYA", "laya healthcare", etc. → "Laya Healthcare"
Watch out for "Laya App", "Laya Health" (not company name variants)
Apply AFTER curly quote normalization.

### Additional Issues Found (and fixed in follow-up session)
7. **Triple-space in section headers**: `derive_section_header()` replaces `__` → ` - ` then `-` → ` `, turning ` - ` into `   ` (3 spaces). Fix: added `_normalise_header_text()` helper that calls `re.sub(r" {2,}", " ", ...)` after all replacements; also added explicit `formembers__` prefix handler.
8. **"on prior" orphan from phone stripping**: "contact team on [stripped phone] prior to..." → "team on  prior" (double-space). The 10b regex must use `\s+` (not literal space) to match before double-space collapse at step 10 runs.

## Output Stats (last run)
- 46 sections processed (45 non-plan + 1 consolidated plan list)
- 129 plan files collapsed
- 2,247 output lines, ~147KB
- All quality checks pass: no emails, phones, URLs, markdown headers, double periods, template vars, double-spaces, or dangling orphan prepositions

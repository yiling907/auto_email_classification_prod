#!/usr/bin/env python3
"""
Knowledge base text cleaner for RAG/embedding pipeline.
Processes all .txt files in knowledge_base/ and produces a single
consolidated, clean output file optimized for vector search.
"""

import re
from pathlib import Path

# -----------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------
KB_DIR = Path("/Users/leiyiling/IdeaProjects/auto_email_classification_prod/tests/test_data/knowledge_base")
OUTPUT_FILE = Path("/tests/test_data/knowledge_base/knowledge_base_clean.txt")

SKIP_FILES = {
    "Laya Rules.pdf",
    "laya-allpmirules-053-0825.pdf",
}

# Files that contain only a page-header block with no usable body content
BOILERPLATE_ONLY_FILES = {
    "checkcover.txt",
    "contactus.txt",
    "coverchecker.txt",
    "create.txt",
    "find.txt",
    "login.txt",
    "memberarea.txt",
    "memberarea__howtousememberarea.txt",
    "questions.txt",
    "webclaims.txt",
    "writetous.txt",
}

# Standalone lines that are pure navigation UI, template variables, or
# section labels with no semantic content for RAG.
SKIP_LINE_EXACT = {
    "find out more",
    "get a quote",
    "download",
    "download your benefit guide",
    "view plans",
    "learn more",
    "register here",
    "log in",
    "get in touch",
    "discover",
    "compare",
    "find",
    "your benefit guide",
    "find out more about our benefits",
    "member area",
    "become a member",
    "quick & easy",
    "switching process",
    "fastest growing",
    "health insurer in ireland",
    "compare easily",
    "with other providers",
    "why switch?",
    "no results found",
    "search results",
    "key terms explained",
    "specialist healthcare",
    "urgent care",
    "digital health",
    "hospitals & scan centres",
    "mental wellbeing",
    "expert guidance",
    "member support",
    "description for expert guidance category.",
    "lower cost for members",
    "out of hours services",
    "screening",
    # price-table fragment lines left after stripping "#### (within 72 hours)"
    "(within 72 hours - same condition)",
    "(after 72 hours - same condition)",
    "(wound dressing, etc)",
    "(covered by laya directly)",
    # Claims-related orphan lines
    "contact us at",
    "for urgent claim inquiries, contact:",
    "members can check claim status online at",
    "pre-auth requests:",
    "check your urgent care cover now.",
}

SKIP_LINE_STARTSWITH = (
    "retrieving information",
    "retrieving benefit",
    "retrieving informatin",
    "chat to our",
    "check your cover",
    "see how you can save",
    "become a member",
    "stay a beat ahead",
    "join today",
    "join our",
    "join thousands",
    "join laya",
    "didn't find an answer",
    "didn't find an answer",  # curly apostrophe variant
    "check your urgent care cover",
    "urgent care clinics available",
    "faster access in comparison",
    "why laya?",
    "irish-based call centre",
    "18 years' experience",
    "nearly 500,000 members",
    "ireland's no. 2",
    "get a beat ahead",
    "not a laya member?",
    "hoping to start a family",
    "want the reassurance",
    "before you visit",
    "frequently asked questions",
    "mri & x-ray",
    "making you better before",
    "looking after you always.",
    "get health insurance quote",
    "if you'd like to arrange different levels",
    "laya life",
    "life insurance and mortgage protection",
    "travel insurance",
    "looking after you always, home or abroad",
    "no benefits were found",
    "700,000+",
    "new to health insurance?",
    "still have questions about switching?",
    "worried about waiting periods?",
    "we're always thinking",
    "we're always looking",
    "find out more about",
    "find out more information",
)

# Inline suffixes to strip from the END of sentences (link artifacts)
# These appear after a URL was stripped, leaving dangling anchor text.
INLINE_LINK_SUFFIXES = re.compile(
    r"\s*\.\s+(?:Find out more|Learn more|Get a Quote|Download|"
    r"Check your cover here|Go to your Member Area|View Plans)[\s.]*$",
    re.IGNORECASE,
)
# "... here. Find out more ." pattern
INLINE_FIND_MORE = re.compile(
    r"\s*Find out more(?:\s+here)?[\s.]*$",
    re.IGNORECASE,
)
# Dangling "here ." artifacts where a URL was stripped mid-sentence
DANGLING_HERE = re.compile(r"\s+here\s*\.\s*$")
# Space before period artifact: "Laya Healthcare ."
SPACE_BEFORE_PERIOD = re.compile(r"\s+\.")


def normalize_quotes(text: str) -> str:
    """Normalize curly/Unicode quotes and apostrophes to straight ASCII."""
    # Curly apostrophes and single quotes
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    # Curly double quotes
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    return text


def should_skip_line(stripped: str) -> bool:
    """Return True if the line carries no semantic content."""
    # Normalize curly apostrophes before comparison
    normalized = normalize_quotes(stripped)
    lower = normalized.lower()
    if lower in SKIP_LINE_EXACT:
        return True
    for prefix in SKIP_LINE_STARTSWITH:
        if lower.startswith(prefix):
            return True
    # Template variables
    if re.match(r"^\{\{.*\}\}$", stripped):
        return True
    return False


def clean_line_end(line: str) -> str:
    """Remove trailing link artifacts from the end of a content line."""

    # Apply cleanup in a loop to handle multiple trailing nav artifacts
    # e.g. "...here. Find out more about waiting periods here. Find out more ."
    max_iterations = 5
    for _ in range(max_iterations):
        prev = line

        # "... Find out more about X here." or "... Find out more ."
        def safe_replace(m):
            base = line[:m.start()].rstrip()
            if not base:
                return ""
            if base.endswith("."):
                return ""
            return "."

        line = re.sub(
            r"\s+Find out more(?:\s+about\s+[^.]*?)?\s*(?:here)?\s*\.?\s*$",
            safe_replace,
            line,
            flags=re.IGNORECASE,
        )
        # Standalone trailing "Find out more ." or "Find out more."
        line = re.sub(r"\.\s+Find out more\s*\.?\s*$", ".", line, flags=re.IGNORECASE)
        # "Learn more at our X page." (URL was stripped, leaving orphan text)
        line = re.sub(
            r"\s+Learn more at our \S+ page\.?\s*$",
            ".",
            line,
            flags=re.IGNORECASE,
        )
        # " ." artifact from URL removal
        line = re.sub(r"(\S)\s+\.\s*$", r"\1.", line)
        # Double period artifact "home.." → "home."
        line = re.sub(r"\.{2,}", ".", line)
        line = line.rstrip()

        if line == prev:
            break  # no more changes

    return line


def remove_price_table_split_duplicates(lines: list) -> list:
    """
    The clinics.txt (and similar) files have price tables rendered as BOTH:
      (a) a bullet line: "Initial consultation €190"
      (b) a heading+price pair: "Initial consultation" followed by "€190"

    After bullet and heading stripping both become plain text.
    Strategy: collect all "name price" single-line entries. When we encounter
    a standalone name line immediately followed by a standalone price line,
    and together they match an already-seen combined entry, drop both.
    """
    # Collect combined "name €price" entries from full combined lines
    combined_seen: set = set()
    price_re = re.compile(r"€[\d.,]+|€0")
    for line in lines:
        stripped = line.strip()
        if price_re.search(stripped) and len(stripped) > 5:
            key = re.sub(r"\s+", " ", stripped.lower().strip())
            combined_seen.add(key)

    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # If no price on this line but next line IS a price
        if (
            stripped
            and not price_re.search(stripped)
            and i + 1 < len(lines)
        ):
            next_stripped = lines[i + 1].strip()
            if next_stripped and price_re.match(next_stripped):
                candidate = re.sub(
                    r"\s+", " ", (stripped + " " + next_stripped).lower().strip()
                )
                if candidate in combined_seen:
                    # Drop this heading line and the following price line
                    i += 2
                    continue
        result.append(line)
        i += 1
    return result


def normalize_laya_brand(text: str) -> str:
    """Normalize all Laya Healthcare brand name variants consistently."""
    # "laya healthcare" (any case) → "Laya Healthcare"
    text = re.sub(r"\blaya\s+healthcare\b", "Laya Healthcare", text, flags=re.IGNORECASE)
    # "laya's" → "Laya Healthcare's"
    text = re.sub(r"(?<!\w)laya(?='s\b)", "Laya Healthcare", text, flags=re.IGNORECASE)
    # "laya" standalone (not followed by Health, App, member, life, or another word)
    # meaning it's used as a company shorthand
    text = re.sub(
        r"(?<!\w)laya(?!\s+health|\s+app|\s+member|\s+life|\s+[\w])",
        "Laya Healthcare",
        text,
        flags=re.IGNORECASE,
    )
    return text


def deduplicate_adjacent_paragraphs(paragraphs: list) -> list:
    """Remove consecutive duplicate paragraphs (normalized comparison)."""
    result = []
    seen = set()
    for para in paragraphs:
        key = re.sub(r"\s+", " ", para).strip().lower()
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        result.append(para)
    return result


def clean_file_content(raw: str) -> str:
    """Apply full cleaning pipeline to one file's raw text."""

    text = raw

    # --- 1. Strip page-header metadata block ---
    text = re.sub(r"^PAGE TITLE:.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^DESCRIPTION:.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^SOURCE URL:.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^={3,}$", "", text, flags=re.MULTILINE)

    # --- 2. Remove PII: emails, phone numbers, URLs ---
    # Emails
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}\b", "", text)
    # Irish phone numbers (021 202 xxxx, 0818 xxx xxx, 1800 xxx xxx)
    text = re.sub(r"\b021[\s\-]?202[\s\-]?\d{4}\b", "", text)
    text = re.sub(r"\b0818[\s\-]?\d{3}[\s\-]?\d{3}\b", "", text)
    text = re.sub(r"\b1800[\s\-]?\d{3}[\s\-]?\d{3}\b", "", text)
    # US-style phone/claim-line patterns
    text = re.sub(r"\b1-800-[A-Z0-9-]+\b", "", text)
    text = re.sub(r"\(\d{3}\)[\s\-]\d{3}[\s\-]\d{4}", "", text)
    # URLs with scheme
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"www\.\S+", "", text)
    # Bare domain references (e.g., "insuremailai.com/claims", "revenue.ie")
    text = re.sub(r"\b[\w-]+\.(?:com|ie|org|net|gov)(?:/\S*)?", "", text)

    # --- 2b. Normalize Unicode curly quotes/apostrophes to ASCII ---
    text = normalize_quotes(text)

    # --- 3. Strip markdown heading markers (keep text) ---
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

    # --- 4. Process line by line ---
    raw_lines = text.split("\n")
    step4_lines = []
    for line in raw_lines:
        line = line.rstrip()
        # Remove pipe-prefix from table cells "  | content"
        line = re.sub(r"^\s*\|\s*", "", line)
        # Remove markdown bullet prefix "  - item"
        line = re.sub(r"^\s*[-*•]\s+", "", line)
        # Strip leading whitespace
        line = line.lstrip()
        # Clean trailing link artifacts
        line = clean_line_end(line)
        # Skip navigation-only lines
        if should_skip_line(line.strip()):
            continue
        step4_lines.append(line)

    # --- 5. Remove price-table split duplicates ---
    step4_lines = remove_price_table_split_duplicates(step4_lines)

    text = "\n".join(step4_lines)

    # --- 6. Normalize Laya brand ---
    text = normalize_laya_brand(text)

    # --- 7. Collapse consecutive blank lines ---
    text = re.sub(r"\n{3,}", "\n\n", text)

    # --- 8. Deduplicate adjacent identical paragraphs ---
    # Split on blank lines, deduplicate, rejoin
    paragraphs = re.split(r"\n\n+", text)
    paragraphs = deduplicate_adjacent_paragraphs(paragraphs)
    text = "\n\n".join(paragraphs)

    # --- 9. Global line-level deduplication across all paragraphs ---
    # Some files have: bullet version (combined) in one paragraph, followed
    # by heading+body version (split) in a subsequent paragraph.
    # E.g.: "Minor burns and scalds Get a minor burn assessed and treated."
    # followed (after blank line) by: "Minor burns and scalds" / "Get a minor burn..."
    # We deduplicate ALL non-blank lines globally within the document.
    # To avoid removing intentional repeated info (e.g. in FAQ sections),
    # we only suppress a line if its FULL normalized text was seen before.
    # We also suppress a line if it is a SUBSTRING of a previously seen line
    # (e.g., "Get a minor burn or scald assessed and treated." is a substring
    #  of "Minor burns and scalds Get a minor burn or scald assessed and treated.")
    lines = text.split("\n")
    global_seen_sentences: set = set()
    deduped_lines = []
    # First pass: collect all non-blank normalized lines
    all_norms = []
    for line in lines:
        norm = re.sub(r"\s+", " ", line).strip().lower()
        all_norms.append(norm)
    # Build a set for substring lookup
    all_norms_set = set(n for n in all_norms if n)

    # Second pass: output only non-duplicate lines
    for line, norm in zip(lines, all_norms):
        if not norm:
            deduped_lines.append(line)
            continue
        # Skip if exact duplicate
        if norm in global_seen_sentences:
            continue
        # Skip if this line is a strict substring of a longer already-seen line
        # (catches split-heading lines like "Get a minor burn..." which appeared
        # already inside "Minor burns and scalds Get a minor burn...")
        is_substring_of_seen = any(
            norm in seen and norm != seen
            for seen in global_seen_sentences
        )
        if is_substring_of_seen:
            continue
        global_seen_sentences.add(norm)
        deduped_lines.append(line)
    text = "\n".join(deduped_lines)

    # --- 10b. Clean orphaned sentence fragments from phone/email stripping ---
    # "contact one of our customer service advisers on  to check" →
    # "contact one of our customer service advisers to check"
    text = re.sub(r"\bon\s+to\b", "to", text)
    # "contact our customer care team on [stripped number] prior to your health check" →
    # "contact our customer care team prior to your health check"
    # Note: \s+ handles cases where double-space has not yet been collapsed.
    text = re.sub(r"\bteam\s+on\s+prior\b", "team prior", text, flags=re.IGNORECASE)
    # Generic: "... on [stripped] prior to ..." where "on" is dangling after phone removal
    text = re.sub(r"\b(\w+)\s+on\s+prior to\b", r"\1 prior to", text, flags=re.IGNORECASE)
    text = re.sub(r"\bcall us on\s+or email us at\s*$", "call our customer service team", text, flags=re.MULTILINE | re.IGNORECASE)
    text = re.sub(r"\bor email us at\s*$", "", text, flags=re.MULTILINE | re.IGNORECASE)
    text = re.sub(r"\bcall or email us.*?on\s*$", "contact our Healthcare Concierge team", text, flags=re.MULTILINE | re.IGNORECASE)
    text = re.sub(r"\bcontact us on our details above\b", "contact us for further details", text, flags=re.IGNORECASE)
    # "New to Member Area? Register here" (nav trailing)
    text = re.sub(r"\s+New to Member Area\? Register here\.?\s*$", ".", text, flags=re.MULTILINE | re.IGNORECASE)
    # "Click or tap the pink dropdowns below to find out how to make different types of claims."
    text = re.sub(r"^Click or tap the pink dropdowns.*$", "", text, flags=re.MULTILINE | re.IGNORECASE)
    # "For questions about our privacy practices or compliance, contact:" → remove trailing empty line
    text = re.sub(r"^For questions about our privacy practices.*$", "For questions about our privacy practices or compliance, refer to our compliance documentation.", text, flags=re.MULTILINE | re.IGNORECASE)

    # --- 10b2. Fix remaining orphaned fragments from contact info stripping ---
    # "Chat to our award-winning team on" (phone stripped, "on" dangling)
    text = re.sub(r"\bChat to our award-winning team on\s*$", "contact our award-winning Customer Care team for assistance.", text, flags=re.MULTILINE | re.IGNORECASE)
    # "Just call or email" (both stripped)
    text = re.sub(r"^Just call or email\s*$", "", text, flags=re.MULTILINE | re.IGNORECASE)
    # "Contact Nurseline, 24/7" (nav button)
    text = re.sub(r"^Contact Nurseline, 24/7\s*$", "", text, flags=re.MULTILINE | re.IGNORECASE)
    # "We're here for you, always, on." → "We're here for you, always."
    text = re.sub(r", always, on\.\s*$", ", always.", text, flags=re.MULTILINE | re.IGNORECASE)
    # "on or check our waiting period FAQ page" → "or check our waiting period information"
    text = re.sub(r"\bon or check our waiting period FAQ page\b", "or review our waiting period information", text, flags=re.IGNORECASE)
    # "Already a member? You can check your cover easily in your Member Area , or by calling our award-winning Customer Care team"
    text = re.sub(r", or by calling our award-winning Customer Care team\s*$", ".", text, flags=re.MULTILINE | re.IGNORECASE)
    # "or call our helpful team for a quote to suit your needs" (nav/CTA)
    text = re.sub(r"^Not a member\? You can get a quote online , or call our helpful team.*$", "", text, flags=re.MULTILINE | re.IGNORECASE)
    # " , " double-space comma artifact from URL stripping
    text = re.sub(r"\s+,\s", ", ", text)
    # " ." leftover from URLs in middle of text
    text = re.sub(r" \. ", ". ", text)
    # "here." at end where "here" was an anchor text
    # Strip "here." at sentence end when it follows a nav trigger
    text = re.sub(r"\. Check your cover here\.\s*$", ".", text, flags=re.MULTILINE | re.IGNORECASE)
    # " . " artifact left mid-sentence from URL
    text = re.sub(r"(\w) \. (\w)", r"\1. \2", text)

    # --- 10c. Fix double periods from stripping artifacts ---
    text = re.sub(r"\.{2,}", ".", text)

    # --- 10. Final whitespace cleanup ---
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    # Fix double-spaces created by URL/phone removal
    text = re.sub(r"(?<=\S)  +(?=\S)", " ", text)
    # Remove lines that became blank after cleanup
    text = re.sub(r"^\s+$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    return text


def _normalise_header_text(text: str) -> str:
    """Collapse any multi-space runs created by separator-to-space replacements."""
    return re.sub(r" {2,}", " ", text).strip()


def derive_section_header(filename: str) -> str:
    """Convert a filename to a clean uppercase section header."""
    name = filename.replace(".txt", "")
    if name.startswith("productsandservices__plan__scheme__"):
        plan_name = name.replace("productsandservices__plan__scheme__", "")
        plan_name = plan_name.replace("-", " ").replace("_", " ").upper()
        return f"PLAN: {_normalise_header_text(plan_name)}"
    if name.startswith("productsandservices__"):
        rest = name.replace("productsandservices__", "")
        rest = rest.replace("__", " - ").replace("-", " ").replace("_", " ").upper()
        return f"PRODUCTS AND SERVICES - {_normalise_header_text(rest)}"
    if name.startswith("yourbenefits__"):
        rest = name.replace("yourbenefits__", "")
        rest = rest.replace("__", " - ").replace("-", " ").replace("_", " ").upper()
        return f"YOUR BENEFITS - {_normalise_header_text(rest)}"
    if name.startswith("howtoclaim__"):
        rest = name.replace("howtoclaim__", "")
        rest = rest.replace("__", " - ").replace("-", " ").replace("_", " ").upper()
        return f"HOW TO CLAIM - {_normalise_header_text(rest)}"
    if name.startswith("clinics__"):
        rest = name.replace("clinics__", "")
        rest = rest.replace("__", " - ").replace("-", " ").replace("_", " ").upper()
        return f"CLINICS - {_normalise_header_text(rest)}"
    if name.startswith("formembers__"):
        rest = name.replace("formembers__", "")
        rest = rest.replace("__", " - ").replace("-", " ").replace("_", " ").upper()
        return f"FOR MEMBERS - {_normalise_header_text(rest)}"
    header = name.replace("__", " - ").replace("-", " ").replace("_", " ").upper()
    return _normalise_header_text(header)


def has_meaningful_content(text: str) -> bool:
    return len(re.sub(r"\s+", "", text)) > 80


def extract_plan_name_from_filename(fname: str) -> str:
    """Extract a human-readable plan name from a scheme filename."""
    name = fname.replace("productsandservices__plan__scheme__", "").replace(".txt", "")
    # Convert kebab-case to title-case words
    words = name.replace("-", " ").replace("_", " ").split()
    return " ".join(w.capitalize() for w in words)


def is_plan_file_boilerplate_only(raw: str) -> bool:
    """Return True if the plan file has only dynamically-loaded placeholder content."""
    lines = [l.strip() for l in raw.split("\n") if l.strip()]
    # Strip markdown heading markers and bullet prefixes for comparison
    cleaned_lines = []
    for l in lines:
        l = re.sub(r"^#{1,6}\s+", "", l)
        l = re.sub(r"^\s*[-*]\s+", "", l)
        cleaned_lines.append(l.strip())

    # These are the known boilerplate lines present in ALL plan files
    boilerplate_set = {
        "full benefits", "hospital cover", "day-to-day expenses",
        "looking after you always.", "looking after you always",
        "heartbeat screening", "cancer care cover", "excellent cardiac cover",
        "scan cover", "emergency overseas cover", "everyday medical expenses",
        "maternity, infertility & child healthcare benefits", "cancer treatment",
        "hospitals covered", "why laya?...", "irish-based call centre",
        "18 years' experience", "nearly 500,000 members",
        "ireland's no. 2 health insurance provider",
    }
    skip_prefixes = (
        "page title:", "description:", "source url:", "===",
        "retrieving", "the following schemes are available",
        "advantage ", "assure ", "care manager", "completecare", "health smart",
        "company care", "companycare", "companyhealth", "connect care",
        "connectcare", "connectchoice", "control suite", "control 1", "control 3",
        "control 4", "control 6", "empower", "essential", "everyday health",
        "evolve", "excelcare", "flex 1", "flex 2", "flex 5", "health manager",
        "health secure", "ideal simplicity", "inspire", "momentum", "optimum",
        "power", "precision", "prime", "primecare", "principle", "prosper",
        "signify", "simply", "simplicity", "total health", "transform",
        "core connect", "360-care", "accesscare", "accesshealth",
    )
    content_lines = []
    for l in cleaned_lines:
        lower = l.lower()
        if lower in boilerplate_set:
            continue
        if any(lower.startswith(p) for p in skip_prefixes):
            continue
        if not l:
            continue
        content_lines.append(l)

    return len(content_lines) <= 1


def process_all_files() -> None:
    txt_files = sorted(KB_DIR.glob("*.txt"))
    non_plan = [f for f in txt_files if not f.name.startswith("productsandservices__plan__scheme__")]
    plan_files = sorted([f for f in txt_files if f.name.startswith("productsandservices__plan__scheme__")])

    sections = []
    processed = 0
    skipped_boilerplate = 0
    skipped_empty = 0
    warnings = []

    # --- Process non-plan files ---
    for filepath in non_plan:
        fname = filepath.name
        if fname in SKIP_FILES:
            continue
        try:
            raw = filepath.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            warnings.append(f"WARNING: Could not read {fname}: {e}")
            continue
        if fname in BOILERPLATE_ONLY_FILES:
            skipped_boilerplate += 1
            continue

        cleaned = clean_file_content(raw)

        if not has_meaningful_content(cleaned):
            skipped_empty += 1
            warnings.append(f"NOTE: {fname} had no meaningful content after cleaning.")
            continue

        header = derive_section_header(fname)
        section_text = f"{header}\n\n{cleaned}"
        sections.append(section_text)
        processed += 1

    # --- Process plan files: collapse all boilerplate-only plans into one section ---
    all_plan_names = []
    plans_with_unique_content = []

    for filepath in plan_files:
        fname = filepath.name
        if fname in SKIP_FILES:
            continue
        try:
            raw = filepath.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            warnings.append(f"WARNING: Could not read {fname}: {e}")
            continue

        plan_name = extract_plan_name_from_filename(fname)

        if is_plan_file_boilerplate_only(raw):
            all_plan_names.append(plan_name)
            skipped_boilerplate += 1
        else:
            # Has some unique content: process and emit individually
            cleaned = clean_file_content(raw)
            if has_meaningful_content(cleaned):
                header = derive_section_header(fname)
                section_text = f"{header}\n\n{cleaned}"
                plans_with_unique_content.append(section_text)
                processed += 1
                all_plan_names.append(plan_name)
            else:
                all_plan_names.append(plan_name)
                skipped_empty += 1

    # Emit consolidated plan listing
    if all_plan_names:
        plan_list_text = (
            "AVAILABLE LAYA HEALTHCARE INSURANCE PLANS\n\n"
            "The following private health insurance plans (schemes) are available from Laya Healthcare. "
            "Each plan provides a combination of hospital cover, day-to-day medical expense benefits, "
            "maternity benefits, cancer care cover, cardiac screening, and emergency overseas cover. "
            "Specific benefit levels, excess amounts, and coverage limits vary by plan and can be "
            "verified through the Member Area.\n\n"
            "Available plans:\n"
            + "\n".join(f"- {name}" for name in sorted(all_plan_names))
        )
        sections.append(plan_list_text)
        processed += 1

    sections.extend(plans_with_unique_content)

    title_block = "LAYA HEALTHCARE — INSURANCE KNOWLEDGE BASE (CLEANED)"
    separator = "=" * 60

    output_lines = [title_block, ""]
    for section in sections:
        output_lines.append(separator)
        output_lines.append("")
        output_lines.append(section)
        output_lines.append("")

    final_output = "\n".join(output_lines)
    # Clean up triple+ blank lines in final output
    final_output = re.sub(r"\n{3,}", "\n\n", final_output)
    final_output = final_output.strip() + "\n"

    OUTPUT_FILE.write_text(final_output, encoding="utf-8")

    print(f"\nProcessing complete.")
    print(f"  Files processed:          {processed}")
    print(f"  Skipped (boilerplate):    {skipped_boilerplate}")
    print(f"  Skipped (empty content):  {skipped_empty}")
    print(f"  Output file:              {OUTPUT_FILE}")
    print(f"  Output size:              {OUTPUT_FILE.stat().st_size:,} bytes")
    print(f"  Output lines:             {final_output.count(chr(10)):,}")
    if warnings:
        print(f"\n  Warnings/Notes:")
        for w in warnings:
            print(f"    {w}")


if __name__ == "__main__":
    process_all_files()

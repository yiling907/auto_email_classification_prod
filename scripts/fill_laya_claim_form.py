#!/usr/bin/env python3
"""
fill_laya_claim_form.py
=======================
Fills the Laya Healthcare Out-patient Claim Form PDF using synthetic
customer + case data from the laya_synthetic_dataset_starter dataset.

Uses:
  - customer  : CUST-000798  Maeve Kennedy
  - email     : EML-000008   Neck strain treatment – City Sports Injury Clinic
  - case      : CASE-000008  3 invoices, EUR 360.16 each
  - attachments: ATT-000010 (physiotherapy), ATT-000011 (dental), ATT-000012 (medical)

Output: Laya_Healthcare-Out-patient_Claim_Form_FILLED.pdf
"""

import io
import os
import sys

from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas as rl_canvas
import pypdf

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC  = os.path.join(BASE, "Laya_Healthcare-Out-patient_Claim_Form.pdf")
OUT  = os.path.join(BASE, "Laya_Healthcare-Out-patient_Claim_Form_FILLED.pdf")

# ── Form data (from synthetic dataset) ───────────────────────────────────────
DATA = {
    # ── Section 1: Member's Details ──────────────────────────────────────────
    "membership_no":   "MEM-000798",
    "title":           "Ms",
    "surname":         "Kennedy",
    "forenames":       "Maeve",
    "dob_day":         "09",
    "dob_month":       "10",
    "dob_year":        "1992",
    "telephone":       "087 929 1304",
    "address":         "41 St Patricks Avenue, Galway, Co. Waterford",

    # ── Section 3: MRI (N/A for this claim) ──────────────────────────────────
    # Not filled – physiotherapy/sports injury claim, no MRI referral

    # ── Section 4: Accidents ─────────────────────────────────────────────────
    "accident_desc":   "Neck strain – sports injury",
    "accident_day":    "11",
    "accident_month":  "05",
    "accident_year":   "2025",
    "recoverable_no":  True,   # expenses NOT recoverable from third party

    # ── Section 5: Emergency Dental ──────────────────────────────────────────
    "dental_day":      "11",
    "dental_month":    "05",
    "dental_year":     "2025",
    "dental_place":    "City Sports Injury Clinic, Galway",
    "dental_desc":     "Dental consultation (Inv INV-7597)",
    "dental_date_start": "11/05/2025",
    "dental_cost":     "€360.16",

    # ── Section 6: Receipt details ────────────────────────────────────────────
    # Row 1: physiotherapy receipt
    "r1_type":   "Physiotherapy",
    "r1_num":    "1",
    "r1_total":  "€360.16",
    # Row 2: medical invoice
    "r2_type":   "Medical Consultation",
    "r2_num":    "1",
    "r2_total":  "€360.16",
    # Row 3: dental (entered in §5 but also listed here for reference)
    "r3_type":   "Dental",
    "r3_num":    "1",
    "r3_total":  "€360.16",

    # ── Section 7: Payment details ────────────────────────────────────────────
    "account_holder":  "Maeve Kennedy",
    "account_number":  "— (card payment)",
    "bank_sort_code":  "—",
    "bank_name":       "—",
    "payment_day":     "11",
    "payment_month":   "05",
    "payment_year":    "2025",

    # ── Section 8: Declaration date ───────────────────────────────────────────
    "decl_date":       "11/05/2025",
}

# ── Styling ───────────────────────────────────────────────────────────────────
INK        = HexColor("#1a1a2e")   # near-black, slightly navy to blend with form
FONT       = "Helvetica"
FONT_BOLD  = "Helvetica-Bold"
SIZE_NORM  = 9
SIZE_SM    = 8


# ══════════════════════════════════════════════════════════════════════════════
# Overlay builders – one per page
# ══════════════════════════════════════════════════════════════════════════════

def _build_page1_overlay(w: float, h: float) -> bytes:
    """Draw all filled values for page 1 onto a transparent overlay."""
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(w, h))
    c.setFont(FONT, SIZE_NORM)
    c.setFillColor(INK)

    def t(x, y, text, bold=False, size=SIZE_NORM):
        c.setFont(FONT_BOLD if bold else FONT, size)
        c.drawString(x, y, str(text))

    # ── §1 Member's Details ───────────────────────────────────────────────────
    # "Membership no:" label y≈546
    t(155, 546, DATA["membership_no"])

    # "Title:  Surname:  Forenames:" row y≈528
    t(90,  528, DATA["title"])
    t(230, 528, DATA["surname"])
    t(455, 528, DATA["forenames"])

    # "Date of birth: Day  Month  Year   Telephone:" row y≈509
    t(125, 509, DATA["dob_day"])
    t(175, 509, DATA["dob_month"])
    t(228, 509, DATA["dob_year"])
    t(330, 509, DATA["telephone"])

    # Correspondence address y≈491
    t(195, 491, DATA["address"])

    # ── §4 Accidents ─────────────────────────────────────────────────────────
    # "Description and date of accident/injury: Day Month Year" y≈181
    t(57,  171, DATA["accident_desc"], size=SIZE_SM)
    t(200, 181, DATA["accident_day"])
    t(258, 181, DATA["accident_month"])
    t(318, 181, DATA["accident_year"])

    # "Are expenses recoverable? Yes □  No □" y≈164.9
    # Mark "No" checkbox with an X  (No is at x≈284)
    t(284, 165, "X", bold=True)

    # Signed lines (member + subscriber) y≈67 – draw a signature-style string
    t(57,  67, "Maeve Kennedy",  bold=True)
    t(370, 67, "Maeve Kennedy",  bold=True)

    c.save()
    return buf.getvalue()


def _build_page2_overlay(w: float, h: float) -> bytes:
    """Draw all filled values for page 2 onto a transparent overlay."""
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(w, h))
    c.setFont(FONT, SIZE_NORM)
    c.setFillColor(INK)

    def t(x, y, text, bold=False, size=SIZE_NORM):
        c.setFont(FONT_BOLD if bold else FONT, size)
        c.drawString(x, y, str(text))

    # ── §5 Emergency Dental ───────────────────────────────────────────────────
    # "Date and place of injury: Day Month Year" y≈817
    t(57,  806, DATA["dental_place"], size=SIZE_SM)
    t(145, 817, DATA["dental_day"])
    t(200, 817, DATA["dental_month"])
    t(265, 817, DATA["dental_year"])

    # "Description of accident/injury:" y≈800
    t(195, 800, DATA["dental_desc"], size=SIZE_SM)

    # Dentist section – Date / Description of work / Cost row  y≈734 (Date treatment commenced)
    t(188, 734, DATA["dental_date_start"],  size=SIZE_SM)
    t(260, 734, "Dental consultation – neck-related pain",  size=SIZE_SM)
    t(550, 734, DATA["dental_cost"],         size=SIZE_SM)

    # ── §6 Receipt details ────────────────────────────────────────────────────
    # Columns: Treatment type (x≈95), Num (x≈215), Total (x≈258)
    # Right columns: Treatment type (x≈345), Num (x≈465), Total (x≈510)
    rows = [
        (DATA["r1_type"], DATA["r1_num"], DATA["r1_total"]),
        (DATA["r2_type"], DATA["r2_num"], DATA["r2_total"]),
        (DATA["r3_type"], DATA["r3_num"], DATA["r3_total"]),
    ]
    row_y = [583.8, 566.5, 549.3]
    for i, ((rtype, rnum, rtotal), ry) in enumerate(zip(rows, row_y)):
        t(95,  ry, rtype,  size=SIZE_SM)
        t(215, ry, rnum,   size=SIZE_SM)
        t(258, ry, rtotal, size=SIZE_SM)

    # ── §7 Payment details ────────────────────────────────────────────────────
    # "Name of account holder(s):" y≈377.5
    t(340, 377, DATA["account_holder"])

    # "Account number:" y≈440  "Bank sort code:" y≈437
    t(290, 440, DATA["account_number"],  size=SIZE_SM)
    t(450, 437, DATA["bank_sort_code"],  size=SIZE_SM)

    # Bank name/address (below sort code line) y≈408
    t(201, 408, DATA["bank_name"], size=SIZE_SM)

    # Signature y≈371
    t(285, 371, DATA["account_holder"], bold=True, size=SIZE_SM)

    # Date: Day Month Year y≈337
    t(250, 337, DATA["payment_day"])
    t(290, 337, DATA["payment_month"])
    t(348, 337, DATA["payment_year"])

    # ── §8 Declaration ────────────────────────────────────────────────────────
    # "Member's signature  (a parent or guardian if patient is under 16)  Date:" y≈244
    t(57,  244, DATA["account_holder"], bold=True)
    t(530, 244, DATA["decl_date"],      size=SIZE_SM)

    c.save()
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
# Merge overlay into original PDF
# ══════════════════════════════════════════════════════════════════════════════

def fill_form():
    reader  = pypdf.PdfReader(SRC)
    writer  = pypdf.PdfWriter()

    for page_idx, page in enumerate(reader.pages):
        w = float(page.mediabox.width)
        h = float(page.mediabox.height)

        if page_idx == 0:
            overlay_bytes = _build_page1_overlay(w, h)
        else:
            overlay_bytes = _build_page2_overlay(w, h)

        overlay_reader = pypdf.PdfReader(io.BytesIO(overlay_bytes))
        overlay_page   = overlay_reader.pages[0]

        # Merge: draw overlay on top of original page
        page.merge_page(overlay_page)
        writer.add_page(page)

    with open(OUT, "wb") as fh:
        writer.write(fh)

    print(f"Filled PDF written to: {OUT}")


if __name__ == "__main__":
    fill_form()

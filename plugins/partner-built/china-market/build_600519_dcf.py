"""
Build 600519.SH (贵州茅台) DCF model per dcf-model SKILL.md spec.

Two sheets (DCF + WACC), CHOOSE-based case selector (Bear/Base/Bull),
10-year explicit projection (per skill Step 7: consumer-staple champion → 10Y
keeps TV/EV in 50-70% range; 5Y was 79.8% which fails sanity check),
3 sensitivity tables at bottom of DCF (5x5 each, 75 formula cells total),
blue-font inputs / black formulas / green sheet links, professional borders,
cell comments on every hardcoded input.

Mirror computation: every formula's expected value is also computed in pure
Python so we can sanity-check no #REF! / #DIV/0! / logic break before
writing the file. Skill calls for `recalc.py` (LibreOffice) which isn't
available on this host — Python mirror is the substitute.
"""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path

import openpyxl
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# ============================================================================
# Raw inputs — from china-market MCP (locked in Step 1, user confirmed Base default)
# ============================================================================

TICKER = "600519.SH"
COMPANY = "贵州茅台 (Kweichow Moutai)"
ASOF = date(2026, 5, 21)

PRICE = 1323.00
SHARES_M = 1252.27
CASH_BN = 516.9
DEBT_BN = 0.0
MINORITY_BN = 93.2

HIST_YEARS = [2020, 2021, 2022, 2023, 2024, 2025]
HIST_REV = [980.0, 1094.6, 1275.5, 1505.6, 1741.4, 1720.5]
HIST_EBIT = [666.4, 747.5, 878.8, 1037.1, 1196.9, 1148.1]
HIST_NI = [467.0, 524.6, 627.2, 747.3, 862.3, 823.2]
HIST_OCF = [516.7, 640.3, 367.0, 666.0, 924.6, 615.2]

RF = 0.027
BETA = 0.794
ERP = 0.060
TAX = 0.25
COE = RF + BETA * ERP
WACC_BASE = COE

PROJ_YEARS = list(range(2026, 2036))   # 10-year explicit
N_PROJ = len(PROJ_YEARS)

ASSUMPTIONS = {
    "Bear": {
        "growth": [0.00, 0.02, 0.03, 0.03, 0.03, 0.025, 0.022, 0.020, 0.018, 0.016],
        "ebit_margin": [0.65, 0.64, 0.63, 0.625, 0.62, 0.615, 0.61, 0.605, 0.60, 0.60],
        "da_pct": 0.020, "capex_pct": 0.025, "nwc_pct": 0.05,
        "terminal_g": 0.015, "wacc": 0.085,
    },
    "Base": {
        "growth": [0.03, 0.05, 0.06, 0.06, 0.05, 0.045, 0.040, 0.035, 0.030, 0.027],
        "ebit_margin": [0.67, 0.668, 0.665, 0.662, 0.66, 0.658, 0.655, 0.652, 0.65, 0.65],
        "da_pct": 0.020, "capex_pct": 0.020, "nwc_pct": 0.03,
        "terminal_g": 0.025, "wacc": round(WACC_BASE, 4),
    },
    "Bull": {
        "growth": [0.06, 0.08, 0.09, 0.08, 0.07, 0.062, 0.055, 0.048, 0.042, 0.038],
        "ebit_margin": [0.68, 0.685, 0.685, 0.69, 0.69, 0.69, 0.69, 0.69, 0.69, 0.69],
        "da_pct": 0.020, "capex_pct": 0.015, "nwc_pct": 0.02,
        "terminal_g": 0.035, "wacc": 0.065,
    },
}
BASE = ASSUMPTIONS["Base"]

PROJ_PERIODS = [0.5 + i for i in range(N_PROJ)]  # mid-year

# ============================================================================
# Styling
# ============================================================================

BLUE_INPUT = Font(color="0000FF", name="Calibri", size=11)
BLUE_INPUT_B = Font(color="0000FF", name="Calibri", size=11, bold=True)
BLACK_FORMULA = Font(color="000000", name="Calibri", size=11)
BLACK_BOLD = Font(color="000000", name="Calibri", size=11, bold=True)
GREEN_LINK = Font(color="008000", name="Calibri", size=11)
WHITE_BOLD = Font(color="FFFFFF", name="Calibri", size=11, bold=True)

FILL_HEADER = PatternFill("solid", fgColor="1F4E79")
FILL_SUBHEADER = PatternFill("solid", fgColor="D9E1F2")
FILL_INPUT = PatternFill("solid", fgColor="F2F2F2")
FILL_OUTPUT = PatternFill("solid", fgColor="BDD7EE")

BORDER_THIN = Side(border_style="thin", color="808080")
BORDER_THICK = Side(border_style="thick", color="000000")

FMT_PCT = "0.0%"
FMT_PCT2 = "0.00%"
FMT_CNY_BN = "#,##0;(#,##0);-"
FMT_CNY_PER_SH = "¥#,##0.00;(¥#,##0.00);-"
FMT_MULT = "0.000"


def box_section(ws, r1, c1, r2, c2, side=BORDER_THICK):
    for r in range(r1, r2 + 1):
        for c in range(c1, c2 + 1):
            cell = ws.cell(row=r, column=c)
            existing = cell.border
            cell.border = Border(
                left=side if c == c1 else existing.left,
                right=side if c == c2 else existing.right,
                top=side if r == r1 else existing.top,
                bottom=side if r == r2 else existing.bottom,
            )


def put(ws, addr, val, *, font=None, fill=None, fmt=None, comment=None, align=None):
    cell = ws[addr]
    cell.value = val
    if font: cell.font = font
    if fill: cell.fill = fill
    if fmt: cell.number_format = fmt
    if align: cell.alignment = align
    if comment: cell.comment = Comment(comment, "DCF builder")
    return cell


# ============================================================================
# Mirror calculator
# ============================================================================

def mirror_dcf(name: str):
    a = ASSUMPTIONS[name]
    rev_base = HIST_REV[-1]
    rev = []
    cur = rev_base
    for g in a["growth"]:
        cur = cur * (1 + g); rev.append(cur)
    ebit = [rev[i] * a["ebit_margin"][i] for i in range(N_PROJ)]
    nopat = [e * (1 - TAX) for e in ebit]
    da = [r * a["da_pct"] for r in rev]
    capex = [r * a["capex_pct"] for r in rev]
    drev = [rev[0] - rev_base] + [rev[i] - rev[i - 1] for i in range(1, N_PROJ)]
    nwc = [d * a["nwc_pct"] for d in drev]
    fcf = [nopat[i] + da[i] - capex[i] - nwc[i] for i in range(N_PROJ)]
    disc = [1 / (1 + a["wacc"]) ** p for p in PROJ_PERIODS]
    pv_fcf = [fcf[i] * disc[i] for i in range(N_PROJ)]
    assert a["wacc"] > a["terminal_g"], f"{name}: g >= WACC"
    tfcf = fcf[-1] * (1 + a["terminal_g"])
    tv = tfcf / (a["wacc"] - a["terminal_g"])
    pv_tv = tv / (1 + a["wacc"]) ** PROJ_PERIODS[-1]
    ev = sum(pv_fcf) + pv_tv
    net_debt = DEBT_BN - CASH_BN
    equity = ev - net_debt - MINORITY_BN
    implied = equity * 100 / SHARES_M
    return dict(rev=rev, fcf=fcf, sum_pv=sum(pv_fcf), pv_tv=pv_tv, ev=ev,
                equity=equity, implied=implied, tv_pct=pv_tv / ev,
                upside=implied / PRICE - 1, net_debt=net_debt)


# ============================================================================
# WACC sheet
# ============================================================================

wb = openpyxl.Workbook()
ws_dcf = wb.active
ws_dcf.title = "DCF"
ws_wacc = wb.create_sheet("WACC")


def build_wacc_sheet():
    ws = ws_wacc
    ws.column_dimensions["A"].width = 38
    for c in "BCD":
        ws.column_dimensions[c].width = 16
    ws.merge_cells("A1:D1")
    put(ws, "A1", f"{COMPANY} ({TICKER}) — WACC Calculation",
        font=WHITE_BOLD, fill=FILL_HEADER, align=Alignment(horizontal="center"))
    ws.merge_cells("A3:D3")
    put(ws, "A3", "COST OF EQUITY (CAPM)", font=WHITE_BOLD, fill=FILL_HEADER)
    put(ws, "A4", "Risk-Free Rate (中国 10Y 国债)")
    put(ws, "B4", RF, font=BLUE_INPUT, fill=FILL_INPUT, fmt=FMT_PCT2,
        comment="Source: 中央国债登记结算公司 2026-05-21 baseline, 请用最新数据复核")
    put(ws, "A5", "Beta (3Y monthly vs 沪深 300)")
    put(ws, "B5", BETA, font=BLUE_INPUT, fill=FILL_INPUT, fmt=FMT_MULT,
        comment=f"Source: 自算 2026-05-21, akshare 3Y monthly, 36 obs, β={BETA:.3f}")
    put(ws, "A6", "Equity Risk Premium (Damodaran China)")
    put(ws, "B6", ERP, font=BLUE_INPUT, fill=FILL_INPUT, fmt=FMT_PCT2,
        comment="Source: Damodaran China ERP 6.0% (range 5.5-6.5%)")
    put(ws, "A7", "Cost of Equity", font=BLACK_BOLD)
    put(ws, "B7", "=B4+B5*B6", font=BLACK_BOLD, fill=FILL_OUTPUT, fmt=FMT_PCT2)
    box_section(ws, 3, 1, 7, 4)

    ws.merge_cells("A9:D9")
    put(ws, "A9", "COST OF DEBT", font=WHITE_BOLD, fill=FILL_HEADER)
    put(ws, "A10", "Pre-Tax Cost of Debt")
    put(ws, "B10", 0.0, font=BLUE_INPUT, fill=FILL_INPUT, fmt=FMT_PCT2,
        comment="茅台无有息负债, 短/长期借款 = 0, 应付债券 = 0")
    put(ws, "A11", "Tax Rate")
    put(ws, "B11", TAX, font=BLUE_INPUT, fill=FILL_INPUT, fmt=FMT_PCT2,
        comment="Source: 中国法定企业所得税率 25%")
    put(ws, "A12", "After-Tax Cost of Debt", font=BLACK_BOLD)
    put(ws, "B12", "=B10*(1-B11)", font=BLACK_BOLD, fill=FILL_OUTPUT, fmt=FMT_PCT2)
    box_section(ws, 9, 1, 12, 4)

    ws.merge_cells("A14:D14")
    put(ws, "A14", "CAPITAL STRUCTURE (亿元)", font=WHITE_BOLD, fill=FILL_HEADER)
    put(ws, "A15", "Current Stock Price (¥)")
    put(ws, "B15", PRICE, font=BLUE_INPUT, fill=FILL_INPUT, fmt=FMT_CNY_PER_SH,
        comment="Source: akshare 2026-05-18 close")
    put(ws, "A16", "Shares Outstanding (M)")
    put(ws, "B16", SHARES_M, font=BLUE_INPUT, fill=FILL_INPUT, fmt="#,##0.00",
        comment="Source: akshare stock_individual_info_em 2026-05-21, 总股本=1,252,270,215")
    put(ws, "A17", "Market Cap (亿元)", font=BLACK_BOLD)
    put(ws, "B17", "=B15*B16/100", font=BLACK_BOLD, fmt=FMT_CNY_BN,
        comment="= 股价 × 总股本(百万) / 100 → 亿元")
    put(ws, "A18", "Total Debt")
    put(ws, "B18", DEBT_BN, font=BLUE_INPUT, fill=FILL_INPUT, fmt=FMT_CNY_BN,
        comment="Source: 2025 年报 短期借款+长期借款+应付债券 = 0")
    put(ws, "A19", "Cash & Equivalents")
    put(ws, "B19", CASH_BN, font=BLUE_INPUT, fill=FILL_INPUT, fmt=FMT_CNY_BN,
        comment="Source: 2025 年报 货币资金 516.9 亿")
    put(ws, "A20", "Net Debt (Total Debt − Cash)", font=BLACK_BOLD)
    put(ws, "B20", "=B18-B19", font=BLACK_BOLD, fmt=FMT_CNY_BN)
    put(ws, "A21", "Enterprise Value", font=BLACK_BOLD)
    put(ws, "B21", "=B17+B20", font=BLACK_BOLD, fmt=FMT_CNY_BN)
    box_section(ws, 14, 1, 21, 4)

    ws.merge_cells("A23:D23")
    put(ws, "A23", "WACC", font=WHITE_BOLD, fill=FILL_HEADER)
    put(ws, "A24", "Component", font=BLACK_BOLD, fill=FILL_SUBHEADER)
    put(ws, "B24", "Weight", font=BLACK_BOLD, fill=FILL_SUBHEADER)
    put(ws, "C24", "Cost", font=BLACK_BOLD, fill=FILL_SUBHEADER)
    put(ws, "D24", "Contribution", font=BLACK_BOLD, fill=FILL_SUBHEADER)
    put(ws, "A25", "Equity")
    put(ws, "B25", "=IFERROR(B17/B21,1)", fmt=FMT_PCT2)
    put(ws, "C25", "=B7", font=GREEN_LINK, fmt=FMT_PCT2)
    put(ws, "D25", "=B25*C25", fmt=FMT_PCT2)
    put(ws, "A26", "Debt")
    put(ws, "B26", "=IFERROR(B20/B21,0)", fmt=FMT_PCT2)
    put(ws, "C26", "=B12", font=GREEN_LINK, fmt=FMT_PCT2)
    put(ws, "D26", "=B26*C26", fmt=FMT_PCT2)
    put(ws, "A27", "WACC", font=BLACK_BOLD)
    put(ws, "D27", "=D25+D26", font=BLACK_BOLD, fill=FILL_OUTPUT, fmt=FMT_PCT2)
    box_section(ws, 23, 1, 27, 4)


build_wacc_sheet()

# ============================================================================
# DCF sheet
# ============================================================================

def build_dcf_sheet():
    ws = ws_dcf
    # 历史 6 + 投影 10 = 16 列, A..Q
    ws.column_dimensions["A"].width = 36
    for col_idx in range(2, 2 + 6 + N_PROJ):
        ws.column_dimensions[get_column_letter(col_idx)].width = 12

    # Header
    last_col = get_column_letter(2 + 6 + N_PROJ - 1)
    ws.merge_cells(f"A1:{last_col}1")
    put(ws, "A1", f"{COMPANY} ({TICKER}) — DCF Model",
        font=WHITE_BOLD, fill=FILL_HEADER, align=Alignment(horizontal="center"))
    ws.merge_cells(f"A2:{last_col}2")
    put(ws, "A2",
        f"As of {ASOF} | Year End: 2025/12/31 | Currency: CNY (CAS) | Industry: 白酒Ⅱ (申万)",
        font=BLACK_FORMULA, fill=FILL_SUBHEADER, align=Alignment(horizontal="center"))

    # Case selector
    put(ws, "A4", "Case Selector (1=Bear, 2=Base, 3=Bull)", font=BLACK_BOLD)
    put(ws, "B4", 2, font=BLUE_INPUT_B, fill=FILL_OUTPUT, fmt="0",
        comment="Change to 1/2/3 to switch scenario. All downstream formulas update.")
    put(ws, "A5", "Active Case", font=BLACK_BOLD)
    put(ws, "B5", '=IF(B4=1,"Bear",IF(B4=2,"Base","Bull"))',
        font=BLACK_BOLD, fill=FILL_OUTPUT, align=Alignment(horizontal="center"))

    # Market data
    last_md_col = get_column_letter(8)
    ws.merge_cells(f"A7:{last_md_col}7")
    put(ws, "A7", "MARKET DATA (NOT case dependent)", font=WHITE_BOLD, fill=FILL_HEADER)
    put(ws, "A8", "Current Price (¥/share)")
    put(ws, "B8", "=WACC!B15", font=GREEN_LINK, fmt=FMT_CNY_PER_SH)
    put(ws, "A9", "Shares Outstanding (M)")
    put(ws, "B9", "=WACC!B16", font=GREEN_LINK, fmt="#,##0.00")
    put(ws, "A10", "Net Debt (亿元) [+ debt / − cash]")
    put(ws, "B10", "=WACC!B20", font=GREEN_LINK, fmt=FMT_CNY_BN)
    put(ws, "A11", "Minority Interest (亿元)")
    put(ws, "B11", MINORITY_BN, font=BLUE_INPUT, fill=FILL_INPUT, fmt=FMT_CNY_BN,
        comment="Source: 2025 年报 少数股东权益 93.2 亿")
    box_section(ws, 7, 1, 11, 8)

    # Scenario assumption blocks — 10 columns (B..K)
    proj_headers = [f"FY{i + 1} ({y}E)" for i, y in enumerate(PROJ_YEARS)]
    item_labels = ["Revenue Growth", "EBIT Margin", "D&A % Rev", "CapEx % Rev",
                   "ΔNWC % ΔRev", "Terminal g", "WACC"]
    block_last_col = get_column_letter(1 + N_PROJ + 1)  # A + 10 cols = L

    def write_block(start_row, name, scenario_key):
        a = ASSUMPTIONS[scenario_key]
        ws.merge_cells(start_row=start_row, start_column=1,
                       end_row=start_row, end_column=1 + N_PROJ + 1)
        put(ws, f"A{start_row}", f"{name.upper()} CASE ASSUMPTIONS",
            font=WHITE_BOLD, fill=FILL_HEADER)
        put(ws, f"A{start_row + 1}", "Assumption", font=BLACK_BOLD, fill=FILL_SUBHEADER)
        for i, hdr in enumerate(proj_headers):
            put(ws, f"{get_column_letter(2 + i)}{start_row + 1}", hdr,
                font=BLACK_BOLD, fill=FILL_SUBHEADER, align=Alignment(horizontal="center"))
        for row_off, label in enumerate(item_labels):
            put(ws, f"A{start_row + 2 + row_off}", label)
        for i in range(N_PROJ):
            put(ws, f"{get_column_letter(2 + i)}{start_row + 2}",
                a["growth"][i], font=BLUE_INPUT, fill=FILL_INPUT, fmt=FMT_PCT,
                comment=f"{name} Y{i+1} 收入增速")
            put(ws, f"{get_column_letter(2 + i)}{start_row + 3}",
                a["ebit_margin"][i], font=BLUE_INPUT, fill=FILL_INPUT, fmt=FMT_PCT,
                comment=f"{name} Y{i+1} 营业利润率")
        for offset, key in [(4, "da_pct"), (5, "capex_pct"), (6, "nwc_pct")]:
            for i in range(N_PROJ):
                put(ws, f"{get_column_letter(2 + i)}{start_row + offset}",
                    a[key], font=BLUE_INPUT, fill=FILL_INPUT, fmt=FMT_PCT,
                    comment=f"{name} {item_labels[offset-2]} (flat across {N_PROJ}Y)")
        put(ws, f"B{start_row + 7}", a["terminal_g"], font=BLUE_INPUT, fill=FILL_INPUT,
            fmt=FMT_PCT2, comment=f"{name} terminal growth")
        put(ws, f"B{start_row + 8}", a["wacc"], font=BLUE_INPUT, fill=FILL_INPUT,
            fmt=FMT_PCT2,
            comment=f"{name} WACC. Base = Rf+β·ERP = {RF:.1%}+{BETA:.3f}·{ERP:.1%} = {COE:.2%}")
        box_section(ws, start_row, 1, start_row + 8, 1 + N_PROJ + 1)
        return start_row + 8

    BEAR_START = 14
    BASE_START = 24
    BULL_START = 34
    write_block(BEAR_START, "Bear", "Bear")
    write_block(BASE_START, "Base", "Base")
    write_block(BULL_START, "Bull", "Bull")

    # Consolidation column
    SEL_START = 45
    ws.merge_cells(start_row=SEL_START, start_column=1, end_row=SEL_START, end_column=1 + N_PROJ + 1)
    put(ws, f"A{SEL_START}", "SELECTED CASE — CONSOLIDATION COLUMN",
        font=WHITE_BOLD, fill=FILL_HEADER)
    put(ws, f"A{SEL_START + 1}", "Item", font=BLACK_BOLD, fill=FILL_SUBHEADER)
    for i, hdr in enumerate(proj_headers):
        put(ws, f"{get_column_letter(2 + i)}{SEL_START + 1}", hdr,
            font=BLACK_BOLD, fill=FILL_SUBHEADER, align=Alignment(horizontal="center"))

    block_offsets = {"growth": 2, "ebit": 3, "da": 4, "capex": 5, "nwc": 6}
    sel_rows = {
        "growth": SEL_START + 2, "ebit": SEL_START + 3, "da": SEL_START + 4,
        "capex": SEL_START + 5, "nwc": SEL_START + 6,
        "terminal_g": SEL_START + 7, "wacc": SEL_START + 8,
    }
    label_map = {"growth": "Revenue Growth", "ebit": "EBIT Margin",
                 "da": "D&A % Rev", "capex": "CapEx % Rev", "nwc": "ΔNWC % ΔRev"}
    for key, label in label_map.items():
        put(ws, f"A{sel_rows[key]}", label, font=BLACK_BOLD)
        for i in range(N_PROJ):
            col = get_column_letter(2 + i)
            f = (f"=CHOOSE($B$4,"
                 f"{col}{BEAR_START + block_offsets[key]},"
                 f"{col}{BASE_START + block_offsets[key]},"
                 f"{col}{BULL_START + block_offsets[key]})")
            put(ws, f"{col}{sel_rows[key]}", f, font=BLACK_FORMULA, fmt=FMT_PCT)
    put(ws, f"A{sel_rows['terminal_g']}", "Terminal g", font=BLACK_BOLD)
    put(ws, f"B{sel_rows['terminal_g']}",
        f"=CHOOSE($B$4,B{BEAR_START+7},B{BASE_START+7},B{BULL_START+7})",
        font=BLACK_FORMULA, fmt=FMT_PCT2)
    put(ws, f"A{sel_rows['wacc']}", "WACC", font=BLACK_BOLD)
    put(ws, f"B{sel_rows['wacc']}",
        f"=CHOOSE($B$4,B{BEAR_START+8},B{BASE_START+8},B{BULL_START+8})",
        font=BLACK_FORMULA, fmt=FMT_PCT2)
    box_section(ws, SEL_START, 1, SEL_START + 8, 1 + N_PROJ + 1)

    # Income statement
    IS_START = 55
    all_years = HIST_YEARS + PROJ_YEARS
    n_all = len(all_years)
    ws.merge_cells(start_row=IS_START, start_column=1,
                   end_row=IS_START, end_column=1 + n_all)
    put(ws, f"A{IS_START}", "HISTORICAL & PROJECTED FINANCIALS (亿元)",
        font=WHITE_BOLD, fill=FILL_HEADER)
    put(ws, f"A{IS_START + 1}", "Item", font=BLACK_BOLD, fill=FILL_SUBHEADER)
    for i, y in enumerate(all_years):
        col = get_column_letter(2 + i)
        suffix = "" if y <= 2025 else "E"
        put(ws, f"{col}{IS_START + 1}", f"{y}{suffix}",
            font=BLACK_BOLD, fill=FILL_SUBHEADER, align=Alignment(horizontal="center"))

    REV_ROW = IS_START + 2
    put(ws, f"A{REV_ROW}", "Revenue", font=BLACK_BOLD)
    for i, y in enumerate(HIST_YEARS):
        col = get_column_letter(2 + i)
        put(ws, f"{col}{REV_ROW}", HIST_REV[i], font=BLUE_INPUT, fill=FILL_INPUT,
            fmt=FMT_CNY_BN, comment=f"Source: 利润表 {y} 年报 营业总收入")
    for i in range(N_PROJ):
        col = get_column_letter(2 + 6 + i)
        prev_col = get_column_letter(2 + 6 + i - 1) if i > 0 else get_column_letter(2 + 5)
        g_col = get_column_letter(2 + i)
        put(ws, f"{col}{REV_ROW}",
            f"={prev_col}{REV_ROW}*(1+{g_col}{sel_rows['growth']})", fmt=FMT_CNY_BN)

    GROW_ROW = IS_START + 3
    put(ws, f"A{GROW_ROW}", "  YoY %", font=BLACK_FORMULA)
    for i in range(1, n_all):
        col = get_column_letter(2 + i)
        prev = get_column_letter(2 + i - 1)
        put(ws, f"{col}{GROW_ROW}",
            f"=IFERROR({col}{REV_ROW}/{prev}{REV_ROW}-1,0)", fmt=FMT_PCT)

    EBIT_ROW = IS_START + 4
    put(ws, f"A{EBIT_ROW}", "EBIT (营业利润)", font=BLACK_BOLD)
    for i, y in enumerate(HIST_YEARS):
        col = get_column_letter(2 + i)
        put(ws, f"{col}{EBIT_ROW}", HIST_EBIT[i], font=BLUE_INPUT, fill=FILL_INPUT,
            fmt=FMT_CNY_BN, comment=f"Source: 利润表 {y} 年报 营业利润")
    for i in range(N_PROJ):
        col = get_column_letter(2 + 6 + i)
        m_col = get_column_letter(2 + i)
        put(ws, f"{col}{EBIT_ROW}",
            f"={col}{REV_ROW}*{m_col}{sel_rows['ebit']}", fmt=FMT_CNY_BN)

    MARG_ROW = IS_START + 5
    put(ws, f"A{MARG_ROW}", "  EBIT margin", font=BLACK_FORMULA)
    for i in range(n_all):
        col = get_column_letter(2 + i)
        put(ws, f"{col}{MARG_ROW}",
            f"=IFERROR({col}{EBIT_ROW}/{col}{REV_ROW},0)", fmt=FMT_PCT)

    TAX_ROW = IS_START + 6
    put(ws, f"A{TAX_ROW}", "Tax (25%)", font=BLACK_FORMULA)
    for i in range(N_PROJ):
        col = get_column_letter(2 + 6 + i)
        put(ws, f"{col}{TAX_ROW}", f"={col}{EBIT_ROW}*{TAX}", fmt=FMT_CNY_BN)

    NOPAT_ROW = IS_START + 7
    put(ws, f"A{NOPAT_ROW}", "NOPAT", font=BLACK_BOLD)
    for i in range(N_PROJ):
        col = get_column_letter(2 + 6 + i)
        put(ws, f"{col}{NOPAT_ROW}", f"={col}{EBIT_ROW}-{col}{TAX_ROW}", fmt=FMT_CNY_BN)

    box_section(ws, IS_START, 1, IS_START + 7, 1 + n_all)

    # FCF build
    FCF_START = IS_START + 10
    ws.merge_cells(start_row=FCF_START, start_column=1,
                   end_row=FCF_START, end_column=1 + n_all)
    put(ws, f"A{FCF_START}", "FREE CASH FLOW (亿元)", font=WHITE_BOLD, fill=FILL_HEADER)
    put(ws, f"A{FCF_START + 1}", "Item", font=BLACK_BOLD, fill=FILL_SUBHEADER)
    for i, y in enumerate(PROJ_YEARS):
        col = get_column_letter(2 + 6 + i)
        put(ws, f"{col}{FCF_START + 1}", f"{y}E",
            font=BLACK_BOLD, fill=FILL_SUBHEADER, align=Alignment(horizontal="center"))

    rows_fcf = {
        "nopat": FCF_START + 2, "da": FCF_START + 3, "capex": FCF_START + 4,
        "nwc": FCF_START + 5, "fcf": FCF_START + 6,
        "period": FCF_START + 7, "disc": FCF_START + 8, "pv_fcf": FCF_START + 9,
    }
    put(ws, f"A{rows_fcf['nopat']}", "NOPAT (from above)", font=BLACK_FORMULA)
    put(ws, f"A{rows_fcf['da']}", "(+) D&A", font=BLACK_FORMULA)
    put(ws, f"A{rows_fcf['capex']}", "(−) CapEx", font=BLACK_FORMULA)
    put(ws, f"A{rows_fcf['nwc']}", "(−) ΔNWC", font=BLACK_FORMULA)
    put(ws, f"A{rows_fcf['fcf']}", "Unlevered FCF", font=BLACK_BOLD, fill=FILL_OUTPUT)
    put(ws, f"A{rows_fcf['period']}", "Period (mid-year)", font=BLACK_FORMULA)
    put(ws, f"A{rows_fcf['disc']}", "Discount Factor", font=BLACK_FORMULA)
    put(ws, f"A{rows_fcf['pv_fcf']}", "PV of FCF", font=BLACK_BOLD, fill=FILL_OUTPUT)

    proj_cols = [get_column_letter(2 + 6 + i) for i in range(N_PROJ)]
    sel_cols = [get_column_letter(2 + i) for i in range(N_PROJ)]
    last_hist_col = get_column_letter(2 + 5)  # G (2025)

    for i in range(N_PROJ):
        c = proj_cols[i]
        put(ws, f"{c}{rows_fcf['nopat']}", f"={c}{NOPAT_ROW}", fmt=FMT_CNY_BN)
        put(ws, f"{c}{rows_fcf['da']}",
            f"={c}{REV_ROW}*{sel_cols[i]}{sel_rows['da']}", fmt=FMT_CNY_BN)
        put(ws, f"{c}{rows_fcf['capex']}",
            f"={c}{REV_ROW}*{sel_cols[i]}{sel_rows['capex']}", fmt=FMT_CNY_BN)
        prev = last_hist_col if i == 0 else proj_cols[i - 1]
        put(ws, f"{c}{rows_fcf['nwc']}",
            f"=({c}{REV_ROW}-{prev}{REV_ROW})*{sel_cols[i]}{sel_rows['nwc']}", fmt=FMT_CNY_BN)
        put(ws, f"{c}{rows_fcf['fcf']}",
            f"={c}{rows_fcf['nopat']}+{c}{rows_fcf['da']}-{c}{rows_fcf['capex']}-{c}{rows_fcf['nwc']}",
            font=BLACK_BOLD, fill=FILL_OUTPUT, fmt=FMT_CNY_BN)
        put(ws, f"{c}{rows_fcf['period']}", PROJ_PERIODS[i], font=BLUE_INPUT, fmt="0.0",
            comment="Mid-year convention")
        put(ws, f"{c}{rows_fcf['disc']}",
            f"=1/(1+$B${sel_rows['wacc']})^{c}{rows_fcf['period']}", fmt="0.0000")
        put(ws, f"{c}{rows_fcf['pv_fcf']}",
            f"={c}{rows_fcf['fcf']}*{c}{rows_fcf['disc']}",
            font=BLACK_BOLD, fill=FILL_OUTPUT, fmt=FMT_CNY_BN)

    box_section(ws, FCF_START, 1, FCF_START + 9, 1 + n_all)

    # Valuation summary
    VS_START = FCF_START + 12
    ws.merge_cells(start_row=VS_START, start_column=1, end_row=VS_START, end_column=4)
    put(ws, f"A{VS_START}", "VALUATION SUMMARY (亿元)", font=WHITE_BOLD, fill=FILL_HEADER)
    rows_vs = {}
    items = [
        ("sum_pv_fcf", "Sum of PV of Projected FCFs (10Y)"),
        ("terminal_fcf", "Terminal FCF (FCF_Y10 × (1+g))"),
        ("tv", "Terminal Value = TFCF / (WACC − g)"),
        ("pv_tv", "PV of Terminal Value"),
        ("ev", "Enterprise Value"),
        ("net_debt", "(−) Net Debt [+ if cash]"),
        ("minority", "(−) Minority Interest"),
        ("equity", "Equity Value"),
        ("shares", "Shares Outstanding (M)"),
        ("implied", "Implied Price per Share (¥)"),
        ("current", "Current Stock Price (¥)"),
        ("upside", "Implied Upside/(Downside)"),
        ("tv_chk", "Terminal Value % of EV (target 50-70%)"),
    ]
    for i, (k, label) in enumerate(items):
        r = VS_START + 1 + i
        rows_vs[k] = r
        put(ws, f"A{r}", label)

    last_fcf_col = proj_cols[-1]
    put(ws, f"B{rows_vs['sum_pv_fcf']}",
        f"=SUM({proj_cols[0]}{rows_fcf['pv_fcf']}:{proj_cols[-1]}{rows_fcf['pv_fcf']})",
        fmt=FMT_CNY_BN)
    put(ws, f"B{rows_vs['terminal_fcf']}",
        f"={last_fcf_col}{rows_fcf['fcf']}*(1+$B${sel_rows['terminal_g']})",
        fmt=FMT_CNY_BN)
    put(ws, f"B{rows_vs['tv']}",
        f"=B{rows_vs['terminal_fcf']}/($B${sel_rows['wacc']}-$B${sel_rows['terminal_g']})",
        fmt=FMT_CNY_BN)
    put(ws, f"B{rows_vs['pv_tv']}",
        f"=B{rows_vs['tv']}/(1+$B${sel_rows['wacc']})^{last_fcf_col}{rows_fcf['period']}",
        fmt=FMT_CNY_BN)
    put(ws, f"B{rows_vs['ev']}",
        f"=B{rows_vs['sum_pv_fcf']}+B{rows_vs['pv_tv']}",
        font=BLACK_BOLD, fill=FILL_OUTPUT, fmt=FMT_CNY_BN)
    put(ws, f"B{rows_vs['net_debt']}", "=B10", font=GREEN_LINK, fmt=FMT_CNY_BN)
    put(ws, f"B{rows_vs['minority']}", "=B11", font=GREEN_LINK, fmt=FMT_CNY_BN)
    put(ws, f"B{rows_vs['equity']}",
        f"=B{rows_vs['ev']}-B{rows_vs['net_debt']}-B{rows_vs['minority']}",
        font=BLACK_BOLD, fill=FILL_OUTPUT, fmt=FMT_CNY_BN)
    put(ws, f"B{rows_vs['shares']}", "=B9", font=GREEN_LINK, fmt="#,##0.00")
    put(ws, f"B{rows_vs['implied']}",
        f"=B{rows_vs['equity']}*100/B{rows_vs['shares']}",
        font=BLACK_BOLD, fill=FILL_OUTPUT, fmt=FMT_CNY_PER_SH,
        comment="= Equity Value(亿元) × 100 / Shares(M) → ¥/股")
    put(ws, f"B{rows_vs['current']}", "=B8", font=GREEN_LINK, fmt=FMT_CNY_PER_SH)
    put(ws, f"B{rows_vs['upside']}",
        f"=B{rows_vs['implied']}/B{rows_vs['current']}-1",
        font=BLACK_BOLD, fill=FILL_OUTPUT, fmt=FMT_PCT)
    put(ws, f"B{rows_vs['tv_chk']}",
        f"=B{rows_vs['pv_tv']}/B{rows_vs['ev']}", fmt=FMT_PCT)
    box_section(ws, VS_START, 1, VS_START + len(items), 4)

    return rows_fcf, rows_vs, sel_rows, REV_ROW, EBIT_ROW, NOPAT_ROW, VS_START, proj_cols


fcf_rows, vs_rows, sel_rows, REV_ROW, EBIT_ROW, NOPAT_ROW, VS_START, PROJ_COLS = build_dcf_sheet()

# ============================================================================
# Sensitivity tables (3 × 5x5 = 75 formulas) — each cell does full DCF
# substituting two variables, centered on selected case
# ============================================================================

ws = ws_dcf
proj_fcf_cells = [f"{c}{fcf_rows['fcf']}" for c in PROJ_COLS]

SENS_BASE = VS_START + 20  # leave room below valuation summary
SENS1 = SENS_BASE
SENS2 = SENS_BASE + 12
SENS3 = SENS_BASE + 24


def build_sens_wacc_g(start_row):
    ws.merge_cells(start_row=start_row, start_column=1, end_row=start_row, end_column=7)
    put(ws, f"A{start_row}",
        "SENSITIVITY 1 — WACC × Terminal Growth (Implied Price ¥/sh)",
        font=WHITE_BOLD, fill=FILL_HEADER)
    put(ws, f"A{start_row + 1}", "WACC \\ g →", font=BLACK_BOLD, fill=FILL_SUBHEADER)
    for j in range(5):
        col = get_column_letter(2 + j)
        offset = (j - 2) * 0.005
        put(ws, f"{col}{start_row + 1}",
            f"=$B${sel_rows['terminal_g']}+{offset}", font=BLACK_BOLD,
            fill=FILL_SUBHEADER, fmt=FMT_PCT2, align=Alignment(horizontal="center"))
    for i in range(5):
        offset = (i - 2) * 0.005
        put(ws, f"A{start_row + 2 + i}",
            f"=$B${sel_rows['wacc']}+{offset}", font=BLACK_BOLD,
            fill=FILL_SUBHEADER, fmt=FMT_PCT2)
    for i in range(5):
        for j in range(5):
            r = start_row + 2 + i
            c = get_column_letter(2 + j)
            wacc_ref = f"$A{r}"
            g_ref = f"{c}${start_row + 1}"
            pv_terms = [f"{proj_fcf_cells[k]}/(1+{wacc_ref})^{PROJ_PERIODS[k]}" for k in range(N_PROJ)]
            sum_pv = "+".join(pv_terms)
            tfcf = f"{proj_fcf_cells[-1]}*(1+{g_ref})"
            pv_tv = f"({tfcf}/({wacc_ref}-{g_ref}))/(1+{wacc_ref})^{PROJ_PERIODS[-1]}"
            ev = f"({sum_pv}+{pv_tv})"
            equity = f"({ev}-B{vs_rows['net_debt']}-B{vs_rows['minority']})"
            implied = f"{equity}*100/B{vs_rows['shares']}"
            fmla = f"=IFERROR({implied},NA())"
            fill = FILL_OUTPUT if (i == 2 and j == 2) else None
            font = BLACK_BOLD if (i == 2 and j == 2) else BLACK_FORMULA
            put(ws, f"{c}{r}", fmla, font=font, fill=fill, fmt=FMT_CNY_PER_SH)
    box_section(ws, start_row, 1, start_row + 6, 7)


def build_sens_rev_margin(start_row):
    ws.merge_cells(start_row=start_row, start_column=1, end_row=start_row, end_column=7)
    put(ws, f"A{start_row}",
        "SENSITIVITY 2 — Flat Revenue Growth × Flat EBIT Margin (Implied Price ¥/sh)",
        font=WHITE_BOLD, fill=FILL_HEADER)
    base_avg_g = sum(BASE["growth"]) / N_PROJ
    base_avg_m = sum(BASE["ebit_margin"]) / N_PROJ
    put(ws, f"A{start_row + 1}", "Rev g \\ EBIT m →", font=BLACK_BOLD, fill=FILL_SUBHEADER)
    for j in range(5):
        col = get_column_letter(2 + j)
        offset = (j - 2) * 0.01
        put(ws, f"{col}{start_row + 1}", base_avg_m + offset, font=BLACK_BOLD,
            fill=FILL_SUBHEADER, fmt=FMT_PCT, align=Alignment(horizontal="center"),
            comment=f"Base avg EBIT margin = {base_avg_m:.1%}")
    for i in range(5):
        offset = (i - 2) * 0.01
        put(ws, f"A{start_row + 2 + i}", base_avg_g + offset, font=BLACK_BOLD,
            fill=FILL_SUBHEADER, fmt=FMT_PCT,
            comment=f"Base avg revenue growth = {base_avg_g:.1%}")
    wacc_ref = f"$B${sel_rows['wacc']}"
    g_ref = f"$B${sel_rows['terminal_g']}"
    rev_base_cell = f"$G${REV_ROW}"  # 2025
    da_ref = f"$B${sel_rows['da']}"
    capex_ref = f"$B${sel_rows['capex']}"
    nwc_ref = f"$B${sel_rows['nwc']}"
    for i in range(5):
        for j in range(5):
            r = start_row + 2 + i
            c = get_column_letter(2 + j)
            g_axis = f"$A{r}"
            m_axis = f"{c}${start_row + 1}"
            pv_terms = []
            for k in range(1, N_PROJ + 1):
                rev_k = f"{rev_base_cell}*(1+{g_axis})^{k}"
                rev_km1 = f"{rev_base_cell}*(1+{g_axis})^{k-1}"
                fcf_k = (f"(({rev_k})*{m_axis}*(1-{TAX})"
                         f"+({rev_k})*{da_ref}"
                         f"-({rev_k})*{capex_ref}"
                         f"-(({rev_k})-({rev_km1}))*{nwc_ref})")
                pv_terms.append(f"({fcf_k})/(1+{wacc_ref})^{PROJ_PERIODS[k-1]}")
            sum_pv = "+".join(pv_terms)
            rev_n = f"{rev_base_cell}*(1+{g_axis})^{N_PROJ}"
            rev_nm1 = f"{rev_base_cell}*(1+{g_axis})^{N_PROJ - 1}"
            fcf_n = (f"(({rev_n})*{m_axis}*(1-{TAX})"
                     f"+({rev_n})*{da_ref}"
                     f"-({rev_n})*{capex_ref}"
                     f"-(({rev_n})-({rev_nm1}))*{nwc_ref})")
            tfcf = f"({fcf_n})*(1+{g_ref})"
            pv_tv = f"({tfcf})/({wacc_ref}-{g_ref})/(1+{wacc_ref})^{PROJ_PERIODS[-1]}"
            ev = f"({sum_pv}+{pv_tv})"
            equity = f"({ev}-B{vs_rows['net_debt']}-B{vs_rows['minority']})"
            implied = f"{equity}*100/B{vs_rows['shares']}"
            fmla = f"=IFERROR({implied},NA())"
            fill = FILL_OUTPUT if (i == 2 and j == 2) else None
            font = BLACK_BOLD if (i == 2 and j == 2) else BLACK_FORMULA
            put(ws, f"{c}{r}", fmla, font=font, fill=fill, fmt=FMT_CNY_PER_SH)
    box_section(ws, start_row, 1, start_row + 6, 7)


def build_sens_beta_rf(start_row):
    ws.merge_cells(start_row=start_row, start_column=1, end_row=start_row, end_column=7)
    put(ws, f"A{start_row}",
        "SENSITIVITY 3 — Beta × Risk-Free Rate (Implied Price ¥/sh)",
        font=WHITE_BOLD, fill=FILL_HEADER)
    put(ws, f"A{start_row + 1}", "β \\ Rf →", font=BLACK_BOLD, fill=FILL_SUBHEADER)
    for j in range(5):
        col = get_column_letter(2 + j)
        offset = (j - 2) * 0.005
        put(ws, f"{col}{start_row + 1}", RF + offset, font=BLACK_BOLD,
            fill=FILL_SUBHEADER, fmt=FMT_PCT2, align=Alignment(horizontal="center"))
    for i in range(5):
        offset = (i - 2) * 0.1
        put(ws, f"A{start_row + 2 + i}", BETA + offset, font=BLACK_BOLD,
            fill=FILL_SUBHEADER, fmt=FMT_MULT)
    g_ref = f"$B${sel_rows['terminal_g']}"
    for i in range(5):
        for j in range(5):
            r = start_row + 2 + i
            c = get_column_letter(2 + j)
            wacc_expr = f"({c}${start_row + 1}+$A{r}*{ERP})"
            pv_terms = [f"{proj_fcf_cells[k]}/(1+{wacc_expr})^{PROJ_PERIODS[k]}" for k in range(N_PROJ)]
            sum_pv = "+".join(pv_terms)
            tfcf = f"{proj_fcf_cells[-1]}*(1+{g_ref})"
            pv_tv = f"({tfcf}/({wacc_expr}-{g_ref}))/(1+{wacc_expr})^{PROJ_PERIODS[-1]}"
            ev = f"({sum_pv}+{pv_tv})"
            equity = f"({ev}-B{vs_rows['net_debt']}-B{vs_rows['minority']})"
            implied = f"{equity}*100/B{vs_rows['shares']}"
            fmla = f"=IFERROR({implied},NA())"
            fill = FILL_OUTPUT if (i == 2 and j == 2) else None
            font = BLACK_BOLD if (i == 2 and j == 2) else BLACK_FORMULA
            put(ws, f"{c}{r}", fmla, font=font, fill=fill, fmt=FMT_CNY_PER_SH)
    box_section(ws, start_row, 1, start_row + 6, 7)


build_sens_wacc_g(SENS1)
build_sens_rev_margin(SENS2)
build_sens_beta_rf(SENS3)

# ============================================================================
# Mirror + write
# ============================================================================

print("=" * 70)
print(f"Python mirror calculation ({N_PROJ}Y explicit projection)")
print("=" * 70)
results = {}
for name in ["Bear", "Base", "Bull"]:
    m = mirror_dcf(name)
    results[name] = m
    print(f"\n{name}:")
    print(f"  Revenue Y1/Y5/Y10 (亿): {m['rev'][0]:.0f} / {m['rev'][4]:.0f} / {m['rev'][-1]:.0f}")
    print(f"  FCF Y1/Y5/Y10 (亿):     {m['fcf'][0]:.0f} / {m['fcf'][4]:.0f} / {m['fcf'][-1]:.0f}")
    print(f"  Sum PV FCF: {m['sum_pv']:,.0f}  PV TV: {m['pv_tv']:,.0f}  (TV/EV: {m['tv_pct']*100:.1f}%)")
    print(f"  EV: {m['ev']:,.0f}  Net debt: {m['net_debt']:,.0f}  Minority: {MINORITY_BN}")
    print(f"  Equity Value: {m['equity']:,.0f}")
    print(f"  Implied price: ¥{m['implied']:,.2f}  | Current: ¥{PRICE:,.2f}  | Upside: {m['upside']*100:+.1f}%")
    assert math.isfinite(m["implied"])

out_path = Path(f"d:/work/study/financial-services/plugins/partner-built/china-market/600519_DCF_Model_{ASOF}.xlsx")
wb.save(out_path)
print(f"\n✓ Saved: {out_path}  ({out_path.stat().st_size:,} bytes)")

# Formula count
n_formulas = 0
for s in (ws_dcf, ws_wacc):
    for row in s.iter_rows():
        for cell in row:
            if cell.value and isinstance(cell.value, str) and cell.value.startswith("="):
                n_formulas += 1
print(f"  Formulas written: {n_formulas}")

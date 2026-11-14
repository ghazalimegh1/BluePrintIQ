from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Paragraph
from reportlab.pdfgen.canvas import Canvas


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "blueprintiq-system-architecture.pdf"

BG = colors.HexColor("#0f1717")
PANEL = colors.HexColor("#172321")
PANEL_ALT = colors.HexColor("#1d2b28")
MINT = colors.HexColor("#72d1b6")
GOLD = colors.HexColor("#d7a565")
BLUE = colors.HexColor("#72b9d1")
TEXT = colors.HexColor("#e4eee8")
MUTED = colors.HexColor("#98aaa2")
LINE = colors.HexColor("#35504a")


styles = getSampleStyleSheet()
BODY = ParagraphStyle(
    "body",
    parent=styles["Normal"],
    fontName="Helvetica",
    fontSize=7.3,
    leading=9.2,
    textColor=TEXT,
)
SMALL = ParagraphStyle(
    "small",
    parent=BODY,
    fontSize=6.4,
    leading=7.8,
    textColor=MUTED,
)
BOX_TITLE = ParagraphStyle(
    "box-title",
    parent=BODY,
    fontName="Helvetica-Bold",
    fontSize=8.3,
    leading=10,
    textColor=TEXT,
)


def paragraph(canvas: Canvas, text: str, x: float, y: float, width: float, height: float, style: ParagraphStyle = BODY) -> None:
    item = Paragraph(text, style)
    _, item_height = item.wrap(width, height)
    item.drawOn(canvas, x, y + height - item_height)


def box(canvas: Canvas, x: float, y: float, width: float, height: float, title: str, body: str, accent: colors.Color = MINT, fill: colors.Color = PANEL) -> None:
    canvas.setFillColor(fill)
    canvas.setStrokeColor(accent)
    canvas.setLineWidth(0.8)
    canvas.roundRect(x, y, width, height, 4 * mm, fill=1, stroke=1)
    canvas.setFillColor(accent)
    canvas.roundRect(x, y + height - 5 * mm, width, 5 * mm, 4 * mm, fill=1, stroke=0)
    canvas.rect(x, y + height - 5 * mm, width, 2 * mm, fill=1, stroke=0)
    paragraph(canvas, title, x + 4 * mm, y + height - 15 * mm, width - 8 * mm, 8 * mm, BOX_TITLE)
    paragraph(canvas, body, x + 4 * mm, y + 4 * mm, width - 8 * mm, height - 20 * mm, BODY)


def arrow(canvas: Canvas, x1: float, y1: float, x2: float, y2: float, color: colors.Color = MINT) -> None:
    canvas.setStrokeColor(color)
    canvas.setFillColor(color)
    canvas.setLineWidth(1.2)
    canvas.line(x1, y1, x2, y2)
    import math

    angle = math.atan2(y2 - y1, x2 - x1)
    size = 3 * mm
    left = (x2 - size * math.cos(angle - 0.45), y2 - size * math.sin(angle - 0.45))
    right = (x2 - size * math.cos(angle + 0.45), y2 - size * math.sin(angle + 0.45))
    canvas.line(x2, y2, *left)
    canvas.line(x2, y2, *right)


def pill(canvas: Canvas, text: str, x: float, y: float, color: colors.Color) -> None:
    width = stringWidth(text, "Helvetica-Bold", 6.4) + 8 * mm
    canvas.setFillColor(color)
    canvas.roundRect(x, y, width, 5.5 * mm, 2.5 * mm, fill=1, stroke=0)
    canvas.setFillColor(BG)
    canvas.setFont("Helvetica-Bold", 6.4)
    canvas.drawCentredString(x + width / 2, y + 1.8 * mm, text)


def make_pdf() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    page_w, page_h = landscape(A4)
    canvas = Canvas(str(OUTPUT), pagesize=(page_w, page_h))
    canvas.setTitle("BluePrintIQ System Architecture")
    canvas.setAuthor("BluePrintIQ")

    canvas.setFillColor(BG)
    canvas.rect(0, 0, page_w, page_h, fill=1, stroke=0)
    margin = 12 * mm
    canvas.setFillColor(MINT)
    canvas.setFont("Helvetica-Bold", 18)
    canvas.drawString(margin, page_h - 17 * mm, "BluePrintIQ")
    canvas.setFillColor(TEXT)
    canvas.setFont("Helvetica", 11)
    canvas.drawString(margin + 37 * mm, page_h - 17 * mm, "Evidence-linked construction intelligence")
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 7)
    canvas.drawRightString(page_w - margin, page_h - 16 * mm, "SYSTEM ARCHITECTURE / JUNCTION 2026")
    canvas.setStrokeColor(LINE)
    canvas.line(margin, page_h - 22 * mm, page_w - margin, page_h - 22 * mm)

    # Main flow.
    y = page_h - 51 * mm
    h = 29 * mm
    w = 42 * mm
    gap = 8 * mm
    x1 = margin
    x2 = x1 + w + gap
    x3 = x2 + w + gap
    x4 = x3 + w + gap
    x5 = x4 + w + gap
    box(canvas, x1, y, w, h, "1. SOURCE FILES", "PDF / PNG / JPEG<br/>IFC / DXF / DWG / SVG<br/><font color='#98aaa2'>Original files stay linked.</font>", GOLD)
    box(canvas, x2, y, w, h, "2. INGEST + NORMALIZE", "Format detection<br/>Preview rendering<br/>Native coordinates<br/><font color='#98aaa2'>Page, sheet and model identity.</font>", BLUE)
    box(canvas, x3, y, w, h, "3. ROUTER", "Question normalization<br/>Typo correction<br/>Scope and tool selection<br/><font color='#98aaa2'>Only compatible tools run.</font>", MINT)
    box(canvas, x4, y, w, h, "4. EVIDENCE TOOLS", "IFC typed queries<br/>PDF/SVG/OCR search<br/>DXF geometry<br/>Local vision models", GOLD)
    box(canvas, x5, y, w, h, "5. VERIFIED ANSWER", "Answer + confidence<br/>Calculation + warnings<br/>Source-linked evidence<br/><font color='#98aaa2'>Abstain when unsupported.</font>", MINT)
    for left, right in ((x1, x2), (x2, x3), (x3, x4), (x4, x5)):
        arrow(canvas, left + w, y + h / 2, right, y + h / 2)

    # Lower model lanes.
    lane_y = y - 55 * mm
    lane_h = 38 * mm
    lane_w = (page_w - 2 * margin - 2 * gap) / 3
    lane1 = margin
    lane2 = margin + lane_w + gap
    lane3 = margin + 2 * (lane_w + gap)
    box(canvas, lane1, lane_y, lane_w, lane_h, "LOCAL VISION / 2D", "<b>Grounding DINO Tiny</b> - candidate boxes for doors, windows and symbols.<br/><b>SAM 2.1</b> - instance masks from candidate boxes.<br/><b>CubiCasa5K</b> - walls, rooms and floor-plan symbols.<br/><b>PaddleOCR / EasyOCR</b> - Finnish and multilingual text regions.", BLUE, PANEL_ALT)
    box(canvas, lane2, lane_y, lane_w, lane_h, "NATIVE GEOMETRY / BIM", "<b>IfcOpenShell</b> tessellates native IFC meshes and preserves GlobalIds, storeys and properties.<br/><b>ezdxf</b> reads named blocks, layers and closed room geometry.<br/><font color='#98aaa2'>Native geometry is preferred over reconstruction.</font>", GOLD, PANEL_ALT)
    box(canvas, lane3, lane_y, lane_w, lane_h, "REASONING + ARBITRATION", "<b>Planner</b> interprets natural language and selects allowlisted tools.<br/><b>Evidence validator</b> checks counts against returned records.<br/><b>Arbitration</b> exposes detector disagreement instead of inventing certainty.<br/><font color='#98aaa2'>Known / detected / inferred / unknown remain distinct.</font>", MINT, PANEL_ALT)
    arrow(canvas, x4 + w / 2, y, lane1 + lane_w / 2, lane_y + lane_h, BLUE)
    arrow(canvas, x4 + w / 2, y, lane2 + lane_w / 2, lane_y + lane_h, GOLD)
    arrow(canvas, x3 + w / 2, y, lane3 + lane_w / 2, lane_y + lane_h, MINT)

    # Frontend verification strip.
    strip_y = 13 * mm
    canvas.setFillColor(PANEL)
    canvas.setStrokeColor(LINE)
    canvas.roundRect(margin, strip_y, page_w - 2 * margin, 20 * mm, 4 * mm, fill=1, stroke=1)
    canvas.setFillColor(TEXT)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.drawString(margin + 5 * mm, strip_y + 14 * mm, "HUMAN VERIFICATION SURFACE")
    paragraph(canvas, "React + TypeScript + Three.js presents the original drawing beside the spatial model. Every answer can expose its source page, pixel/PDF-point box, polygon or IFC GlobalId. Clicking evidence performs a staged zoom to the original region or a contextual 3D camera move.", margin + 5 * mm, strip_y + 3 * mm, page_w - 2 * margin - 10 * mm, 9 * mm, SMALL)
    pill(canvas, "SOURCE-LINKED", margin + 82 * mm, strip_y + 13 * mm, MINT)
    pill(canvas, "UNCERTAINTY VISIBLE", margin + 118 * mm, strip_y + 13 * mm, GOLD)
    pill(canvas, "NO UNSUPPORTED CLAIM", margin + 164 * mm, strip_y + 13 * mm, BLUE)

    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 6.5)
    canvas.drawString(margin, 6 * mm, "BluePrintIQ architecture overview | Native IFC is metric; raster 2.5D is display-only and explicitly uncertain.")
    canvas.drawRightString(page_w - margin, 6 * mm, "1")
    canvas.showPage()
    canvas.save()


if __name__ == "__main__":
    make_pdf()

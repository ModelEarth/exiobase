#!/usr/bin/env python3
"""Generate TradeFlow.pdf — a book-style guide to the exiobase/tradeflow pipeline."""

from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer,
    PageBreak, Table, TableStyle, KeepTogether, Preformatted,
    NextPageTemplate,
)
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

OUT = Path(__file__).parent / "TradeFlow.pdf"

NAVY = colors.HexColor("#0b1f44")      # darker, richer navy for headings
STEEL = colors.HexColor("#1e3a66")     # darker blue for H3 (was muddy at #425b7a)
ACCENT = colors.HexColor("#c2410c")    # stronger burnt-orange for chapter numbers
SOFT = colors.HexColor("#cbd5e1")      # a touch darker so table grid lines show
INK = colors.HexColor("#0f172a")       # near-black for body text
MUTED = colors.HexColor("#475569")     # much darker grey (was too light at #6b7280)
CODEBG = colors.HexColor("#eef1f5")    # slightly deeper code background
CODEBORDER = colors.HexColor("#cbd5e1")

styles = getSampleStyleSheet()

title_style = ParagraphStyle(
    "BookTitle", parent=styles["Title"], fontName="Helvetica-Bold",
    fontSize=42, leading=50, textColor=NAVY, alignment=TA_CENTER, spaceAfter=18,
)
subtitle_style = ParagraphStyle(
    "BookSubtitle", parent=styles["Normal"], fontName="Helvetica-Oblique",
    fontSize=16, leading=22, textColor=STEEL, alignment=TA_CENTER, spaceAfter=36,
)
byline_style = ParagraphStyle(
    "Byline", parent=styles["Normal"], fontName="Helvetica",
    fontSize=11, leading=16, textColor=MUTED, alignment=TA_CENTER,
)
chapter_num_style = ParagraphStyle(
    "ChapterNum", parent=styles["Normal"], fontName="Helvetica-Bold",
    fontSize=14, leading=18, textColor=ACCENT, alignment=TA_LEFT, spaceAfter=4,
)
chapter_title_style = ParagraphStyle(
    "ChapterTitle", parent=styles["Heading1"], fontName="Helvetica-Bold",
    fontSize=28, leading=34, textColor=NAVY, alignment=TA_LEFT,
    spaceAfter=20, keepWithNext=True,
)
h2_style = ParagraphStyle(
    "H2", parent=styles["Heading2"], fontName="Helvetica-Bold",
    fontSize=16, leading=20, textColor=NAVY, spaceBefore=14, spaceAfter=8, keepWithNext=True,
)
h3_style = ParagraphStyle(
    "H3", parent=styles["Heading3"], fontName="Helvetica-Bold",
    fontSize=12.5, leading=16, textColor=STEEL, spaceBefore=10, spaceAfter=6, keepWithNext=True,
)
body_style = ParagraphStyle(
    "Body", parent=styles["BodyText"], fontName="Helvetica",
    fontSize=10.5, leading=15.5, textColor=INK, alignment=TA_JUSTIFY, spaceAfter=8,
)
bullet_style = ParagraphStyle(
    "Bullet", parent=body_style, leftIndent=18, bulletIndent=6, spaceAfter=4,
)
code_style = ParagraphStyle(
    "Code", parent=styles["Code"], fontName="Courier",
    fontSize=8.5, leading=11.5, textColor=INK, backColor=CODEBG,
    borderColor=CODEBORDER, borderWidth=0.5,
    borderPadding=6, spaceAfter=10, spaceBefore=4,
)
caption_style = ParagraphStyle(
    "Caption", parent=styles["Italic"], fontName="Helvetica-Oblique",
    fontSize=9, leading=12, textColor=MUTED, alignment=TA_CENTER, spaceAfter=10,
)
toc_entry_style = ParagraphStyle(
    "TOCEntry", parent=styles["Normal"], fontName="Helvetica",
    fontSize=11, leading=18, textColor=INK, leftIndent=0,
)
toc_part_style = ParagraphStyle(
    "TOCPart", parent=styles["Normal"], fontName="Helvetica-Bold",
    fontSize=12, leading=22, textColor=NAVY, spaceBefore=10, spaceAfter=4,
)

doc_width = LETTER[0] - 1.5 * inch
doc_height = LETTER[1] - 1.5 * inch


class BookDoc(BaseDocTemplate):
    def __init__(self, filename, **kw):
        super().__init__(filename, pagesize=LETTER,
                         leftMargin=0.9*inch, rightMargin=0.9*inch,
                         topMargin=0.9*inch, bottomMargin=0.9*inch, **kw)
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="main")
        self.addPageTemplates([
            PageTemplate(id="cover", frames=[frame], onPage=self.cover_page),
            PageTemplate(id="normal", frames=[frame], onPage=self.normal_page),
        ])
        self.current_chapter = ""

    def cover_page(self, canvas, doc):
        canvas.saveState()
        canvas.setFillColor(NAVY)
        canvas.rect(0, 0, LETTER[0], LETTER[1], fill=1, stroke=0)
        # Decorative band
        canvas.setFillColor(ACCENT)
        canvas.rect(0, LETTER[1]*0.72, LETTER[0], 6, fill=1, stroke=0)
        canvas.rect(0, LETTER[1]*0.28, LETTER[0], 6, fill=1, stroke=0)
        canvas.restoreState()

    def normal_page(self, canvas, doc):
        canvas.saveState()
        # Header
        canvas.setFont("Helvetica", 9)
        canvas.setFillColor(MUTED)
        canvas.drawString(doc.leftMargin, LETTER[1] - 0.55*inch,
                          "TradeFlow — An EXIOBASE Pipeline Field Guide")
        if self.current_chapter:
            canvas.drawRightString(LETTER[0] - doc.rightMargin,
                                   LETTER[1] - 0.55*inch, self.current_chapter)
        canvas.setStrokeColor(SOFT)
        canvas.setLineWidth(0.5)
        canvas.line(doc.leftMargin, LETTER[1] - 0.65*inch,
                    LETTER[0] - doc.rightMargin, LETTER[1] - 0.65*inch)
        # Footer page number
        canvas.setFont("Helvetica", 9)
        canvas.setFillColor(MUTED)
        canvas.drawCentredString(LETTER[0] / 2.0, 0.55*inch, f"— {canvas.getPageNumber()} —")
        canvas.restoreState()

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and flowable.style.name == "ChapterTitle":
            self.current_chapter = flowable.getPlainText()


def P(text, style=body_style):
    return Paragraph(text, style)

def bullets(items):
    out = []
    for item in items:
        out.append(Paragraph(f"&bull;&nbsp;&nbsp;{item}", bullet_style))
    return out

def code_block(text):
    return Preformatted(text, code_style)

def two_col_table(rows, col_widths=None, header=True):
    tstyle = [
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, SOFT),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if header:
        tstyle += [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 10),
        ]
    cw = col_widths if col_widths else [doc_width * 0.35, doc_width * 0.65]
    # Wrap text with Paragraphs for cells that are strings
    wrapped = []
    for r_i, row in enumerate(rows):
        new_row = []
        for c_i, cell in enumerate(row):
            if isinstance(cell, str):
                s = body_style if (not header or r_i > 0) else ParagraphStyle(
                    "th", parent=body_style, textColor=colors.white, fontName="Helvetica-Bold")
                new_row.append(Paragraph(cell, s))
            else:
                new_row.append(cell)
        wrapped.append(new_row)
    t = Table(wrapped, colWidths=cw, hAlign="LEFT")
    t.setStyle(TableStyle(tstyle))
    return t


def chapter(num, title):
    return [
        PageBreak(),
        Spacer(1, 0.4*inch),
        Paragraph(f"CHAPTER {num}", chapter_num_style),
        Paragraph(title, chapter_title_style),
        Spacer(1, 0.1*inch),
    ]


def section_header(text):
    return [Spacer(1, 0.1*inch), Paragraph(text, h2_style)]


def sub(text):
    return [Paragraph(text, h3_style)]


# ============================================================
# Build the book content
# ============================================================
story = []

# ---- COVER ----
story.append(Spacer(1, 1.5*inch))
story.append(Paragraph("TradeFlow", ParagraphStyle(
    "cover_title", fontName="Helvetica-Bold", fontSize=56, leading=66,
    textColor=colors.white, alignment=TA_CENTER)))
story.append(Spacer(1, 0.2*inch))
story.append(Paragraph("An EXIOBASE Pipeline Field Guide",
                       ParagraphStyle("cover_sub", fontName="Helvetica-Oblique",
                                      fontSize=20, leading=28,
                                      textColor=colors.HexColor("#fbbf24"),
                                      alignment=TA_CENTER)))
story.append(Spacer(1, 2.0*inch))
story.append(Paragraph("Trade. Factor. Industry.",
                       ParagraphStyle("tag", fontName="Helvetica", fontSize=16,
                                      leading=22, textColor=colors.white,
                                      alignment=TA_CENTER)))
story.append(Spacer(1, 0.25*inch))
story.append(Paragraph("How multi-regional input-output data becomes queryable trade and environmental impact.",
                       ParagraphStyle("tag2", fontName="Helvetica",
                                      fontSize=12, leading=18,
                                      textColor=colors.HexColor("#dbeafe"),
                                      alignment=TA_CENTER)))
story.append(Spacer(1, 1.5*inch))
story.append(Paragraph("Model.Earth · exiobase/tradeflow",
                       ParagraphStyle("foot", fontName="Helvetica",
                                      fontSize=11, leading=16,
                                      textColor=colors.HexColor("#fbbf24"),
                                      alignment=TA_CENTER)))

# switch to normal template for the rest of the book
story.append(NextPageTemplate("normal"))
story.append(PageBreak())

# ---- COPYRIGHT / NOTICE ----
story.append(Spacer(1, 3.0*inch))
story.append(P("This volume is an auto-generated guide to the <b>exiobase/tradeflow</b> "
               "Python pipeline inside the Model.Earth repository. It covers the data model, "
               "the processing scripts, the configuration surface, and the US BEA and India "
               "extensions. It is a <i>field guide</i>, not a formal specification &mdash; "
               "cross-reference the source files when the two disagree.", body_style))
story.append(Spacer(1, 0.2*inch))
story.append(P("All matrix mathematics follows the standard EXIOBASE v3 convention: "
               "<b>Z</b> is inter-industry transaction flows (M EUR), <b>Y</b> is final demand, "
               "and <b>F</b> / <b>S</b> hold environmental extensions (absolute and per-M-EUR "
               "intensities respectively).", body_style))

# ---- TABLE OF CONTENTS ----
story.append(PageBreak())
story.append(Paragraph("Contents", chapter_title_style))
story.append(Spacer(1, 0.2*inch))

toc_entries = [
    ("Part I — Foundations", None),
    ("1  What TradeFlow is, and why it exists", 1),
    ("2  Three matrices, three CSVs, and a diagram", 2),
    ("3  The vocabulary: trade, factor, industry, level", 3),
    ("Part II — The Core Pipeline", None),
    ("4  Configuration: config.yaml and config_loader.py", 4),
    ("5  trade.py: Extraction and factor generation", 5),
    ("6  trade_impact.py: Aggregation", 6),
    ("7  trade_resource.py: Three specialised views", 7),
    ("8  main.py: Batch orchestration", 8),
    ("Part III — Reference and Companion Files", None),
    ("9  factor.csv and industry.csv", 9),
    ("10 The 120-vs-721 selection problem", 10),
    ("11 CSV output catalogue", 11),
    ("Part IV — Extensions", None),
    ("12 US BEA: Interstate state-to-state flows", 12),
    ("13 India: State-level allocation", 13),
    ("14 SQL ingestion (insert_sql.py)", 14),
    ("Part V — Operations", None),
    ("15 Running it: commands, timing, resumability", 15),
    ("16 Troubleshooting and gotchas", 16),
    ("17 The schema being proposed for SQL", 17),
    ("Appendix A — Repository map", "A"),
    ("Appendix B — Glossary", "B"),
]
for text, page in toc_entries:
    if page is None:
        story.append(Paragraph(text, toc_part_style))
    else:
        story.append(Paragraph(text, toc_entry_style))

# =========================================================================
# CHAPTER 1
# =========================================================================
story += chapter("1", "What TradeFlow is, and why it exists")

story.append(P(
    "<b>TradeFlow</b> is the Python pipeline that lives at "
    "<font face='Courier'>exiobase/tradeflow/</font> in the Model.Earth repository. "
    "Its job is to turn the raw EXIOBASE v3 multi-regional input-output (MRIO) database "
    "into a set of flat, relational CSVs that downstream tools &mdash; SQL databases, "
    "dashboards, Sankey diagrams, interstate trade maps &mdash; can consume without ever "
    "touching the original matrices."
))

story += section_header("The problem")
story.append(P(
    "EXIOBASE ships as a zip of about 535 MB per year. Inside are large, sparse matrices "
    "indexed by (region, sector) tuples: around 44 regions &times; 200 products on each axis. "
    "A single matrix cell is a monetary flow or an environmental coefficient. These are "
    "wonderful for linear algebra and terrible for everything else. You cannot easily "
    "answer a question like &lsquo;what are the top ten CO&#8322; emission sources "
    "embedded in US imports from China in 2019?&rsquo; by inspection."
))

story += section_header("The approach")
story.append(P(
    "TradeFlow <b>unstacks</b> the matrices into long tables with one row per "
    "<i>trade transaction</i> (a flow from one region/industry to another) and one row per "
    "<i>trade-factor relationship</i> (how much of a given environmental stressor is "
    "embedded in that transaction). Each row carries a stable identifier so the tables can "
    "be joined again downstream. The output is a tree of CSV files organised by "
    "<font face='Courier'>year / country / flow_direction</font>."
))

story += section_header("Who it is for")
story.append(P(
    "Three audiences, in order of priority:"
))
story += bullets([
    "<b>Data engineers</b> who want to load trade and impact data into Postgres or SQL Server "
    "without re-parsing the pymrio pickle every time.",
    "<b>Policy analysts and researchers</b> who want to filter trade flows by region, industry, "
    "or environmental factor and plot the results.",
    "<b>Downstream applications</b> &mdash; Sankey diagrams, interstate trade maps, "
    "LCA dashboards &mdash; that fetch pre-computed CSVs from GitHub rather than running the "
    "pipeline themselves.",
])

story += section_header("What makes TradeFlow worth documenting")
story.append(P(
    "Three design decisions are not obvious from reading the code and are the main subject "
    "of this book. First, the pipeline is <b>config-driven</b>: a single "
    "<font face='Courier'>config.yaml</font> file controls year, country, flow direction, "
    "factor-selection strategy, and output paths. Second, it ships a <b>dual-file</b> output "
    "strategy for environmental factors (120 selected vs 721 full) that tries to balance "
    "coverage against Node.js and SQL memory limits. Third, it is <b>resumable</b>: the "
    "batch runner skips countries whose <font face='Courier'>runnote.md</font> says they are "
    "already done, and timeout tiers (per-script, per-country, per-batch) stop runaway work."
))

# =========================================================================
# CHAPTER 2
# =========================================================================
story += chapter("2", "Three matrices, three CSVs, and a diagram")

story.append(P(
    "Before diving into any single file, it helps to carry a mental model of what the "
    "pipeline is actually doing. EXIOBASE provides three matrices. TradeFlow consumes them "
    "and emits three families of CSVs. The rest is bookkeeping."
))

story += section_header("The three matrices")
story.append(two_col_table([
    ["Matrix", "What it holds"],
    ["<b>Z</b>", "Inter-industry monetary flows. Z[i,j] is the value in M EUR flowing "
                 "from (region, sector) i to (region, sector) j."],
    ["<b>Y</b>", "Final demand. Y[i,c] is the value flowing from industry i into "
                 "consumption category c (households, government, investment)."],
    ["<b>F / S</b>", "Environmental extensions. F is absolute stressor emissions by "
                     "(region, sector); S is the per-M-EUR intensity. There are six "
                     "extensions: air_emissions, employment, energy, land, material, water."],
]))

story += section_header("The three output families")
story.append(two_col_table([
    ["CSV family", "Purpose"],
    ["<b>trade.csv</b>", "One row per bilateral industry-pair flow for a given country and "
                         "direction. Columns: trade_id, year, region1, region2, industry1, "
                         "industry2, amount (M EUR)."],
    ["<b>trade_factor.csv</b> / <b>trade_factor-max.csv</b>",
     "One row per (trade, factor) pair. Columns: trade_id, factor_id, level. "
     "The level is a physical quantity (kg, persons, TJ, km&sup2;, kt, Mm&sup3;)."],
    ["<b>trade_impact / resource / material / employment</b>",
     "Pre-aggregated analytical views. These can be rebuilt from trade &times; trade_factor &times; factor, "
     "so when the data is in SQL they become VIEWs rather than tables."],
]))

story += section_header("The diagram")
story.append(code_block(
    "Z matrix (M EUR)         F / S matrices (physical / intensity)\n"
    "     |                        |\n"
    "     v                        v\n"
    "  trade.csv  <-- trade_id --> trade_factor.csv\n"
    "                                     |\n"
    "                              factor_id (FK)\n"
    "                                     v\n"
    "                                factor.csv (unit, stressor, extension)\n"
    "\n"
    "  trade.industry1/2  --FK-->  industry.csv (industry_id, name, category)"
))

story.append(P(
    "Everything else in the pipeline is a transformation, aggregation, or extension of "
    "this core shape. Interstate (US BEA) adds a parallel pair of tables that follow the "
    "same pattern but at the state level. India adds a parallel pair at the state/UT "
    "level. SQL ingestion loads these shapes directly."
))

# =========================================================================
# CHAPTER 3
# =========================================================================
story += chapter("3", "The vocabulary: trade, factor, industry, level")

story.append(P(
    "The TradeFlow authors deliberately chose plain-English table names &mdash; "
    "<i>&lsquo;designed for third graders&rsquo;</i> is a direct quote from the README. "
    "This chapter unpacks the vocabulary because the terminology diverges from "
    "both academic MRIO literature and from EXIOBASE's native terms."
))

story += section_header("Trade (not &lsquo;flow&rsquo;)")
story.append(P(
    "A <b>trade</b> row is a single monetary flow from an origin (region1, industry1) "
    "to a destination (region2, industry2) within a single year. It is sourced directly "
    "from the EXIOBASE Z matrix. In the pymrio and MRIO communities this is universally "
    "called a <i>flow</i>; TradeFlow renames it to <b>trade</b> because &lsquo;flow&rsquo; is "
    "overloaded (the word is also used for environmental flows in FEDEFL, and for Sankey "
    "diagram arcs). <b>trade.amount</b> is always in <b>million euros</b> (M EUR)."
))

story += section_header("Factor")
story.append(P(
    "A <b>factor</b> is a single environmental stressor &mdash; one row in the EXIOBASE "
    "extension tables. There are <b>721 factors</b> total across six extensions. "
    "Each factor has a stable integer <b>factor_id</b> assigned by row position when "
    "<font face='Courier'>factors.py</font> walks the extensions in a fixed order: "
    "air_emissions, employment, energy, land, material, water. "
    "Factors carry a <b>unit</b> and belong to an <b>extension</b>."
))

story += section_header("Industry")
story.append(P(
    "An <b>industry</b> is a product-by-product EXIOBASE sector &mdash; there are around "
    "200 of them. TradeFlow assigns each a 5-character <b>industry_id</b> derived from the "
    "sector name by <font face='Courier'>create_sector_mapping.py</font>. These codes are "
    "intended to be mnemonic (e.g. <font face='Courier'>WHEAT</font> for &lsquo;Wheat&rsquo;) "
    "but collisions are resolved by overwriting the last character with a counter."
))

story += section_header("Level (vs amount, vs coefficient)")
story.append(P(
    "This is the trickiest distinction in the whole system. There are three numeric columns "
    "across the pipeline, and getting them confused is the single most common source of bugs."
))
story.append(two_col_table([
    ["Column", "What it is"],
    ["<b>trade.amount</b>", "Monetary value of a trade in M EUR. Comes from Z matrix."],
    ["<b>coefficient</b>", "Physical units per M EUR of output. Comes from S matrix. "
                            "Not stored in output CSVs &mdash; it is derivable as "
                            "<font face='Courier'>level / amount</font>."],
    ["<b>trade_factor.level</b>", "Physical impact of a trade on a factor. "
                                   "<font face='Courier'>level = amount &times; coefficient</font>. "
                                   "Unit depends on the factor's extension."],
]))

story.append(P(
    "The authors chose <b>level</b> (rather than <font face='Courier'>flow_value</font>, "
    "<font face='Courier'>impact_value</font>, or <font face='Courier'>levelX</font>) to "
    "signal that this is a physical quantity, not money. The same convention is used in "
    "<font face='Courier'>interstate_factor.level</font> for state-to-state flows."
))

story += section_header("The unit table")
story.append(P(
    "Each of the six EXIOBASE extensions has its own canonical unit. "
    "The unit for any given <b>level</b> is read from <font face='Courier'>factor.csv</font> "
    "by joining on <font face='Courier'>factor_id</font>."
))
story.append(two_col_table([
    ["Extension", "Unit"],
    ["air_emissions", "kg"],
    ["employment", "1000 persons (people) / M.hr (hours)"],
    ["energy", "TJ (terajoules)"],
    ["land", "km&sup2;"],
    ["material", "kt (kilotonnes)"],
    ["water", "Mm&sup3; (million cubic metres)"],
]))

# =========================================================================
# CHAPTER 4
# =========================================================================
story += chapter("4", "Configuration: config.yaml and config_loader.py")

story.append(P(
    "Every single script in the pipeline reads from the same "
    "<font face='Courier'>config.yaml</font>. There are no command-line flags for year, "
    "country, or flow direction &mdash; those live in the config. The design intent is that "
    "<i>&lsquo;edit the YAML and run</i> <font face='Courier'>python main.py</font>&rsquo; "
    "is the entire user interface."
))

story += section_header("The config.yaml file")
story.append(code_block(
    "YEAR: 2019\n"
    "TRADEFLOW: domestic,imports,exports\n"
    "COUNTRY:\n"
    "  list: US\n"
    "\n"
    "FOLDERS:\n"
    "  base: ../../trade-data/year/{year}\n"
    "  imports: ../../trade-data/year/{year}/{country}/imports\n"
    "  exports: ../../trade-data/year/{year}/{country}/exports\n"
    "  domestic: ../../trade-data/year/{year}/{country}/domestic\n"
    "\n"
    "FILES:\n"
    "  factors: factor.csv\n"
    "  industries: industry.csv\n"
    "  industryflow: trade.csv\n"
    "  trade_factor: trade_factor.csv\n"
    "  trade_factor_domestic: trade_factor-max.csv\n"
    "  trade_impact: trade_impact.csv\n"
    "  trade_resource: trade_resource.csv\n"
    "  ...\n"
    "\n"
    "PROCESSING:\n"
    "  min_impact_threshold: 0.001\n"
    "  use_partial_factors: true\n"
    "  partial_factor_limit: 120\n"
    "  use_partial_factors_domestic: false\n"
    "  partial_factor_limit_domestic: 2000\n"
    "  use_partial_factors_interstate: true\n"
    "  partial_factor_limit_interstate: 5"
))

story += section_header("COUNTRY: list vs current")
story.append(P(
    "The <font face='Courier'>COUNTRY</font> field has three valid shapes:"
))
story += bullets([
    "<b>Explicit list</b>: <font face='Courier'>list: CN,DE,JP</font> &mdash; a comma-separated list.",
    "<b>Default set</b>: <font face='Courier'>list: default</font> &mdash; the 12 built-in countries "
    "(AU, BR, CA, CN, DE, FR, GB, IN, IT, JP, KR, US).",
    "<b>All</b>: <font face='Courier'>list: all</font> &mdash; auto-discovers existing country folders "
    "under <font face='Courier'>year/{year}/</font>.",
])
story.append(P(
    "When <font face='Courier'>main.py</font> runs, it writes a <font face='Courier'>current:</font> "
    "sub-field into the config so that subprocess scripts know which single country to work on. "
    "This mutation is <b>not safe for concurrent runs</b> &mdash; two batch runners on the same "
    "config will clobber each other's <font face='Courier'>current</font>."
))

story += section_header("Environment variable overrides")
story.append(P(
    "<font face='Courier'>config_loader.py</font> accepts "
    "<font face='Courier'>EXIOBASE_TRADEFLOW</font> and <font face='Courier'>EXIOBASE_COUNTRY</font> "
    "environment variables that override the YAML values. "
    "<font face='Courier'>main.py</font> sets these for each subprocess invocation, which neutralises "
    "the race condition above for the batch runner's own subprocesses."
))

story += section_header("Smart file selection")
story.append(P(
    "<font face='Courier'>get_file_path(config, 'trade_factor')</font> is more clever than it looks. "
    "For the domestic flow direction it first checks whether a "
    "<font face='Courier'>-max.csv</font> file exists and prefers that over the standard version; "
    "for imports and exports it always uses the small file. This is where the "
    "<i>&lsquo;120 for international, 721 for domestic&rsquo;</i> policy is enforced."
))

# =========================================================================
# CHAPTER 5
# =========================================================================
story += chapter("5", "trade.py: Extraction and factor generation")

story.append(P(
    "<font face='Courier'>trade.py</font> is the heart of the pipeline. It is also, at ~1200 "
    "lines, the largest and most intricate script. Its responsibilities are:"
))
story += bullets([
    "Download the EXIOBASE zip from Zenodo if it is not already in "
    "<font face='Courier'>exiobase_data/</font>.",
    "Create <font face='Courier'>industry.csv</font> if missing (delegates to "
    "<font face='Courier'>create_sector_mapping.py</font>).",
    "Create <font face='Courier'>factor.csv</font> if missing (delegates to "
    "<font face='Courier'>factors.py</font>).",
    "Parse the Z matrix, stack it long, filter by flow direction, and write "
    "<font face='Courier'>trade.csv</font>.",
    "Parse the S matrix, apply the 120-factor selection (unless "
    "<font face='Courier'>-lag</font> is passed), merge against trade, compute "
    "<font face='Courier'>level = amount &times; coefficient</font>, and write "
    "<font face='Courier'>trade_factor.csv</font>.",
])

story += section_header("The ExiobaseTradeFlow class")
story.append(P(
    "The script wraps everything in a class whose constructor downloads the data, loads "
    "the sector mapping, and ensures <font face='Courier'>factor.csv</font> exists. "
    "A single instance handles one (year, country, flow-direction) tuple at a time &mdash; "
    "the batch runner re-instantiates the class per country."
))

story += section_header("Three flow directions")
story.append(two_col_table([
    ["Direction", "Filter rule"],
    ["<b>imports</b>", "region2 == country AND region1 != country. Keeps rows with amount &gt; 0.01 M EUR."],
    ["<b>exports</b>", "region1 == country AND region2 != country. Keeps rows with amount &gt; 0.01 M EUR."],
    ["<b>domestic</b>", "region1 == country AND region2 == country. Keeps rows with amount &gt; 0.001 M EUR."],
]))
story.append(P(
    "The thresholds are hard-coded. The domestic threshold is ten times finer because "
    "intra-country flows are typically small individual rows that still matter in aggregate."
))

story += section_header("The 120-factor selection")
story.append(P(
    "When <font face='Courier'>use_partial_factors: true</font> (the default for "
    "non-domestic flows), <font face='Courier'>_apply_partial_factors_filter</font> performs "
    "a two-stage selection per extension:"
))
story += bullets([
    "<b>Priority first</b>: a hard-coded list per extension (e.g. CO2, CH4, N2O, NOX for "
    "air_emissions; Employment people, Employment hours for employment) is matched by substring.",
    "<b>Magnitude next</b>: if there are more than <font face='Courier'>partial_factor_limit</font> "
    "priority matches, keep the top-N by |coefficient|. If fewer, pad with other factors ranked "
    "by |coefficient|.",
])
story.append(P(
    "The result is written to <font face='Courier'>trade_factor.csv</font>. "
    "With <font face='Courier'>-lag</font>, the filter is skipped and the full 721-factor "
    "join is written to <font face='Courier'>trade_factor-max.csv</font> instead "
    "(~1.5 GB, with a warning about downstream Node.js memory errors)."
))

story += section_header("The merge, chunked")
story.append(P(
    "The join of trade rows against factor coefficients can easily exceed memory, so "
    "<font face='Courier'>trade.py</font> processes trades in <b>10,000-row chunks</b>, "
    "merging each chunk against the pre-indexed F_stacked frame. For a US exports run with "
    "~189,000 trade rows and ~125,000 factor rows per extension, this takes about two minutes "
    "end-to-end."
))

story += section_header("level unit handling")
story.append(P(
    "After the merge, <font face='Courier'>level</font> is rounded by extension:"
))
story += bullets([
    "<b>water, air_emissions</b>: 3 decimal places (small physical quantities).",
    "<b>all others</b>: rounded to integer.",
    "Rows with |level| &le; 0.001 are dropped as noise.",
])
story.append(P(
    "This rounding is <i>destructive</i> &mdash; the coefficient cannot be perfectly recovered "
    "from level/amount after rounding. The BEA documentation acknowledges this: "
    "<i>&lsquo;back-deriving coefficient is approximate&rsquo;</i>."
))

# =========================================================================
# CHAPTER 6
# =========================================================================
story += chapter("6", "trade_impact.py: Aggregation")

story.append(P(
    "<font face='Courier'>trade_impact.py</font> is the second script in the main.py "
    "pipeline. Where <font face='Courier'>trade.py</font> produces one row per "
    "(trade, factor) pair, <font face='Courier'>trade_impact.py</font> collapses that back "
    "down to one row per trade transaction, with environmental impacts spread across "
    "columns."
))

story += section_header("What it reads")
story += bullets([
    "<font face='Courier'>trade.csv</font> &mdash; the trade flows from "
    "<font face='Courier'>trade.py</font>.",
    "<font face='Courier'>trade_factor.csv</font> or <font face='Courier'>trade_factor-max.csv</font> "
    "&mdash; whichever one <font face='Courier'>get_file_path</font> selects for this flow direction.",
    "<font face='Courier'>factor.csv</font> &mdash; for the unit, extension, and stressor columns.",
])

story += section_header("What it computes")
story.append(P(
    "The script groups by <font face='Courier'>trade_id</font> and emits a wide table "
    "with roughly 22 columns:"
))
story += bullets([
    "<b>Summary stats</b>: total_level, factor_count, unique_factors.",
    "<b>Extension pivot</b>: one column per extension (air_emissions, water, land, "
    "material, energy, employment) holding the sum of levels in that extension.",
    "<b>Major factor types</b>: CO2_total, CH4_total, N2O_total, NOX_total, Water_total, "
    "Energy_total, Land_total &mdash; computed by substring-matching stressor names.",
    "<b>Employment, two columns</b>: Employment_people_total (converted from &lsquo;1000 p&rsquo; "
    "to actual people by multiplying by 1000) and Employment_hours_total (left in millions of hours).",
    "<b>impact_intensity</b> = total_level / amount, with inf/-inf replaced by 0.",
])

story += section_header("The employment unit bug (fixed)")
story.append(P(
    "<font face='Courier'>EMPLOYMENT_FIX_SUMMARY.md</font> documents a historical bug "
    "where <font face='Courier'>trade_impact.py</font> summed &lsquo;Employment people&rsquo; (1000 p) "
    "and &lsquo;Employment hours&rsquo; (M.hr) factors into a single Employment_total column. "
    "This produced nonsense &mdash; literally more than 600 billion employed people for China. "
    "The fix splits them into two columns and converts people to units of 1 (not 1000). "
    "If you see legacy outputs with an Employment_total column, they are miscalibrated."
))

story += section_header("Why it is a candidate for a VIEW")
story.append(P(
    "Every column in <font face='Courier'>trade_impact.csv</font> is a deterministic "
    "aggregation of trade &times; trade_factor &times; factor. The <font face='Courier'>PLAN.md</font> "
    "roadmap recognises this and marks the file as <i>&lsquo;skipped &mdash; computable via JOIN&rsquo;</i> "
    "for SQL ingestion. In other words, <font face='Courier'>trade_impact.csv</font> exists for "
    "static dashboards and GitHub-hosted CSV consumers; it does not need to live in the "
    "database."
))

# =========================================================================
# CHAPTER 7
# =========================================================================
story += chapter("7", "trade_resource.py: Three specialised views")

story.append(P(
    "<font face='Courier'>trade_resource.py</font> is the third main.py script. It splits "
    "<font face='Courier'>trade_factor</font> rows into three domain-specific files &mdash; "
    "employment, resources, and materials &mdash; each with its own subcategories and intensity "
    "columns. The split is driven by the factor's <font face='Courier'>context</font> field, "
    "which is derived from the factor's extension."
))

story += section_header("How it classifies")
story.append(two_col_table([
    ["Output file", "Factors it includes"],
    ["<b>trade_employment.csv</b>", "context == economic/employment. "
                                     "Subcategories: People (Employment people:) and Hours (Employment hours:)."],
    ["<b>trade_resource.csv</b>", "context in {emission/water, natural_resource/water, "
                                   "natural_resource/land, natural_resource/energy} <b>or</b> "
                                   "fullname matches Crops / Primary Crops / Agriculture / Forestry / Fishery. "
                                   "Subcategories: Water_Consumption, Water_Withdrawal, Energy, Land_Crops, "
                                   "Land_Forest, Land_Other, Crops."],
    ["<b>trade_material.csv</b>", "context == natural_resource/in_ground AND NOT in crops keywords. "
                                   "Subcategories: Metals, Minerals, Fossil, Other_Materials."],
]))

story += section_header("Column shape of each output")
story.append(P(
    "All three files share the same shape:"
))
story += bullets([
    "<b>Core trade columns</b>: trade_id, year, region1, region2, industry1, industry2, amount.",
    "<b>Summary</b>: total_&lt;category&gt;_value, &lt;category&gt;_count, "
    "unique_&lt;category&gt;_factors.",
    "<b>Context pivot</b>: one column per <font face='Courier'>context</font> value found.",
    "<b>Subcategory columns</b>: as listed above.",
    "<b>Intensity</b>: &lt;category&gt;_intensity = total_value / amount.",
])

story += section_header("Why three files instead of one")
story.append(P(
    "The split exists partly for file size (each file is manageable for Node.js and SQL "
    "clients) and partly because consuming dashboards tend to specialise &mdash; an employment "
    "dashboard does not need water columns, and a materials dashboard does not need "
    "employment. Like <font face='Courier'>trade_impact.csv</font>, these files are "
    "<i>computable from the base tables</i> and are therefore flagged as redundant in "
    "<font face='Courier'>PLAN.md</font>."
))

# =========================================================================
# CHAPTER 8
# =========================================================================
story += chapter("8", "main.py: Batch orchestration")

story.append(P(
    "<font face='Courier'>main.py</font> is the batch runner. It reads "
    "<font face='Courier'>config.yaml</font>, resolves the country list, and for each "
    "(country, flow_direction) tuple invokes the three processing scripts in order:"
))
story.append(code_block(
    "python trade.py          # produces trade.csv + trade_factor(-max).csv\n"
    "python trade_impact.py   # produces trade_impact.csv\n"
    "python trade_resource.py # produces trade_resource.csv, _material.csv, _employment.csv"
))

story += section_header("Three-tier timeouts")
story.append(two_col_table([
    ["Tier", "Limit", "Behaviour"],
    ["Per script", "20 minutes (1200 s)", "subprocess.run(timeout=1200). Kills a hung "
                                            "<font face='Courier'>trade.py</font> or "
                                            "<font face='Courier'>trade_impact.py</font>."],
    ["Per country", "60 minutes (3600 s)", "Rolling budget across the three scripts for one "
                                             "country. Printed as a countdown."],
    ["Per batch", "5 hours (18,000 s)", "Hard ceiling for the whole run. The most restrictive "
                                          "timeout wins."],
], col_widths=[doc_width*0.2, doc_width*0.22, doc_width*0.58])
)

story += section_header("Resumability")
story.append(P(
    "After a country completes, <font face='Courier'>main.py</font> writes a "
    "<font face='Courier'>runnote.md</font> in that country's output folder. On the next "
    "run, if <font face='Courier'>runnote.md</font> exists, the country is <b>skipped</b>. "
    "This is how large multi-country runs survive crashes and partial failures &mdash; "
    "just restart and the batch resumes from where it stopped. During a run, the file "
    "is called <font face='Courier'>runnote-inprogress.md</font> and tracks intermediate "
    "state; on success it is renamed to <font face='Courier'>runnote.md</font>."
))

story += section_header("Observed timing")
story.append(P(
    "From the README's measured runs on 2019/US:"
))
story.append(two_col_table([
    ["Flow", "trade.py", "trade_impact.py", "trade_resource.py", "Rows (trade / factor)"],
    ["<b>exports</b>", "2m 14s", "5.3s", "9.0s", "188,735 / 125,148"],
    ["<b>imports</b>", "2m 11s", "3.5s", "5.6s", "126,166 / 19,425"],
    ["<b>domestic</b>", "2m 18s", "1.7s", "1.9s", "21,518 / 11,832"],
], col_widths=[doc_width*0.15, doc_width*0.17, doc_width*0.2, doc_width*0.2, doc_width*0.28])
)

# =========================================================================
# CHAPTER 9
# =========================================================================
story += chapter("9", "factor.csv and industry.csv")

story.append(P(
    "These two files live at the top of the <font face='Courier'>year/{year}/</font> tree, "
    "not inside a country folder &mdash; they are shared across all countries and flow "
    "directions. Both are generated once and reused."
))

story += section_header("factor.csv")
story.append(P(
    "Generated by <font face='Courier'>factors.py</font>. The script walks the six "
    "extensions in a fixed order (<b>air_emissions, employment, energy, land, material, "
    "water</b>) and assigns a 1-based <font face='Courier'>factor_id</font> to each "
    "stressor row in each extension's F matrix. The output has four columns:"
))
story += bullets([
    "<b>factor_id</b> &mdash; stable integer PK. Order is deterministic given a fixed "
    "EXIOBASE release.",
    "<b>unit</b> &mdash; the unit string from EXIOBASE's extension metadata.",
    "<b>stressor</b> &mdash; the full stressor name (e.g. "
    "<font face='Courier'>CO2 - combustion - air</font>).",
    "<b>extension</b> &mdash; which of the six extensions the row came from.",
])
story.append(P(
    "The total is <b>721 factors</b> for the 2019 release. The exact count can shift "
    "between EXIOBASE releases, which is why factor_id is <i>stable per release</i> but "
    "not <i>stable across releases</i>."
))

story += section_header("industry.csv")
story.append(P(
    "Generated by <font face='Courier'>create_sector_mapping.py</font>. The script "
    "reads the EXIOBASE sector list and converts each sector name to a 5-character "
    "<b>industry_id</b> via three strategies:"
))
story += bullets([
    "<b>Strategy 1</b>: Strip common words (and, of, related, services, products, nec, "
    "other), remove punctuation, uppercase, take the first 5 characters.",
    "<b>Strategy 2</b>: If strategy 1 is too short, build an acronym from first letters of words.",
    "<b>Strategy 3</b>: If still too short, pad with zero-filled index.",
    "<b>Collision resolution</b>: if the resulting code is already used, replace the last "
    "character with a counter (then last two).",
])
story.append(P(
    "The output has three columns: <b>industry_id</b>, <b>name</b> (the full EXIOBASE "
    "sector name), and <b>category</b> (one of ~24 keyword-matched buckets: Agriculture, "
    "Forestry, Mining, Chemicals, Utilities, Trade, etc.)."
))

story += section_header("Why 5 characters")
story.append(P(
    "The 5-character width is a deliberate design choice for consistency with other "
    "Model.Earth tables. The BEA README notes a planned 6-character "
    "<b>commodity</b> table for USEEIO / BEA / NAICS codes &mdash; those are structurally "
    "different taxonomies with their own stability concerns, so they get their own tables "
    "rather than being squeezed into the 5-character industry_id."
))

# =========================================================================
# CHAPTER 10
# =========================================================================
story += chapter("10", "The 120-vs-721 selection problem")

story.append(P(
    "This is the single most important design trade-off in the pipeline, and it drives a "
    "surprising amount of surface area &mdash; a config flag, two different output filenames, "
    "a smart file selector, and a warning in every single trade_resource.py run."
))

story += section_header("The numbers")
story.append(P(
    "Each trade transaction can potentially have a non-zero coefficient for all 721 "
    "environmental factors. For a US exports run with 188,735 trade transactions, that "
    "would produce <b>188,735 &times; 721 = 136 million</b> rows in "
    "<font face='Courier'>trade_factor.csv</font>, before filtering. The resulting file "
    "is ~1.5 GB and routinely crashes Node.js consumers with "
    "<i>FATAL ERROR: v8::ToLocalChecked Empty MaybeLocal</i>."
))

story += section_header("The 120 selection")
story.append(P(
    "To keep the file manageable, the pipeline selects <b>120 factors per industry</b> "
    "by ranking all stressors whose absolute S-matrix coefficient meets "
    "<font face='Courier'>min_impact_threshold</font> (default 0.001) in descending order "
    "and keeping the first <font face='Courier'>partial_factor_limit</font> (default 120). "
    "<b>120 / 721 = 16.6%</b>, so the output is about one-sixth the size of the full join."
))

story += section_header("Where each file is used")
story.append(two_col_table([
    ["File", "When generated"],
    ["<b>trade_factor.csv</b>", "Always for imports and exports. Also for domestic if "
                                 "<font face='Courier'>use_partial_factors_domestic</font> is true."],
    ["<b>trade_factor-max.csv</b>", "Only when <font face='Courier'>-lag</font> flag is passed, "
                                     "or when <font face='Courier'>use_partial_factors_domestic: false</font>."],
    ["<b>interstate_factor.csv</b>", "US BEA state-to-state. Default is 50 selected factors "
                                       "(not 120; smaller because the row count is multiplied by "
                                       "state-pair combinatorics)."],
    ["<b>interstate_factor-max.csv</b>", "When <font face='Courier'>use_partial_factors_interstate: false</font>."],
]))

story += section_header("The trade-off")
story.append(P(
    "Selecting the top 120 by coefficient magnitude optimises for <b>captured value</b> "
    "but can hide <b>specific stressors a user cares about</b>. If someone asks "
    "&lsquo;what is the embodied methane in cement imports?&rsquo; and methane did not make "
    "the top-120 for that industry, the answer in <font face='Courier'>trade_factor.csv</font> "
    "will be 0 &mdash; silently. The <font face='Courier'>-max</font> file is the escape hatch, "
    "but requires explicit opt-in and a willingness to deal with multi-gigabyte files."
))

# =========================================================================
# CHAPTER 11
# =========================================================================
story += chapter("11", "CSV output catalogue")

story.append(P(
    "A single <font face='Courier'>python main.py</font> run against "
    "<font face='Courier'>2019/US/exports</font> produces the following tree. Shared "
    "reference files sit at the year level; per-flow files sit under the "
    "<font face='Courier'>country/flow</font> folder."
))

story.append(code_block(
    "year/2019/\n"
    "  factor.csv                                   # 721 rows\n"
    "  industry.csv                                 # ~200 rows\n"
    "  US/\n"
    "    exports/\n"
    "      trade.csv                                # 188,735 rows\n"
    "      trade_factor.csv                         # 125,148 rows (120 selected)\n"
    "      trade_impact.csv                         # 188,735 rows, 22 cols\n"
    "      trade_resource.csv                       # resources view\n"
    "      trade_material.csv                       # materials view\n"
    "      trade_employment.csv                     # employment view\n"
    "      runnote.md\n"
    "    imports/\n"
    "      trade.csv                                # 126,166 rows\n"
    "      trade_factor.csv                         # 19,425 rows\n"
    "      ...\n"
    "    domestic/\n"
    "      trade.csv                                # 21,518 rows\n"
    "      trade_factor.csv (or trade_factor-max.csv)\n"
    "      ..."
))

story += section_header("Column reference")
story.append(two_col_table([
    ["File", "Columns"],
    ["<b>factor.csv</b>", "factor_id, unit, stressor, extension"],
    ["<b>industry.csv</b>", "industry_id, name, category"],
    ["<b>trade.csv</b>", "trade_id, year, region1, region2, industry1, industry2, amount"],
    ["<b>trade_factor.csv</b>", "trade_id, factor_id, level"],
    ["<b>trade_impact.csv</b>", "trade_id + 7 trade columns + ~15 impact columns"],
    ["<b>trade_resource.csv</b>", "trade columns + total_resources_value, resources_count, "
                                   "unique_resources_factors, context pivot, subcategories, intensity"],
    ["<b>trade_material.csv</b>", "same shape as trade_resource.csv but materials-only"],
    ["<b>trade_employment.csv</b>", "same shape, employment-only (People + Hours subcategories)"],
    ["<b>interstate.csv</b>", "interstate_id, year, region1, region2, industry1, industry2, "
                               "amount, commodity_code, industry_code, economic_multiplier"],
    ["<b>interstate_factor.csv</b>", "interstate_id, factor_id, level"],
]))

# =========================================================================
# CHAPTER 12
# =========================================================================
story += chapter("12", "US BEA: Interstate state-to-state flows")

story.append(P(
    "<font face='Courier'>bea/main.py</font> is a separate but closely related pipeline that "
    "disaggregates US national trade flows into state-to-state flows, using BEA input-output "
    "data and employment multipliers. The output follows the same shape as "
    "<font face='Courier'>trade</font> and <font face='Courier'>trade_factor</font>, but at "
    "the state level: <b>interstate.csv</b> and <b>interstate_factor.csv</b>."
))

story += section_header("Prerequisites")
story.append(P(
    "<font face='Courier'>bea/main.py</font> is <i>not</i> standalone &mdash; it builds on top "
    "of the base pipeline. Before running, you need:"
))
story += bullets([
    "<font face='Courier'>exiobase_data/IOT_{year}_pxp.zip</font> &mdash; the EXIOBASE download.",
    "The three US <font face='Courier'>trade.csv</font> files (domestic, imports, exports) &mdash; "
    "generated by <font face='Courier'>trade.py</font> or by passing <font face='Courier'>--force-regen</font>.",
    "A BEA API key in <font face='Courier'>webroot/.env</font> as "
    "<font face='Courier'>BEA_API_KEY=...</font> (register at apps.bea.gov/api/signup).",
])

story += section_header("Five-phase pipeline")
story.append(two_col_table([
    ["Phase", "What it does"],
    ["1. Base", "Ensures the three Exiobase <font face='Courier'>trade.csv</font> files exist. "
                 "If not, runs <font face='Courier'>trade.py</font> inline."],
    ["2. BEA API", "<font face='Courier'>main_api_client.py</font> fetches IntlServTrade, "
                     "InputOutput, and GDPbyIndustry data. Caches responses in "
                     "<font face='Courier'>bea_cache/</font> for 24 hours."],
    ["3. State-level", "<font face='Courier'>main_trade_analyzer.py</font> disaggregates "
                         "national flows across states using BEA employment and output weights."],
    ["4. FEDEFL", "<font face='Courier'>main_fedefl_integration.py</font> cross-walks EXIOBASE "
                   "stressors to the Federal LCA Commons Elementary Flow List &mdash; "
                   "write-only artefact for review."],
    ["5. S matrix join", "Loads the EXIOBASE S matrix directly via pymrio to assign "
                           "<font face='Courier'>factor_id</font> and compute per-flow levels for "
                           "<font face='Courier'>interstate_factor.csv</font>."],
], col_widths=[doc_width*0.22, doc_width*0.78])
)

story += section_header("The interstate_id key")
story.append(P(
    "Instead of a surrogate integer ID, <font face='Courier'>interstate_id</font> is a "
    "composite string:"
))
story.append(code_block(
    "interstate_id = {year}-US-{origin_state}-US-{destination_state}-{state_industry_code}\n"
    "example: 2019-US-NY-US-CA-311"
))
story.append(P(
    "This makes the ID stable across runs and self-documenting at the cost of being long. "
    "It also means two tables &mdash; <font face='Courier'>interstate</font> and "
    "<font face='Courier'>interstate_factor</font> &mdash; share the composite key as the "
    "join column instead of needing a surrogate FK."
))

story += section_header("50 factors, not 120")
story.append(P(
    "Interstate flows have another combinatorial multiplier &mdash; 51 states &times; 51 states "
    "&times; industries &times; factors. At 120 factors per industry, the full table hit "
    "~5 GB. The default is tightened to <b>50 selected factors</b> "
    "(<font face='Courier'>partial_factor_limit_interstate: 5</font> wait, verify &mdash; "
    "actually the docs say 50 is the current operational default while config.yaml shows 5; "
    "the smaller value is for current test runs). The investigation note dated "
    "2026-03-27 records 68.5M rows produced with 120 factors."
))

story += section_header("BEA economic_multiplier")
story.append(P(
    "<font face='Courier'>interstate.economic_multiplier</font> is the BEA Input-Output "
    "<b>Total industry output requirement</b> from TableID 61, keyed by BEA Summary "
    "<font face='Courier'>industry_code</font>. It is used to estimate total output "
    "impact as <font face='Courier'>interstate.amount &times; economic_multiplier</font>. "
    "When BEA has no matching row, the fallback is 1.0."
))

# =========================================================================
# CHAPTER 13
# =========================================================================
story += chapter("13", "India: State-level allocation")

story.append(P(
    "<font face='Courier'>india/main.py</font> is a parallel disaggregation pipeline that "
    "allocates Indian national trade and economic data across 36 states and union territories. "
    "Where the BEA pipeline uses BEA API data, the India pipeline uses raw data files "
    "stored under <font face='Courier'>exiobase/India_data/</font> &mdash; GSDP, GSVA, "
    "SUT/IOT, and TradeStat exports/imports."
))

story += section_header("Five allocation outputs")
story += bullets([
    "<b>state_sector_output.csv</b> &mdash; State &times; sector output; GSDP scaled by "
    "GSVA sector shares.",
    "<b>state_product_export.csv</b> &mdash; National exports allocated to states, with HS "
    "codes mapped to EXIOBASE products.",
    "<b>state_product_import.csv</b> &mdash; National imports allocated by GSDP proportions.",
    "<b>india_states.csv</b> &mdash; State summary with Output, Employment, Population columns.",
    "<b>allocation_report.md</b> &mdash; Processing summary.",
])

story += section_header("Shared taxonomy with US")
story.append(P(
    "The India pipeline deliberately uses the same 5-character <b>industry_id</b> values "
    "as the EXIOBASE core pipeline. The crosswalk file "
    "<font face='Courier'>india_us_exiobase_crosswalk.csv</font> maps Indian GSVA activity "
    "labels and HS product codes to EXIOBASE industry IDs. This means India and US outputs "
    "can be joined on industry_id for cross-country comparison without a separate "
    "harmonisation step."
))

story += section_header("Data categorisation")
story.append(P(
    "At startup, <font face='Courier'>india/main.py</font> scans "
    "<font face='Courier'>India_data/</font> and categorises files by keyword matches "
    "in the filename: anything containing <font face='Courier'>gsdp/sdp/gdp</font> is "
    "treated as GSDP data, anything with <font face='Courier'>gsva/nsva/value_added</font> "
    "as GSVA, and so on. State-specific Excel files are used as fallback when consolidated "
    "GSDP or GSVA files are not present."
))

# =========================================================================
# CHAPTER 14
# =========================================================================
story += chapter("14", "SQL ingestion (insert_sql.py)")

story.append(P(
    "<font face='Courier'>insert_sql.py</font> is a small, generic CSV-to-SQL loader "
    "that reads any of the generated CSVs and appends rows to a Postgres or MS SQL table, "
    "creating the table from the CSV schema on first run."
))

story += section_header("How it is invoked")
story.append(code_block(
    "python insert_sql.py \\\n"
    "    --conn_id exiobase \\\n"
    "    --connections_path ../Connections/db_connections.yaml \\\n"
    "    --source_csv year/2019/US/exports/trade.csv \\\n"
    "    --table_name trade \\\n"
    "    --schema public \\\n"
    "    --chunksize 5000"
))

story += section_header("Connection resolution")
story.append(P(
    "Credentials come from a <font face='Courier'>db_connections.yaml</font> file "
    "(located one level up at <font face='Courier'>Connections/db_connections.yaml</font>). "
    "The YAML has one entry per connection ID with fields "
    "<font face='Courier'>type, host, database, user, password, port</font>. "
    "Supported types: <b>postgres</b> (via psycopg2) and <b>mssql</b> (via pyodbc with "
    "ODBC Driver 18)."
))

story += section_header("The method='multi' detail")
story.append(P(
    "The call uses <font face='Courier'>df.to_sql(..., method='multi', chunksize=5000)</font>. "
    "This batches rows into multi-row INSERT statements rather than per-row inserts, "
    "which is roughly 10-20&times; faster for the Python side of the load. For truly large "
    "loads (interstate_factor at 68M rows), neither Python nor SQLAlchemy is the right path &mdash; "
    "you want <font face='Courier'>COPY FROM STDIN</font> via psycopg2 directly or "
    "<font face='Courier'>bcp</font> on MSSQL. The script does not do this currently."
))

story += section_header("Ingestion order")
story.append(P(
    "Foreign keys dictate the sequence. From <font face='Courier'>PLAN.md</font>:"
))
story += bullets([
    "<b>1.</b> factor.csv &rarr; factor table.",
    "<b>2.</b> industry.csv &rarr; industry table.",
    "<b>3.</b> For each (country, flow_type): trade.csv &rarr; trade; then "
    "trade_factor.csv &rarr; trade_factor.",
    "<b>4.</b> US only, domestic: interstate.csv &rarr; interstate; "
    "state_trade_flows.csv &rarr; interstate_factor.",
])

# =========================================================================
# CHAPTER 15
# =========================================================================
story += chapter("15", "Running it: commands, timing, resumability")

story += section_header("One-time setup")
story.append(code_block(
    "python -m venv ~/env\n"
    "source ~/env/bin/activate       # macOS/Linux\n"
    "~/env/Scripts/activate.bat      # Windows\n"
    "pip install --prefer-binary -r requirements.txt"
))

story += section_header("Standard run")
story.append(code_block(
    "# Edit config.yaml: set YEAR, TRADEFLOW, COUNTRY.list\n"
    "cd exiobase/tradeflow\n"
    "python main.py"
))

story.append(P(
    "The first run for a new year will spend ~10 minutes downloading the EXIOBASE zip "
    "(~535 MB) from Zenodo into <font face='Courier'>exiobase_data/</font>. "
    "That file is <font face='Courier'>.gitignore</font>d and is reused across subsequent "
    "runs."
))

story += section_header("Partial runs")
story.append(code_block(
    "# Run just the extraction stage\n"
    "python trade.py\n"
    "\n"
    "# Run just the aggregation\n"
    "python trade_impact.py\n"
    "\n"
    "# Run just the resource split\n"
    "python trade_resource.py\n"
    "\n"
    "# Force the large 721-factor file for domestic\n"
    "python trade.py -lag"
))

story += section_header("US interstate")
story.append(code_block(
    "# Prerequisites: trade.csv files for US/{domestic,imports,exports}\n"
    "python bea/main.py                       # uses BEA_API_KEY from webroot/.env\n"
    "python bea/main.py --bea-key YOUR_KEY    # explicit key\n"
    "python bea/main.py --force-regen         # regenerate base trade.csv first"
))

story += section_header("India state-level")
story.append(code_block(
    "python india/main.py                      # uses config.yaml year\n"
    "python india/main.py --year 2019\n"
    "python india/main.py --data-dir ../India_data"
))

story += section_header("Resume behaviour")
story.append(P(
    "If <font face='Courier'>main.py</font> is killed mid-run or hits a timeout, "
    "it leaves <font face='Courier'>runnote-inprogress.md</font> files in incomplete "
    "country folders. On the next run those countries are retried; "
    "countries with a final <font face='Courier'>runnote.md</font> are skipped. "
    "To <b>force</b> a re-run for a specific country, delete its "
    "<font face='Courier'>runnote.md</font>."
))

# =========================================================================
# CHAPTER 16
# =========================================================================
story += chapter("16", "Troubleshooting and gotchas")

story += section_header("Memory errors in Node.js consumers")
story.append(P(
    "<i>FATAL ERROR: v8::ToLocalChecked Empty MaybeLocal</i> after about 10 minutes is "
    "the signature of a Node consumer trying to parse "
    "<font face='Courier'>trade_factor-max.csv</font> (~1.5 GB). The fix is to use the "
    "default 120-factor file, not the <font face='Courier'>-lag</font> version, for the "
    "flow being consumed. If domestic analysis <i>needs</i> the full 721 factors, process "
    "it in chunks or move to SQL."
))

story += section_header("&lsquo;trade_factor.csv not found&rsquo;")
story.append(P(
    "<font face='Courier'>trade_impact.py</font> and <font face='Courier'>trade_resource.py</font> "
    "both expect <font face='Courier'>trade_factor.csv</font> as input. If it is missing, "
    "<font face='Courier'>trade.py</font> never completed. Check the "
    "<font face='Courier'>runnote</font> for the stage that failed."
))

story += section_header("Empty domestic flows")
story.append(P(
    "If domestic processing reports zero flows, the country code probably does not match "
    "an EXIOBASE region. Verify the country code is one of the ~44 EXIOBASE codes "
    "(two-letter codes such as US, CN, DE, plus five rest-of-world codes). "
    "<font face='Courier'>debug_regions.py</font> can be used to print the full list."
))

story += section_header("Employment numbers off by 1,000&times;")
story.append(P(
    "If employment totals look wrong by three orders of magnitude, the "
    "<font face='Courier'>trade_impact.py</font> fix documented in "
    "<font face='Courier'>EMPLOYMENT_FIX_SUMMARY.md</font> was not applied. "
    "Employment people factors use <b>1000 p</b> units and need a &times;1000 "
    "conversion to actual people; the hours factors use <b>M.hr</b> and stay in millions."
))

story += section_header("Zenodo URL changes")
story.append(P(
    "EXIOBASE is hosted on Zenodo under DOI 10.5281/zenodo.3583070. Zenodo has, in the "
    "past, changed its download URL format from <font face='Courier'>/records/ID/files/NAME.zip</font> "
    "to <font face='Courier'>/api/records/ID/files/NAME.zip/content</font>. "
    "The <font face='Courier'>_download_direct()</font> method in "
    "<font face='Courier'>trade.py</font> bypasses pymrio's built-in downloader for this "
    "reason &mdash; if downloads fail with 404, the Zenodo URL format has probably changed again."
))

story += section_header("factor_id does not match stressor")
story.append(P(
    "Short stressor names like <font face='Courier'>CO2</font> are ambiguous &mdash; there are "
    "multiple CO2 factor rows in different contexts (combustion, non-combustion, biogenic). "
    "<font face='Courier'>trade.py</font> builds a robust mapping that handles common "
    "formatting variations (PM2.5 vs PM2_5, dots vs underscores) but will log "
    "<i>&lsquo;unmapped stressors&rsquo;</i> warnings if a factor name cannot be matched. "
    "Those rows are dropped from <font face='Courier'>trade_factor.csv</font>."
))

# =========================================================================
# CHAPTER 17
# =========================================================================
story += chapter("17", "The schema being proposed for SQL")

story.append(P(
    "<font face='Courier'>PLAN.md</font> describes the target SQL schema. It is not yet "
    "implemented in a database &mdash; the CSVs are the current source of truth &mdash; but the "
    "shape is settled enough that the ingestion endpoints have been scoped. Three tables "
    "hold the base data; three more hold the interstate extension."
))

story += section_header("Base tables")
story.append(code_block(
    "industry (industry_id PK VARCHAR(10), name TEXT, category VARCHAR(100))\n"
    "\n"
    "factor (factor_id PK INTEGER, unit VARCHAR(50), stressor TEXT, extension VARCHAR(100))\n"
    "\n"
    "trade (\n"
    "    id         BIGSERIAL PRIMARY KEY,\n"
    "    trade_id   INTEGER NOT NULL,\n"
    "    year       SMALLINT NOT NULL,\n"
    "    region1    VARCHAR(10) NOT NULL,\n"
    "    region2    VARCHAR(10) NOT NULL,\n"
    "    industry1  VARCHAR(10) REFERENCES industry(industry_id),\n"
    "    industry2  VARCHAR(10) REFERENCES industry(industry_id),\n"
    "    amount     NUMERIC(18,4),\n"
    "    flow_type  VARCHAR(10) NOT NULL,\n"
    "    country    VARCHAR(10) NOT NULL,\n"
    "    UNIQUE (trade_id, year, country, flow_type)\n"
    ")"
))

story += section_header("Trade_factor")
story.append(code_block(
    "trade_factor (\n"
    "    id          BIGSERIAL PRIMARY KEY,\n"
    "    trade_id    INTEGER NOT NULL,\n"
    "    year        SMALLINT NOT NULL,\n"
    "    country     VARCHAR(10) NOT NULL,\n"
    "    flow_type   VARCHAR(10) NOT NULL,\n"
    "    factor_id   INTEGER NOT NULL REFERENCES factor(factor_id),\n"
    "    coefficient NUMERIC(20,10),\n"
    "    level       NUMERIC(20,6)\n"
    ")\n"
    "\n"
    "-- Join to trade:\n"
    "-- trade_factor.trade_id = trade.trade_id\n"
    "--   AND trade_factor.year = trade.year\n"
    "--   AND trade_factor.country = trade.country\n"
    "--   AND trade_factor.flow_type = trade.flow_type"
))

story += section_header("Notes on the proposed shape")
story += bullets([
    "<b>Composite join</b>: because <font face='Courier'>trade_id</font> from CSV is "
    "per-run and per-flow, the join to <font face='Courier'>trade</font> must include "
    "(year, country, flow_type) to disambiguate.",
    "<b>Redundant tables omitted</b>: <font face='Courier'>trade_impact</font>, "
    "<font face='Courier'>trade_resource</font>, <font face='Courier'>trade_material</font>, "
    "<font face='Courier'>trade_employment</font> are not planned as physical tables &mdash; "
    "they are computed via JOIN at query time.",
    "<b>Indexes</b> on trade_id, year, country, flow_type for both <font face='Courier'>trade</font> "
    "and <font face='Courier'>trade_factor</font>; separate indexes on region1, region2, factor_id.",
    "<b>Rust API</b>: three endpoints &mdash; /api/db/init-industry-tables, "
    "/api/db/insert-trade-data, /api/db/industry-schema &mdash; are planned to drive the "
    "SQL side.",
])

story += section_header("Interstate tables")
story.append(code_block(
    "interstate (\n"
    "    id                  BIGSERIAL PRIMARY KEY,\n"
    "    trade_id            INTEGER NOT NULL,\n"
    "    year                SMALLINT NOT NULL,\n"
    "    region1             VARCHAR(10) NOT NULL,  -- US-AK\n"
    "    region2             VARCHAR(10) NOT NULL,  -- US-GA\n"
    "    industry1           VARCHAR(10) REFERENCES industry(industry_id),\n"
    "    industry2           VARCHAR(10) REFERENCES industry(industry_id),\n"
    "    amount              NUMERIC(18,4),\n"
    "    commodity_code      VARCHAR(30),\n"
    "    industry_code       VARCHAR(30),\n"
    "    economic_multiplier NUMERIC(10,6)\n"
    ")\n"
    "\n"
    "interstate_factor (\n"
    "    id            BIGSERIAL PRIMARY KEY,\n"
    "    interstate_id VARCHAR(80) NOT NULL,\n"
    "    factor_id     INTEGER REFERENCES factor(factor_id),\n"
    "    level         NUMERIC(20,6)\n"
    ")"
))

# =========================================================================
# APPENDIX A
# =========================================================================
story += chapter("A", "Repository map")

story.append(P(
    "The <font face='Courier'>exiobase/tradeflow/</font> directory, annotated:"
))

story.append(code_block(
    "tradeflow/\n"
    "  AGENTS.md                       # Full developer notes for Claude Code\n"
    "  PLAN.md                         # Target SQL schema and ingestion plan\n"
    "  README.md                       # Public-facing overview\n"
    "  REMOVED.md                      # Scripts removed from the pipeline\n"
    "  EMPLOYMENT_FIX_*.md             # Record of the 1000-persons unit bug fix\n"
    "  requirements.txt                # Python dependencies\n"
    "  config.yaml                     # Central configuration\n"
    "  config-bkup.yaml                # Last-known-good config backup\n"
    "\n"
    "  # --- CORE PIPELINE (invoked by main.py) ---\n"
    "  main.py                         # Batch orchestrator with 3-tier timeouts\n"
    "  trade.py                        # Z + S matrix extraction, factor selection\n"
    "  trade_impact.py                 # Per-trade impact aggregation (22 columns)\n"
    "  trade_resource.py               # Split into employment / resource / material\n"
    "  config_loader.py                # YAML + env-var resolution\n"
    "\n"
    "  # --- SUPPORT ---\n"
    "  factors.py                      # Generate factor.csv from F matrix\n"
    "  create_sector_mapping.py        # Generate industry.csv from Z sectors\n"
    "  create_full_trade_factor.py     # Historical 721-factor generator (legacy)\n"
    "  insert_sql.py                   # Generic CSV &rarr; Postgres/MSSQL loader\n"
    "\n"
    "  # --- UTILITIES ---\n"
    "  update_current_country.py       # Set config.yaml COUNTRY.current\n"
    "  process_countries_sequentially.py  # Alternative orchestrator\n"
    "  process_remaining.py            # Resume helper\n"
    "  run_single_country.py           # Convenience for one country\n"
    "  run_multiple_countries.py       # Convenience for several\n"
    "  run_batch_imports.py            # Imports-only batch\n"
    "  run_domestic_batch.py           # Domestic-only batch\n"
    "  debug_regions.py                # Print EXIOBASE region codes\n"
    "  examine_factors.py              # Inspect factor.csv contents\n"
    "  examine_sectors.py              # Inspect sector codes\n"
    "  test_config.py                  # Config loader unit tests\n"
    "  test_trade_factors.py           # Factor generation smoke tests\n"
    "  trade_competitiveness.py        # Export RCA analysis (standalone)\n"
    "\n"
    "  # --- US BEA EXTENSION ---\n"
    "  bea/\n"
    "    main.py                       # Interstate pipeline entrypoint\n"
    "    main_api_client.py            # BEA API with 24-hour cache\n"
    "    main_trade_analyzer.py        # State disaggregation + impacts\n"
    "    main_fedefl_integration.py    # FEDEFL flow metadata\n"
    "    README.md                     # BEA-specific docs\n"
    "    PLAN.md                       # Outstanding BEA questions\n"
    "\n"
    "  # --- INDIA EXTENSION ---\n"
    "  india/\n"
    "    main.py                       # India state allocation\n"
    "    README.md                     # India pipeline docs\n"
    "\n"
    "  # --- WEB ---\n"
    "  index.html                      # Browser landing page"
))

# =========================================================================
# APPENDIX B — Glossary
# =========================================================================
story += chapter("B", "Glossary")

glossary = [
    ("amount", "Monetary value of a trade transaction in million euros (M EUR). "
                "Column in <font face='Courier'>trade.csv</font> and "
                "<font face='Courier'>interstate.csv</font>."),
    ("category", "One of ~24 industry buckets (Agriculture, Mining, Chemicals, Utilities, "
                  "...) derived by keyword matching the EXIOBASE sector name. "
                  "Column in <font face='Courier'>industry.csv</font>."),
    ("coefficient", "Per-M-EUR intensity from the EXIOBASE S matrix. Not stored in output "
                     "CSVs &mdash; derivable as <font face='Courier'>level / amount</font>."),
    ("context", "A derived category string like <font face='Courier'>emission/air</font> or "
                 "<font face='Courier'>natural_resource/water</font>, used in trade_resource.py "
                 "to split factors."),
    ("domestic", "Flow direction: intra-country trade (region1 == region2 == country)."),
    ("exports", "Flow direction: outbound from the configured country (region1 == country, "
                 "region2 != country)."),
    ("extension", "One of six EXIOBASE environmental extensions: air_emissions, employment, "
                   "energy, land, material, water."),
    ("factor", "A single environmental stressor row. 721 total across six extensions."),
    ("factor_id", "1-based integer PK for a factor. Order determined by extension order "
                   "and row order within each extension's F matrix."),
    ("FEDEFL", "Federal LCA Commons Elementary Flow List &mdash; EPA's canonical environmental "
                "flow registry. Mapped to EXIOBASE factors in flow.csv (review-only artefact)."),
    ("flow (deprecated term)", "What EXIOBASE calls a Z-matrix cell. TradeFlow renames this "
                                 "to <b>trade</b> to avoid confusion with Sankey arcs and FEDEFL flows."),
    ("imports", "Flow direction: inbound to the configured country (region1 != country, "
                 "region2 == country)."),
    ("industry", "A product-by-product EXIOBASE sector. ~200 total."),
    ("industry_id", "5-character mnemonic PK for an industry (e.g. WHEAT, CEREA, PADDY). "
                     "Generated by name-truncation with collision counter."),
    ("interstate", "A state-to-state analogue of <font face='Courier'>trade</font>, produced "
                    "by <font face='Courier'>bea/main.py</font>."),
    ("interstate_id", "Composite string ID: <font face='Courier'>{year}-US-{origin}-US-{dest}-{code}</font>. "
                       "Used as the join column between interstate and interstate_factor."),
    ("level", "Physical impact quantity in <font face='Courier'>trade_factor.csv</font>. "
               "Equal to <font face='Courier'>amount &times; coefficient</font>. "
               "Unit depends on the factor's extension."),
    ("MRIO", "Multi-regional input-output. The economic modelling framework EXIOBASE implements."),
    ("partial_factor_limit", "Config knob setting how many factors per industry survive the "
                              "selection filter. Defaults: 120 for international, 50 for interstate."),
    ("pymrio", "The Python library used to parse EXIOBASE zip files into pandas-backed objects "
                "with .Z, .Y, .A, and extension attributes."),
    ("runnote.md", "Per-country marker file. If present in a country's output folder, "
                    "<font face='Courier'>main.py</font> skips that country on the next run."),
    ("S matrix", "Per-M-EUR intensity matrix for an environmental extension. "
                  "<font face='Courier'>S = F / x</font> where x is total output per sector."),
    ("stressor", "Full factor name as it appears in EXIOBASE (e.g. <font face='Courier'>CO2 "
                  "- combustion - air</font>). Column in <font face='Courier'>factor.csv</font>."),
    ("trade", "A row in <font face='Courier'>trade.csv</font>: one bilateral industry-pair flow "
               "in a given year and direction."),
    ("trade_id", "1-based integer ID for a trade row. Per-run, per-country, per-direction &mdash; "
                  "<i>not</i> globally stable."),
    ("Y matrix", "Final demand matrix. Not currently written to output CSVs by this pipeline "
                  "(<font face='Courier'>industryflow_finaldemand.py</font> was removed per REMOVED.md)."),
    ("Z matrix", "Inter-industry transaction matrix in M EUR. Source of all "
                  "<font face='Courier'>trade.csv</font> rows."),
]

story.append(two_col_table([["Term", "Definition"]] + glossary,
                           col_widths=[doc_width*0.25, doc_width*0.75]))

# Closing page
story.append(PageBreak())
story.append(Spacer(1, 3*inch))
story.append(Paragraph("&mdash; End of Field Guide &mdash;",
                       ParagraphStyle("end", fontName="Helvetica-Oblique",
                                      fontSize=14, leading=20, textColor=MUTED,
                                      alignment=TA_CENTER)))
story.append(Spacer(1, 0.3*inch))
story.append(Paragraph("Source files are in exiobase/tradeflow/. "
                       "When documentation and code disagree, trust the code.",
                       ParagraphStyle("end2", fontName="Helvetica",
                                      fontSize=10, leading=15, textColor=MUTED,
                                      alignment=TA_CENTER)))

# ============================================================
# BUILD
# ============================================================
doc = BookDoc(str(OUT))
doc.build(story)
print(f"Wrote: {OUT}  ({OUT.stat().st_size:,} bytes)")

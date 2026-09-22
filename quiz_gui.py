#!/usr/bin/env python3
"""
quiz_gui.py — Security+ (SY0-701) quiz, GUI edition (PySide6 / Qt6).

A native desktop window wrapping the same question bank, drill tables and
stats store as quiz.py (the terminal version). Shares questions.json,
acronyms.json, crypto.json and stats.json with the CLI, so progress carries
across both tools.

Screens (QStackedWidget): Home, Drill setup, Acronym setup, Crypto setup,
Question, Summary, Stats, plus a Drill question screen and Drill summary for
the acronym and crypto drills.

Both drills are driven by ONE generic widget set keyed off the shared drill
modules (acronyms.py / crypto.py), mirroring the CLI — a drift between the two
front-ends (and between the two drills) is structurally impossible.

Theme: a 1980s CRT terminal / phosphor-green reskin applied with an explicit
QPalette + stylesheet (never the system palette), so --screenshot renders are
a faithful preview of the real window.

Flags:
    --selftest     run a headless 10-question round AND scripted acronym/crypto
                   drill rounds through the real click/answer handlers, print
                   the score / per-domain tally. Writes to a TEMPORARY stats
                   file (never the real stats.json) unless an explicit
                   --stats PATH is given.
    --screenshot DIR  render every screen offscreen and save numbered PNGs of
                   the actual widgets into DIR; never touches real stats.
    --seed N       deterministic shuffling (same semantics as the CLI).
    --bank PATH    explicit question-bank path.
    --stats PATH   explicit stats path.
"""

import argparse
import json
import os
import random
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# Reuse the CLI's pure-stdlib logic so shuffling, selection, and the stats
# schema stay identical across both tools. quiz.py, acronyms.py and crypto.py
# import only the stdlib.
import quiz
import acronyms
import crypto

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QGuiApplication,
    QIcon,
    QPainter,
    QPalette,
)
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

DEFAULT_BANK = os.path.join(SCRIPT_DIR, "questions.json")
DEFAULT_STATS = os.path.join(SCRIPT_DIR, "stats.json")
ICON_PATH = os.path.join(os.path.expanduser("~"),
                         ".local/share/icons/security-plus-quiz.svg")

APP_NAME = "Security+ Quiz"
DESKTOP_FILE = "security-plus-quiz"

# The longest (uppercased) domain name; keeps the per-domain stat bars aligned.
DOMAIN_PAD = max(len(quiz.DOMAIN_NAMES[d].upper()) for d in quiz.DOMAIN_NAMES)

# ---------------------------------------------------------------- theme

# Fixed CRT palette. Every value is explicit so the UI is identical whether it
# is drawn on a real desktop or rendered offscreen for --screenshot.
C_BG = "#05100a"          # window/panel base
C_BG_PANEL = "#07160d"    # slightly lighter panel fill
C_GREEN_BRIGHT = "#3dff7a"  # headings, question text, primary UI
C_GREEN_BODY = "#8affb8"  # body / explanation text
C_GREEN_DIM = "#2f9e57"   # borders, dividers, secondary labels (5.67:1 vs #05100a, WCAG AA)
C_AMBER = "#ffb454"       # warnings, medium-difficulty tags, highlights
C_RED = "#ff4d4d"         # wrong answers / ACCESS DENIED
C_INVERT_BG = "#05100a"   # inverse-video foreground
C_INVERT_FG = "#3dff7a"   # inverse-video background

# Body floor is 12pt; headings are set larger and bold in the widgets.
_MONO_CANDIDATES = ["JetBrains Mono", "Hack", "Noto Sans Mono",
                    "Liberation Mono", "monospace"]

# Difficulty tag -> (label, colour).
_DIFF_TAG = {
    "easy": ("EASY", C_GREEN_DIM),
    "medium": ("MED", C_AMBER),
    "hard": ("HARD", C_RED),
}

BLOCK_FULL = "\u2588"    # █
BLOCK_LIGHT = "\u2591"   # ░
BLOCK_CURSOR = "\u258c"  # ▌


def resolve_mono_family():
    """Pick the first available monospace family via QFontDatabase."""
    avail = set(f.lower() for f in QFontDatabase.families())
    for cand in _MONO_CANDIDATES:
        if cand.lower() in avail:
            return cand
    return "monospace"


def build_stylesheet():
    """Return the explicit retro stylesheet. Zero radius, 1px borders, no
    system-palette inheritance anywhere."""
    return """
    QLabel { color: #3dff7a; background: transparent; }
    QLabel[role="body"] { color: #8affb8; }
    QLabel[role="dim"] { color: #2f9e57; }
    QLabel[role="amber"] { color: #ffb454; }
    QLabel[role="red"] { color: #ff4d4d; }
    QLabel[role="heading"] { color: #3dff7a; font-weight: bold; }
    QLabel#boxHeader { color: #3dff7a; font-weight: bold; }
    QLabel#bootLog { color: #8affb8; }
    QLabel[verdict="correct"] { color: #3dff7a; font-weight: bold; }
    QLabel[verdict="incorrect"] { color: #ff4d4d; font-weight: bold; }

    QWidget#statusStrip { background: #07160d; border-bottom: 1px solid #2f9e57; }
    QLabel#statusText { color: #8affb8; }
    QLabel#statusCursor { color: #3dff7a; }

    ClickableText { color: #3dff7a; background: transparent; padding: 3px 6px; }
    ClickableText[hovered="true"] { color: #05100a; }
    ClickableText[state="correct"] { color: #05100a; }
    ClickableText[state="incorrect"] { color: #05100a; }
    ClickableText[state="muted"] { color: #2f9e57; }

    QPushButton { background: #07160d; color: #3dff7a;
                  border: 1px solid #2f9e57; border-radius: 0; padding: 5px 14px; }
    QPushButton:hover { background: #3dff7a; color: #05100a; }
    QPushButton:pressed { background: #3dff7a; color: #05100a; }
    QPushButton:disabled { color: #2f9e57; border-color: #2f9e57; background: #07160d; }
    QPushButton:focus { border-color: #3dff7a; }
    QPushButton[role="menu"] { background: transparent; color: #3dff7a;
        border: none; text-align: left; padding: 4px 8px; }
    QPushButton[role="menu"]:hover { background: #3dff7a; color: #05100a; }
    QPushButton[role="menu"]:pressed { background: #3dff7a; color: #05100a; }

    QCheckBox, QRadioButton { background: transparent; color: #3dff7a; spacing: 0px; }
    QCheckBox::indicator, QRadioButton::indicator { width: 0px; height: 0px; border: none; }
    QCheckBox:hover, QRadioButton:hover { background: #3dff7a; color: #05100a; }

    QListWidget { background: #05100a; color: #8affb8; border: 1px solid #2f9e57; }
    QListWidget::item { padding: 3px 4px; }
    QListWidget::item:selected { background: #07160d; color: #3dff7a; }

    QLineEdit { background: #05100a; color: #3dff7a;
                border: 1px solid #2f9e57; padding: 4px 6px; }
    QLineEdit:focus { border-color: #3dff7a; }
    """


def apply_theme(app):
    """Apply the full retro theme to `app`. Returns the resolved mono family.

    The base is an explicit dark QPalette (Window #05100a) plus the stylesheet
    above; nothing is inherited from the host system palette, so offscreen
    renders match the real window exactly.
    """
    family = resolve_mono_family()

    app.setStyle("Fusion")

    f = QFont(family)
    f.setPointSize(12)  # hard floor for body text
    app.setFont(f)

    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(C_BG))
    pal.setColor(QPalette.WindowText, QColor(C_GREEN_BRIGHT))
    pal.setColor(QPalette.Base, QColor(C_BG))
    pal.setColor(QPalette.AlternateBase, QColor(C_BG_PANEL))
    pal.setColor(QPalette.Text, QColor(C_GREEN_BRIGHT))
    pal.setColor(QPalette.Button, QColor(C_BG_PANEL))
    pal.setColor(QPalette.ButtonText, QColor(C_GREEN_BRIGHT))
    pal.setColor(QPalette.Highlight, QColor(C_GREEN_BRIGHT))
    pal.setColor(QPalette.HighlightedText, QColor(C_INVERT_BG))
    pal.setColor(QPalette.ToolTipBase, QColor(C_BG_PANEL))
    pal.setColor(QPalette.ToolTipText, QColor(C_GREEN_BODY))
    pal.setColor(QPalette.Link, QColor(C_GREEN_BRIGHT))
    app.setPalette(pal)

    app.setStyleSheet(build_stylesheet())
    return family


def make_glow():
    """Phosphor glow: green_bright halo, offset 0,0, blur ~12."""
    fx = QGraphicsDropShadowEffect()
    fx.setOffset(0, 0)
    fx.setBlurRadius(12)
    c = QColor(C_GREEN_BRIGHT)
    c.setAlpha(220)
    fx.setColor(c)
    return fx


def _pad(s, width):
    """Pad to a fixed width using non-breaking spaces (survives rich-text
    whitespace collapsing so monospace columns stay aligned)."""
    s = str(s)
    return s + "\u00a0" * max(0, width - len(s))


def ascii_bar_html(pct, width):
    """Coloured ASCII bar: filled block green_bright, remainder green_dim."""
    pct = max(0.0, min(100.0, float(pct)))
    filled = int(round(pct / 100.0 * width))
    filled = max(0, min(width, filled))
    return ('<span style="color:%s">%s</span><span style="color:%s">%s</span>'
            % (C_GREEN_BRIGHT, BLOCK_FULL * filled,
               C_GREEN_DIM, BLOCK_LIGHT * (width - filled)))


def ascii_progress_html(index, total, width=16):
    """'[████████░░░░░░░░] 50%' style progress bar."""
    pct = (100.0 * index / total) if total else 0.0
    return "[%s] %d%%" % (ascii_bar_html(pct, width), round(pct))


def domain_bar_html(d, name, correct, total, pct):
    """'DOM-2 THREATS, VULNERABILITIES...  ██████  75%  (3/4)' aligned line.

    The name is padded to DOMAIN_PAD (the longest Security+ domain name) and
    the bar is 6 blocks so the trailing "(n/m)" stays on-screen even with
    three-digit totals at the 560x420 minimum window width.
    """
    label = "DOM-%d %s" % (d, _pad(name, DOMAIN_PAD))
    return ('<span style="color:%s">%s  %s  %s (%d/%d)</span>'
            % (C_GREEN_BODY, label, ascii_bar_html(pct, 6),
               _pad("%d%%" % round(pct), 4), correct, total))


# ---------------------------------------------------------------- data I/O

def load_bank_gui(path):
    """Return (bank, error_message). Mirrors quiz.py's wording."""
    if not os.path.exists(path):
        return None, "question bank file not found: %s" % path
    try:
        with open(path, encoding="utf-8") as f:
            bank = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, "question bank is not valid JSON: %s" % path
    if not isinstance(bank, list) or not bank:
        return None, "question bank is empty or malformed: %s" % path
    return bank, None


def build_options(q, rng):
    """Shuffle option order using the CLI's make_choices; return display texts
    and the 0-based index of the correct option in display order."""
    keys, shown, correct_key = quiz.make_choices(q, rng)
    texts = [t for _, t in shown]
    correct_index = keys.index(correct_key)
    return texts, correct_index, q["type"]


# ---------------------------------------------------------------- widgets

class StatusStrip(QWidget):
    """Top status strip: monospace, 1px green_dim rule under it, trailing ▌."""

    def __init__(self, animate=True, parent=None):
        super().__init__(parent)
        self.setObjectName("statusStrip")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(0)

        self.text_label = QLabel("")
        self.text_label.setObjectName("statusText")
        self.cursor_label = QLabel(BLOCK_CURSOR)
        self.cursor_label.setObjectName("statusCursor")

        lay.addWidget(self.text_label)
        lay.addWidget(self.cursor_label)
        lay.addStretch(1)

        self._animate = animate
        self._timer = None
        if animate:
            self._timer = QTimer(self)
            self._timer.setInterval(500)
            self._timer.timeout.connect(self._blink)
            self._timer.start()
            self._cursor_on = True

    def _blink(self):
        self._cursor_on = not self._cursor_on
        self.cursor_label.setVisible(self._cursor_on)

    def set_status(self, text):
        self.text_label.setText(text)

    def stop(self):
        if self._timer is not None:
            self._timer.stop()


class ClickableText(QLabel):
    """A wrapped, clickable terminal line. Hover = inverse video; 'state'
    property drives correct/incorrect/muted feedback colours."""

    clicked = Signal()

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        self.setAttribute(Qt.WA_Hover, True)
        self._interactive = True
        self._hovered = False
        self.setProperty("state", "")
        self.setProperty("hovered", False)

    def set_interactive(self, on):
        self._interactive = on
        if not on:
            self._hovered = False
            self.setCursor(Qt.ArrowCursor)
            self.setProperty("hovered", False)
            self.style().unpolish(self)
            self.style().polish(self)

    def set_state(self, s):
        self.setProperty("state", s)
        self._refresh()

    def hoverEnterEvent(self, e):
        if self._interactive:
            self._hovered = True
            self._refresh()
        super().hoverEnterEvent(e)

    def hoverLeaveEvent(self, e):
        if self._hovered:
            self._hovered = False
            self._refresh()
        super().hoverLeaveEvent(e)

    def mousePressEvent(self, e):
        if self._interactive and e.button() == Qt.LeftButton:
            self.clicked.emit()
        else:
            super().mousePressEvent(e)

    def click(self):
        # Programmatic click (drives the real handler in selftest).
        if self._interactive:
            self.clicked.emit()

    def _refresh(self):
        self.setProperty("hovered", self._hovered)
        self.style().unpolish(self)
        self.style().polish(self)

    def _background_color(self):
        """Opaque background colour for the current state. Always returns a
        solid colour (never None) so the row fully clears its own rect on every
        repaint: the base #05100a in the neutral/muted states, the inverse-video
        fill in the correct/incorrect/hover states."""
        state = self.property("state")
        if state == "correct" or self._hovered:
            return QColor(C_GREEN_BRIGHT)
        if state == "incorrect":
            return QColor(C_RED)
        return QColor(C_BG)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), self._background_color())
        super().paintEvent(event)


class TermCheckBox(QCheckBox):
    """Checkbox rendered as '[x] label' / '[ ] label'."""

    def __init__(self, label, parent=None):
        super().__init__(parent)
        self._label = label
        self.setCursor(Qt.PointingHandCursor)
        self.toggled.connect(self._refresh)
        self._refresh()

    def _refresh(self):
        self.setText(("[x] " if self.isChecked() else "[ ] ") + self._label)


class TermRadio(QRadioButton):
    """Radio rendered as '(x) label' / '( ) label'."""

    def __init__(self, label, parent=None):
        super().__init__(parent)
        self._label = label
        self.setCursor(Qt.PointingHandCursor)
        self.toggled.connect(self._refresh)
        self._refresh()

    def _refresh(self):
        self.setText(("(x) " if self.isChecked() else "( ) ") + self._label)


class ScanlineOverlay(QWidget):
    """CRT scanlines: horizontal dark lines, ~2px pitch, alpha ~0.12, drawn
    over the content area. Transparent to the mouse and OFF-safe (hiding it
    stops all painting)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setPen(Qt.NoPen)
        w = self.width()
        h = self.height()
        color = QColor(0, 0, 0, int(255 * 0.12))
        y = 0
        while y < h:
            p.fillRect(0, y, w, 1, color)
            y += 2


# ---------------------------------------------------------------- screens

class HomeWidget(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setFocusPolicy(Qt.StrongFocus)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 10, 18, 14)
        lay.setSpacing(6)

        self.status = StatusStrip(controller.animate)
        lay.addWidget(self.status)

        self.box_header = QLabel(self._box_header_text())
        self.box_header.setObjectName("boxHeader")
        f = self.box_header.font()
        f.setPointSize(15)
        f.setBold(True)
        self.box_header.setFont(f)
        self.box_header.setAlignment(Qt.AlignCenter)
        self.box_header.setGraphicsEffect(make_glow())
        lay.addWidget(self.box_header)

        lay.addSpacing(4)

        self.boot_label = QLabel("")
        self.boot_label.setObjectName("bootLog")
        self.boot_label.setTextInteractionFlags(Qt.NoTextInteraction)
        lay.addWidget(self.boot_label)

        lay.addSpacing(8)

        menu_items = [
            ("[1] QUICK 10", controller.start_quick),
            ("[2] DOMAIN DRILL", controller.show_drill),
            ("[3] ACRONYM DRILL", controller.show_acronym_drill),
            ("[4] CRYPTO & CONTROLS DRILL", controller.show_crypto_drill),
            ("[5] REVIEW MISSED", controller.start_review),
            ("[6] REVIEW ACRONYMS", controller.start_review_acronyms),
            ("[7] REVIEW CRYPTO & CONTROLS", controller.start_review_crypto),
            ("[8] STATS", controller.show_stats),
            ("[9] QUIT", controller.close),
        ]
        self.buttons = []
        for label, cb in menu_items:
            b = QPushButton(label)
            b.setProperty("role", "menu")
            b.setFocusPolicy(Qt.NoFocus)
            b.setMinimumHeight(30)
            b.clicked.connect(cb)
            lay.addWidget(b)
            self.buttons.append(b)

        lay.addSpacing(8)

        self.scan_cb = TermCheckBox("CRT SCANLINES")
        self.scan_cb.setFocusPolicy(Qt.NoFocus)
        self.scan_cb.setChecked(True)
        self.scan_cb.toggled.connect(controller.set_scanlines)
        lay.addWidget(self.scan_cb)

        lay.addStretch(1)

        self._boot_text = self._boot_log()
        self._boot_done = False
        self._boot_timer = QTimer(self)
        self._boot_timer.setInterval(15)
        self._boot_timer.timeout.connect(self._boot_tick)
        self._boot_reveal = 0

    @staticmethod
    def _box_header_text():
        inner = "   SECURITY+  QUIZ  [SY0-701] "
        w = len(inner)
        top = "\u250c" + "\u2500" * w + "\u2510"
        mid = "\u2502" + inner + "\u2502"
        bot = "\u2514" + "\u2500" * w + "\u2518"
        return "\n".join([top, mid, bot])

    def _boot_log(self):
        n = len(self.controller.bank)
        lines = ["> INITIALIZING QUIZ MODULE ................ OK",
                 "> LOADING QUESTION BANK (%d RECORDS) ..... OK" % n]
        a = self.controller.acronyms
        if a is not None:
            lines.append("> LOADING ACRONYM TABLE (%d RECORDS) .... OK" % len(a))
        c = self.controller.crypto
        if c is not None:
            lines.append("> LOADING CRYPTO TABLE (%d RECORDS) ..... OK" % len(c))
        lines.append("> TERMINAL READY")
        return "\n".join(lines)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._boot_done:
            if self.controller.animate:
                self._boot_reveal = 0
                self.boot_label.setText("")
                self._boot_timer.start()
            else:
                self.boot_label.setText(self._boot_text)
                self._boot_done = True

    def _boot_tick(self):
        n = len(self._boot_text)
        step = max(1, n // 50)
        self._boot_reveal += step
        if self._boot_reveal >= n:
            self._boot_reveal = n
            self._boot_timer.stop()
            self._boot_done = True
        self.boot_label.setText(self._boot_text[:self._boot_reveal])


class DrillSetupWidget(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setFocusPolicy(Qt.StrongFocus)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 10, 18, 14)
        lay.setSpacing(6)

        self.status = StatusStrip(controller.animate)
        lay.addWidget(self.status)

        title = QLabel("DOMAIN DRILL")
        title.setProperty("role", "heading")
        f = title.font()
        f.setPointSize(15)
        f.setBold(True)
        title.setFont(f)
        lay.addWidget(title)

        sel = QLabel("SELECT DOMAIN(S):")
        sel.setProperty("role", "dim")
        lay.addWidget(sel)

        self.all_cb = TermCheckBox("ALL DOMAINS")
        lay.addWidget(self.all_cb)

        self.domain_cbs = []
        for d in range(1, 6):
            cb = TermCheckBox("%d - %s" % (d, quiz.DOMAIN_NAMES[d].upper()))
            lay.addWidget(cb)
            self.domain_cbs.append(cb)

        self.all_cb.toggled.connect(self._on_all_toggled)
        for cb in self.domain_cbs:
            cb.toggled.connect(self._on_domain_toggled)

        lay.addSpacing(8)

        len_label = QLabel("LENGTH:")
        len_label.setProperty("role", "dim")
        lay.addWidget(len_label)

        len_row = QHBoxLayout()
        self.len_group = QButtonGroup(self)
        self.len_10 = TermRadio("10")
        self.len_20 = TermRadio("20")
        self.len_all = TermRadio("ALL")
        self.len_10.setChecked(True)
        for r in (self.len_10, self.len_20, self.len_all):
            self.len_group.addButton(r)
            len_row.addWidget(r)
        len_row.addStretch(1)
        lay.addLayout(len_row)

        lay.addStretch(1)

        row = QHBoxLayout()
        self.back_btn = QPushButton("[ BACK ]")
        self.start_btn = QPushButton("[ START ]")
        self.start_btn.setDefault(True)
        self.back_btn.clicked.connect(controller.go_home)
        self.start_btn.clicked.connect(controller.start_drill)
        row.addWidget(self.back_btn)
        row.addStretch(1)
        row.addWidget(self.start_btn)
        lay.addLayout(row)

    def _on_all_toggled(self, checked):
        for cb in self.domain_cbs:
            cb.blockSignals(True)
            cb.setChecked(checked)
            cb.blockSignals(False)

    def _on_domain_toggled(self, checked):
        all_on = all(cb.isChecked() for cb in self.domain_cbs)
        self.all_cb.blockSignals(True)
        self.all_cb.setChecked(all_on)
        self.all_cb.blockSignals(False)

    def selected_domains(self):
        return [d + 1 for d, cb in enumerate(self.domain_cbs) if cb.isChecked()]

    def selected_length(self):
        if self.len_10.isChecked():
            return 10
        if self.len_20.isChecked():
            return 20
        return None  # "all"


class QuestionWidget(QWidget):
    answered_signal = Signal(dict, bool)   # (question, correct)
    advance_signal = Signal()
    go_home = Signal()

    def __init__(self, rng, controller, parent=None):
        super().__init__(parent)
        self.rng = rng
        self.controller = controller
        self.q = None
        self.qtype = "mc"
        self.answered = False
        self.chosen_index = None
        self.correct_index = None
        self.display_keys = []
        self.correct_display_key = None
        self.option_buttons = []

        self.setFocusPolicy(Qt.StrongFocus)
        self.setAutoFillBackground(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 6, 16, 6)
        lay.setSpacing(6)

        self.status = StatusStrip(controller.animate)
        lay.addWidget(self.status)

        self.qheader_label = QLabel("")
        self.qheader_label.setTextInteractionFlags(Qt.NoTextInteraction)
        lay.addWidget(self.qheader_label)

        self.progress_label = QLabel("")
        self.progress_label.setTextInteractionFlags(Qt.NoTextInteraction)
        lay.addWidget(self.progress_label)

        self.question_label = QLabel("")
        self.question_label.setWordWrap(True)
        self.question_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        f = self.question_label.font()
        f.setPointSize(13)
        self.question_label.setFont(f)
        lay.addWidget(self.question_label)

        lay.addSpacing(4)

        self.options_layout = QVBoxLayout()
        self.options_layout.setSpacing(3)
        lay.addLayout(self.options_layout)

        lay.addSpacing(4)

        self.verdict_label = QLabel("")
        self.verdict_label.setVisible(False)
        self.verdict_label.setGraphicsEffect(make_glow())
        lay.addWidget(self.verdict_label)

        self.explanation_label = QLabel("")
        self.explanation_label.setWordWrap(True)
        self.explanation_label.setProperty("role", "body")
        self.explanation_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.explanation_label.setVisible(False)
        lay.addWidget(self.explanation_label)

        self.source_label = QLabel("")
        self.source_label.setWordWrap(True)
        self.source_label.setProperty("role", "dim")
        self.source_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.source_label.setVisible(False)
        lay.addWidget(self.source_label)

        lay.addStretch(1)

        bottom = QHBoxLayout()
        self.home_button = QPushButton("[ HOME ]")
        self.home_button.setFocusPolicy(Qt.NoFocus)
        self.home_button.clicked.connect(self.go_home.emit)
        bottom.addWidget(self.home_button)
        bottom.addStretch(1)
        self.next_button = QPushButton("[ NEXT ]")
        self.next_button.setFocusPolicy(Qt.NoFocus)
        self.next_button.setEnabled(False)
        self.next_button.clicked.connect(self.advance)
        bottom.addWidget(self.next_button)
        lay.addLayout(bottom)

    def show_question(self, q, index, total):
        self.q = q
        self.answered = False
        self.chosen_index = None

        dname = quiz.DOMAIN_NAMES[q["domain"]].upper()
        dlabel, dcolor = _DIFF_TAG.get(q["difficulty"].lower(),
                                       (q["difficulty"].upper(), C_GREEN_BRIGHT))
        header = "Q%02d/%d  [DOM-%d %s]" % (index, total, q["domain"], dname)
        self.qheader_label.setText(
            '<span style="color:%s">%s</span>  <span style="color:%s">[%s]</span>'
            % (C_GREEN_BRIGHT, header, dcolor, dlabel))
        self.progress_label.setText(ascii_progress_html(index, total))

        self.question_label.setText(q["question"])

        texts, self.correct_index, self.qtype = build_options(q, self.rng)
        if self.qtype == "mc":
            self.display_keys = ["1", "2", "3", "4"]
        else:
            self.display_keys = ["T", "F"]
        self.correct_display_key = self.display_keys[self.correct_index]

        while self.options_layout.count():
            item = self.options_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self.option_buttons = []
        for key, text in zip(self.display_keys, texts):
            opt = ClickableText("[%s] %s" % (key, text))
            opt.clicked.connect(lambda k=key: self.answer(k))
            self.options_layout.addWidget(opt)
            self.option_buttons.append(opt)

        self.verdict_label.setVisible(False)
        self.explanation_label.setVisible(False)
        self.source_label.setVisible(False)
        self.next_button.setEnabled(False)
        self.update()

    def answer(self, key):
        if self.answered or key not in self.display_keys:
            return
        self.answered = True
        self.chosen_index = self.display_keys.index(key)
        correct = (self.chosen_index == self.correct_index)

        for i, opt in enumerate(self.option_buttons):
            opt.set_interactive(False)
            if i == self.correct_index:
                state = "correct"
            elif i == self.chosen_index:
                state = "incorrect"
            else:
                state = "muted"
            opt.set_state(state)

        if correct:
            self.verdict_label.setText(">> ACCESS GRANTED")
            self.verdict_label.setProperty("verdict", "correct")
        else:
            self.verdict_label.setText("!! ACCESS DENIED")
            self.verdict_label.setProperty("verdict", "incorrect")
        self.verdict_label.style().unpolish(self.verdict_label)
        self.verdict_label.style().polish(self.verdict_label)
        self.verdict_label.setVisible(True)

        self.explanation_label.setText(self.q["explanation"])
        self.explanation_label.setVisible(True)

        src = self.q["source"]
        self.source_label.setText("// source: %s > %s"
                                  % (src["note"], src["section"]))
        self.source_label.setVisible(True)

        self.next_button.setEnabled(True)
        self.answered_signal.emit(self.q, correct)

    def advance(self):
        if not self.answered:
            return
        self.advance_signal.emit()

    def keyPressEvent(self, event):
        key = event.key()
        txt = event.text().lower()

        if key == Qt.Key_Escape:
            self.go_home.emit()
            event.accept()
            return

        if self.answered:
            if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
                self.advance()
                event.accept()
                return
            super().keyPressEvent(event)
            return

        handled = False
        if self.qtype == "mc":
            num_map = {Qt.Key_1: "1", Qt.Key_2: "2",
                       Qt.Key_3: "3", Qt.Key_4: "4"}
            if key in num_map:
                self.answer(num_map[key])
                handled = True
            elif txt in ("a", "b", "c", "d"):
                idx = ord(txt) - ord("a")
                if idx < len(self.display_keys):
                    self.answer(self.display_keys[idx])
                    handled = True
        else:
            if txt in ("t", "f"):
                self.answer(txt.upper())
                handled = True

        if handled:
            event.accept()
            return
        super().keyPressEvent(event)


class SummaryWidget(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAutoFillBackground(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 10, 18, 14)
        lay.setSpacing(6)

        self.status = StatusStrip(controller.animate)
        lay.addWidget(self.status)

        title = QLabel("SESSION COMPLETE")
        title.setProperty("role", "heading")
        f = title.font()
        f.setPointSize(15)
        f.setBold(True)
        title.setFont(f)
        lay.addWidget(title)

        self.score_label = QLabel("")
        lay.addWidget(self.score_label)

        pd = QLabel("PER-DOMAIN:")
        pd.setProperty("role", "dim")
        lay.addWidget(pd)

        self.breakdown_label = QLabel("")
        self.breakdown_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.breakdown_label)

        lay.addSpacing(4)

        self.missed_header = QLabel("MISSED QUEUE:")
        self.missed_header.setProperty("role", "dim")
        self.missed_header.setVisible(False)
        lay.addWidget(self.missed_header)

        self.missed_list = QListWidget()
        self.missed_list.setWordWrap(True)
        self.missed_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.missed_list.setFocusPolicy(Qt.NoFocus)
        self.missed_list.setVisible(False)
        lay.addWidget(self.missed_list, 1)

        self.clean_label = QLabel("CLEAN ROUND - NOTHING MISSED.")
        self.clean_label.setProperty("role", "body")
        self.clean_label.setVisible(False)
        lay.addWidget(self.clean_label)

        row = QHBoxLayout()
        self.again_btn = QPushButton("[ R ] REPLAY")
        self.review_btn = QPushButton("[ M ] REVIEW MISSED")
        self.home_btn = QPushButton("[ B ] BACK TO HOME")
        self.again_btn.clicked.connect(controller.play_again)
        self.review_btn.clicked.connect(controller.review_from_summary)
        self.home_btn.clicked.connect(controller.go_home)
        row.addWidget(self.again_btn)
        row.addWidget(self.review_btn)
        row.addStretch(1)
        row.addWidget(self.home_btn)
        lay.addLayout(row)

    def update(self, results):
        total = len(results)
        score = sum(1 for _, ok in results if ok)
        pct = 100.0 * score / total if total else 0.0
        self.score_label.setText("SCORE %02d/%02d    ACCURACY %3d%%"
                                 % (score, total, round(pct)))

        agg = {}
        for q, ok in results:
            a = agg.setdefault(q["domain"], [0, 0])
            a[1] += 1
            if ok:
                a[0] += 1

        lines = []
        for d in sorted(agg):
            c, t = agg[d]
            p = 100.0 * c / t if t else 0.0
            lines.append(domain_bar_html(d, quiz.DOMAIN_NAMES[d].upper(), c, t, p))
        self.breakdown_label.setText(
            "<br>".join(lines) if lines
            else '<span style="color:%s">(none)</span>' % C_GREEN_DIM)

        missed = [q for q, ok in results if not ok]
        self.missed_list.clear()
        if missed:
            self.missed_header.setVisible(True)
            self.missed_list.setVisible(True)
            self.clean_label.setVisible(False)
            for q in missed:
                self.missed_list.addItem(
                    QListWidgetItem("[DOM-%d] %s" % (q["domain"], q["question"])))
        else:
            self.missed_header.setVisible(False)
            self.missed_list.setVisible(False)
            self.clean_label.setVisible(True)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_R:
            self.controller.play_again()
            event.accept()
            return
        if key == Qt.Key_M:
            self.controller.review_from_summary()
            event.accept()
            return
        if key == Qt.Key_B:
            self.controller.go_home()
            event.accept()
            return
        super().keyPressEvent(event)


class StatsWidget(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setFocusPolicy(Qt.StrongFocus)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 10, 18, 14)
        lay.setSpacing(6)

        self.status = StatusStrip(controller.animate)
        lay.addWidget(self.status)

        title = QLabel("STATISTICS")
        title.setProperty("role", "heading")
        f = title.font()
        f.setPointSize(15)
        f.setBold(True)
        title.setFont(f)
        lay.addWidget(title)

        self.lifetime_label = QLabel("")
        lay.addWidget(self.lifetime_label)
        self.streak_label = QLabel("")
        lay.addWidget(self.streak_label)
        self.best_label = QLabel("")
        lay.addWidget(self.best_label)

        lay.addSpacing(6)

        pd = QLabel("PER-DOMAIN:")
        pd.setProperty("role", "dim")
        lay.addWidget(pd)

        self.domain_label = QLabel("")
        self.domain_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.domain_label)

        lay.addSpacing(6)

        self.hardest_label = QLabel("")
        lay.addWidget(self.hardest_label)
        self.missed_label = QLabel("")
        lay.addWidget(self.missed_label)
        self.acronym_label = QLabel("")
        lay.addWidget(self.acronym_label)
        self.crypto_label = QLabel("")
        lay.addWidget(self.crypto_label)

        lay.addStretch(1)

        row = QHBoxLayout()
        self.home_btn = QPushButton("[ B ] BACK TO HOME")
        self.home_btn.clicked.connect(controller.go_home)
        row.addStretch(1)
        row.addWidget(self.home_btn)
        lay.addLayout(row)

    def update(self, stats):
        lt = stats["lifetime"]
        tot, corr = lt["total"], lt["correct"]
        acc = 100.0 * corr / tot if tot else 0.0
        self.lifetime_label.setText("%-18s%d/%d  (%.1f%%)" % ("LIFETIME", corr, tot, acc))
        self.streak_label.setText("%-18s%d" % ("CURRENT STREAK", stats["current_streak"]))
        self.best_label.setText("%-18s%d" % ("BEST STREAK", stats["best_streak"]))

        lines = []
        hardest, hard_acc = None, None
        for d in ("1", "2", "3", "4", "5"):
            pd = stats["per_domain"].get(d)
            if pd and pd["total"] > 0:
                a = 100.0 * pd["correct"] / pd["total"]
                lines.append(domain_bar_html(int(d),
                                             quiz.DOMAIN_NAMES[int(d)].upper(),
                                             pd["correct"], pd["total"], a))
                if hard_acc is None or a < hard_acc:
                    hard_acc, hardest = a, d
        self.domain_label.setText(
            "<br>".join(lines) if lines
            else '<span style="color:%s">(no attempts yet)</span>' % C_GREEN_DIM)

        if hardest is not None:
            self.hardest_label.setText("%-18s%s (%s)"
                                       % ("HARDEST DOMAIN", hardest,
                                          quiz.DOMAIN_NAMES[int(hardest)].upper()))
        else:
            self.hardest_label.setText("%-18s%s" % ("HARDEST DOMAIN",
                                                    "none (no attempts yet)"))
        self.missed_label.setText("%-18s%d" % ("MISSED QUEUE",
                                               len(stats["missed_ids"])))
        a = stats["acronyms"]
        a_acc = 100.0 * a["correct"] / a["total"] if a["total"] else 0.0
        self.acronym_label.setText("%-18s%d/%d  (%.1f%%)   [%d missed]"
                                   % ("ACRONYM DRILL", a["correct"], a["total"],
                                      a_acc, len(a["missed_ids"])))
        c = stats["crypto"]
        c_acc = 100.0 * c["correct"] / c["total"] if c["total"] else 0.0
        self.crypto_label.setText("%-18s%d/%d  (%.1f%%)   [%d missed]"
                                  % ("CRYPTO & CONTROLS DRILL", c["correct"], c["total"],
                                     c_acc, len(c["missed_ids"])))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_B:
            self.controller.go_home()
            event.accept()
            return
        super().keyPressEvent(event)


class DrillModeSetupWidget(QWidget):
    """Drill setup for the acronym and crypto drills: direction (mixed plus the
    two drill directions) and length (10 / 20 / all). One widget class drives
    both drills via the shared drill module's DIRECTION_CHOICES."""

    def __init__(self, controller, mod, title, start_cb):
        super().__init__()
        self.controller = controller
        self.mod = mod
        self.setFocusPolicy(Qt.StrongFocus)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 10, 18, 14)
        lay.setSpacing(6)

        self.status = StatusStrip(controller.animate)
        lay.addWidget(self.status)

        title_label = QLabel(title)
        title_label.setProperty("role", "heading")
        f = title_label.font()
        f.setPointSize(15)
        f.setBold(True)
        title_label.setFont(f)
        lay.addWidget(title_label)

        sel = QLabel("DIRECTION:")
        sel.setProperty("role", "dim")
        lay.addWidget(sel)

        dir_row = QHBoxLayout()
        self.dir_group = QButtonGroup(self)
        self._dir_radios = []  # (radio, key)
        for label, key in mod.DIRECTION_CHOICES:
            radio = TermRadio(label.upper())
            self.dir_group.addButton(radio)
            self._dir_radios.append((radio, key))
            dir_row.addWidget(radio)
        self._dir_radios[0][0].setChecked(True)  # "mixed" is first
        dir_row.addStretch(1)
        lay.addLayout(dir_row)

        lay.addSpacing(8)

        len_label = QLabel("LENGTH:")
        len_label.setProperty("role", "dim")
        lay.addWidget(len_label)

        len_row = QHBoxLayout()
        self.len_group = QButtonGroup(self)
        self.len_10 = TermRadio("10")
        self.len_20 = TermRadio("20")
        self.len_all = TermRadio("ALL")
        self.len_10.setChecked(True)
        for r in (self.len_10, self.len_20, self.len_all):
            self.len_group.addButton(r)
            len_row.addWidget(r)
        len_row.addStretch(1)
        lay.addLayout(len_row)

        lay.addStretch(1)

        row = QHBoxLayout()
        self.back_btn = QPushButton("[ BACK ]")
        self.start_btn = QPushButton("[ START ]")
        self.start_btn.setDefault(True)
        self.back_btn.clicked.connect(controller.go_home)
        self.start_btn.clicked.connect(start_cb)
        row.addWidget(self.back_btn)
        row.addStretch(1)
        row.addWidget(self.start_btn)
        lay.addLayout(row)

    def selected_direction(self):
        for radio, key in self._dir_radios:
            if radio.isChecked():
                return key
        return self.mod.DIR_MIXED

    def selected_length(self):
        if self.len_10.isChecked():
            return 10
        if self.len_20.isChecked():
            return 20
        return None  # "all"


class DrillQuestionWidget(QWidget):
    """Free-text drill-question screen for the acronym and crypto drills:
    prompt, typed answer, verdict, explanation, citation. The active drill
    module is read from the controller, so one widget serves both drills."""

    answered_signal = Signal(object, object, object)   # (item, correct, answer)
    advance_signal = Signal()
    go_home = Signal()

    def __init__(self, rng, controller, parent=None):
        super().__init__(parent)
        self.rng = rng
        self.controller = controller
        self.item = None
        self.answered = False
        self.correct = False
        self.correct_answer = ""

        self.setFocusPolicy(Qt.StrongFocus)
        self.setAutoFillBackground(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 6, 16, 6)
        lay.setSpacing(6)

        self.status = StatusStrip(controller.animate)
        lay.addWidget(self.status)

        self.qheader_label = QLabel("")
        self.qheader_label.setTextInteractionFlags(Qt.NoTextInteraction)
        lay.addWidget(self.qheader_label)

        self.progress_label = QLabel("")
        self.progress_label.setTextInteractionFlags(Qt.NoTextInteraction)
        lay.addWidget(self.progress_label)

        self.prompt_label = QLabel("")
        self.prompt_label.setWordWrap(True)
        self.prompt_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        f = self.prompt_label.font()
        f.setPointSize(13)
        self.prompt_label.setFont(f)
        lay.addWidget(self.prompt_label)

        lay.addSpacing(4)

        entry_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("type answer...")
        self.input.returnPressed.connect(self.submit)
        self.submit_btn = QPushButton("[ ENTER ]")
        self.submit_btn.clicked.connect(self.submit)
        entry_row.addWidget(self.input, 1)
        entry_row.addWidget(self.submit_btn)
        lay.addLayout(entry_row)

        lay.addSpacing(4)

        self.verdict_label = QLabel("")
        self.verdict_label.setVisible(False)
        self.verdict_label.setGraphicsEffect(make_glow())
        lay.addWidget(self.verdict_label)

        self.explanation_label = QLabel("")
        self.explanation_label.setWordWrap(True)
        self.explanation_label.setProperty("role", "body")
        self.explanation_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.explanation_label.setVisible(False)
        lay.addWidget(self.explanation_label)

        self.source_label = QLabel("")
        self.source_label.setWordWrap(True)
        self.source_label.setProperty("role", "dim")
        self.source_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.source_label.setVisible(False)
        lay.addWidget(self.source_label)

        lay.addStretch(1)

        bottom = QHBoxLayout()
        self.home_button = QPushButton("[ HOME ]")
        self.home_button.setFocusPolicy(Qt.NoFocus)
        self.home_button.clicked.connect(self.go_home.emit)
        bottom.addWidget(self.home_button)
        bottom.addStretch(1)
        self.next_button = QPushButton("[ NEXT ]")
        self.next_button.setFocusPolicy(Qt.NoFocus)
        self.next_button.setEnabled(False)
        self.next_button.clicked.connect(self.advance)
        bottom.addWidget(self.next_button)
        lay.addLayout(bottom)

    def show_item(self, item, index, total):
        self.item = item
        self.answered = False
        self.correct = False
        self.correct_answer = ""

        mod = self.controller.drill_mod
        direction = mod.direction_label(item["direction"]).upper()
        header = "%s  [%s]" % (mod.TITLE, direction)
        self.qheader_label.setText(
            '<span style="color:%s">%s%02d/%d</span>'
            '  <span style="color:%s">%s</span>'
            % (C_GREEN_BRIGHT, mod.Q_PREFIX, index, total, C_GREEN_DIM, header))
        self.progress_label.setText(ascii_progress_html(index, total))

        self.prompt_label.setText(item["prompt"])

        self.input.clear()
        self.input.setEnabled(True)
        self.submit_btn.setEnabled(True)
        self.verdict_label.setVisible(False)
        self.explanation_label.setVisible(False)
        self.source_label.setVisible(False)
        self.next_button.setEnabled(False)
        self.input.setFocus()
        self.update()

    def submit(self):
        if self.answered or self.item is None:
            return
        raw = self.input.text()
        mod = self.controller.drill_mod
        self.correct, self.correct_answer, _, _ = mod.grade(self.item, raw)
        self.answered = True

        self.input.setEnabled(False)
        self.submit_btn.setEnabled(False)

        if self.correct:
            self.verdict_label.setText(">> ACCESS GRANTED")
            self.verdict_label.setProperty("verdict", "correct")
        else:
            self.verdict_label.setText("!! ACCESS DENIED")
            self.verdict_label.setProperty("verdict", "incorrect")
        self.verdict_label.style().unpolish(self.verdict_label)
        self.verdict_label.style().polish(self.verdict_label)
        self.verdict_label.setVisible(True)

        if self.correct:
            self.explanation_label.setText(self.item["explanation"])
        else:
            self.explanation_label.setText("ANSWER: %s\n%s"
                                           % (self.correct_answer,
                                              self.item["explanation"]))
        self.explanation_label.setVisible(True)

        src = self.item["source"]
        self.source_label.setText("// source: %s > %s"
                                  % (src["note"], src["section"]))
        self.source_label.setVisible(True)

        self.next_button.setEnabled(True)
        self.answered_signal.emit(self.item, self.correct, self.correct_answer)

    def advance(self):
        if not self.answered:
            return
        self.advance_signal.emit()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Escape:
            self.go_home.emit()
            event.accept()
            return
        if self.answered:
            if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
                self.advance()
                event.accept()
                return
        super().keyPressEvent(event)


class DrillSummaryWidget(QWidget):
    """End-of-drill-round summary: score, accuracy, missed items."""

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAutoFillBackground(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 10, 18, 14)
        lay.setSpacing(6)

        self.status = StatusStrip(controller.animate)
        lay.addWidget(self.status)

        self.title = QLabel("")
        self.title.setProperty("role", "heading")
        f = self.title.font()
        f.setPointSize(15)
        f.setBold(True)
        self.title.setFont(f)
        lay.addWidget(self.title)

        self.score_label = QLabel("")
        lay.addWidget(self.score_label)

        missed = QLabel("MISSED:")
        missed.setProperty("role", "dim")
        lay.addWidget(missed)

        self.missed_list = QListWidget()
        self.missed_list.setWordWrap(True)
        self.missed_list.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        self.missed_list.setFocusPolicy(Qt.NoFocus)
        lay.addWidget(self.missed_list, 1)

        self.clean_label = QLabel("CLEAN ROUND - NOTHING MISSED.")
        self.clean_label.setProperty("role", "body")
        self.clean_label.setVisible(False)
        lay.addWidget(self.clean_label)

        row = QHBoxLayout()
        self.again_btn = QPushButton("[ R ] REPLAY")
        self.home_btn = QPushButton("[ B ] BACK TO HOME")
        self.again_btn.clicked.connect(controller.drill_play_again)
        self.home_btn.clicked.connect(controller.go_home)
        row.addWidget(self.again_btn)
        row.addStretch(1)
        row.addWidget(self.home_btn)
        lay.addLayout(row)

    def update(self, results):
        self.title.setText("%s SESSION COMPLETE" % self.controller.drill_mod.TITLE)
        total = len(results)
        score = sum(1 for _, ok, _ in results if ok)
        pct = 100.0 * score / total if total else 0.0
        self.score_label.setText("SCORE %02d/%02d    ACCURACY %3d%%"
                                 % (score, total, round(pct)))

        missed = [(it, ca) for it, ok, ca in results if not ok]
        self.missed_list.clear()
        if missed:
            self.clean_label.setVisible(False)
            self.missed_list.setVisible(True)
            for it, ca in missed:
                self.missed_list.addItem(
                    QListWidgetItem("%s  ->  %s" % (it["prompt"], ca)))
        else:
            self.clean_label.setVisible(True)
            self.missed_list.setVisible(False)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_R:
            self.controller.drill_play_again()
            event.accept()
            return
        if key == Qt.Key_B:
            self.controller.go_home()
            event.accept()
            return
        super().keyPressEvent(event)


# ---------------------------------------------------------------- main window

class QuizWindow(QMainWindow):
    def __init__(self, bank, stats, stats_path, rng, animate=True):
        super().__init__()
        self.bank = bank
        self.stats = stats
        self.stats_path = stats_path
        self.rng = rng
        self.animate = animate
        self.acronyms, self.acronyms_error = acronyms.load_table_or_error()
        self.crypto, self.crypto_error = crypto.load_table_or_error()

        self.order = []
        self.results = []
        self.score = 0
        self.round_index = 0
        self.mode = None
        self.drill_domains = None
        self.drill_length = None

        # Generic drill state — the active module (acronyms or crypto) and its
        # round bookkeeping. Both drills share this one code path.
        self.drill_mod = None
        self.drill_direction = None
        self.drill_length = None
        self.drill_order = []
        self.drill_results = []
        self.drill_score = 0
        self.drill_index = 0

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(ICON_PATH))
        self.resize(640, 460)
        self.setMinimumSize(560, 420)

        self.stack = QStackedWidget()
        self.content_area = QWidget()
        cl = QVBoxLayout(self.content_area)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self.stack)
        self.setCentralWidget(self.content_area)

        self.home_widget = HomeWidget(self)
        self.drill_widget = DrillSetupWidget(self)
        self.acronym_setup_widget = DrillModeSetupWidget(
            self, acronyms, "ACRONYM DRILL", self.start_acronym_drill)
        self.crypto_setup_widget = DrillModeSetupWidget(
            self, crypto, "CRYPTO & CONTROLS DRILL", self.start_crypto_drill)
        self.question_widget = QuestionWidget(self.rng, self)
        self.drill_question_widget = DrillQuestionWidget(self.rng, self)
        self.summary_widget = SummaryWidget(self)
        self.drill_summary_widget = DrillSummaryWidget(self)
        self.stats_widget = StatsWidget(self)

        for w in (self.home_widget, self.drill_widget,
                  self.acronym_setup_widget, self.crypto_setup_widget,
                  self.question_widget, self.drill_question_widget,
                  self.summary_widget, self.drill_summary_widget,
                  self.stats_widget):
            self.stack.addWidget(w)

        self.question_widget.answered_signal.connect(self._on_answered)
        self.question_widget.advance_signal.connect(self._on_next)
        self.question_widget.go_home.connect(self.go_home)

        self.drill_question_widget.answered_signal.connect(
            self._on_drill_answered)
        self.drill_question_widget.advance_signal.connect(self._on_drill_next)
        self.drill_question_widget.go_home.connect(self.go_home)

        # CRT scanlines overlay drawn on top of the content area.
        self.scanlines = ScanlineOverlay(self.content_area)
        self.scanlines.setGeometry(self.content_area.rect())
        self.scanlines.raise_()
        self.scanlines.setVisible(True)

        self.home_widget.status.set_status(self._status() + " [ MODE:STANDBY ]")

        self._center_on_screen()

    def _status(self):
        return "[ SYS:SY0-701 ] [ BANK:%d ]" % len(self.bank)

    def _round_status(self):
        total = len(self.order) if self.order else 0
        return "%s [ SCORE:%02d/%d ] [ STREAK:%d ]" % (
            self._status(), self.score, total, self.stats["current_streak"])

    def _center_on_screen(self):
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            frame = self.frameGeometry()
            frame.moveCenter(geo.center())
            self.move(frame.topLeft())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.scanlines.setGeometry(self.content_area.rect())
        self.scanlines.raise_()

    def showEvent(self, event):
        super().showEvent(event)
        self.scanlines.setGeometry(self.content_area.rect())
        self.scanlines.raise_()

    def set_scanlines(self, on):
        self.scanlines.setVisible(on)
        self.scanlines.raise_()

    # ----- navigation -----

    def go_home(self):
        self.home_widget.status.set_status(self._status() + " [ MODE:STANDBY ]")
        self.stack.setCurrentWidget(self.home_widget)
        self.home_widget.setFocus()

    def show_drill(self):
        self.drill_widget.status.set_status(self._status() + " [ MODE:DRILL ]")
        self.stack.setCurrentWidget(self.drill_widget)
        self.drill_widget.setFocus()

    def _show_drill_setup(self, mod, setup_widget, table, error, mode_label):
        if table is None:
            QMessageBox.warning(self, APP_NAME, error or "%s unavailable" % mode_label)
            return
        setup_widget.status.set_status(self._status() + " [ MODE:%s ]" % mode_label)
        self.stack.setCurrentWidget(setup_widget)
        setup_widget.setFocus()

    def show_acronym_drill(self):
        self._show_drill_setup(acronyms, self.acronym_setup_widget,
                               self.acronyms, self.acronyms_error,
                               "ACRONYM DRILL")

    def show_crypto_drill(self):
        self._show_drill_setup(crypto, self.crypto_setup_widget,
                               self.crypto, self.crypto_error, "CRYPTO & CONTROLS DRILL")

    def show_stats(self):
        self.stats_widget.status.set_status(self._status() + " [ MODE:STATS ]")
        self.stats_widget.update(self.stats)
        self.stack.setCurrentWidget(self.stats_widget)
        self.stats_widget.setFocus()

    # ----- round start -----

    def start_quick(self):
        qs = quiz.select_quick(self.bank, self.rng)
        self.start_round(qs, "quick")

    def start_drill(self):
        domains = self.drill_widget.selected_domains()
        if not domains:
            QMessageBox.warning(self, APP_NAME, "Select at least one domain.")
            return
        length = self.drill_widget.selected_length()
        qs = quiz.select_drill(self.bank, self.rng, domains, length)
        if not qs:
            QMessageBox.warning(self, APP_NAME, "No questions match that selection.")
            return
        self.start_round(qs, "drill", domains, length)

    def start_review(self):
        qs = quiz.select_review(self.bank, self.stats)
        if not qs:
            QMessageBox.information(
                self, APP_NAME,
                "Nothing to review - you have no missed questions yet.")
            return
        self.start_round(qs, "review")

    def review_from_summary(self):
        self.start_review()

    def play_again(self):
        if self.mode == "quick":
            self.start_quick()
        elif self.mode == "drill":
            qs = quiz.select_drill(self.bank, self.rng,
                                   self.drill_domains, self.drill_length)
            if qs:
                self.start_round(qs, "drill", self.drill_domains,
                                 self.drill_length)
        elif self.mode == "review":
            self.start_review()

    def start_round(self, questions, mode, domains=None, length=None):
        self.mode = mode
        self.drill_domains = domains
        self.drill_length = length
        self.order = list(questions)
        self.rng.shuffle(self.order)
        self.results = []
        self.score = 0
        self.round_index = 0
        self._show_current_question()
        self.question_widget.status.set_status(self._round_status())
        self.stack.setCurrentWidget(self.question_widget)
        self.question_widget.setFocus()

    # ----- round flow -----

    def _show_current_question(self):
        q = self.order[self.round_index]
        self.question_widget.show_question(q, self.round_index + 1,
                                           len(self.order))

    def _on_answered(self, q, correct):
        self.results.append((q, correct))
        if correct:
            self.score += 1
        quiz.record_answer(self.stats, q, correct)
        quiz.save_stats(self.stats, self.stats_path)
        self.question_widget.status.set_status(self._round_status())

    def _on_next(self):
        self.round_index += 1
        if self.round_index < len(self.order):
            self._show_current_question()
            self.question_widget.setFocus()
        else:
            self._show_summary()

    def _show_summary(self):
        self.summary_widget.status.set_status(self._round_status())
        self.summary_widget.update(self.results)
        self.stack.setCurrentWidget(self.summary_widget)
        self.summary_widget.setFocus()

    # ----- drill round flow -----

    def _drill_round_status(self):
        total = len(self.drill_order) if self.drill_order else 0
        return "%s [ SCORE:%02d/%d ]" % (self._status(), self.drill_score, total)

    def start_acronym_drill(self):
        if self.acronyms is None:
            QMessageBox.warning(self, APP_NAME,
                                self.acronyms_error or "acronym table unavailable")
            return
        self._start_drill_setup_round(acronyms, self.acronyms,
                                      self.acronym_setup_widget)

    def start_crypto_drill(self):
        if self.crypto is None:
            QMessageBox.warning(self, APP_NAME,
                                self.crypto_error or "crypto table unavailable")
            return
        self._start_drill_setup_round(crypto, self.crypto,
                                      self.crypto_setup_widget)

    def _start_drill_setup_round(self, mod, table, setup_widget):
        direction = setup_widget.selected_direction()
        length = setup_widget.selected_length()
        pool = mod.build_items(table, direction)
        items = mod.select_items(pool, self.rng, length)
        if not items:
            QMessageBox.warning(self, APP_NAME, "No drill items to drill.")
            return
        self.start_drill_round(mod, items, direction, length)

    def start_review_acronyms(self):
        if self.acronyms is None:
            QMessageBox.warning(self, APP_NAME,
                                self.acronyms_error or "acronym table unavailable")
            return
        self._start_review_drill(acronyms, self.acronyms, "acronyms")

    def start_review_crypto(self):
        if self.crypto is None:
            QMessageBox.warning(self, APP_NAME,
                                self.crypto_error or "crypto table unavailable")
            return
        self._start_review_drill(crypto, self.crypto, "crypto")

    def _start_review_drill(self, mod, table, label):
        items = quiz.select_review_drill(mod, table, self.stats)
        if not items:
            QMessageBox.information(
                self, APP_NAME,
                "Nothing to review - you have no missed %s yet." % label)
            return
        self.start_drill_round(mod, items, mod.DIR_MIXED)

    def start_drill_round(self, mod, items, direction, length=None):
        self.drill_mod = mod
        self.drill_direction = direction
        self.drill_length = length
        self.drill_order = list(items)
        self.rng.shuffle(self.drill_order)
        self.drill_results = []
        self.drill_score = 0
        self.drill_index = 0
        self._show_current_drill_item()
        self.drill_question_widget.status.set_status(self._drill_round_status())
        self.stack.setCurrentWidget(self.drill_question_widget)
        self.drill_question_widget.setFocus()

    def _show_current_drill_item(self):
        item = self.drill_order[self.drill_index]
        self.drill_question_widget.show_item(item, self.drill_index + 1,
                                             len(self.drill_order))

    def _on_drill_answered(self, item, correct, correct_answer):
        self.drill_results.append((item, correct, correct_answer))
        if correct:
            self.drill_score += 1
        self.drill_mod.record_answer(self.stats, item["id"], correct)
        quiz.save_stats(self.stats, self.stats_path)
        self.drill_question_widget.status.set_status(self._drill_round_status())

    def _on_drill_next(self):
        self.drill_index += 1
        if self.drill_index < len(self.drill_order):
            self._show_current_drill_item()
            self.drill_question_widget.setFocus()
        else:
            self._show_drill_summary()

    def _show_drill_summary(self):
        self.drill_summary_widget.status.set_status(self._drill_round_status())
        self.drill_summary_widget.update(self.drill_results)
        self.stack.setCurrentWidget(self.drill_summary_widget)
        self.drill_summary_widget.setFocus()

    def drill_play_again(self):
        if self.drill_mod is None or self.drill_direction is None:
            self.go_home()
            return
        mod = self.drill_mod
        table = self.acronyms if mod is acronyms else self.crypto
        pool = mod.build_items(table, self.drill_direction)
        items = mod.select_items(pool, self.rng, self.drill_length)
        if items:
            self.start_drill_round(mod, items, self.drill_direction,
                                   self.drill_length)

    # ----- keyboard shortcuts for non-question screens -----

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Escape:
            if self.stack.currentWidget() is not self.home_widget:
                self.go_home()
                event.accept()
                return
        if self.stack.currentWidget() is self.home_widget:
            if key == Qt.Key_S:
                cb = self.home_widget.scan_cb
                cb.setChecked(not cb.isChecked())
                event.accept()
                return
            num_map = {Qt.Key_1: 0, Qt.Key_2: 1, Qt.Key_3: 2, Qt.Key_4: 3,
                       Qt.Key_5: 4, Qt.Key_6: 5, Qt.Key_7: 6, Qt.Key_8: 7,
                       Qt.Key_9: 8}
            if key in num_map:
                self.home_widget.buttons[num_map[key]].click()
                event.accept()
                return
        super().keyPressEvent(event)


# ---------------------------------------------------------------- selftest

def run_selftest(args):
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    tmp_stats = None
    if args.stats is None:
        fd, tmp_stats = tempfile.mkstemp(prefix="secplus-gui-selftest-",
                                         suffix=".json")
        os.close(fd)
        stats_path = tmp_stats
    else:
        stats_path = args.stats

    try:
        app = QApplication([sys.argv[0]])
        app.setApplicationName(APP_NAME)
        app.setDesktopFileName(DESKTOP_FILE)
        apply_theme(app)

        bank, err = load_bank_gui(args.bank)
        if err:
            print("SELFTEST FAIL: %s" % err)
            return 1

        stats = quiz.load_stats(stats_path)
        rng = random.Random(args.seed if args.seed is not None else 42)
        win = QuizWindow(bank, stats, stats_path, rng, animate=False)
        win.show()
        app.processEvents()

        win.start_quick()
        if not win.order:
            print("SELFTEST FAIL: no questions selected")
            return 1

        total = len(win.order)
        for idx in range(total):
            app.processEvents()
            qw = win.question_widget
            correct_key = qw.correct_display_key
            if (idx + 1) % 2 == 1:
                chosen = correct_key
            else:
                chosen = next(k for k in qw.display_keys if k != correct_key)
            qw.option_buttons[qw.display_keys.index(chosen)].click()
            app.processEvents()
            qw.next_button.click()
            app.processEvents()

        score = win.score
        tally = {}
        for q, ok in win.results:
            a = tally.setdefault(q["domain"], [0, 0])
            a[1] += 1
            if ok:
                a[0] += 1

        print("SELF-TEST (scripted 10-question round, seed=%d)"
              % (args.seed if args.seed is not None else 42))
        print("Questions driven: %d" % total)
        print("Final score: %d/%d (%.0f%%)" % (score, total, 100.0 * score / total))
        print("Per-domain tally:")
        for d in sorted(tally):
            c, t = tally[d]
            print("  Domain %d (%s): %d/%d" % (d, quiz.DOMAIN_NAMES[d], c, t))

        # Acronym + crypto drills: scripted mixed round (10 items) through the
        # real answer handler (free-text input -> grade -> stats).
        for mod, table, err in ((acronyms, win.acronyms, win.acronyms_error),
                                (crypto, win.crypto, win.crypto_error)):
            if table is None:
                print("SELFTEST FAIL: %s" % (err or "%s table unavailable" % mod.TITLE))
                return 1
            pool = mod.build_items(table, mod.DIR_MIXED)
            items = mod.select_items(pool, rng, 10)
            win.start_drill_round(mod, items, mod.DIR_MIXED, 10)
            n = len(win.drill_order)
            for idx in range(n):
                app.processEvents()
                dw = win.drill_question_widget
                item = dw.item
                chosen = (item["answer"] if (idx + 1) % 2 == 1
                          else "zzz-not-a-real-answer")
                dw.input.setText(chosen)
                dw.submit()
                app.processEvents()
                dw.next_button.click()
                app.processEvents()
            print("%s driven: %d items" % (mod.TITLE, n))
            print("%s score: %d/%d (%.0f%%)"
                  % (mod.TITLE, win.drill_score, n,
                     100.0 * win.drill_score / n))

        # Review drills: drill ONLY the missed ids, then verify a fully-correct
        # round clears them without touching the question-level missed_ids.
        before_q_missed = list(stats["missed_ids"])
        for mod, table, err in ((acronyms, win.acronyms, win.acronyms_error),
                                (crypto, win.crypto, win.crypto_error)):
            bucket = stats[mod.STATS_KEY]
            if not bucket["missed_ids"]:
                bucket["missed_ids"] = [e["id"] for e in table[:2]]
                quiz.save_stats(stats, stats_path)
            before = set(bucket["missed_ids"])
            if mod is acronyms:
                win.start_review_acronyms()
            else:
                win.start_review_crypto()
            rn = len(win.drill_order)
            r_ids = [it["id"] for it in win.drill_order]
            if not r_ids or any(i not in before for i in r_ids):
                print("SELFTEST FAIL: %s review drew outside missed_ids" % mod.STATS_KEY)
                return 1
            for idx in range(rn):
                app.processEvents()
                dw = win.drill_question_widget
                dw.input.setText(dw.item["answer"])
                dw.submit()
                app.processEvents()
                dw.next_button.click()
                app.processEvents()
            after = set(bucket["missed_ids"])
            remaining = after & set(r_ids)
            if remaining:
                print("SELFTEST FAIL: %s review left ids missed: %s"
                      % (mod.STATS_KEY, sorted(remaining)))
                return 1
            if stats["missed_ids"] != before_q_missed:
                print("SELFTEST FAIL: %s review mutated question missed_ids" % mod.STATS_KEY)
                return 1
            print("%s review cleared: %d missed ids" % (mod.STATS_KEY, len(before)))

        if os.path.exists(stats_path):
            try:
                with open(stats_path, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError) as e:
                print("SELFTEST FAIL: stats unreadable: %s" % e)
                return 1
            lt = data.get("lifetime", {})
            a = data.get("acronyms", {})
            c = data.get("crypto", {})
            print("stats written: lifetime correct=%s total=%s"
                  % (lt.get("correct"), lt.get("total")))
            print("acronyms stats: correct=%s total=%s"
                  % (a.get("correct"), a.get("total")))
            print("crypto stats: correct=%s total=%s"
                  % (c.get("correct"), c.get("total")))
            print("SELFTEST PASS")
            return 0

        print("SELFTEST FAIL: stats was not written")
        return 1
    finally:
        if tmp_stats is not None:
            try:
                os.remove(tmp_stats)
            except OSError:
                pass


# ---------------------------------------------------------------- screenshots

def run_screenshot(args):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

    outdir = args.screenshot
    try:
        os.makedirs(outdir, exist_ok=True)
    except OSError as e:
        print("SCREENSHOT FAIL: cannot create output dir: %s" % e)
        return 1

    app = QApplication([sys.argv[0]])
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName(DESKTOP_FILE)
    apply_theme(app)

    bank, err = load_bank_gui(args.bank)
    if err:
        print("SCREENSHOT FAIL: %s" % err)
        return 1

    fd, stats_path = tempfile.mkstemp(prefix="secplus-gui-screenshot-",
                                      suffix=".json")
    os.close(fd)

    written = []

    def shot(fname):
        app.processEvents()
        pm = win.content_area.grab()
        path = os.path.join(outdir, fname)
        if not pm.save(path, "PNG"):
            print("SCREENSHOT FAIL: could not write %s" % path)
            return False
        size = os.path.getsize(path)
        if size <= 0:
            print("SCREENSHOT FAIL: empty file %s" % path)
            return False
        written.append((path, size))
        return True

    ok = True
    try:
        stats = quiz.load_stats(stats_path)
        rng = random.Random(args.seed if args.seed is not None else 42)
        win = QuizWindow(bank, stats, stats_path, rng, animate=False)
        win.show()
        app.processEvents()

        # 01 — home screen with all nine buttons.
        win.go_home()
        ok = shot("01-home.png") and ok

        # 02 — domain drill setup (check all domains so the selection is visible).
        win.show_drill()
        win.drill_widget.all_cb.setChecked(True)
        ok = shot("02-drill.png") and ok

        # 03 — acronym drill setup.
        win.show_acronym_drill()
        ok = shot("03-acronym-setup.png") and ok

        # 04 — crypto drill setup.
        win.show_crypto_drill()
        ok = shot("04-crypto-setup.png") and ok

        # Start a deterministic quick round.
        win.start_quick()
        if not win.order:
            print("SCREENSHOT FAIL: no questions selected")
            return 1
        total = len(win.order)

        # 05 — unanswered question 1.
        ok = shot("05-question.png") and ok

        # 06 — correct answer feedback.
        qw = win.question_widget
        qw.option_buttons[qw.display_keys.index(qw.correct_display_key)].click()
        ok = shot("06-feedback-correct.png") and ok
        qw.next_button.click()

        # 07 — wrong answer feedback.
        qw = win.question_widget
        wrong_key = next(k for k in qw.display_keys if k != qw.correct_display_key)
        qw.option_buttons[qw.display_keys.index(wrong_key)].click()
        ok = shot("07-feedback-wrong.png") and ok
        qw.next_button.click()

        # Drive the rest of the round so the summary is a genuine final state.
        for _ in range(2, total):
            qw = win.question_widget
            qw.option_buttons[qw.display_keys.index(qw.correct_display_key)].click()
            qw.next_button.click()

        # 08 — end-of-round summary.
        ok = shot("08-summary.png") and ok

        # 09 — stats screen with non-zero data accumulated by the round above.
        win.show_stats()
        ok = shot("09-stats.png") and ok

        # Acronym drill (deterministic mixed round, 10 items).
        pool = acronyms.build_items(win.acronyms, acronyms.DIR_MIXED)
        a_items = acronyms.select_items(pool, rng, 10)
        win.start_drill_round(acronyms, a_items, acronyms.DIR_MIXED, 10)
        ok = shot("10-acronym-question.png") and ok
        dw = win.drill_question_widget
        dw.input.setText(dw.item["answer"])
        dw.submit()
        ok = shot("11-acronym-feedback.png") and ok
        dw.next_button.click()
        for _ in range(1, len(a_items)):
            dw = win.drill_question_widget
            dw.input.setText(dw.item["answer"])
            dw.submit()
            dw.next_button.click()
        ok = shot("12-acronym-summary.png") and ok

        # Crypto drill (deterministic mixed round, 10 items).
        pool = crypto.build_items(win.crypto, crypto.DIR_MIXED)
        c_items = crypto.select_items(pool, rng, 10)
        win.start_drill_round(crypto, c_items, crypto.DIR_MIXED, 10)
        ok = shot("13-crypto-question.png") and ok
        dw = win.drill_question_widget
        dw.input.setText(dw.item["answer"])
        dw.submit()
        ok = shot("14-crypto-feedback.png") and ok
        dw.next_button.click()
        for _ in range(1, len(c_items)):
            dw = win.drill_question_widget
            dw.input.setText(dw.item["answer"])
            dw.submit()
            dw.next_button.click()
        ok = shot("15-crypto-summary.png") and ok

        if not ok:
            return 1

        for path, size in written:
            print("%s  %d bytes" % (path, size))
        print("SCREENSHOT COMPLETE: %d images" % len(written))
        return 0
    finally:
        try:
            os.remove(stats_path)
        except OSError:
            pass


# ---------------------------------------------------------------- entrypoint

def main(argv=None):
    ap = argparse.ArgumentParser(description="Security+ (SY0-701) quiz - GUI")
    ap.add_argument("--bank", default=DEFAULT_BANK)
    ap.add_argument("--stats", default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--screenshot", metavar="DIR", default=None)
    args = ap.parse_args(argv)

    if args.selftest:
        return run_selftest(args)
    if args.screenshot:
        return run_screenshot(args)

    app = QApplication([sys.argv[0]])
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName(DESKTOP_FILE)
    app.setWindowIcon(QIcon(ICON_PATH))
    apply_theme(app)

    bank, err = load_bank_gui(args.bank)
    if err:
        QMessageBox.critical(None, APP_NAME, err)
        return 1

    stats_path = args.stats or DEFAULT_STATS
    stats = quiz.load_stats(stats_path)
    rng = random.Random(args.seed)
    win = QuizWindow(bank, stats, stats_path, rng, animate=True)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

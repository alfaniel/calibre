#!/usr/bin/env python
# vim:fileencoding=utf-8
from __future__ import (unicode_literals, division, absolute_import,
                        print_function)

__license__ = 'GPL v3'
__copyright__ = '2013, Kovid Goyal <kovid at kovidgoyal.net>'

import textwrap
from future_builtins import map

import regex
from PyQt4.Qt import (
    QPlainTextEdit, QFontDatabase, QToolTip, QPalette, QFont,
    QTextEdit, QTextFormat, QWidget, QSize, QPainter, Qt, QRect)

from calibre.gui2.tweak_book import tprefs
from calibre.gui2.tweak_book.editor import SYNTAX_PROPERTY
from calibre.gui2.tweak_book.editor.themes import THEMES, default_theme, theme_color
from calibre.gui2.tweak_book.editor.syntax.base import SyntaxHighlighter
from calibre.gui2.tweak_book.editor.syntax.html import HTMLHighlighter, XMLHighlighter
from calibre.gui2.tweak_book.editor.syntax.css import CSSHighlighter

PARAGRAPH_SEPARATOR = '\u2029'

_dff = None
def default_font_family():
    global _dff
    if _dff is None:
        families = set(map(unicode, QFontDatabase().families()))
        for x in ('Ubuntu Mono', 'Consolas', 'Liberation Mono'):
            if x in families:
                _dff = x
                break
        if _dff is None:
            _dff = 'Courier New'
    return _dff

class LineNumbers(QWidget):  # {{{

    def __init__(self, parent):
        QWidget.__init__(self, parent)

    def sizeHint(self):
        return QSize(self.parent().line_number_area_width(), 0)

    def paintEvent(self, ev):
        self.parent().paint_line_numbers(ev)
# }}}

class TextEdit(QPlainTextEdit):

    def __init__(self, parent=None):
        QPlainTextEdit.__init__(self, parent)
        self.current_cursor_line = None
        self.current_search_mark = None
        self.highlighter = SyntaxHighlighter(self)
        self.apply_settings()
        self.setMouseTracking(True)
        self.cursorPositionChanged.connect(self.highlight_cursor_line)
        self.blockCountChanged[int].connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.line_number_area = LineNumbers(self)

    @dynamic_property
    def is_modified(self):
        ''' True if the document has been modified since it was loaded or since
        the last time is_modified was set to False. '''
        def fget(self):
            return self.document().isModified()
        def fset(self, val):
            self.document().setModified(bool(val))
        return property(fget=fget, fset=fset)

    @property
    def selected_text(self):
        return unicode(self.textCursor().selectedText())

    def sizeHint(self):
        return self.size_hint

    def apply_settings(self, prefs=None):  # {{{
        prefs = prefs or tprefs
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth if prefs['editor_line_wrap'] else QPlainTextEdit.NoWrap)
        theme = THEMES.get(prefs['editor_theme'], None)
        if theme is None:
            theme = THEMES[default_theme()]
        self.apply_theme(theme)

    def apply_theme(self, theme):
        self.theme = theme
        pal = self.palette()
        pal.setColor(pal.Base, theme_color(theme, 'Normal', 'bg'))
        pal.setColor(pal.AlternateBase, theme_color(theme, 'CursorLine', 'bg'))
        pal.setColor(pal.Text, theme_color(theme, 'Normal', 'fg'))
        pal.setColor(pal.Highlight, theme_color(theme, 'Visual', 'bg'))
        pal.setColor(pal.HighlightedText, theme_color(theme, 'Visual', 'fg'))
        self.setPalette(pal)
        self.tooltip_palette = pal = QPalette()
        pal.setColor(pal.ToolTipBase, theme_color(theme, 'Tooltip', 'bg'))
        pal.setColor(pal.ToolTipText, theme_color(theme, 'Tooltip', 'fg'))
        self.line_number_palette = pal = QPalette()
        pal.setColor(pal.Base, theme_color(theme, 'LineNr', 'bg'))
        pal.setColor(pal.Text, theme_color(theme, 'LineNr', 'fg'))
        pal.setColor(pal.BrightText, theme_color(theme, 'LineNrC', 'fg'))
        font = self.font()
        ff = tprefs['editor_font_family']
        if ff is None:
            ff = default_font_family()
        font.setFamily(ff)
        font.setPointSize(tprefs['editor_font_size'])
        self.tooltip_font = QFont(font)
        self.tooltip_font.setPointSize(font.pointSize() - 1)
        self.setFont(font)
        self.highlighter.apply_theme(theme)
        w = self.fontMetrics()
        self.number_width = max(map(lambda x:w.width(str(x)), xrange(10)))
        self.size_hint = QSize(100 * w.averageCharWidth(), 50 * w.height())
        self.highlight_color = theme_color(theme, 'HighlightRegion', 'bg')
    # }}}

    def load_text(self, text, syntax='html', process_template=False):
        self.highlighter = {'html':HTMLHighlighter, 'css':CSSHighlighter, 'xml':XMLHighlighter}.get(syntax, SyntaxHighlighter)(self)
        self.highlighter.apply_theme(self.theme)
        self.highlighter.setDocument(self.document())
        self.setPlainText(text)
        if process_template and QPlainTextEdit.find(self, '%CURSOR%'):
            c = self.textCursor()
            c.insertText('')

    def replace_text(self, text):
        c = self.textCursor()
        pos = c.position()
        c.beginEditBlock()
        c.clearSelection()
        c.select(c.Document)
        c.insertText(text)
        c.endEditBlock()
        c.setPosition(min(pos, len(text)))
        self.setTextCursor(c)
        self.ensureCursorVisible()

    def go_to_line(self, lnum):
        lnum = max(1, min(self.blockCount(), lnum))
        c = self.textCursor()
        c.clearSelection()
        c.movePosition(c.Start)
        c.movePosition(c.NextBlock, n=lnum - 1)
        c.movePosition(c.StartOfLine)
        c.movePosition(c.EndOfLine, c.KeepAnchor)
        text = unicode(c.selectedText())
        c.movePosition(c.StartOfLine)
        lt = text.lstrip()
        if text and lt and lt != text:
            c.movePosition(c.NextWord)
        self.setTextCursor(c)
        self.ensureCursorVisible()

    def update_extra_selections(self):
        sel = []
        if self.current_cursor_line is not None:
            sel.append(self.current_cursor_line)
        if self.current_search_mark is not None:
            sel.append(self.current_search_mark)
        self.setExtraSelections(sel)

    def fix_html(self):
        from calibre.ebooks.oeb.polish.pretty import fix_html
        self.replace_text(fix_html(unicode(self.toPlainText())).decode('utf-8'))

    # Search and replace {{{
    def mark_selected_text(self):
        sel = QTextEdit.ExtraSelection()
        sel.format.setBackground(self.highlight_color)
        sel.cursor = self.textCursor()
        if sel.cursor.hasSelection():
            self.current_search_mark = sel
            c = self.textCursor()
            c.clearSelection()
            self.setTextCursor(c)
        else:
            self.current_search_mark = None
        self.update_extra_selections()

    def find_in_marked(self, pat, wrap=False):
        if self.current_search_mark is None:
            return False
        csm = self.current_search_mark.cursor
        reverse = pat.flags & regex.REVERSE
        c = self.textCursor()
        c.clearSelection()
        m_start = min(csm.position(), csm.anchor())
        m_end = max(csm.position(), csm.anchor())
        if c.position() < m_start:
            c.setPosition(m_start)
        if c.position() > m_end:
            c.setPosition(m_end)
        pos = m_start if reverse else m_end
        if wrap:
            pos = m_end if reverse else m_start
        c.setPosition(pos, c.KeepAnchor)
        raw = unicode(c.selectedText()).replace(PARAGRAPH_SEPARATOR, '\n')
        m = pat.search(raw)
        if m is None:
            return False
        start, end = m.span()
        if start == end:
            return False
        if wrap:
            if reverse:
                textpos = c.anchor()
                start, end = textpos + end, textpos + start
            else:
                start, end = m_start + start, m_start + end
        else:
            if reverse:
                start, end = m_start + end, m_start + start
            else:
                start, end = c.anchor() + start, c.anchor() + end

        c.clearSelection()
        c.setPosition(start)
        c.setPosition(end, c.KeepAnchor)
        self.setTextCursor(c)
        return True

    def all_in_marked(self, pat, template=None):
        if self.current_search_mark is None:
            return 0
        c = self.current_search_mark.cursor
        raw = unicode(c.selectedText()).replace(PARAGRAPH_SEPARATOR, '\n')
        if template is None:
            count = len(pat.findall(raw))
        else:
            raw, count = pat.subn(template, raw)
            if count > 0:
                c.setKeepPositionOnInsert(True)
                c.insertText(raw)
                c.setKeepPositionOnInsert(False)
                self.update_extra_selections()
        return count

    def find(self, pat, wrap=False, marked=False, complete=False):
        if marked:
            return self.find_in_marked(pat, wrap=wrap)
        reverse = pat.flags & regex.REVERSE
        c = self.textCursor()
        c.clearSelection()
        if complete:
            # Search the entire text
            c.movePosition(c.End if reverse else c.Start)
        pos = c.Start if reverse else c.End
        if wrap and not complete:
            pos = c.End if reverse else c.Start
        c.movePosition(pos, c.KeepAnchor)
        raw = unicode(c.selectedText()).replace(PARAGRAPH_SEPARATOR, '\n')
        m = pat.search(raw)
        if m is None:
            return False
        start, end = m.span()
        if start == end:
            return False
        if wrap and not complete:
            if reverse:
                textpos = c.anchor()
                start, end = textpos + end, textpos + start
        else:
            if reverse:
                # Put the cursor at the start of the match
                start, end = end, start
            else:
                textpos = c.anchor()
                start, end = textpos + start, textpos + end
        c.clearSelection()
        c.setPosition(start)
        c.setPosition(end, c.KeepAnchor)
        self.setTextCursor(c)
        return True

    def replace(self, pat, template):
        c = self.textCursor()
        raw = unicode(c.selectedText()).replace(PARAGRAPH_SEPARATOR, '\n')
        m = pat.fullmatch(raw)
        if m is None:
            return False
        text = m.expand(template)
        c.insertText(text)
        return True
    # }}}

    # Line numbers and cursor line {{{
    def highlight_cursor_line(self):
        sel = QTextEdit.ExtraSelection()
        sel.format.setBackground(self.palette().alternateBase())
        sel.format.setProperty(QTextFormat.FullWidthSelection, True)
        sel.cursor = self.textCursor()
        sel.cursor.clearSelection()
        self.current_cursor_line = sel
        self.update_extra_selections()
        # Update the cursor line's line number in the line number area
        try:
            self.line_number_area.update(0, self.last_current_lnum[0], self.line_number_area.width(), self.last_current_lnum[1])
        except AttributeError:
            pass
        block = self.textCursor().block()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        height = int(self.blockBoundingRect(block).height())
        self.line_number_area.update(0, top, self.line_number_area.width(), height)

    def update_line_number_area_width(self, block_count=0):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def line_number_area_width(self):
        digits = 1
        limit = max(1, self.blockCount())
        while limit >= 10:
            limit /= 10
            digits += 1

        return 8 + self.number_width * digits

    def update_line_number_area(self, rect, dy):
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width()

    def resizeEvent(self, ev):
        QPlainTextEdit.resizeEvent(self, ev)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def paint_line_numbers(self, ev):
        painter = QPainter(self.line_number_area)
        painter.fillRect(ev.rect(), self.line_number_palette.color(QPalette.Base))

        block = self.firstVisibleBlock()
        num = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        current = self.textCursor().block().blockNumber()
        painter.setPen(self.line_number_palette.color(QPalette.Text))

        while block.isValid() and top <= ev.rect().bottom():
            if block.isVisible() and bottom >= ev.rect().top():
                if current == num:
                    painter.save()
                    painter.setPen(self.line_number_palette.color(QPalette.BrightText))
                    f = QFont(self.font())
                    f.setBold(True)
                    painter.setFont(f)
                    self.last_current_lnum = (top, bottom - top)
                painter.drawText(0, top, self.line_number_area.width() - 5, self.fontMetrics().height(),
                              Qt.AlignRight, str(num + 1))
                if current == num:
                    painter.restore()
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            num += 1
    # }}}

    # Tooltips {{{
    def event(self, ev):
        if ev.type() == ev.ToolTip:
            self.show_tooltip(ev)
            return True
        return QPlainTextEdit.event(self, ev)

    def syntax_format_for_cursor(self, cursor):
        if cursor.isNull():
            return
        pos = cursor.positionInBlock()
        for r in cursor.block().layout().additionalFormats():
            if r.start <= pos < r.start + r.length and r.format.property(SYNTAX_PROPERTY).toBool():
                return r.format

    def show_tooltip(self, ev):
        c = self.cursorForPosition(ev.pos())
        fmt = self.syntax_format_for_cursor(c)
        if fmt is not None:
            tt = unicode(fmt.toolTip())
            if tt:
                QToolTip.setFont(self.tooltip_font)
                QToolTip.setPalette(self.tooltip_palette)
                QToolTip.showText(ev.globalPos(), textwrap.fill(tt))
        QToolTip.hideText()
        ev.ignore()
    # }}}


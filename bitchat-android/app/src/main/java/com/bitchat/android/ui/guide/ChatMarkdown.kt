package com.bitchat.android.ui.guide

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.ParagraphStyle
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextIndent
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp

/**
 * Small Markdown renderer for the disaster chatbot's answers (no extra dependency).
 *
 * The AI answers in Markdown. Shown as plain text, users saw the raw markers ("**Call 112**",
 * "- step"). This turns the parts the chatbot uses into real formatting:
 *   **bold**, __bold__, *italic*, _italic_, ~~strike~~, `code`, [text](link),
 *   # / ## / ### headings, - * + • bullets, 1. 1) numbered lists, > quotes, tables, --- rules.
 * Anything else stays as text, so nothing the AI writes is ever hidden.
 */
object ChatMarkdown {

    private val heading = Regex("""^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$""")
    private val bullet = Regex("""^(\s*)[-*+•]\s+(.*)$""")
    private val numbered = Regex("""^(\s*)(\d{1,3})[.)]\s+(.*)$""")
    private val quote = Regex("""^\s*>\s?(.*)$""")
    private val rule = Regex("""^\s*([-*_])(\s*\1){2,}\s*$""")
    private val tableSep = Regex("""^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$""")

    fun render(markdown: String, codeBackground: Color = Color(0x22888888)): AnnotatedString {
        val lines = markdown.replace("\r\n", "\n").split("\n")
        return buildAnnotatedString {
            var first = true
            var blankPending = false
            for (raw in lines) {
                val line = raw.trimEnd()
                if (line.isBlank()) { blankPending = !first; continue }
                if (line.contains('|') && tableSep.matches(line)) continue   // table header divider: just drop it
                if (rule.matches(line)) { blankPending = !first; continue }  // --- rule: a gap between sections

                // one paragraph per source line; a blank line in the source = a little extra space
                val (indent, prefix, body, size, bold) = classify(line)
                if (!first) append("\n")
                if (blankPending) append("\n")
                blankPending = false
                first = false

                val para = if (prefix.isNotEmpty())
                    ParagraphStyle(textIndent = TextIndent(firstLine = (indent * 1.2).em, restLine = (indent * 1.2 + 1.2).em))
                else null
                if (para != null) pushStyle(para)
                if (size != null || bold) pushStyle(SpanStyle(fontWeight = FontWeight.Bold, fontSize = size ?: androidx.compose.ui.unit.TextUnit.Unspecified))
                append(prefix)
                appendInline(this, body, codeBackground)
                if (size != null || bold) pop()
                if (para != null) pop()
            }
        }
    }

    private data class Block(val indent: Int, val prefix: String, val body: String, val size: androidx.compose.ui.unit.TextUnit?, val bold: Boolean)

    private fun classify(line: String): Block {
        heading.matchEntire(line)?.let { m ->
            val level = m.groupValues[1].length
            return Block(0, "", m.groupValues[2], if (level <= 2) 15.sp else 14.sp, true)
        }
        numbered.matchEntire(line)?.let { m ->
            return Block(m.groupValues[1].length / 2, "${m.groupValues[2]}. ", m.groupValues[3], null, false)
        }
        bullet.matchEntire(line)?.let { m ->
            return Block(m.groupValues[1].length / 2, "•  ", m.groupValues[2], null, false)
        }
        quote.matchEntire(line)?.let { m -> return Block(0, "", m.groupValues[1], null, false) }
        if (line.trimStart().startsWith("|")) {
            // table row: "| a | b |" -> "a · b"
            val cells = line.trim().trim('|').split("|").map { it.trim() }.filter { it.isNotEmpty() }
            return Block(0, "", cells.joinToString("  ·  "), null, false)
        }
        return Block(0, "", line, null, false)
    }

    // order matters: ** before *, __ before _
    private val inline = listOf(
        Regex("""\*\*(.+?)\*\*""") to "b",
        Regex("""(?<![\w])__(.+?)__(?![\w])""") to "b",
        Regex("""~~(.+?)~~""") to "s",
        Regex("""`([^`]+)`""") to "c",
        Regex("""\[([^\]]+)]\((https?://[^)\s]+)\)""") to "l",
        Regex("""(?<![\w*])\*(?!\s)([^*]+?)(?<!\s)\*(?![\w*])""") to "i",
        Regex("""(?<![\w])_(?!\s)([^_]+?)(?<!\s)_(?![\w])""") to "i",
    )

    private fun appendInline(b: AnnotatedString.Builder, text: String, codeBg: Color) {
        var rest = text
        while (rest.isNotEmpty()) {
            // earliest marker wins (ties: the order above)
            var best: Pair<MatchResult, String>? = null
            for ((re, kind) in inline) {
                val m = re.find(rest) ?: continue
                if (best == null || m.range.first < best.first.range.first) best = m to kind
            }
            if (best == null) { b.append(unescape(rest)); return }
            val (m, kind) = best
            b.append(unescape(rest.substring(0, m.range.first)))
            val inner = m.groupValues[1]
            when (kind) {
                "b" -> { b.pushStyle(SpanStyle(fontWeight = FontWeight.Bold)); appendInline(b, inner, codeBg); b.pop() }
                "i" -> { b.pushStyle(SpanStyle(fontStyle = FontStyle.Italic)); appendInline(b, inner, codeBg); b.pop() }
                "s" -> { b.pushStyle(SpanStyle(textDecoration = TextDecoration.LineThrough)); appendInline(b, inner, codeBg); b.pop() }
                "c" -> { b.pushStyle(SpanStyle(fontFamily = FontFamily.Monospace, background = codeBg)); b.append(inner); b.pop() }
                "l" -> { b.pushStyle(SpanStyle(textDecoration = TextDecoration.Underline)); appendInline(b, inner, codeBg); b.pop() }
            }
            rest = rest.substring(m.range.last + 1)
        }
    }

    private fun unescape(s: String) = s.replace(Regex("""\\([\\`*_{}\[\]()#+\-.!>~|])"""), "$1")
}

package com.bitchat

import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import com.bitchat.android.ui.guide.ChatMarkdown
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ChatMarkdownTest {

    private fun boldTexts(md: String): List<String> {
        val s = ChatMarkdown.render(md)
        return s.spanStyles.filter { it.item.fontWeight == FontWeight.Bold }.map { s.text.substring(it.start, it.end) }
    }

    @Test
    fun boldMarkersAreRemovedAndTextIsBold() {
        val md = "**Call emergency services (112) immediately.** Then move to high ground."
        val s = ChatMarkdown.render(md)
        assertEquals("Call emergency services (112) immediately. Then move to high ground.", s.text)
        assertEquals(listOf("Call emergency services (112) immediately."), boldTexts(md))
    }

    @Test
    fun realChatbotAnswerHasNoMarkdownSymbolsLeft() {
        // shape of an actual answer from the server (Hindi + markdown)
        val md = """
            **सबसे पहले, 112 पर कॉल करें।**
            ⚠️ DANGER / WARNING: आग में फँसने पर तुरंत बाहर निकलें।

            1. **बाहर निकलें** – सीढ़ियों का इस्तेमाल करें।
            2. धुएँ से बचने के लिए *नीचे झुककर* चलें।
            - Bitchat में **SOS** भेजें
        """.trimIndent()
        val text = ChatMarkdown.render(md).text
        assertFalse("no ** left: $text", text.contains("**"))
        assertFalse("no stray * left: $text", text.contains("*"))
        assertTrue(text.contains("1. बाहर निकलें"))
        assertTrue(text.contains("•  Bitchat में SOS भेजें"))
        assertTrue(text.contains("112"))
    }

    @Test
    fun italicHeadingsCodeAndLinks() {
        val s = ChatMarkdown.render("## Flood safety\nStay *calm*, call `112`, see [guide](https://ndma.gov.in).")
        assertEquals("Flood safety\nStay calm, call 112, see guide.", s.text)
        val italic = s.spanStyles.filter { it.item.fontStyle == FontStyle.Italic }.map { s.text.substring(it.start, it.end) }
        assertEquals(listOf("calm"), italic)
        assertTrue(boldTexts("## Flood safety").contains("Flood safety"))
    }

    @Test
    fun bulletsWithStarsAreListsNotItalics() {
        val s = ChatMarkdown.render("* Turn off electricity\n* Go to the roof")
        assertEquals("•  Turn off electricity\n•  Go to the roof", s.text)
    }

    @Test
    fun plainTextAndUnderscoresInWordsAreLeftAlone() {
        val md = "Use 2*3 bottles; file_name stays; 5 * 4 = 20"
        assertEquals(md, ChatMarkdown.render(md).text)
    }

    @Test
    fun tablesAndRulesBecomeReadableText() {
        val s = ChatMarkdown.render("| Number | Service |\n|---|---|\n| 112 | All emergencies |\n---\nDone")
        assertEquals("Number  ·  Service\n112  ·  All emergencies\n\nDone", s.text)
    }

    @Test
    fun blankLinesBecomeOneEmptyLine() {
        assertEquals("A\n\nB", ChatMarkdown.render("A\n\n\n\nB").text)
    }
}

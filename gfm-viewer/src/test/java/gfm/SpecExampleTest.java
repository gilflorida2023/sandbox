package gfm;

import gfm.parser.*;
import org.junit.Test;
import static org.junit.Assert.*;

public class SpecExampleTest {

    private String render(String md) {
        BlockParser bp = new BlockParser();
        AstNode doc = bp.parse(md);
        HtmlRenderer hr = new HtmlRenderer();
        return hr.render(doc).stripTrailing();
    }

    @Test
    public void testThematicBreak() {
        assertEquals("<hr />", render("***").strip());
    }

    @Test
    public void testAtxHeading() {
        assertEquals("<h1>foo</h1>", render("# foo").strip());
        assertEquals("<h2>foo</h2>", render("## foo").strip());
        assertEquals("<h6>foo</h6>", render("###### foo").strip());
    }

    @Test
    public void testParagraph() {
        assertEquals("<p>hello world</p>", render("hello world").strip());
    }

    @Test
    public void testFencedCodeBlock() {
        String md = "```\ncode\n```";
        String html = render(md);
        assertTrue(html.contains("<pre><code>"));
        assertTrue(html.contains("code"));
    }

    @Test
    public void testBlockQuote() {
        String md = "> quote";
        String html = render(md);
        assertTrue(html.contains("<blockquote>"));
        assertTrue(html.contains("quote"));
    }

    @Test
    public void testInlineEmphasis() {
        String html = render("*em*");
        assertTrue(html.contains("<em>"));
        assertTrue(html.contains("</em>"));
    }

    @Test
    public void testInlineStrong() {
        String html = render("**strong**");
        assertTrue(html.contains("<strong>"));
        assertTrue(html.contains("</strong>"));
    }

    @Test
    public void testInlineCode() {
        String html = render("`code`");
        assertTrue(html.contains("<code>code</code>"));
    }

    @Test
    public void testLink() {
        String html = render("[text](http://example.com)");
        assertTrue(html.contains("<a href="));
        assertTrue(html.contains("http://example.com"));
        assertTrue(html.contains("text"));
    }

    @Test
    public void testImage() {
        String html = render("![alt](img.png)");
        assertTrue(html.contains("<img"));
        assertTrue(html.contains("img.png"));
        assertTrue(html.contains("alt"));
    }

    @Test
    public void testUnorderedList() {
        String html = render("- one\n- two\n- three");
        assertTrue(html.contains("<ul>"));
        assertTrue(html.contains("<li>"));
    }

    @Test
    public void testStrikethrough() {
        String html = render("~~strike~~");
        assertTrue(html.contains("<del>strike</del>"));
    }

    @Test
    public void testAutolink() {
        String html = render("<http://example.com>");
        assertTrue(html.contains("<a href="));
    }

    @Test
    public void testSetextHeading() {
        assertEquals("<h1>Foo</h1>", render("Foo\n===").strip());
    }

    @Test
    public void testThematicBreakVsSetext() {
        // "Foo\n---" should be a setext heading, not a paragraph + hr
        String html = render("Foo\n---").strip();
        assertTrue(html.startsWith("<h2>"));
    }
}

package gfm.parser;

import java.util.*;
import java.util.stream.*;

public class HtmlRenderer {
    private static final Set<String> VOID_TAGS = Set.of("br", "hr", "img", "input");

    public String render(AstNode node) {
        StringBuilder html = new StringBuilder();
        renderNode(node, html, 0);
        return html.toString();
    }

    private void renderNode(AstNode node, StringBuilder html, int indent) {
        switch (node.type) {
            case DOCUMENT -> {
                for (AstNode child : node.children) {
                    renderNode(child, html, indent);
                }
            }
            case PARAGRAPH -> {
                html.append("<p>");
                renderInlines(node, html);
                html.append("</p>\n");
            }
            case HEADING_1, HEADING_2, HEADING_3, HEADING_4, HEADING_5, HEADING_6 -> {
                int level = node.type.ordinal() - AstNode.Type.HEADING_1.ordinal() + 1;
                html.append("<h").append(level).append(">");
                if (node.literal != null) {
                    renderInlineString(node.literal, html);
                } else {
                    renderInlines(node, html);
                }
                html.append("</h").append(level).append(">\n");
            }
            case THEMATIC_BREAK -> html.append("<hr />\n");
            case CODE_BLOCK -> {
                html.append("<pre><code>");
                html.append(escapeHtml(node.literal != null ? node.literal : ""));
                html.append("</code></pre>\n");
            }
            case FENCED_CODE_BLOCK -> {
                String lang = node.info != null ? node.info.split("[ \\t]")[0] : "";
                html.append("<pre><code");
                if (!lang.isEmpty()) {
                    html.append(" class=\"language-").append(escapeHtmlAttr(lang)).append("\"");
                }
                html.append(">");
                html.append(escapeHtml(node.literal != null ? node.literal : ""));
                html.append("</code></pre>\n");
            }
            case HTML_BLOCK -> {
                html.append(node.literal != null ? node.literal : "");
                html.append("\n");
            }
            case BLOCK_QUOTE -> {
                html.append("<blockquote>\n");
                for (AstNode child : node.children) {
                    renderNode(child, html, indent + 1);
                }
                html.append("</blockquote>\n");
            }
            case LIST -> {
                boolean ordered = false;
                for (AstNode child : node.children) {
                    if (child.type == AstNode.Type.LIST_ITEM && child.literal != null) {
                        // Check first child's content for ordered marker
                    }
                }
                html.append("<ul>\n");
                for (AstNode child : node.children) {
                    renderNode(child, html, indent + 1);
                }
                html.append("</ul>\n");
            }
            case LIST_ITEM -> {
                html.append("<li");
                if (node.taskListItem) {
                    html.append(" class=\"task-list-item\"");
                }
                html.append(">");
                if (node.taskListItem) {
                    html.append("<input type=\"checkbox\"")
                         .append(node.taskChecked ? " checked=\"\" " : " disabled=\"\" ")
                         .append("/>");
                }
                if (node.literal != null) {
                    renderInlineString(node.literal, html);
                } else {
                    for (AstNode child : node.children) {
                        renderNode(child, html, indent + 1);
                    }
                }
                html.append("</li>\n");
            }
            case TABLE -> {
                html.append("<table>\n");
                for (AstNode child : node.children) {
                    renderNode(child, html, indent + 1);
                }
                html.append("</table>\n");
            }
            case TABLE_ROW -> html.append("<tr>\n");
            case TABLE_CELL -> html.append("<td>");
            // Inline types
            case TEXT -> html.append(escapeHtml(node.literal != null ? node.literal : ""));
            case CODE_SPAN -> html.append("<code>").append(escapeHtml(node.literal != null ? node.literal : "")).append("</code>");
            case EMPHASIS -> {
                html.append("<em>");
                renderInlines(node, html);
                html.append("</em>");
            }
            case STRONG_EMPHASIS -> {
                html.append("<strong>");
                renderInlines(node, html);
                html.append("</strong>");
            }
            case STRIKETHROUGH -> {
                html.append("<del>");
                renderInlines(node, html);
                html.append("</del>");
            }
            case LINK -> {
                html.append("<a href=\"").append(escapeHtmlAttr(node.destination != null ? node.destination : ""));
                if (node.title != null && !node.title.isEmpty()) {
                    html.append("\" title=\"").append(escapeHtmlAttr(node.title));
                }
                html.append("\">");
                if (!node.children.isEmpty()) {
                    renderInlines(node, html);
                } else if (node.literal != null) {
                    renderInlineString(node.literal, html);
                }
                html.append("</a>");
            }
            case IMAGE -> {
                html.append("<img src=\"").append(escapeHtmlAttr(node.destination != null ? node.destination : ""));
                html.append("\" alt=\"").append(escapeHtmlAttr(node.literal != null ? node.literal : ""));
                if (node.title != null && !node.title.isEmpty()) {
                    html.append("\" title=\"").append(escapeHtmlAttr(node.title));
                }
                html.append("\" />");
            }
            case HARD_LINE_BREAK -> html.append("<br />\n");
            case SOFT_LINE_BREAK -> html.append("\n");
            case RAW_HTML -> html.append(node.literal != null ? node.literal : "");
            case AUTOLINK -> {
                String url = node.destination != null ? node.destination : (node.literal != null ? node.literal : "");
                html.append("<a href=\"").append(escapeHtmlAttr(url)).append("\">")
                    .append(escapeHtml(node.literal != null ? node.literal : url))
                    .append("</a>");
            }
            case ESCAPED_CHAR -> html.append(escapeHtml(node.literal != null ? node.literal : ""));
            case ENTITY -> html.append(node.literal != null ? node.literal : "");
            default -> {
                if (node.literal != null) {
                    html.append(escapeHtml(node.literal));
                }
                renderInlines(node, html);
            }
        }
    }

    private void renderInlines(AstNode node, StringBuilder html) {
        if (node.literal != null) {
            renderInlineString(node.literal, html);
        }
        for (AstNode child : node.children) {
            renderNode(child, html, 0);
        }
    }

    private void renderInlineString(String text, StringBuilder html) {
        InlineParser ip = new InlineParser();
        List<AstNode> inlines = ip.parse(text);
        for (AstNode n : inlines) {
            renderNode(n, html, 0);
        }
    }

    private String escapeHtml(String text) {
        if (text == null) return "";
        return text.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace("\"", "&quot;");
    }

    private String escapeHtmlAttr(String text) {
        if (text == null) return "";
        return escapeHtml(text).replace("'", "&#39;");
    }
}

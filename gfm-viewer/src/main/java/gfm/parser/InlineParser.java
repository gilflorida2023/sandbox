package gfm.parser;

import java.util.*;
import java.util.regex.*;

public class InlineParser {
    private static final Pattern BACKSLASH_ESCAPE = Pattern.compile("\\\\([]!\"#$%&'()*+,\\-./:;<=>?@\\[\\\\^_`{|}~])");
    private static final Pattern ENTITY = Pattern.compile("&(?:#[xX][0-9a-fA-F]+|#[0-9]+|[a-zA-Z][a-zA-Z0-9]*);");
    private static final Pattern CODE_SPAN = Pattern.compile("(`+)(.+?)\\1(?!`)");
    private static final Pattern AUTOLINK = Pattern.compile("<([a-zA-Z][a-zA-Z0-9+.-]{1,31}:[^<>\\u0000-\\u0020]*)>");
    private static final Pattern EMAIL_AUTOLINK = Pattern.compile("<([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,})>");
    private static final Pattern HARD_BREAK = Pattern.compile("  \\n|\\\\\\n");

    // Emphasis patterns
    private static final String PUNCTUATION = "!\"#$%&'()*+,\\-./:;<=>?@\\[\\\\\\]^_`{|}~";
    private static final String NOT_SPACE = "[^ \\t\\n]";

    public List<AstNode> parse(String text) {
        List<AstNode> inlines = new ArrayList<>();
        parseInlines(text, inlines);
        return inlines;
    }

    private void parseInlines(String text, List<AstNode> result) {
        if (text == null || text.isEmpty()) return;
        int pos = 0;
        StringBuilder textBuf = new StringBuilder();

        while (pos < text.length()) {
            char c = text.charAt(pos);

            // Hard line break
            if (pos + 1 < text.length() && c == ' ' && text.charAt(pos + 1) == ' ') {
                textBuf.append(' ');
                pos++;
                continue;
            }
            if (c == ' ' && pos + 2 < text.length() && text.charAt(pos + 1) == ' ' && text.charAt(pos + 2) == '\n') {
                flushText(textBuf, result);
                result.add(new AstNode(AstNode.Type.HARD_LINE_BREAK));
                pos += 3;
                continue;
            }
            if (pos + 1 < text.length() && c == '\\' && text.charAt(pos + 1) == '\n') {
                flushText(textBuf, result);
                result.add(new AstNode(AstNode.Type.HARD_LINE_BREAK));
                pos += 2;
                continue;
            }

            // Soft line break
            if (c == '\n') {
                flushText(textBuf, result);
                result.add(new AstNode(AstNode.Type.SOFT_LINE_BREAK));
                pos++;
                continue;
            }

            // Backslash escape
            if (c == '\\' && pos + 1 < text.length()) {
                String pair = text.substring(pos, pos + 2);
                Matcher esc = BACKSLASH_ESCAPE.matcher(pair);
                if (esc.matches()) {
                    flushText(textBuf, result);
                    result.add(new AstNode(AstNode.Type.ESCAPED_CHAR, esc.group(1)));
                    pos += 2;
                    continue;
                }
            }

            // Code span
            if (c == '`') {
                Matcher code = CODE_SPAN.matcher(text.substring(pos));
                if (code.find() && code.start() == 0) {
                    flushText(textBuf, result);
                    result.add(new AstNode(AstNode.Type.CODE_SPAN, decodeEntities(code.group(2))));
                    pos += code.group(0).length();
                    continue;
                }
            }

            // Autolink
            if (c == '<') {
                Matcher al = AUTOLINK.matcher(text.substring(pos));
                if (al.find() && al.start() == 0) {
                    flushText(textBuf, result);
                    AstNode link = new AstNode(AstNode.Type.AUTOLINK, al.group(1));
                    link.destination = al.group(1);
                    result.add(link);
                    pos += al.group(0).length();
                    continue;
                }
                Matcher email = EMAIL_AUTOLINK.matcher(text.substring(pos));
                if (email.find() && email.start() == 0) {
                    flushText(textBuf, result);
                    AstNode link = new AstNode(AstNode.Type.AUTOLINK, email.group(1));
                    link.destination = "mailto:" + email.group(1);
                    result.add(link);
                    pos += email.group(0).length();
                    continue;
                }
            }

            // Emphasis/strong
            if (c == '*' || c == '_') {
                int matchLen = parseEmphasis(text, pos);
                if (matchLen > 0) {
                    flushText(textBuf, result);
                    result.addAll(parseEmphasisNodes(text.substring(pos, pos + matchLen)));
                    pos += matchLen;
                    continue;
                }
            }

            // Strikethrough
            if (c == '~' && pos + 1 < text.length() && text.charAt(pos + 1) == '~') {
                int end = text.indexOf("~~", pos + 2);
                if (end > pos + 2) {
                    flushText(textBuf, result);
                    AstNode strike = new AstNode(AstNode.Type.STRIKETHROUGH);
                    strike.children = parse(text.substring(pos + 2, end));
                    result.add(strike);
                    pos = end + 2;
                    continue;
                }
            }

            // Image
            if (c == '!' && pos + 1 < text.length() && text.charAt(pos + 1) == '[') {
                int end = findLinkEnd(text, pos + 1);
                if (end > 0) {
                    flushText(textBuf, result);
                    String inner = text.substring(pos + 2, end - 1);
                    // Check for inline link: ![](url) or ![alt](url)
                    int parenStart = text.indexOf('(', end);
                    if (parenStart == end && parenStart < text.length() - 1) {
                        int parenEnd = text.indexOf(')', parenStart + 1);
                        if (parenEnd > parenStart) {
                            String url = text.substring(parenStart + 1, parenEnd);
                            AstNode img = new AstNode(AstNode.Type.IMAGE, inner);
                            img.destination = url.strip();
                            result.add(img);
                            pos = parenEnd + 1;
                            continue;
                        }
                    }
                }
            }

            // Link
            if (c == '[') {
                int end = findLinkEnd(text, pos);
                if (end > 0) {
                    int parenStart = text.indexOf('(', end);
                    if (parenStart == end && parenStart < text.length() - 1) {
                        int parenEnd = text.indexOf(')', parenStart + 1);
                        if (parenEnd > parenStart) {
                            String urlPart = text.substring(parenStart + 1, parenEnd).strip();
                            // Parse optional title
                            String dest = urlPart;
                            String title = null;
                            int titleStart = urlPart.indexOf('"');
                            if (titleStart > 0) {
                                dest = urlPart.substring(0, titleStart).strip();
                                int titleEnd = urlPart.indexOf('"', titleStart + 1);
                                if (titleEnd > titleStart) {
                                    title = urlPart.substring(titleStart + 1, titleEnd);
                                }
                            } else {
                                int titleStart2 = urlPart.indexOf('\'');
                                if (titleStart2 > 0) {
                                    dest = urlPart.substring(0, titleStart2).strip();
                                    int titleEnd2 = urlPart.indexOf('\'', titleStart2 + 1);
                                    if (titleEnd2 > titleStart2) {
                                        title = urlPart.substring(titleStart2 + 1, titleEnd2);
                                    }
                                }
                            }

                            flushText(textBuf, result);
                            String linkText = text.substring(pos + 1, end - 1);
                            AstNode link = new AstNode(AstNode.Type.LINK);
                            link.destination = dest;
                            link.title = title;
                            link.children = parse(linkText);
                            result.add(link);
                            pos = parenEnd + 1;
                            continue;
                        }
                    }
                }
            }

            // Entity
            if (c == '&') {
                Matcher ent = ENTITY.matcher(text.substring(pos));
                if (ent.find() && ent.start() == 0) {
                    flushText(textBuf, result);
                    result.add(new AstNode(AstNode.Type.ENTITY, ent.group(0)));
                    pos += ent.group(0).length();
                    continue;
                }
            }

            textBuf.append(c);
            pos++;
        }
        flushText(textBuf, result);
    }

    private void flushText(StringBuilder buf, List<AstNode> result) {
        if (buf.length() > 0) {
            result.add(new AstNode(AstNode.Type.TEXT, buf.toString()));
            buf.setLength(0);
        }
    }

    private int findLinkEnd(String text, int start) {
        int depth = 1;
        for (int i = start + 1; i < text.length(); i++) {
            char c = text.charAt(i);
            if (c == '[') depth++;
            else if (c == ']') {
                depth--;
                if (depth == 0) return i + 1;
            }
            // Code span inside - skip
            if (c == '`') {
                int end = text.indexOf('`', i + 1);
                if (end > i) i = end;
            }
        }
        return -1;
    }

    private int parseEmphasis(String text, int pos) {
        char c = text.charAt(pos);
        boolean doubleMarker = pos + 1 < text.length() && text.charAt(pos + 1) == c;

        if (doubleMarker && pos + 2 < text.length() && text.charAt(pos + 2) == c) {
            return 0; // triple marker, not supported
        }

        int markerLen = doubleMarker ? 2 : 1;
        String search = doubleMarker ? String.valueOf(c) + c : String.valueOf(c);

        // Find closing markers
        int searchFrom = pos + markerLen;
        while (searchFrom < text.length()) {
            int closeIdx = text.indexOf(search, searchFrom);
            if (closeIdx < 0) break;

            // Check if the closing is valid (not at start of line, etc.)
            if (closeIdx > pos + markerLen) {
                return closeIdx + markerLen - pos;
            }
            searchFrom = closeIdx + markerLen;
        }
        return 0;
    }

    private List<AstNode> parseEmphasisNodes(String text) {
        List<AstNode> nodes = new ArrayList<>();
        if (text.startsWith("**") && text.endsWith("**") && text.length() > 4) {
            AstNode strong = new AstNode(AstNode.Type.STRONG_EMPHASIS);
            strong.children = parse(text.substring(2, text.length() - 2));
            nodes.add(strong);
        } else if (text.startsWith("*") && text.endsWith("*") && text.length() > 2) {
            AstNode em = new AstNode(AstNode.Type.EMPHASIS);
            em.children = parse(text.substring(1, text.length() - 1));
            nodes.add(em);
        } else if (text.startsWith("__") && text.endsWith("__") && text.length() > 4) {
            AstNode strong = new AstNode(AstNode.Type.STRONG_EMPHASIS);
            strong.children = parse(text.substring(2, text.length() - 2));
            nodes.add(strong);
        } else if (text.startsWith("_") && text.endsWith("_") && text.length() > 2) {
            AstNode em = new AstNode(AstNode.Type.EMPHASIS);
            em.children = parse(text.substring(1, text.length() - 1));
            nodes.add(em);
        }
        return nodes;
    }

    private String decodeEntities(String text) {
        return text.replace("&amp;", "&")
                    .replace("&lt;", "<")
                    .replace("&gt;", ">")
                    .replace("&quot;", "\"")
                    .replace("&#39;", "'");
    }
}

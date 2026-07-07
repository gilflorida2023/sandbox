package gfm.parser;

import java.util.*;
import java.util.regex.*;

public class BlockParser {
    // Patterns from the GFM spec
    private static final Pattern THEMATIC_BREAK = Pattern.compile("^ {0,3}([-*_])[ \\t]*\\1[ \\t]*\\1[ \\t]*$");
    private static final Pattern ATX_HEADING = Pattern.compile("^ {0,3}(#{1,6})(?:[ \\t]+|$)");
    private static final Pattern ATX_CLOSING = Pattern.compile("[ \\t]+#+[ \\t]*$");
    private static final Pattern FENCED_START = Pattern.compile("^ {0,3}(`{3,}|~{3,})([^`]*)$");
    private static final Pattern FENCED_CLOSE = Pattern.compile("^ {0,3}(`{3,}|~{3,})[ \\t]*$");
    private static final Pattern BLOCK_QUOTE = Pattern.compile("^ {0,3}> ?");
    private static final Pattern LIST_MARKER = Pattern.compile("^ {0,3}([-+*]|[0-9]{1,9}\\.)");
    private static final Pattern ORDERED_LIST = Pattern.compile("^ {0,3}([0-9]{1,9})\\.(?:[ \\t]|$)");
    private static final Pattern UNORDERED_LIST = Pattern.compile("^ {0,3}([-+*])(?:[ \\t]|$)");
    private static final Pattern INDENTED_CODE = Pattern.compile("^    ");
    private static final Pattern BLANK_LINE = Pattern.compile("^[ \\t]*$");
    private static final Pattern SETEXT_UNDERLINE = Pattern.compile("^ {0,3}(=+|-+)[ \\t]*$");
    private static final Pattern TASK_MARKER = Pattern.compile("^\\s*\\[([ xX])\\]");

    private static final Set<String> HTML_BLOCK_TAGS = Set.of(
        "pre", "script", "style", "textarea", "title", "xmp",
        "iframe", "noembed", "noframes", "noscript"
    );
    private static final Pattern HTML_BLOCK_1 = Pattern.compile(
        "^ {0,3}<(script|pre|style|textarea)[> \\t\\n\\r].*", Pattern.CASE_INSENSITIVE
    );
    private static final Pattern HTML_BLOCK_7 = Pattern.compile(
        "^ {0,3}<(\\?|![A-Z])", Pattern.CASE_INSENSITIVE
    );

    private List<String> lines;
    private int pos;

    public AstNode parse(String text) {
        lines = Arrays.asList(text.split("\n", -1));
        pos = 0;
        AstNode doc = new AstNode(AstNode.Type.DOCUMENT);
        parseBlocks(doc, 0);
        return doc;
    }

    private void parseBlocks(AstNode container, int indent) {
        while (pos < lines.size()) {
            String line = lines.get(pos);
            if (BLANK_LINE.matcher(line).matches()) {
                pos++;
                continue;
            }

            // Check for thematic break
            if (THEMATIC_BREAK.matcher(line).matches()) {
                container.appendChild(new AstNode(AstNode.Type.THEMATIC_BREAK));
                pos++;
                continue;
            }

            // Check for ATX heading
            Matcher atx = ATX_HEADING.matcher(line);
            if (atx.find()) {
                int level = atx.group(1).length();
                String content = line.substring(atx.end());
                // Remove closing #s
                content = ATX_CLOSING.matcher(content).replaceFirst("");
                content = content.strip();
                AstNode.Type hType = AstNode.Type.values()[AstNode.Type.HEADING_1.ordinal() + (level - 1)];
                AstNode heading = new AstNode(hType);
                heading.literal = content;
                container.appendChild(heading);
                pos++;
                continue;
            }

            // Check for fenced code block
            Matcher fence = FENCED_START.matcher(line);
            if (fence.find()) {
                String fenceChar = fence.group(1);
                String infoStr = fence.group(2).strip();
                AstNode codeBlock = new AstNode(AstNode.Type.FENCED_CODE_BLOCK);
                codeBlock.info = infoStr;
                StringBuilder code = new StringBuilder();
                pos++;
                while (pos < lines.size()) {
                    String l = lines.get(pos);
                    Matcher close = FENCED_CLOSE.matcher(l);
                    if (close.find() && close.group(1).charAt(0) == fenceChar.charAt(0)
                            && close.group(1).length() >= fenceChar.length()) {
                        pos++;
                        break;
                    }
                    if (code.length() > 0) code.append("\n");
                    code.append(l);
                    pos++;
                }
                codeBlock.literal = code.toString();
                container.appendChild(codeBlock);
                continue;
            }

            // Check for block quote
            Matcher bq = BLOCK_QUOTE.matcher(line);
            if (bq.find()) {
                AstNode bqNode = new AstNode(AstNode.Type.BLOCK_QUOTE);
                container.appendChild(bqNode);
                // Process lines with > prefix
                List<String> bqLines = new ArrayList<>();
                while (pos < lines.size()) {
                    String l = lines.get(pos);
                    Matcher bqm = BLOCK_QUOTE.matcher(l);
                    if (bqm.find()) {
                        bqLines.add(l.substring(bqm.end()));
                        pos++;
                    } else if (BLANK_LINE.matcher(l).matches()) {
                        bqLines.add(l);
                        pos++;
                        // Check if next line continues
                        if (pos < lines.size()) {
                            String next = lines.get(pos);
                            if (!BLOCK_QUOTE.matcher(next).find() && !BLANK_LINE.matcher(next).matches()) {
                                break;
                            }
                        }
                    } else {
                        break;
                    }
                }
                // Parse inner blocks
                int savedPos = pos;
                pos = 0;
                List<String> savedLines = lines;
                lines = bqLines;
                parseBlocks(bqNode, indent + 1);
                lines = savedLines;
                pos = savedPos - (bqLines.size() - pos);
                continue;
            }

            // Check for list item
            Matcher ol = ORDERED_LIST.matcher(line);
            Matcher ul = UNORDERED_LIST.matcher(line);
            if (ol.find() || (ul.find() && line.length() > ul.end())) {
                boolean ordered = ol.find();
                // Normalize list item indent
                int markerEnd = ordered ? ol.end() : ul.end();
                int contentIndent = markerEnd;
                String marker = ordered ? ol.group(0) : ul.group(0);

                AstNode listContainer;
                if (container.children.isEmpty() ||
                    !(container.children.get(container.children.size() - 1).type == AstNode.Type.LIST)) {
                    listContainer = new AstNode(AstNode.Type.LIST);
                    container.appendChild(listContainer);
                } else {
                    listContainer = container.children.get(container.children.size() - 1);
                }

                // Check for task list
                String contentStr = line.substring(contentIndent).stripTrailing();
                boolean taskItem = false;
                boolean taskChecked = false;
                Matcher task = TASK_MARKER.matcher(contentStr);
                if (task.find()) {
                    taskItem = true;
                    taskChecked = !task.group(1).equals(" ");
                }

                AstNode li = new AstNode(AstNode.Type.LIST_ITEM);
                li.taskListItem = taskItem;
                li.taskChecked = taskChecked;
                listContainer.appendChild(li);

                // Parse continuation lines
                pos++;
                while (pos < lines.size()) {
                    String l = lines.get(pos);
                    if (BLANK_LINE.matcher(l).matches()) {
                        pos++;
                        continue;
                    }
                    // Check if this is a new list item at same level
                    Matcher nextOl = ORDERED_LIST.matcher(l);
                    Matcher nextUl = UNORDERED_LIST.matcher(l);
                    boolean nextOlMatch = nextOl.find();
                    boolean nextUlMatch = nextUl.find();
                    if ((nextOlMatch && nextOl.end() <= contentIndent) ||
                        (nextUlMatch && nextUl.end() <= contentIndent && l.length() > nextUl.end())) {
                        break;
                    }
                    break;
                }
                continue;
            }

            // Check for indented code block
            if (INDENTED_CODE.matcher(line).matches()) {
                StringBuilder code = new StringBuilder();
                while (pos < lines.size()) {
                    String l = lines.get(pos);
                    if (INDENTED_CODE.matcher(l).matches()) {
                        if (code.length() > 0) code.append("\n");
                        code.append(l.substring(4));
                        pos++;
                    } else if (BLANK_LINE.matcher(l).matches()) {
                        if (code.length() > 0) code.append("\n");
                        pos++;
                    } else {
                        break;
                    }
                }
                AstNode cb = new AstNode(AstNode.Type.CODE_BLOCK);
                cb.literal = code.toString();
                container.appendChild(cb);
                continue;
            }

            // Check for setext heading underline (must follow paragraph text)
            // (Handled during paragraph processing below)

            // Default: paragraph
            StringBuilder paraText = new StringBuilder();
            int startPos = pos;
            while (pos < lines.size()) {
                String l = lines.get(pos);
                boolean isListItem = false;
                Matcher olPara = ORDERED_LIST.matcher(l);
                Matcher ulPara = UNORDERED_LIST.matcher(l);
                if (olPara.find()) {
                    isListItem = l.length() > olPara.end();
                } else if (ulPara.find()) {
                    isListItem = l.length() > ulPara.end();
                }
                // Check for setext heading (takes precedence over thematic break)
                if (pos > startPos) {
                    Matcher se = SETEXT_UNDERLINE.matcher(l);
                    if (se.find()) {
                        String headingText = paraText.toString().stripTrailing();
                        int level = se.group(1).charAt(0) == '=' ? 1 : 2;
                        AstNode.Type hType = level == 1 ? AstNode.Type.HEADING_1 : AstNode.Type.HEADING_2;
                        AstNode heading = new AstNode(hType);
                        heading.literal = headingText;
                        container.appendChild(heading);
                        pos++;
                        paraText.setLength(0);
                        break;
                    }
                }
                if (BLANK_LINE.matcher(l).matches() ||
                    THEMATIC_BREAK.matcher(l).matches() ||
                    ATX_HEADING.matcher(l).find() ||
                    FENCED_START.matcher(l).find() ||
                    BLOCK_QUOTE.matcher(l).find() ||
                    isListItem) {
                    break;
                }
                if (paraText.length() > 0) paraText.append("\n");
                paraText.append(l);
                pos++;
            }
            if (!paraText.isEmpty()) {
                AstNode para = new AstNode(AstNode.Type.PARAGRAPH);
                para.literal = paraText.toString();
                container.appendChild(para);
            }
        }
    }
}

package gfm.parser;

import java.util.ArrayList;
import java.util.List;

public class AstNode {
    public enum Type {
        DOCUMENT,
        PARAGRAPH,
        HEADING_1, HEADING_2, HEADING_3, HEADING_4, HEADING_5, HEADING_6,
        THEMATIC_BREAK,
        CODE_BLOCK,
        FENCED_CODE_BLOCK,
        HTML_BLOCK,
        BLOCK_QUOTE,
        LIST,
        LIST_ITEM,
        TABLE,
        TABLE_ROW,
        TABLE_CELL,
        // Inline types
        TEXT,
        CODE_SPAN,
        EMPHASIS,
        STRONG_EMPHASIS,
        STRIKETHROUGH,
        LINK,
        IMAGE,
        HARD_LINE_BREAK,
        SOFT_LINE_BREAK,
        RAW_HTML,
        AUTOLINK,
        ESCAPED_CHAR,
        ENTITY
    }

    public Type type;
    public String literal;
    public List<AstNode> children;
    public AstNode parent;
    // For links/images
    public String destination;
    public String title;
    // For fenced code blocks
    public String info;
    // For tables
    public String align;
    // For list items
    public boolean taskListItem;
    public boolean taskChecked;

    public AstNode(Type type) {
        this.type = type;
        this.children = new ArrayList<>();
    }

    public AstNode(Type type, String literal) {
        this(type);
        this.literal = literal;
    }

    public void appendChild(AstNode child) {
        child.parent = this;
        children.add(child);
    }

    public void appendLiteral(String text) {
        if (literal == null) {
            literal = text;
        } else {
            literal += text;
        }
    }

    public String stringValue() {
        if (literal != null) return literal;
        StringBuilder sb = new StringBuilder();
        for (AstNode c : children) {
            String s = c.stringValue();
            if (s != null) sb.append(s);
        }
        return sb.toString();
    }

    @Override
    public String toString() {
        return type + (literal != null ? "(" + literal.substring(0, Math.min(40, literal.length())) + ")" : "");
    }
}

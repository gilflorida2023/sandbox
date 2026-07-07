#!/usr/bin/env python3
"""Parse GFM spec HTML and write section-chunked markdown files to workspace/specs/."""

import html
import os
import re
import sys

SPECS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "specs")


def unspacify(text):
    """Replace <span class="space"> </span> markers with literal spaces."""
    return re.sub(r'<span class="space">\s*</span>', ' ', text)


def clean_html(html_text):
    """Decode HTML entities and remove spans."""
    text = html_text
    # Remove all HTML tags except <code>, <pre>, <em>, <strong>, etc that we want to preserve
    # Actually for the spec, we want the markdown input and HTML output as plain text
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    return text


def extract_examples(html_content):
    """Extract examples from spec HTML.

    Each example is a div.example with:
    - Example number
    - Markdown input (first .column pre)
    - HTML output (second .column pre)
    """
    examples = []
    pattern = r'<div class="example"[^>]*id="([^"]+)"[^>]*>.*?<div class="examplenum">.*?<a[^>]*>([^<]+)</a>.*?</div>.*?<div class="column">\s*<pre[^>]*>(.*?)</pre>\s*</div>\s*<div class="column">\s*<pre[^>]*>(.*?)</pre>\s*</div>\s*</div>'
    for match in re.finditer(pattern, html_content, re.DOTALL):
        ex_id = match.group(1)
        ex_num = clean_html(match.group(2)).strip()
        md_input = unspacify(match.group(3))
        md_input = re.sub(r'<[^>]+>', '', md_input)
        md_input = html.unescape(md_input)
        html_output = unspacify(match.group(4))
        html_output = re.sub(r'<[^>]+>', '', html_output)
        html_output = html.unescape(html_output)
        examples.append({
            'id': ex_id,
            'number': ex_num,
            'markdown': md_input,
            'html': html_output
        })
    return examples


def extract_sections(html_content):
    """Extract sections (h1/h2) with their content from spec HTML."""
    # Find all h1 and h2 sections
    sections = []
    # Pattern matches h1 or h2 with their IDs and numbers
    heading_pattern = r'<h([12])[^>]*id="([^"]+)"[^>]*>.*?<span class="number">([^<]+)</span>\s*([^<]+?)\s*</h[12]>'
    headings = list(re.finditer(heading_pattern, html_content, re.DOTALL))

    for i, h in enumerate(headings):
        level = int(h.group(1))
        h_id = h.group(2)
        h_num = clean_html(h.group(3)).strip()
        h_title = clean_html(h.group(4)).strip()

        # Get content from this heading to the next heading at same or higher level
        start = h.end()
        if i + 1 < len(headings):
            end = headings[i + 1].start()
        else:
            end = len(html_content)

        content = html_content[start:end]

        sections.append({
            'id': h_id,
            'number': h_num,
            'title': h_title,
            'level': level,
            'content': content,
            'examples': []
        })

    return sections


def extract_section_examples(sections, all_examples):
    """Assign examples to their parent sections based on position in HTML."""
    for section in sections:
        section['examples'] = []
    # Simple approach: assign examples to sections by finding which section's
    # content range contains each example's position
    # We'll use the section content text to find referenced example IDs
    section_texts = [(s, s['content']) for s in sections]

    for ex in all_examples:
        ex_id = ex['id']
        # Find which section's content contains this example ID
        for s, content in section_texts:
            if f'id="{ex_id}"' in content or f'href="#{ex_id}"' in content:
                s['examples'].append(ex)
                break


def content_to_markdown(content, examples):
    """Convert HTML section content to markdown, preserving example structure."""
    lines = []
    # Remove example divs (they'll be rendered separately)
    # Replace example blocks with placeholders
    for ex in examples:
        placeholder = f"<!-- EXAMPLE:{ex['number']} -->"
        # Remove the original example HTML
        pattern = r'<div class="example"[^>]*id="' + re.escape(ex['id']) + r'"[^>]*>.*?</div>\s*'
        content = re.sub(pattern, placeholder + '\n', content, flags=re.DOTALL)

    # Convert remaining HTML to simple text
    # Remove all remaining HTML tags
    text = re.sub(r'<[^>]+>', '', content)
    text = html.unescape(text)
    text = unspacify(text)
    # Decode common entities
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')
    # Normalize whitespace
    text = re.sub(r' +\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    lines.append(text.strip())

    # Append examples
    if examples:
        lines.append("")
        lines.append("---")
        lines.append("")
        for ex in examples:
            lines.append(f"### Example {ex['number']}")
            lines.append("")
            lines.append("**Markdown input:**")
            lines.append("")
            lines.append("```markdown")
            lines.append(ex['markdown'].strip())
            lines.append("```")
            lines.append("")
            lines.append("**Expected HTML output:**")
            lines.append("")
            lines.append("```html")
            lines.append(ex['html'].strip())
            lines.append("```")
            lines.append("")

    return '\n'.join(lines)


def main():
    # Read HTML from stdin or first arg
    if len(sys.argv) > 1:
        with open(sys.argv[1], 'r') as f:
            html_content = f.read()
    else:
        html_content = sys.stdin.read()

    os.makedirs(SPECS_DIR, exist_ok=True)

    sections = extract_sections(html_content)
    all_examples = extract_examples(html_content)

    print(f"Found {len(sections)} sections, {len(all_examples)} examples")

    # For each section, find examples that belong to it by proximity
    # Since the spec has examples interspersed in section content,
    # we use a simpler approach: track which heading each example follows
    section_idx = 0
    for ex in all_examples:
        # Find the example's position in the HTML
        ex_pattern = re.escape(ex['id'])
        pos_match = re.search(r'id="' + ex_pattern + '"', html_content)
        if not pos_match:
            continue
        ex_pos = pos_match.start()

        # Find the last section heading that comes before this example
        while (section_idx + 1 < len(sections) and
               html_content.find(f'id="{sections[section_idx + 1]["id"]}"') < ex_pos and
               html_content.find(f'id="{sections[section_idx + 1]["id"]}"') >= 0):
            section_idx += 1

        sections[section_idx]['examples'].append(ex)

    # Write each section as a markdown file
    index = []
    for i, section in enumerate(sections):
        if section['level'] == 1:
            filename = f"{section['number'].strip()}-{section['id']}.md"
        else:
            filename = f"{section['number'].strip().replace('.', '-')}-{section['id']}.md"
        filename = re.sub(r'[^a-zA-Z0-9_-]', '', filename.lower().replace(' ', '-'))
        filename = filename or f"section-{i}.md"

        md = content_to_markdown(section['content'], section['examples'])
        full_content = f"# {section['title']}\n\n{md}"

        filepath = os.path.join(SPECS_DIR, filename)
        with open(filepath, 'w') as f:
            f.write(full_content)

        file_size = len(full_content)
        num_examples = len(section['examples'])
        print(f"  Wrote {filename} ({file_size} bytes, {num_examples} examples)")
        index.append({
            'file': filename,
            'title': section['title'],
            'number': section['number'],
            'level': section['level'],
            'examples': num_examples,
            'size': file_size
        })

    # Write index
    with open(os.path.join(SPECS_DIR, 'index.json'), 'w') as f:
        import json
        json.dump(index, f, indent=2)

    print(f"\nWrote {len(sections)} files to {SPECS_DIR}/")
    print(f"Total examples: {len(all_examples)}")


if __name__ == '__main__':
    main()

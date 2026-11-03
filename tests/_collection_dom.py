"""A tiny DOM reader for collection markup (not a test module). Stdlib html.parser only:
no JavaScript engine exists in this container outside the one headless Chromium."""
import html.parser
import re

VOID = {"area", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source",
        "track", "wbr"}


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs), parent, []

    def text(self):
        out = []
        for ch in self.children:
            out.append(ch if isinstance(ch, str) else ch.text())
        return "".join(out)

    def name(self):
        """Accessible name from content, whitespace folded (no aria-label is used)."""
        return re.sub(r"\s+", " ", self.attrs.get("aria-label") or self.text()).strip()

    def walk(self):
        for ch in self.children:
            if not isinstance(ch, str):
                yield ch
                yield from ch.walk()

    def find_all(self, pred):
        return [n for n in self.walk() if pred(n)]


class _Parser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", [], None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_endtag(self, tag):
        n = self.cur
        while n is not self.root and n.tag != tag:
            n = n.parent
        if n is not self.root:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def parse(markup):
    p = _Parser()
    p.feed(markup)
    p.close()
    return p.root


def roots(doc):
    return doc.find_all(lambda n: "data-collection" in n.attrs and n.tag == "section")


def buttons(node):
    return node.find_all(lambda n: n.tag == "button")


def visible_text(node):
    """Text a sighted reader sees: everything except the screen-reader-only spans."""
    out = []
    for ch in node.children:
        if isinstance(ch, str):
            out.append(ch)
        elif "ja-coll-sr" not in (ch.attrs.get("class") or "").split():
            out.append(visible_text(ch))
    return re.sub(r"\s+", " ", "".join(out)).strip()

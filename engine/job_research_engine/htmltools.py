"""Small inert HTML tree. Page text is data; scripts are never evaluated."""
from html.parser import HTMLParser
from dataclasses import dataclass, field
import json
from urllib.parse import urljoin
from .model import EngineError, public_url

VOID = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}

@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def walk(self, tag=None):
        if tag is None or self.tag == tag:
            yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk(tag)

    def text(self):
        if self.tag in {'script','style','noscript'}:
            return ''
        return ' '.join(' '.join(c.text() if isinstance(c, Node) else c for c in self.children).split())

    def raw_text(self):
        return ''.join(c.raw_text() if isinstance(c,Node) else c for c in self.children)

    def has_class(self, name):
        return name in self.attrs.get('class','').split()

class Tree(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.root=Node('document');self.stack=[self.root];self.feed(text);self.close()

    def handle_starttag(self, tag, attrs):
        node=Node(tag,dict(attrs));self.stack[-1].children.append(node)
        if tag not in VOID:self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack)-1,0,-1):
            if self.stack[index].tag == tag:
                del self.stack[index:];break

    def handle_data(self, data):self.stack[-1].children.append(data)

def html(payload):
    for encoding in ('utf-8-sig','cp949'):
        try:return Tree(payload.decode(encoding)).root
        except UnicodeDecodeError:pass
    raise EngineError('unsupported page encoding; host inspection needed')

def next_data(root):
    for n in root.walk('script'):
        if n.attrs.get('id') == '__NEXT_DATA__':
            try:return json.loads(n.raw_text())['props']['pageProps']
            except (KeyError,ValueError,TypeError) as e:raise EngineError('Next page contract changed') from e
    raise EngineError('expected server-rendered page data missing; not an empty list')

def links(root, base):
    result=[]
    for n in root.walk('a'):
        target=n.attrs.get('href') or ''
        if not target or target.startswith(('#','javascript:','mailto:','tel:')):continue
        try:url=public_url(urljoin(base,target))
        except EngineError:continue
        result.append((url,n.text(),n))
    return result

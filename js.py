import os

import dukpy

from css import CSSParser
from html_parser import HTMLParser, tree_to_list

RUNTIME_JS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime.js")
with open(RUNTIME_JS_PATH, "r", encoding="utf-8") as _f:
    RUNTIME_JS = _f.read()

# dukpy.handle, dukpy.type은 evaljs에 키워드 인자로 넘긴 값이다
EVENT_DISPATCH_JS = "new Node(dukpy.handle).dispatchEvent(new Event(dukpy.type))"


class JSContext:
    # 페이지 하나의 자바스크립트 실행 환경. 스크립트끼리 변수를 공유하도록
    # 인터프리터를 하나만 두고, DOM API를 파이썬 함수로 export한다.
    def __init__(self, tab):
        self.tab = tab
        self.interp = dukpy.JSInterpreter()
        self.interp.export_function("log", print)
        self.interp.export_function("querySelectorAll", self.querySelectorAll)
        self.interp.export_function("getAttribute", self.getAttribute)
        self.interp.export_function("innerHTML_set", self.innerHTML_set)

        # Element는 파이썬에만 있는 객체라 자바스크립트로 넘길 수 없다.
        # 대신 숫자 핸들을 주고, 양방향 표로 노드와 핸들을 이어 둔다.
        self.node_to_handle = {}
        self.handle_to_node = {}

        self.interp.evaljs(RUNTIME_JS)

    def run(self, script, code):
        # 웹 페이지의 스크립트가 터져도 브라우저는 죽으면 안 된다
        try:
            return self.interp.evaljs(code)
        except dukpy.JSRuntimeError as e:
            print("Script", script, "crashed", e)

    def dispatch_event(self, type, elt):
        # 자바스크립트가 한 번도 만진 적 없는 노드는 핸들이 없고, 리스너도 없다
        handle = self.node_to_handle.get(elt, -1)
        do_default = self.interp.evaljs(EVENT_DISPATCH_JS, type=type, handle=handle)
        # True를 돌려주면 "스크립트가 기본 동작을 취소했다"는 뜻이다
        return not do_default

    def get_handle(self, elt):
        if elt not in self.node_to_handle:
            handle = len(self.node_to_handle)
            self.node_to_handle[elt] = handle
            self.handle_to_node[handle] = elt
        else:
            handle = self.node_to_handle[elt]
        return handle

    def querySelectorAll(self, selector_text):
        # 잘못된 셀렉터면 여기서 예외가 나고, DukPy가 그걸 자바스크립트
        # 예외로 바꿔 주므로 페이지 스크립트가 catch할 수 있다
        selector = CSSParser(selector_text).selector()
        nodes = [
            node for node in tree_to_list(self.tab.nodes, []) if selector.matches(node)
        ]
        return [self.get_handle(node) for node in nodes]

    def getAttribute(self, handle, attr):
        elt = self.handle_to_node[handle]
        attr = elt.attributes.get(attr, None)
        return attr if attr else ""

    def innerHTML_set(self, handle, s):
        # 우리 파서는 문서 전체만 파싱할 줄 안다. 조각을 html/body로 감싸서
        # 파싱한 뒤 body의 자식들만 꺼내 쓴다.
        doc = HTMLParser("<html><body>" + s + "</body></html>").parse()
        new_nodes = doc.children[0].children
        elt = self.handle_to_node[handle]
        elt.children = new_nodes
        for child in elt.children:
            # 그대로 두면 부모가 임시로 만든 body를 가리킨다
            child.parent = elt
        # HTML 트리만 바뀌었으니 레이아웃 트리와 디스플레이 리스트를 다시 만든다
        self.tab.render()

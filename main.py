import sys
import tkinter

from browser import WIDTH, Browser
from css import DEFAULT_STYLE_SHEET, cascade_priority, style
from html_parser import HTMLParser, print_tree
from layout import DocumentLayout
from url import URL

# pytk main.py "file://$PWD/test7.html"
# pytk main.py http://browser.engineering
# pytk main.py --tree "file://$PWD/test.html"
# pytk main.py --tree "view-source:http://browser.engineering"
# pytk main.py --layout "file://$PWD/test.html"

if __name__ == "__main__":
    args = sys.argv[1:]
    if "--tree" in args:
        # 창을 띄우지 않고 파싱된 HTML 트리만 출력한다(파서 디버깅용).
        # view-source: 주소면 트리 대신 받아 온 원문을 그대로 출력한다.
        args.remove("--tree")
        url = URL(args[0])
        body = url.request()
        if url.view_source:
            print(body, end="")
        else:
            print_tree(HTMLParser(body).parse())
    elif "--layout" in args:
        # 레이아웃 트리를 출력한다. 폰트 측정에 Tk가 필요하므로 창은 숨겨서 만든다.
        args.remove("--layout")
        root = tkinter.Tk()
        root.withdraw()
        nodes = HTMLParser(URL(args[0]).request()).parse()
        # 레이아웃이 node.style을 읽으므로 스타일을 먼저 계산해야 한다
        style(nodes, sorted(DEFAULT_STYLE_SHEET.copy(), key=cascade_priority))
        document = DocumentLayout(nodes, WIDTH)
        document.layout()
        print_tree(document)
    else:
        Browser().new_tab(URL(args[0]))
        tkinter.mainloop()

import tkinter

from html_parser import tree_to_list
from layout import InputLayout
from tab import Tab

root = tkinter.Tk()
root.withdraw()

tab = Tab(800, 600)
tab.load("http://localhost:8000/")

inputs = [o for o in tree_to_list(tab.document, []) if isinstance(o, InputLayout)]
print("InputLayouts:", inputs)
field, button = inputs


def center(obj):
    return obj.x + 5, obj.y + obj.height / 2 - tab.scroll


# 입력창 클릭 → 포커스, 커서(DrawLine) 생김
tab.click(*center(field))
print("focus:", tab.focus, tab.focus.is_focused)
cursor = [c for c in tab.display_list if type(c).__name__ == "DrawLine"]
print("cursor lines:", len(cursor))

for ch in "hi there & 안녕":
    tab.keypress(ch)
tab.keypress("\b")
print("value:", repr(tab.focus.attributes["value"]))

# 빈 곳 클릭 → 포커스 해제, 커서 사라짐
tab.click(700, 500)
print("after blur focus:", tab.focus,
      "lines:", len([c for c in tab.display_list if type(c).__name__ == "DrawLine"]))

# 버튼 클릭 → POST /add
inputs = [o for o in tree_to_list(tab.document, []) if isinstance(o, InputLayout)]
tab.click(*center(inputs[1]))
print("url after submit:", tab.url)
texts = [c.text for c in tab.display_list if type(c).__name__ == "DrawText"]
print("page words:", texts)

# 다시 GET / (캐시가 POST 결과를 가리지 않는지, 연결 재사용이 깨지지 않는지)
tab.load("http://localhost:8000/")
texts = [c.text for c in tab.display_list if type(c).__name__ == "DrawText"]
print("reload words:", texts)

tab.load("http://localhost:8000/nope")
print("404 words:", [c.text for c in tab.display_list if type(c).__name__ == "DrawText"])

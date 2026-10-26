// 브라우저가 페이지 스크립트보다 먼저 실행하는 자바스크립트 런타임.
// 파이썬에서 export한 함수(call_python)를 웹 표준과 비슷한 모양으로 감싼다.
// DukPy는 let/const/화살표 함수/class를 모르므로 옛날 문법으로만 쓴다.

console = { log: function(x) { call_python("log", x); } }

document = { querySelectorAll: function(s) {
    // 파이썬은 Element 객체 대신 핸들(숫자)만 돌려준다
    var handles = call_python("querySelectorAll", s);
    return handles.map(function(h) { return new Node(h) });
}}

function Node(handle) { this.handle = handle; }

Node.prototype.getAttribute = function(attr) {
    return call_python("getAttribute", this.handle, attr);
}

// 핸들 → { 이벤트 종류 → 리스너 목록 }. 리스너는 자바스크립트 함수라서
// 파이썬으로 넘길 수 없으므로 자바스크립트 쪽에 보관한다.
LISTENERS = {}

Node.prototype.addEventListener = function(type, listener) {
    if (!LISTENERS[this.handle]) LISTENERS[this.handle] = {};
    var dict = LISTENERS[this.handle];
    if (!dict[type]) dict[type] = [];
    var list = dict[type];
    list.push(listener);
}

function Event(type) {
    this.type = type;
    // preventDefault()가 불렸는지 기록한다. 브라우저는 이 값을 보고
    // 링크 이동, 글자 입력, 폼 제출 같은 기본 동작을 할지 정한다.
    this.do_default = true;
}

Event.prototype.preventDefault = function() {
    this.do_default = false;
}

Node.prototype.dispatchEvent = function(evt) {
    var type = evt.type;
    var handle = this.handle;
    var list = (LISTENERS[handle] && LISTENERS[handle][type]) || [];
    for (var i = 0; i < list.length; i++) {
        // 리스너 안의 this가 이벤트가 일어난 노드를 가리키게 한다
        list[i].call(this, evt);
    }
    return evt.do_default;
}

Object.defineProperty(Node.prototype, 'innerHTML', {
    set: function(s) {
        call_python("innerHTML_set", this.handle, s.toString());
    }
});

import socket
import ssl
import time


class URL:
    # (scheme, host, port) -> (socket, makefile 객체)
    connections = {}
    # "scheme://host:port/path" -> (body, expiry). expiry가 None이면 무기한
    cache = {}

    def __init__(self, url):
        self.view_source = False
        if url.startswith("view-source:"):
            self.view_source = True
            url = url[len("view-source:") :]

        if url.startswith("data:"):
            self.scheme = "data"
            # data:text/html,Hello 이런 타입으로 들어오게 됨.
            self.mediatype, self.data = url[len("data:") :].split(",", 1)
            return

        self.scheme, url = url.split("://", 1)
        assert self.scheme in ["http", "https", "file"]

        if self.scheme == "file":
            self.path = url
            return

        if self.scheme == "http":
            self.port = 80
        elif self.scheme == "https":
            self.port = 443

        if "/" not in url:
            url = url + "/"
        self.host, url = url.split("/", 1)
        self.path = "/" + url
        if ":" in self.host:
            self.host, self.port = self.host.split(":", 1)
            self.port = int(self.port)

    def request(self, max_redirects=10):
        if self.scheme == "data":
            return self.data

        if self.scheme == "file":
            return self.request_file()

        cache_key = "{}://{}:{}{}".format(
            self.scheme, self.host, self.port, self.path
        )
        now = time.time()
        if cache_key in URL.cache:
            cached_body, expiry = URL.cache[cache_key]
            if expiry is None or now < expiry:
                return cached_body
            del URL.cache[cache_key]

        key = (self.scheme, self.host, self.port)
        if key in URL.connections:
            s, response = URL.connections[key]
        else:
            s = socket.socket(
                family=socket.AF_INET,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
            s.connect((self.host, self.port))
            if self.scheme == "https":
                ctx = ssl.create_default_context()
                s = ctx.wrap_socket(s, server_hostname=self.host)
            response = s.makefile("rb")
            URL.connections[key] = (s, response)

        headers = {
            "Host": self.host,
            "Connection": "keep-alive",
            #  Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 크롬은 매우 복잡
            "User-Agent": "baesh",
        }
        request = "GET {} HTTP/1.1\r\n".format(self.path)
        for header, value in headers.items():
            request += "{}: {}\r\n".format(header, value)
        request += "\r\n"
        s.send(request.encode("utf-8"))

        status_line = response.readline().decode("utf-8")
        version, status, explanation = status_line.split(" ", 2)
        response_headers = {}
        while True:
            line = response.readline().decode("utf-8")
            if line == "\r\n":
                break
            header, value = line.split(":", 1)
            response_headers[header.casefold()] = value.strip()
        assert "transfer-encoding" not in response_headers
        assert "content-encoding" not in response_headers

        if "content-length" in response_headers:
            content_length = int(response_headers["content-length"])
            body = response.read(content_length).decode("utf-8")
        else:
            body = ""

        if status.startswith("3") and "location" in response_headers:
            if max_redirects <= 0:
                raise Exception("Too many redirects")
            location = response_headers["location"]
            if "://" not in location:
                location = "{}://{}:{}{}".format(
                    self.scheme, self.host, self.port, location
                )
            result_body = URL(location).request(max_redirects - 1)
        else:
            result_body = body

        if status in ["200", "301", "404"]:
            should_cache = True
            expiry = None
            if "cache-control" in response_headers:
                directives = response_headers["cache-control"].lower().split(",")
                for directive in directives:
                    directive = directive.strip()
                    if directive.startswith("max-age="):
                        expiry = now + int(directive[len("max-age=") :])
                    else:
                        # no-store를 포함해, max-age 외의 값이면 캐시하지 않음
                        should_cache = False
            if should_cache:
                URL.cache[cache_key] = (result_body, expiry)

        return result_body

    def request_file(self):
        with open(self.path, "r", encoding="utf-8") as f:
            return f.read()


def show(body):
    in_tag = False
    text = ""

    for c in body:
        if c == "<":
            in_tag = True
        elif c == ">":
            in_tag = False
        elif not in_tag:
            text += c

    text = text.replace("&lt;", "<").replace("&gt;", ">")
    print(text, end="")


def load(url):
    body = url.request()
    if url.view_source:
        print(body, end="")
    else:
        show(body)


if __name__ == "__main__":
    import os
    import sys

    if len(sys.argv) > 1:
        load(URL(sys.argv[1]))
    else:
        default_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "test.html"
        )
        load(URL("file://" + default_path))

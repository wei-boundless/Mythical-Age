import http.server
import os

os.chdir(r"D:\AI应用\langchain-agent\adventure-island-standalone")
server = http.server.HTTPServer(("127.0.0.1", 8088), http.server.SimpleHTTPRequestHandler)
print("Serving adventure-island-standalone on http://127.0.0.1:8088")
server.serve_forever()

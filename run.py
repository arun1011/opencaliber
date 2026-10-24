"""Launch OpenCaliber's loopback-only local console."""
from http.server import ThreadingHTTPServer
from opencaliber.agent_server import Handler,initialize

if __name__=='__main__':
    initialize()
    print('OpenCaliber: http://127.0.0.1:8787/ · Console: /console',flush=True)
    ThreadingHTTPServer(('127.0.0.1',8787),Handler).serve_forever()

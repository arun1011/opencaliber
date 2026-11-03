"""Generate a backend-independent guide from the console's rendered guide content."""
import html
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]

def build():
    source=(ROOT/'web/developer-guide.js').read_text(encoding='utf-8')
    chapters=json.loads(re.search(r'const chapters=(.*);',source).group(1))
    body=json.loads(re.search(r'const body=(.*);',source).group(1))
    toc=''.join('<a class="btn" href="#guide-'+html.escape(key)+'">'+html.escape(label)+'</a>' for key,label in chapters)
    page='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Developer Guide | OpenCaliber</title><meta name="description" content="Connect agents, inspect actions, compare versions and develop detection checks with OpenCaliber. Practical examples and console screenshots."><link rel="icon" href="/assets/favicon.svg"><link rel="stylesheet" href="/styles.css"></head><body class="marketing"><header class="site-nav"><a href="/" class="logo"><img src="/assets/logo.svg" width="29" height="29" alt="">OpenCaliber</a><nav class="site-links"><a href="/agents">Agents Library</a><a href="/guide" aria-current="page">Developer Guide</a><a class="btn primary" href="/console">Console</a></nav></header><main class="public-guide"><div class="page-heading"><div><h1>Developer Guide</h1><p>Connect an agent, understand its runs and test improvements. Examples and screenshots for every console menu.</p></div></div><p>This guide is available without running the console. To use the tools, <a class="link" href="/api/package">download OpenCaliber</a> and start your own console.</p><nav class="guide-toc" aria-label="Guide chapters">'''+toc+'''</nav><section class="panel panel-content text-content guide-content">'''+body+'''</section></main><footer class="site-footer"><a href="/">OpenCaliber home</a><a href="/agents">Agents Library</a><a href="/guide">Developer Guide</a></footer></body></html>'''
    (ROOT/'web/guide.html').write_text(page,encoding='utf-8')

if __name__=='__main__':build()

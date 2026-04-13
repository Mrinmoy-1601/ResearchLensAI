content = open('frontend/app.js', encoding='utf-8').read()
old = '  // Summary content\n  const sc = $("summary-content");\n  sc.className = "summary-content glass-card prose-content";\n  sc.innerHTML = renderMarkdown(data.summary);'
new = '  // Summary content - show friendly error if quota hit\n  const sc = $("summary-content");\n  const summaryText = formatApiError(data.summary);\n  sc.className = "summary-content glass-card prose-content";\n  sc.innerHTML = renderMarkdown(summaryText);'
if old in content:
    content = content.replace(old, new, 1)
    open('frontend/app.js', 'w', encoding='utf-8').write(content)
    print('REPLACED OK')
else:
    print('NOT FOUND - showing context:')
    lines = content.split('\n')
    for i, l in enumerate(lines[283:296], 284):
        print(f'{i}: {repr(l)}')

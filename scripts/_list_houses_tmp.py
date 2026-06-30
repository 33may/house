import os, re, json, sys
os.chdir('/Users/may/Documents/may/house')
houses = []
for f in sorted(os.listdir('houses')):
    if not f.endswith('.md'):
        continue
    path = f'houses/{f}'
    txt = open(path).read()
    m = re.match(r'^---\n(.*?)\n---', txt, re.DOTALL)
    if not m:
        continue
    fm = m.group(1)
    def g(k):
        r = re.search(rf'^{k}:\s*(.+)', fm, re.MULTILINE)
        return r.group(1).strip() if r else ''
    lm = re.search(r'## Process log\n(.*?)$', txt, re.DOTALL)
    log = lm.group(1).strip() if lm else ''
    houses.append({
        'path': path,
        'funda_id': g('funda_id'),
        'address': g('address'),
        'city': g('city'),
        'status': g('status'),
        'requested': g('requested'),
        'log_tail': log[-400:]
    })
print(json.dumps(houses, indent=2))

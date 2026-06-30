import glob, re

houses = []
for path in sorted(glob.glob('houses/*.md')):
    with open(path) as f:
        content = f.read()
    m = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if not m:
        continue
    fm = m.group(1)
    def get(key, fm=fm):
        r = re.search(r'^' + key + r':\s*(.+)$', fm, re.MULTILINE)
        return r.group(1).strip() if r else ''
    houses.append({
        'path': path,
        'funda_id': get('funda_id'),
        'address': get('address'),
        'city': get('city'),
        'status': get('status'),
        'requested': get('requested'),
    })

for h in houses:
    print(f"{h['address']} | {h['city']} | {h['status']}")

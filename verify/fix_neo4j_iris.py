import json, sys
p = sys.argv[1]
d = json.load(open(p))
for r in d.get('rows', []):
    for i, v in enumerate(d['vars']):
        if v in ('country', 'segment') and r[i]:
            r[i] = ['iri', r[i][1]]
json.dump(d, open(p, 'w'))

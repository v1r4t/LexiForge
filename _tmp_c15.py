import json

a = json.load(open('data/assignment.json'))
g = json.load(open('data/glossary.json'))
gm = {x['term_id']: x for x in g}
c = a['15']
print('real:', c['real'])
for t in c['real']:
    print(t, gm[t]['canonical'])
print('fictional:', c['fictional'])
for t in c['fictional']:
    print(t, gm[t]['canonical'])
print('hnp:', c['hard_negative_pair'])
for t in c['hard_negative_pair']:
    print(t, gm[t]['canonical'])
print('oov:', c['oov'])

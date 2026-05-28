import sys
lines = open('docs/experiments/roguelike_long_task/index.html', 'r', encoding='utf-8').readlines()
print('=== ENTITY DRAW ===')
for i,l in enumerate(lines):
    if ('Entity' in l and 'draw' in l) or ('prototype' in l and 'draw' in l) or ('this.draw' in l) or ('draw:' in l):
        print(f'{i+1}: {l.rstrip()}')
print('=== PLAYER FALLBACK ===')
for i,l in enumerate(lines):
    if 'fallback' in l or 'playerCanvas' in l or 'pctx' in l:
        print(f'{i+1}: {l.rstrip()}')
print('=== ENEMY CONSTRUCTOR & DRAW ===')
for i,l in enumerate(lines):
    if 'Enemy' in l and ('class' in l or 'constructor' in l or 'draw' in l or 'this.img' in l):
        print(f'{i+1}: {l.rstrip()}')
print('=== BOSS CONSTRUCTOR & DRAW ===')
for i,l in enumerate(lines):
    if 'Boss' in l and ('class' in l or 'constructor' in l or 'draw' in l or 'this.img' in l):
        print(f'{i+1}: {l.rstrip()}')
print('=== TILE / MAP RENDER ===')
for i,l in enumerate(lines):
    if 'tile' in l.lower() or 'drawMap' in l or 'renderMap' in l or 'drawRoom' in l or ('ctx.fillRect' in l and 'cell' in l):
        print(f'{i+1}: {l.rstrip()}')

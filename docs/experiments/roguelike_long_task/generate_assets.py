import struct, zlib, os

def chunk(ct, data):
    c = ct + data
    return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)

def make_png(w, h, pixels):
    raw = b''
    for row in pixels:
        raw += b'\x00'
        for r,g,b,a in row:
            raw += struct.pack('BBBB', r, g, b, a)
    ihdr = struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')

def write_png(path, w, h, pixels):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(make_png(w, h, pixels))
    print(f'Written: {path}')

# --- player.png ---
w, h = 256, 256
pixels = []
for y in range(h):
    row = []
    for x in range(w):
        r,g,b,a = 0,0,0,0
        # head
        if 100 <= x <= 156 and 30 <= y <= 79:
            r,g,b,a = 255, 200, 150, 255
        # eyes
        if 110 <= x <= 125 and 46 <= y <= 55:
            r,g,b,a = 0, 0, 0, 255
        if 135 <= x <= 150 and 46 <= y <= 55:
            r,g,b,a = 0, 0, 0, 255
        # body
        if 90 <= x <= 166 and 80 <= y <= 200:
            r,g,b,a = 30, 80, 200, 255
        # belt
        if 90 <= x <= 166 and 138 <= y <= 148:
            r,g,b,a = 120, 80, 40, 255
        # legs
        if 90 <= x <= 120 and 170 <= y <= 220:
            r,g,b,a = 20, 60, 160, 255
        if 136 <= x <= 166 and 170 <= y <= 220:
            r,g,b,a = 20, 60, 160, 255
        # boots
        if 80 <= x <= 120 and 220 <= y <= 240:
            r,g,b,a = 80, 50, 20, 255
        if 136 <= x <= 176 and 220 <= y <= 240:
            r,g,b,a = 80, 50, 20, 255
        # sword blade
        if 170 <= x <= 185 and 70 <= y <= 160:
            r,g,b,a = 180, 180, 180, 255
        # sword guard
        if 156 <= x <= 170 and 105 <= y <= 115:
            r,g,b,a = 120, 70, 20, 255
        row.append((r,g,b,a))
    pixels.append(row)
write_png('docs/experiments/roguelike_long_task/assets/player.png', w, h, pixels)

# --- skeleton_warrior.png ---
w, h = 256, 256
pixels = []
for y in range(h):
    row = []
    for x in range(w):
        r,g,b,a = 0,0,0,0
        # skull
        if 100 <= x <= 156 and 30 <= y <= 70:
            r,g,b,a = 220, 220, 200, 255
        # eye sockets
        if 110 <= x <= 125 and 44 <= y <= 54:
            r,g,b,a = 0, 0, 0, 255
        if 135 <= x <= 150 and 44 <= y <= 54:
            r,g,b,a = 0, 0, 0, 255
        # ribcage
        for ry in range(80, 140, 8):
            if 100 <= x <= 156 and ry <= y <= ry+4:
                r,g,b,a = 200, 200, 180, 255
        # spine
        if 118 <= x <= 138 and 80 <= y <= 180:
            r,g,b,a = 200, 200, 180, 255
        # pelvis
        if 95 <= x <= 161 and 180 <= y <= 195:
            r,g,b,a = 200, 200, 180, 255
        # legs bones
        if 95 <= x <= 110 and 195 <= y <= 240:
            r,g,b,a = 200, 200, 180, 255
        if 145 <= x <= 160 and 195 <= y <= 240:
            r,g,b,a = 200, 200, 180, 255
        # sword
        if 170 <= x <= 185 and 60 <= y <= 150:
            r,g,b,a = 180, 180, 180, 255
        row.append((r,g,b,a))
    pixels.append(row)
write_png('docs/experiments/roguelike_long_task/assets/skeleton_warrior.png', w, h, pixels)

# --- skeleton_archer.png ---
w, h = 256, 256
pixels = []
for y in range(h):
    row = []
    for x in range(w):
        r,g,b,a = 0,0,0,0
        # skull
        if 100 <= x <= 156 and 30 <= y <= 70:
            r,g,b,a = 220, 220, 200, 255
        if 110 <= x <= 125 and 44 <= y <= 54:
            r,g,b,a = 0,0,0,255
        if 135 <= x <= 150 and 44 <= y <= 54:
            r,g,b,a = 0,0,0,255
        # ribs
        for ry in range(80, 140, 8):
            if 100 <= x <= 156 and ry <= y <= ry+4:
                r,g,b,a = 200, 200, 180, 255
        if 118 <= x <= 138 and 80 <= y <= 180:
            r,g,b,a = 200, 200, 180, 255
        # bow (left side)
        if 60 <= x <= 75 and 70 <= y <= 150:
            r,g,b,a = 150, 100, 50, 255
        # arrow
        if 50 <= x <= 90 and 108 <= y <= 112:
            r,g,b,a = 200, 150, 100, 255
        row.append((r,g,b,a))
    pixels.append(row)
write_png('docs/experiments/roguelike_long_task/assets/skeleton_archer.png', w, h, pixels)

# --- shadow_assassin.png ---
w, h = 256, 256
pixels = []
for y in range(h):
    row = []
    for x in range(w):
        r,g,b,a = 0,0,0,0
        # dark silhouette
        if 90 <= x <= 166 and 40 <= y <= 220:
            r,g,b,a = 40, 40, 50, 200
        # head
        if 110 <= x <= 146 and 40 <= y <= 80:
            r,g,b,a = 60, 60, 70, 240
        # eyes (glowing red)
        if 115 <= x <= 125 and 52 <= y <= 60:
            r,g,b,a = 255, 0, 0, 255
        if 131 <= x <= 141 and 52 <= y <= 60:
            r,g,b,a = 255, 0, 0, 255
        # daggers
        if 70 <= x <= 85 and 100 <= y <= 150:
            r,g,b,a = 100, 100, 110, 255
        if 170 <= x <= 185 and 100 <= y <= 150:
            r,g,b,a = 100, 100, 110, 255
        row.append((r,g,b,a))
    pixels.append(row)
write_png('docs/experiments/roguelike_long_task/assets/shadow_assassin.png', w, h, pixels)

# --- boss.png (dark knight) ---
w, h = 256, 256
pixels = []
for y in range(h):
    row = []
    for x in range(w):
        r,g,b,a = 0,0,0,0
        # large body
        if 60 <= x <= 196 and 50 <= y <= 230:
            r,g,b,a = 80, 20, 80, 255
        # helmet with horns
        if 90 <= x <= 166 and 20 <= y <= 70:
            r,g,b,a = 60, 10, 60, 255
        # left horn
        if 70 <= x <= 85 and 10 <= y <= 30:
            r,g,b,a = 120, 30, 30, 255
        if 80 <= x <= 90 and 10 <= y <= 50:
            r,g,b,a = 120, 30, 30, 255
        # right horn
        if 170 <= x <= 185 and 10 <= y <= 30:
            r,g,b,a = 120, 30, 30, 255
        if 166 <= x <= 176 and 10 <= y <= 50:
            r,g,b,a = 120, 30, 30, 255
        # glowing eyes
        if 108 <= x <= 118 and 50 <= y <= 60:
            r,g,b,a = 255, 255, 0, 255
        if 138 <= x <= 148 and 50 <= y <= 60:
            r,g,b,a = 255, 255, 0, 255
        # sword
        if 200 <= x <= 215 and 90 <= y <= 180:
            r,g,b,a = 200, 50, 50, 255
        row.append((r,g,b,a))
    pixels.append(row)
write_png('docs/experiments/roguelike_long_task/assets/boss.png', w, h, pixels)

# --- tile_floor.png ---
w, h = 64, 64
pixels = []
for y in range(h):
    row = []
    for x in range(w):
        # simple stone tile pattern
        if (x // 16 + y // 16) % 2 == 0:
            r,g,b,a = 100, 100, 100, 255
        else:
            r,g,b,a = 80, 80, 80, 255
        # border lines
        if x % 16 == 0 or y % 16 == 0:
            r,g,b,a = 50, 50, 50, 255
        row.append((r,g,b,a))
    pixels.append(row)
write_png('docs/experiments/roguelike_long_task/assets/tile_floor.png', w, h, pixels)

print('All assets generated.')

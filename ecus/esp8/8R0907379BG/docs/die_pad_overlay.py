#!/usr/bin/env python3
"""Generate SVG overlay of TMS470R1B1M bare die pad positions.

Reads b1m_die_pads.csv (extracted from SM470R1B1M-HT datasheet Table 4-1)
and produces an SVG showing all 152 bond pads with signal labels.

Usage:
    python die_pad_overlay.py                         # default: all 4 rotations
    python die_pad_overlay.py --rotate 90             # single rotation (CW degrees)
    python die_pad_overlay.py --highlight can,jtag    # highlight groups
    python die_pad_overlay.py --bonded-only           # show only likely bonded pads
    python die_pad_overlay.py --label-mode compact    # shorter labels (signal only)
    python die_pad_overlay.py -o overlay.svg          # custom output path
"""
import argparse
import csv
import math
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV = os.path.join(SCRIPT_DIR, 'b1m_die_pads.csv')

DIE_W = 5304.99  # um
DIE_H = 5382.01  # um

PAD_GROUPS = {
    'power':  {'VCC', 'VSS', 'VCCIO', 'VSSIO', 'VCCAD', 'VSSAD', 'VCCP'},
    'can':    {'CAN1HRX', 'CAN1HTX', 'CAN2HRX', 'CAN2HTX'},
    'jtag':   {'TDI', 'TDO', 'TCK', 'TMS', 'TMS2', 'TRST'},
    'adc':    {'ADREFHI', 'ADREFLO', 'ADEVT',
               'ADIN[0]', 'ADIN[1]', 'ADIN[2]', 'ADIN[3]', 'ADIN[4]',
               'ADIN[5]', 'ADIN[6]', 'ADIN[7]', 'ADIN[8]', 'ADIN[9]',
               'ADIN[10]', 'ADIN[11]'},
    'reset':  {'RST', 'PORRST'},
    'osc':    {'OSCIN', 'OSCOUT'},
    'het':    {'HET[0]', 'HET[1]', 'HET[2]', 'HET[3]', 'HET[4]', 'HET[5]',
               'HET[6]', 'HET[7]', 'HET[8]', 'HET[18]', 'HET[20]', 'HET[22]'},
    'spi':    {'SPI1CLK', 'SPI1SIMO', 'SPI1SOMI', 'SPI1ENA', 'SPI1SCS',
               'SPI2CLK', 'SPI2SIMO', 'SPI2SOMI', 'SPI2ENA', 'SPI2SCS'},
    'sci':    {'SCI1TX', 'SCI1RX', 'SCI1CLK', 'SCI2TX', 'SCI2RX', 'SCI2CLK',
               'SCI3TX', 'SCI3RX', 'SCI3CLK'},
    'i2c':    {'I2C1SCL', 'I2C1SDA', 'I2C2SCL', 'I2C2SDA', 'I2C3SCL', 'I2C3SDA',
               'I2C4SCL', 'I2C4SDA', 'I2C5SCL', 'I2C5SDA'},
    'test':   {'TEST'},
}

GROUP_COLORS = {
    'power':  '#ff4444',
    'can':    '#00cc00',
    'jtag':   '#ff8800',
    'adc':    '#8844ff',
    'reset':  '#ff00ff',
    'osc':    '#00cccc',
    'het':    '#4488ff',
    'spi':    '#888888',
    'sci':    '#888888',
    'i2c':    '#888888',
    'test':   '#666666',
    'gpio':   '#aaaaaa',
}

ESP8_BONDED = {
    'VCC', 'VSS', 'VCCIO', 'VSSIO', 'VCCAD', 'VSSAD', 'VCCP',
    'CAN1HRX', 'CAN1HTX', 'CAN2HRX', 'CAN2HTX',
    'OSCIN', 'OSCOUT', 'PORRST', 'RST',
    'ADREFHI', 'ADREFLO',
}


def get_group(signal):
    for gname, sigs in PAD_GROUPS.items():
        if signal in sigs:
            return gname
    if signal.startswith('GIO') or '/ECLK' in signal:
        return 'gpio'
    return 'gpio'


def load_pads(csv_path):
    pads = []
    with open(csv_path, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            pads.append({
                'die_pad': int(row['die_pad']),
                'lqfp_pin': int(row['lqfp_pin']) if row['lqfp_pin'] else None,
                'signal': row['signal'],
                'xmin': float(row['x_min_um']),
                'ymin': float(row['y_min_um']),
                'xmax': float(row['x_max_um']),
                'ymax': float(row['y_max_um']),
                'xcenter': float(row['x_center_um']),
                'ycenter': float(row['y_center_um']),
                'is_test': row['is_test_pad'] == 'yes',
                'side': row['side'],
            })
    return pads


def mirror_pads(pads):
    """Horizontal flip about the vertical centreline (x -> DIE_W - x).

    Use when the die photo is mirrored relative to the datasheet coordinate
    convention (e.g. imaged through the back, or a flipped capture). Swaps the
    left/right edges and reverses left-right order along the top/bottom edges.
    Combine with --rotate to cover all 8 possible die orientations.
    """
    for p in pads:
        p['xcenter'] = DIE_W - p['xcenter']
        p['xmin'], p['xmax'] = DIE_W - p['xmax'], DIE_W - p['xmin']
        if p['side'] == 'left':
            p['side'] = 'right'
        elif p['side'] == 'right':
            p['side'] = 'left'
    return pads


def rotate_point(x, y, deg, cx, cy):
    """Rotate (x,y) around (cx,cy) by deg degrees clockwise."""
    rad = math.radians(-deg)
    dx, dy = x - cx, y - cy
    rx = dx * math.cos(rad) - dy * math.sin(rad) + cx
    ry = dx * math.sin(rad) + dy * math.cos(rad) + cy
    return rx, ry


def rotated_side(side, deg):
    """What side does 'side' map to after CW rotation by deg?"""
    order = ['bottom', 'right', 'top', 'left']
    steps = (deg // 90) % 4
    idx = order.index(side)
    return order[(idx + steps) % 4]


def generate_single_svg(pads, rotate_deg=0, highlight=None, bonded_only=False,
                        opacity=0.7, label_mode='full', margin=600):
    """Generate SVG body for one rotation. Returns (svg_body, content_w, content_h)."""
    # After rotation the bounding box changes
    if rotate_deg in (0, 180):
        content_w, content_h = DIE_W, DIE_H
    else:
        content_w, content_h = DIE_H, DIE_W

    # Die center in screen coords (before rotation)
    cx_scr = DIE_W / 2
    cy_scr = DIE_H / 2

    highlight_groups = set()
    if highlight:
        for h in highlight.split(','):
            highlight_groups.add(h.strip().lower())

    lines = []

    # Die outline
    lines.append(f'<rect x="{margin}" y="{margin}" '
                 f'width="{content_w:.0f}" height="{content_h:.0f}" '
                 f'fill="none" stroke="#444" stroke-width="3" stroke-dasharray="20,10"/>')

    # Offset to re-center after rotation
    if rotate_deg in (0, 180):
        off_x, off_y = 0, 0
    else:
        off_x = -(DIE_W - DIE_H) / 2
        off_y = (DIE_W - DIE_H) / 2

    for pad in pads:
        group = get_group(pad['signal'])
        color = GROUP_COLORS.get(group, '#aaaaaa')

        if bonded_only and pad['signal'] not in ESP8_BONDED and not pad['is_test']:
            continue

        if highlight_groups and group not in highlight_groups:
            alpha = 0.12
        else:
            alpha = opacity

        # Convert to screen coords (flip Y)
        pcx = pad['xcenter']
        pcy = DIE_H - pad['ycenter']
        pw = pad['xmax'] - pad['xmin']
        ph = pad['ymax'] - pad['ymin']

        # Rotate around die center
        rcx, rcy = rotate_point(pcx, pcy, rotate_deg, cx_scr, cy_scr)

        # Apply offset + margin
        sx = margin + rcx + off_x
        sy = margin + rcy + off_y

        is_bonded = pad['signal'] in ESP8_BONDED
        stroke = '#000' if is_bonded else '#555'
        sw = 3 if is_bonded else 1

        # Pad rectangle (swap w/h for 90/270 rotation)
        if rotate_deg in (0, 180):
            rw, rh = pw, ph
        else:
            rw, rh = ph, pw

        lines.append(f'<rect x="{sx - rw/2:.1f}" y="{sy - rh/2:.1f}" '
                     f'width="{rw:.1f}" height="{rh:.1f}" '
                     f'fill="{color}" fill-opacity="{alpha:.2f}" '
                     f'stroke="{stroke}" stroke-width="{sw}"/>')

        # Label
        if label_mode == 'compact':
            label = pad['signal']
        elif label_mode == 'pin':
            label = str(pad['lqfp_pin']) if pad['lqfp_pin'] else 'T'
        else:
            label = f"{pad['lqfp_pin']}:{pad['signal']}" if pad['lqfp_pin'] else f"T{pad['die_pad']}"

        rot_side = rotated_side(pad['side'], rotate_deg)

        if rot_side == 'bottom':
            tx, ty = sx, sy + 50
            anchor, rot = 'start', -90
        elif rot_side == 'right':
            tx, ty = sx + 50, sy + 5
            anchor, rot = 'start', 0
        elif rot_side == 'top':
            tx, ty = sx, sy - 50
            anchor, rot = 'end', -90
        else:
            tx, ty = sx - 50, sy + 5
            anchor, rot = 'end', 0

        fsize = 38 if len(label) < 12 else 30

        lines.append(f'<text x="{tx:.1f}" y="{ty:.1f}" '
                     f'text-anchor="{anchor}" '
                     f'transform="rotate({rot},{tx:.1f},{ty:.1f})" '
                     f'font-family="monospace" font-size="{fsize}" '
                     f'fill="{color}" fill-opacity="{min(alpha + 0.3, 1.0):.2f}">'
                     f'{label}</text>')

    # Pin 1 marker
    p1 = [p for p in pads if p['die_pad'] == 1][0]
    p1cx, p1cy = p1['xcenter'], DIE_H - p1['ycenter']
    rp1x, rp1y = rotate_point(p1cx, p1cy, rotate_deg, cx_scr, cy_scr)
    mp1x = margin + rp1x + off_x
    mp1y = margin + rp1y + off_y
    lines.append(f'<circle cx="{mp1x:.0f}" cy="{mp1y:.0f}" r="50" '
                 f'fill="none" stroke="red" stroke-width="4"/>')
    lines.append(f'<text x="{mp1x:.0f}" y="{mp1y - 60:.0f}" text-anchor="middle" '
                 f'font-family="sans-serif" font-size="50" font-weight="bold" fill="red">'
                 f'PIN1</text>')

    return '\n'.join(lines), content_w, content_h


def generate_quad_svg(pads, highlight=None, bonded_only=False, opacity=0.7, label_mode='full'):
    """2x2 grid showing all 4 rotations."""
    margin = 450
    cell_w = max(DIE_W, DIE_H) + 2 * margin
    cell_h = cell_w
    gap = 100
    total_w = cell_w * 2 + gap
    total_h = cell_h * 2 + gap + 150

    lines = []
    lines.append(f'<svg xmlns="http://www.w3.org/2000/svg" '
                 f'viewBox="0 0 {total_w:.0f} {total_h:.0f}" '
                 f'width="{total_w/6:.0f}" height="{total_h/6:.0f}">')

    lines.append(f'<rect width="{total_w:.0f}" height="{total_h:.0f}" fill="white" fill-opacity="0.0"/>')

    lines.append(f'<text x="{total_w/2:.0f}" y="90" text-anchor="middle" '
                 f'font-family="sans-serif" font-size="75" font-weight="bold" fill="#222">'
                 f'SM470R1B1M-HT Bare Die — 4 Rotations</text>')

    for idx, (deg, title) in enumerate([(0, '0 deg (datasheet)'),
                                         (90, '90 deg CW'),
                                         (180, '180 deg'),
                                         (270, '270 deg CW')]):
        col = idx % 2
        row = idx // 2
        ox = col * (cell_w + gap)
        oy = row * (cell_h + gap) + 150

        lines.append(f'<text x="{ox + cell_w/2:.0f}" y="{oy + 55:.0f}" '
                     f'text-anchor="middle" '
                     f'font-family="sans-serif" font-size="55" fill="#444">{title}</text>')

        body, cw, ch = generate_single_svg(pads, rotate_deg=deg, highlight=highlight,
                                            bonded_only=bonded_only, opacity=opacity,
                                            label_mode=label_mode, margin=margin)
        # Center the content in the cell
        dx = (cell_w - cw - 2 * margin) / 2
        dy = (cell_h - ch - 2 * margin) / 2
        lines.append(f'<g transform="translate({ox + dx:.0f},{oy + 70 + dy:.0f})">')
        lines.append(body)
        lines.append('</g>')

    lines.append('</svg>')
    return '\n'.join(lines)


def generate_svg(pads, rotate_deg=0, highlight=None, bonded_only=False,
                 opacity=0.7, label_mode='full'):
    """Single-rotation SVG."""
    margin = 600

    if rotate_deg in (0, 180):
        die_w, die_h = DIE_W, DIE_H
    else:
        die_w, die_h = DIE_H, DIE_W

    svg_w = die_w + 2 * margin
    svg_h = die_h + 2 * margin + 400

    lines = []
    lines.append(f'<svg xmlns="http://www.w3.org/2000/svg" '
                 f'viewBox="0 0 {svg_w:.0f} {svg_h:.0f}" '
                 f'width="{svg_w/5:.0f}" height="{svg_h/5:.0f}">')

    lines.append(f'<rect width="{svg_w:.0f}" height="{svg_h:.0f}" fill="white" fill-opacity="0.0"/>')

    lines.append(f'<text x="{svg_w/2:.0f}" y="{margin - 80}" text-anchor="middle" '
                 f'font-family="sans-serif" font-size="65" font-weight="bold" fill="#222">'
                 f'SM470R1B1M-HT Bare Die ({rotate_deg} deg CW)</text>')

    body, _, _ = generate_single_svg(pads, rotate_deg=rotate_deg, highlight=highlight,
                                      bonded_only=bonded_only, opacity=opacity,
                                      label_mode=label_mode, margin=margin)
    lines.append(body)

    # Legend
    lx = margin + 100
    ly = margin + die_h + 150
    for i, (gname, gcolor) in enumerate(GROUP_COLORS.items()):
        lxi = lx + (i % 4) * 1300
        lyi = ly + (i // 4) * 70
        lines.append(f'<rect x="{lxi}" y="{lyi - 35}" width="40" height="40" '
                     f'fill="{gcolor}" fill-opacity="0.7"/>')
        lines.append(f'<text x="{lxi + 55}" y="{lyi}" '
                     f'font-family="sans-serif" font-size="50" fill="#333">{gname}</text>')

    lines.append(f'<text x="{svg_w/2:.0f}" y="{ly + 210}" '
                 f'text-anchor="middle" font-family="sans-serif" font-size="50" fill="#333">'
                 f'Die: {DIE_W:.0f} x {DIE_H:.0f} um  |  '
                 f'Pad: 65.1 x 65.1 um  |  '
                 f'Bold outline = likely bonded in ESP8  |  '
                 f'Red circle = Pin 1</text>')

    lines.append('</svg>')
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('-i', '--input', default=DEFAULT_CSV)
    ap.add_argument('-o', '--output', default=None)
    ap.add_argument('--rotate', type=int, default=None, choices=[0, 90, 180, 270],
                    help='Single rotation (CW degrees). Omit for all-4 quad view.')
    ap.add_argument('--highlight', default=None,
                    help='Comma-separated groups to highlight (e.g., can,jtag,power)')
    ap.add_argument('--bonded-only', action='store_true')
    ap.add_argument('--mirror', action='store_true',
                    help='Horizontal flip (x -> DIE_W - x) for a mirrored die image. '
                         'Combine with --rotate to cover all 8 orientations.')
    ap.add_argument('--opacity', type=float, default=0.7)
    ap.add_argument('--label-mode', default='full', choices=['full', 'compact', 'pin'],
                    help='full=pin:signal, compact=signal only, pin=pin number only')

    args = ap.parse_args()

    mtag = '_mirror' if args.mirror else ''
    if args.output is None:
        d = os.path.dirname(args.input)
        if args.rotate is not None:
            args.output = os.path.join(d, f'b1m_die_overlay_{args.rotate}deg{mtag}.svg')
        else:
            args.output = os.path.join(d, f'b1m_die_overlay_quad{mtag}.svg')

    pads = load_pads(args.input)
    if args.mirror:
        pads = mirror_pads(pads)
    print(f"Loaded {len(pads)} pads from {args.input}" + (" (mirrored)" if args.mirror else ""))

    if args.rotate is not None:
        svg = generate_svg(pads, rotate_deg=args.rotate, highlight=args.highlight,
                           bonded_only=args.bonded_only, opacity=args.opacity,
                           label_mode=args.label_mode)
    else:
        svg = generate_quad_svg(pads, highlight=args.highlight,
                                bonded_only=args.bonded_only, opacity=args.opacity,
                                label_mode=args.label_mode)

    with open(args.output, 'w') as f:
        f.write(svg)

    size_kb = os.path.getsize(args.output) / 1024
    print(f"SVG written to {args.output} ({size_kb:.1f} KB)")


if __name__ == '__main__':
    main()

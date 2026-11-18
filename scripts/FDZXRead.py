#!/usr/bin/env python3
"""FDZXRead.py - Extract programs from AERCO FD-ZX (ZX81/TS1000) disk images.

Handles the two directory schemes found on FD-ZX disks:
  * AERCO stock DOS ("SADOS+ 16K/64K", 8/83): 20 numbered "pages", names kept
    in the Q$(20,24) array inside the DOS BASIC program on page 1.
  * BBDOS 4.0 (Bill Bell, 1986): 512-byte directory (32-byte header + 20 x
    24-byte entries) stored in side 0 / track 3 / sector 1 (copy in sector 2).

Physical layout (both): 40 tracks x 2 sides x 10 sectors x 512 bytes (DD) =
409,600 bytes.  Image order is track-major with sides interleaved:
    offset = ((track * 2) + side) * 5120 + (sector - 1) * 512
A 16K "page" is 4 consecutive tracks on one side (20,480 bytes) holding a raw
memory image starting at 16393 (VERSN) - i.e. exactly a .P file plus slack.
Pages 1-10 are side 0 tracks 0-3, 4-7 ... 36-39 (outside -> in); pages 11-20
are the same on side 1.  A "64K" page is 3 consecutive 16K pages (61,440 B),
again a linear memory image from 16393.

Usage: FDZXRead.py -f IMAGE.img [-o OUTDIR] [--all-pages]

Programs are written as .p files (the memory image from 16393 up to E_LINE);
pages holding code are also kept as raw .bin with their load address. A
manifest.txt / manifest.json is written to OUTDIR (default: the image name).
"""
import argparse, os, struct, sys, json

TRACKS, SIDES, SECTORS, SECSIZE = 40, 2, 10, 512
TRACKSIZE = SECTORS * SECSIZE
PAGE16 = 4 * TRACKSIZE
SYSBASE = 16393  # .P files start at VERSN

ZXCH = ' ??????????"£$:?()><=+-*/;,.0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'


def zx2asc(b):
    out = []
    for c in b:
        if c < 64:
            out.append(ZXCH[c])
        elif 128 <= c < 192:          # inverse video -> lower case
            out.append(ZXCH[c - 128].lower())
        else:
            out.append('?')
    return ''.join(out)


def safe(name):
    s = ''.join(ch if ch.isalnum() or ch in '-_.' else '_' for ch in name.strip())
    return s.strip('_.') or 'unnamed'


class Disk:
    def __init__(self, path):
        self.data = open(path, 'rb').read()
        if len(self.data) != TRACKS * SIDES * TRACKSIZE:
            raise SystemExit('unexpected image size %d' % len(self.data))

    def track(self, t, side):
        o = (t * 2 + side) * TRACKSIZE
        return self.data[o:o + TRACKSIZE]

    def sector(self, t, side, s):
        o = (t * 2 + side) * TRACKSIZE + (s - 1) * SECSIZE
        return self.data[o:o + SECSIZE]

    def page(self, n):
        """16K page n (1..20)."""
        side, slot = divmod(n - 1, 10)
        return b''.join(self.track(4 * slot + i, side) for i in range(4))

    def page64(self, first):
        return b''.join(self.page(first + i) for i in range(3))


def sysvars(img):
    w = lambda k: struct.unpack_from('<H', img, k)[0]
    return dict(VERSN=img[0], E_PPC=w(1), D_FILE=w(3), DF_CC=w(5), VARS=w(7),
                DEST=w(9), E_LINE=w(11), NXTLIN=w(41) if len(img) > 42 else 0)


def valid_prog(img):
    sv = sysvars(img)
    if not (SYSBASE + 116 <= sv['D_FILE'] < sv['VARS'] < sv['E_LINE']):
        return False, sv
    if sv['E_LINE'] - SYSBASE > len(img):
        return False, sv
    if img[sv['D_FILE'] - SYSBASE] != 0x76:      # display file starts with NEWLINE
        return False, sv
    if img[sv['E_LINE'] - SYSBASE - 1] != 0x80:  # variables end marker
        return False, sv
    return True, sv


def list_lines(img, sv):
    """Return (count, first, last) BASIC line numbers."""
    p, end, nums = 116, sv['D_FILE'] - SYSBASE, []
    while p + 4 <= end:
        n = img[p] * 256 + img[p + 1]
        ln = img[p + 2] | img[p + 3] << 8
        if n > 9999 or ln == 0:
            break
        nums.append(n)
        p += 4 + ln
    return nums


def sados_names(page1):
    """Q$() array from the SADOS DOS program's variables."""
    ok, sv = valid_prog(page1)
    if not ok:
        return None
    w = lambda k: struct.unpack_from('<H', page1, k)[0]
    p, e = sv['VARS'] - SYSBASE, sv['E_LINE'] - SYSBASE
    while p < e and page1[p] != 0x80:
        b = page1[p]; t = b >> 5
        if t == 3: p += 6
        elif t == 2: p += 3 + w(p + 1)
        elif t == 5:
            q = p + 1
            while not page1[q] & 0x80: q += 1
            p = q + 6
        elif t == 4: p += 3 + w(p + 1)
        elif t == 7: p += 18
        elif t == 6:
            n = w(p + 1); nd = page1[p + 3]
            dims = [w(p + 4 + 2 * i) for i in range(nd)]
            if (b & 0x1f) == 0x16 and nd == 2:      # Q$
                d = page1[p + 4 + 2 * nd:p + 3 + n]
                return [zx2asc(d[i * dims[1]:(i + 1) * dims[1]]).rstrip()
                        for i in range(dims[0])]
            p += 3 + n
        else:
            return None
    return None


def bbdos_dir(disk):
    sec = disk.sector(3, 0, 1)
    if zx2asc(sec[:9]) != 'DIRECTORY':
        return None
    hdr = zx2asc(sec[:32]).rstrip()
    ents = []
    for k in range(20):
        e = sec[32 + 24 * k:56 + 24 * k]
        cur, init = e[0], e[1]
        rd, wr, iwr = struct.unpack_from('<HHH', e, 2)
        ents.append(dict(slot=k + 1, cur=cur, init=init, read=rd, write=wr,
                         iwrite=iwr, page=rd - 0x3002, name=zx2asc(e[9:24]).rstrip(),
                         inuse=bool(cur & 1), prog=bool(cur & 2), vars=bool(cur & 4),
                         k16=bool(cur & 0x10), k64=bool(cur & 0x40), end=bool(cur & 0x80)))
    copy_ok = disk.sector(3, 0, 2) == sec
    return hdr, ents, copy_ok


def emit(outdir, base, img, note, manifest, kind_hint=''):
    ok, sv = valid_prog(img)
    rec = dict(file=None, note=note)
    if ok and kind_hint != 'vars':
        body = img[:sv['E_LINE'] - SYSBASE]
        fn = base + '.p'
        open(os.path.join(outdir, fn), 'wb').write(body)
        nums = list_lines(img, sv)
        rec.update(file=fn, type='ZX81 BASIC (.p)', size=len(body),
                   lines=len(nums), first_line=nums[0] if nums else None,
                   last_line=nums[-1] if nums else None,
                   prog_bytes=sv['D_FILE'] - 16509, vars_bytes=sv['E_LINE'] - sv['VARS'])
        if sv['D_FILE'] == 16509 and sv['E_LINE'] - sv['VARS'] > 1:
            rec['note'] += '; NON-STANDARD layout: no BASIC before D_FILE, code/BASIC kept in VARS area (BBDOS/Hot-Z loader)'
        elif sv['D_FILE'] == 16509:
            rec['note'] += '; EMPTY program (NEW state)'
    else:
        fn = base + '.bin'
        open(os.path.join(outdir, fn), 'wb').write(img)
        rec.update(file=fn, type='raw memory image', size=len(img), load_address=SYSBASE,
                   sysvars_valid=ok)
    manifest.append(rec)
    return rec


def main():
    ap = argparse.ArgumentParser(description='Extract programs from AERCO FD-ZX (ZX81/TS1000) disk images')
    ap.add_argument('-f', '--imgfile', required=True, help='IMG filename for input')
    ap.add_argument('-o', '--outdir', help='output directory (default: image name without .img)')
    ap.add_argument('--all-pages', action='store_true', help='also write non-empty pages with no valid program')
    opts = ap.parse_args()
    allpages = opts.all_pages
    args = [opts.imgfile]
    outdir = opts.outdir or os.path.splitext(os.path.basename(opts.imgfile))[0]
    disk = Disk(args[0])
    os.makedirs(outdir, exist_ok=True)
    manifest, used = [], set()
    p1 = disk.page(1)
    bb = bbdos_dir(disk)
    if bb:
        hdr, ents, copy_ok = bb
        fmt = 'BBDOS'
        info = dict(format='BBDOS 4.0', header=hdr, dir_backup_identical=copy_ok)
        for e in ents:
            if not e['inuse']:
                continue
            if e['k64'] and not e['name'] and e['page'] in used:
                continue
            if e['k64']:
                pages = [e['page'], e['page'] + 1, e['page'] + 2]
                img = disk.page64(e['page'])
            else:
                pages = [e['page']]
                img = disk.page(e['page'])
            if not e['name'] and e['page'] in used:
                continue
            used.update(pages)
            base = '%02d_%s' % (e['page'], safe(e['name']))
            note = 'dir slot %d, %s %s page(s) %s, flags cur=%02X init=%02X' % (
                e['slot'], '64K' if e['k64'] else '16K',
                'VARS' if e['vars'] else 'PROG', pages, e['cur'], e['init'])
            rec = emit(outdir, base, img, note, manifest, 'vars' if e['vars'] else '')
            rec.update(name=e['name'], pages=pages)
            if e['page'] == 1:   # keep the whole DOS page (code/overlay lives past E_LINE)
                fn = base + '_page1_full.bin'
                open(os.path.join(outdir, fn), 'wb').write(p1)
                manifest.append(dict(file=fn, name=e['name'] + ' (full page 1 image)',
                                     type='raw memory image', size=len(p1),
                                     load_address=SYSBASE, pages=[1]))
        # mark 64K continuation entries as used
        for e in ents:
            if e['inuse'] and not e['name']:
                used.add(e['page'])
    else:
        names = sados_names(p1)
        if names is None:
            raise SystemExit('not a recognised FD-ZX disk (no BBDOS dir, no SADOS Q$)')
        fmt = 'SADOS'
        info = dict(format='AERCO SADOS (16K page directory in Q$)', header=None)
        for i, nm in enumerate(names, 1):
            if not nm:
                continue
            img = disk.page(i)
            used.add(i)
            rec = emit(outdir, '%02d_%s' % (i, safe(nm)), img, 'page %d (16K)' % i, manifest)
            rec.update(name=nm, pages=[i])
    # pages holding data not accounted for by the directory
    for n in range(1, 21):
        if n in used:
            continue
        img = disk.page(n)
        if len(set(img)) <= 2:
            continue
        ok, sv = valid_prog(img)
        tag = 'unlisted'
        if fmt == 'SADOS' and n in (10, 11, 20) and img[3:13] == p1[3:13]:
            tag = 'boot-copy'  # AERCO writes the 16K DOS to all 4 "corners"
        if ok or allpages:
            rec = emit(outdir, '%02d_%s' % (n, tag), img,
                       'page %d not in directory (%s; stale/leftover data)' % (n, tag), manifest)
            rec.update(name='(%s page %d)' % (tag, n), pages=[n])
        else:
            manifest.append(dict(file=None, name='(page %d)' % n, pages=[n],
                                 note='non-empty page, not in directory, no valid sysvars'))
    info['image'] = os.path.basename(args[0])
    info['files'] = manifest
    json.dump(info, open(os.path.join(outdir, 'manifest.json'), 'w'), indent=1)
    with open(os.path.join(outdir, 'manifest.txt'), 'w') as f:
        f.write('%s  [%s]  %s\n\n' % (info['image'], info['format'], info.get('header') or ''))
        for r in manifest:
            f.write('%-28s %-22s %6s  pages %-12s %s\n' % (
                r.get('file') or '-', (r.get('name') or '')[:22], r.get('size', ''),
                ','.join(map(str, r.get('pages', []))), r.get('note', '')))
            if r.get('lines') is not None:
                f.write('%28s lines=%d (%s-%s) prog=%dB vars=%dB\n' % (
                    '', r['lines'], r['first_line'], r['last_line'], r['prog_bytes'], r['vars_bytes']))
            if r.get('load_address'):
                f.write('%28s raw, load address %d (0x%04X)\n' % ('', r['load_address'], r['load_address']))
    print(open(os.path.join(outdir, 'manifest.txt')).read())


if __name__ == '__main__':
    main()

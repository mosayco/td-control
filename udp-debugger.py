#!/usr/bin/env python3
"""
udp_logger.py — PixelBus UDP debug logger (Windows compatible)
"""

import socket
import struct
import argparse
import datetime

MAGIC       = bytes([0xAB, 0xCD])
LATCH_ID    = 0xFF
PACKET_SIZE = 773

def crc8(data: bytes) -> int:
    return sum(data) % 256

def ts() -> str:
    return datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]

def parse_packet(data: bytes) -> dict:
    if len(data) < 4:
        return {'type': 'SHORT', 'len': len(data)}

    magic   = data[0:2]
    cube_id = data[2]
    flags   = data[3]

    result = {
        'magic_ok': magic == MAGIC,
        'cube_id':  cube_id,
        'flags':    flags,
        'length':   len(data),
    }

    if cube_id == LATCH_ID:
        result['type'] = 'LATCH'
        return result

    result['type'] = 'FRAME'

    if len(data) == PACKET_SIZE:
        payload     = data[4:772]
        crc_recv    = data[772]
        crc_calc    = crc8(payload)
        result['crc_ok'] = (crc_recv == crc_calc)
        result['pixel_0']   = (payload[0],   payload[1],   payload[2])
        result['pixel_127'] = (payload[381], payload[382], payload[383])
        result['pixel_255'] = (payload[765], payload[766], payload[767])
        r0, g0, b0 = payload[0], payload[1], payload[2]
        result['solid'] = all(
            payload[i] == r0 and payload[i+1] == g0 and payload[i+2] == b0
            for i in range(0, 768, 3)
        )
    else:
        result['crc_ok'] = None

    return result

def format_packet(p: dict, sender: str, raw: bool, raw_data: bytes) -> str:
    lines = []
    now = ts()

    if p['type'] == 'LATCH':
        lines.append(f'[{now}] ── LATCH ─────────────────────────── from {sender}')
        return '\n'.join(lines)

    if p['type'] == 'SHORT':
        lines.append(f'[{now}] !! SHORT packet ({p["len"]} bytes) from {sender}')
        return '\n'.join(lines)

    magic_tag = '✓' if p['magic_ok'] else '✗ BAD MAGIC'
    crc_tag   = '✓' if p['crc_ok'] else ('✗ BAD CRC' if p['crc_ok'] is not None else '? (wrong size)')
    solid_tag = f'solid RGB{p["pixel_0"]}' if p.get('solid') else 'varied'

    lines.append(f'[{now}] FRAME  cube={p["cube_id"]}  {p["length"]}B  magic={magic_tag}  crc={crc_tag}')
    lines.append(f'         pixels: [{solid_tag}]  p[0]={p.get("pixel_0")}  p[127]={p.get("pixel_127")}  p[255]={p.get("pixel_255")}')

    if raw:
        hex_preview = raw_data[:16].hex(' ')
        lines.append(f'         hex[0:16]: {hex_preview} …')

    return '\n'.join(lines)

def make_socket_unicast(port: int) -> socket.socket:
    """Fallback: plain UDP on 0.0.0.0 — works when multicast isn't routing."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', port))
    return sock

def make_socket_multicast(port: int, group: str) -> socket.socket:
    """Multicast-joined socket — needed when TD sends to 239.x.x.x."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', port))
    # Windows-safe multicast join — use packed ints, not inet_aton
    group_int = struct.unpack('!I', socket.inet_pton(socket.AF_INET, group))[0]
    mreq = struct.pack('!II', group_int, socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    return sock

def main():
    parser = argparse.ArgumentParser(description='PixelBus UDP debug logger')
    parser.add_argument('--port',     type=int, default=6969,        help='UDP port (default 6969)')
    parser.add_argument('--group',    type=str, default='239.0.0.1', help='Multicast group')
    parser.add_argument('--raw',      action='store_true',           help='Show hex preview of each packet')
    parser.add_argument('--latch',    action='store_true',           help='Show LATCH packets')
    parser.add_argument('--unicast',  action='store_true',           help='Skip multicast join (plain UDP bind)')
    args = parser.parse_args()

    if args.unicast:
        sock = make_socket_unicast(args.port)
        print(f'PixelBus UDP logger — unicast mode, port {args.port}')
    else:
        try:
            sock = make_socket_multicast(args.port, args.group)
            print(f'PixelBus UDP logger — multicast {args.group}:{args.port}')
        except OSError as e:
            print(f'Multicast join failed ({e}), falling back to unicast on port {args.port}')
            sock = make_socket_unicast(args.port)

    print(f'Flags: raw={args.raw}  show_latch={args.latch}')
    print('─' * 60)

    frame_count = 0
    latch_count = 0
    error_count = 0

    try:
        while True:
            data, addr = sock.recvfrom(65535)
            sender = f'{addr[0]}:{addr[1]}'
            p = parse_packet(data)

            if p['type'] == 'LATCH':
                latch_count += 1
                if args.latch:
                    print(format_packet(p, sender, args.raw, data))
                continue

            if p['type'] == 'FRAME':
                frame_count += 1
                if not p['magic_ok'] or p['crc_ok'] == False:
                    error_count += 1

            print(format_packet(p, sender, args.raw, data))

            if frame_count % 10 == 0 and frame_count > 0:
                print(f'  ── {frame_count} frames  {latch_count} latches  {error_count} errors ──')

    except KeyboardInterrupt:
        print(f'\n{"─" * 60}')
        print(f'Stopped. Totals: {frame_count} frames  {latch_count} latches  {error_count} errors')
        sock.close()

if __name__ == '__main__':
    main()
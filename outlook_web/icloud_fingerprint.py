"""Apple FD wire encoding, ported from the pinned MIT icloud-mail reference.
Copyright (c) 2026 t508708. See third_party/icloud-mail-LICENSE.txt.
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

_CODES = {1: (4, 15), 110: (8, 239), 74: (8, 238), 57: (7, 118), 56: (7, 117), 71: (8, 233), 25: (8, 232), 101: (5, 28), 104: (7, 111), 4: (7, 110), 105: (6, 54), 5: (7, 107), 109: (7, 106), 103: (9, 423), 82: (9, 422), 26: (8, 210), 6: (7, 104), 46: (6, 51), 97: (6, 50), 111: (6, 49), 7: (7, 97), 45: (7, 96), 59: (5, 23), 15: (7, 91), 11: (8, 181), 72: (8, 180), 27: (8, 179), 28: (8, 178), 16: (7, 88), 88: (10, 703), 113: (11, 1405), 89: (12, 2809), 107: (13, 5617), 90: (14, 11233), 42: (15, 22465), 64: (16, 44929), 0: (16, 44928), 81: (9, 350), 29: (8, 174), 118: (8, 173), 30: (8, 172), 98: (8, 171), 12: (8, 170), 99: (7, 84), 117: (6, 41), 112: (6, 40), 102: (9, 319), 68: (9, 318), 31: (8, 158), 100: (7, 78), 84: (6, 38), 55: (6, 37), 17: (7, 73), 8: (7, 72), 9: (7, 71), 77: (7, 70), 18: (7, 69), 65: (7, 68), 48: (6, 33), 116: (6, 32), 10: (7, 63), 121: (8, 125), 78: (8, 124), 80: (7, 61), 69: (7, 60), 119: (7, 59), 13: (8, 117), 79: (8, 116), 19: (7, 57), 67: (7, 56), 114: (6, 27), 83: (6, 26), 115: (6, 25), 14: (6, 24), 122: (8, 95), 95: (8, 94), 76: (7, 46), 24: (7, 45), 37: (7, 44), 50: (5, 10), 51: (5, 9), 108: (6, 17), 22: (7, 33), 120: (8, 65), 66: (8, 64), 21: (7, 31), 106: (7, 30), 47: (6, 14), 53: (5, 6), 49: (5, 5), 86: (8, 39), 85: (8, 38), 23: (7, 18), 75: (7, 17), 20: (7, 16), 2: (5, 3), 73: (8, 23), 43: (9, 45), 87: (9, 44), 70: (7, 10), 3: (6, 4), 52: (5, 1), 54: (5, 0)}


def account_fingerprint(timestamp):
    now = datetime.fromtimestamp(timestamp, timezone(timedelta(hours=8)))
    stamp = str(int(timestamp * 1000))
    local = f'{now.month}/{now.day}/{now.year}, {now.hour % 12 or 12}:{now.minute:02d}:{now.second:02d} {"AM" if now.hour < 12 else "PM"}'
    fields = ['TF1', '020'] + [''] * 39
    fields += ['true', 'true', stamp, '-6', '6/7/2005, 9:33:44 PM', '', '', '', '', '', '', stamp, '0', local]
    fields += [''] * 34 + ['5.6.1-0', '']
    raw = ';'.join(quote(value, safe='/@*') for value in fields) + ';'
    encoded = raw
    tokens = '%20 ;;; %3B %2C und fin ed; %28 %29 %3A /53 ike Web 0; .0 e; on il ck 01 in Mo fa 00 32 la .1 ri it %u le'.split(' ')
    for index, token in enumerate(tokens, 1):
        encoded = encoded.replace(token, chr(index))
    alphabet = '.0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz'
    output, buffer, count = [], 0, 0

    def push(width, value):
        nonlocal buffer, count
        buffer = (buffer << width) | value
        count += width
        while count >= 6:
            count -= 6
            output.append(alphabet[(buffer >> count) & 63])
        buffer &= (1 << count) - 1

    push(6, (len(encoded) & 7) << 3)
    push(6, (len(encoded) & 56) | 1)
    for value in encoded.encode():
        if value not in _CODES:
            return raw
        push(*_CODES[value])
    push(*_CODES[0])
    if count:
        push(6 - count, 0)
    crc = 0xffff
    for value in raw.encode():
        crc = ((crc >> 8) | (crc << 8)) & 0xffff
        crc ^= value
        crc ^= (crc & 255) >> 4
        crc ^= (crc << 12) & 0xffff
        crc ^= ((crc & 255) << 5) & 0xffff
    output += [alphabet[(crc >> 12) & 63], alphabet[(crc >> 6) & 63], alphabet[crc & 63]]
    return ''.join(output)

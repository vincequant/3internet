"""Read-only native tile control/object fields, in the same capture page cache.

The original Collector exports static terrain in native column-major order.
Construction also depends on dynamic tile +0xc / +0xe signed 16-bit fields.
Never retain these dynamic fields in the Collector's static terrain cache.
"""
import struct

UNKNOWN = -32768


def with_construction_grid(base):
    class ConstructionCollector(base):
        def terrain_grid(self):
            original = super().terrain_grid()
            if not original:
                return original
            grid = dict(original)
            width, height = grid['width'], grid['height']
            count = width * height
            if not (0 < count <= 1000000):
                raise ValueError('construction grid outside safety bounds')
            header = self.read(self.core + 0x5fc, 28)
            pointer_base = struct.unpack_from('<I', header, 4)[0]
            actual_size = struct.unpack_from('<II', header, 20)
            if actual_size != (width, height) or pointer_base < 0x10000:
                raise ValueError('construction grid header changed')
            pointers = self.read(pointer_base, count * 4)
            kinds, controls = bytearray(count * 2), bytearray(count * 2)
            observed = {}
            failed = 0
            for index in range(count):
                pointer = struct.unpack_from('<I', pointers, index * 4)[0]
                if pointer not in observed:
                    try:
                        if pointer < 0x10000:
                            raise ValueError('invalid tile pointer')
                        observed[pointer] = struct.unpack('<hh', self.read(pointer + 12, 4))
                    except (OSError, RuntimeError, ValueError, struct.error):
                        observed[pointer] = (UNKNOWN, UNKNOWN)
                control, kind = observed[pointer]
                if kind == UNKNOWN or control == UNKNOWN:
                    failed += 1
                struct.pack_into('<h', controls, index * 2, control)
                struct.pack_into('<h', kinds, index * 2, kind)
            grid.update(object_kinds_s16le=kinds.hex(), control_forces_s16le=controls.hex(),
                        layout='column-major', construction_unknown=UNKNOWN,
                        construction_source='native_tile_0x469f6f_plus_0xc_0xe')
            if failed:
                grid['construction_unread_cells'] = failed
            return grid
    return ConstructionCollector

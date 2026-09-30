"""Compare packed cells through recorded logical-to-physical pin mappings."""
import copy

def canonical_cells(design):
    result = {}
    for module_name, module in design['modules'].items():
        aliases = {}
        for name, net in module['netnames'].items():
            for index, bit in enumerate(net['bits']):
                if isinstance(bit, int):
                    aliases.setdefault(bit, []).append((name, index))
        def canonical_bits(bits):
            return [tuple(sorted(aliases[bit])) if isinstance(bit, int) else bit for bit in bits]
        cells = {}
        for name, original in module['cells'].items():
            cell = copy.deepcopy(original)
            attributes = cell['attributes']
            connections, directions = {}, {}
            for physical_port, bits in cell['connections'].items():
                if not bits:  # Packed JSON import omits disconnected ports.
                    continue
                logical_port = attributes.get('X_ORIG_PORT_' + physical_port, physical_port)
                value = canonical_bits(bits)
                direction = cell['port_directions'][physical_port]
                # BRAM packing can give duplicate physical aliases to one
                # logical pin; they must remain tied to the identical net.
                if logical_port in connections:
                    assert connections[logical_port] == value, (name, logical_port)
                    assert directions[logical_port] == direction
                connections[logical_port] = value
                directions[logical_port] = direction
            cell['connections'], cell['port_directions'] = connections, directions
            cell['attributes'] = {
                key: value for key, value in attributes.items()
                if not key.startswith('X_ORIG_PORT_')
                and key not in ['NEXTPNR_BEL', 'BEL_STRENGTH']
            }
            cells[name] = cell
        result[module_name] = cells
    return result

def verify_packed_logic(original, candidate):
    """Include every cell, parameter, logical pin, net alias and other attribute.

    Top-level port declarations and unused net objects are not functional after
    I/O packing; JSON reimport drops them. All packed I/O cells and their
    attributes/connections are compared, just like every internal cell.
    Unmapped supplemental pins (e.g. LUT A6 tied high) remain in the comparison.
    """
    return canonical_cells(original) == canonical_cells(candidate)

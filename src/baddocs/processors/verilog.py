"""Verilog / SystemVerilog code processor.

Extracts modules, parameters, ports (with direction, net type, signedness and
width), always/clocking blocks and submodule instances from Verilog (.v/.vh)
and SystemVerilog (.sv/.svh) sources.

Unlike the placeholder processors for other languages, this one performs real
structural extraction so the documentation prompt is grounded in the actual
module interface -- the piece a hardware engineer needs and that generic
source-doc tools miss entirely (they treat HDL as plain text or "unknown").
"""

import re

from baddocs.processors.base import BaseProcessor


class VerilogProcessor(BaseProcessor):
    """Processor for Verilog and SystemVerilog code."""

    # File extensions this processor claims.
    extensions = ('.v', '.vh', '.sv', '.svh', '.svi')

    _KEYWORDS = {
        'module', 'endmodule', 'always', 'always_ff', 'always_comb',
        'always_latch', 'assign', 'if', 'else', 'begin', 'end', 'case',
        'casex', 'casez', 'endcase', 'for', 'while', 'initial', 'generate',
        'endgenerate', 'wire', 'reg', 'logic', 'localparam', 'parameter',
        'function', 'task', 'genvar', 'integer', 'posedge', 'negedge',
    }

    def __init__(self, config=None):
        super().__init__()
        self.language = 'verilog'
        self.config = config or {}

    # ------------------------------------------------------------------ #
    # BaseProcessor interface
    # ------------------------------------------------------------------ #
    def parse(self, code: str):
        """Parse HDL source into a structural dict."""
        return {'modules': self.extract_modules(code)}

    @staticmethod
    def _infers_multiplier(body: str) -> bool:
        # Drop attribute pragmas and bracketed width/index expressions.
        b = re.sub(r'\(\*.*?\*\)', '', body, flags=re.DOTALL)
        depth, out = 0, []
        for ch in b:
            if ch == '[':
                depth += 1
            elif ch == ']':
                depth = max(0, depth - 1)
            elif depth == 0:
                out.append(ch)
        b = ''.join(out)
        # Real multiply: '*' (not '**') with a signal operand on at least one side.
        for m in re.finditer(r'(\w+)\s*(?<!\*)\*(?!\*)\s*(\w+)', b):
            lhs, rhs = m.group(1), m.group(2)
            if not lhs.isdigit() or not rhs.isdigit():
                return True
        return False

    def extract_symbols(self, code: str):
        """Flat list of documentable symbols (modules + ports)."""
        symbols = []
        for mod in self.extract_modules(code):
            symbols.append({
                'type': 'module',
                'name': mod['name'],
                'ports': len(mod['ports']),
                'parameters': len(mod['parameters']),
                'instances': len(mod['instances']),
            })
            for port in mod['ports']:
                symbols.append({
                    'type': 'port',
                    'name': port['name'],
                    'direction': port['direction'],
                    'module': mod['name'],
                })
        return symbols

    # ------------------------------------------------------------------ #
    # Extraction helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _strip_comments(code: str) -> str:
        code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
        code = re.sub(r'//[^\n]*', '', code)
        return code

    def extract_modules(self, code: str):
        clean = self._strip_comments(code)
        pattern = re.compile(
            r'\bmodule\s+(\w+)\s*(?:#\s*\((.*?)\))?\s*\((.*?)\)\s*;(.*?)\bendmodule',
            re.DOTALL,
        )
        modules = []
        for mo in pattern.finditer(clean):
            name, param_blob, port_blob, body = mo.group(1), mo.group(2) or '', mo.group(3) or '', mo.group(4) or ''
            modules.append({
                'name': name,
                'parameters': self._parse_parameters(param_blob),
                'ports': self._parse_ports(port_blob),
                'instances': self._parse_instances(body, name),
                'always_blocks': len(re.findall(r'\balways(?:_ff|_comb|_latch)?\b', body)),
                'assigns': len(re.findall(r'\bassign\b', body)),
                # Ternary/BitNet signal: flag a real inferred multiplier. Width and
                # bit-select expressions ([2*COLS-1:0], x[ACC_WIDTH*2-1 -: W]) use '*'
                # for index math, not hardware multiply -- strip bracketed spans first,
                # ignore '**' (power) and '(* *)' attributes, then require '*' between
                # two operands where at least one is a signal (not a pure literal).
                'infers_multiplier': self._infers_multiplier(body),
            })
        return modules

    @staticmethod
    def _split_top_level(blob: str):
        """Split on commas that are not inside brackets/parens."""
        depth, cur, items = 0, '', []
        for ch in blob:
            if ch in '[{(':
                depth += 1
            elif ch in ']})':
                depth -= 1
            if ch == ',' and depth == 0:
                items.append(cur)
                cur = ''
            else:
                cur += ch
        if cur.strip():
            items.append(cur)
        return items

    def _parse_parameters(self, blob: str):
        params = []
        for pm in re.finditer(r'(?:parameter|localparam)?\s*(?:\w+\s+)?(\w+)\s*=\s*([^,]+)', blob):
            name, default = pm.group(1), pm.group(2).strip()
            if name in self._KEYWORDS:
                continue
            params.append({'name': name, 'default': default})
        return params

    def _parse_ports(self, blob: str):
        port_re = re.compile(
            r'\b(input|output|inout)\b\s*(reg|wire|logic)?\s*(signed)?\s*(\[[^\]]*\])?\s*(\w+)'
        )
        ports, last_dir = [], None
        for item in self._split_top_level(blob):
            item = item.strip()
            if not item:
                continue
            m = port_re.search(item)
            if m:
                last_dir = m.group(1)
                ports.append({
                    'name': m.group(5),
                    'direction': m.group(1),
                    'net_type': m.group(2) or '',
                    'signed': bool(m.group(3)),
                    'width': (m.group(4) or '').strip(),
                })
            else:
                nm = re.search(r'(\w+)\s*$', item)
                if nm and last_dir and nm.group(1) not in self._KEYWORDS:
                    ports.append({
                        'name': nm.group(1),
                        'direction': last_dir,
                        'net_type': '',
                        'signed': False,
                        'width': '',
                    })
        return ports

    def _parse_instances(self, body: str, self_name: str):
        insts = []
        for im in re.finditer(r'\b(\w+)\s*(?:#\s*\([^;]*?\))?\s+(\w+)\s*\(', body):
            mtype, inst = im.group(1), im.group(2)
            if mtype in self._KEYWORDS or mtype == self_name or inst in self._KEYWORDS:
                continue
            insts.append({'module_type': mtype, 'instance_name': inst})
        return insts

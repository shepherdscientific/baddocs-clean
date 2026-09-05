"""Language-specific code processors."""

from baddocs.processors.base import BaseProcessor
from baddocs.processors.python import PythonProcessor
from baddocs.processors.javascript import JavaScriptProcessor
from baddocs.processors.java import JavaProcessor
from baddocs.processors.csharp import CSharpProcessor
from baddocs.processors.golang import GoProcessor
from baddocs.processors.ruby import RubyProcessor
from baddocs.processors.rust import RustProcessor
from baddocs.processors.php import PHPProcessor
from baddocs.processors.cobol import CobolProcessor
from baddocs.processors.fortran import FortranProcessor
from baddocs.processors.vb6 import VB6Processor
from baddocs.processors.powerbuilder import PowerBuilderProcessor
from baddocs.processors.r import RProcessor
from baddocs.processors.verilog import VerilogProcessor

__all__ = [
    'BaseProcessor',
    'PythonProcessor',
    'JavaScriptProcessor',
    'JavaProcessor',
    'CSharpProcessor',
    'GoProcessor',
    'RubyProcessor',
    'RustProcessor',
    'PHPProcessor',
    'CobolProcessor',
    'FortranProcessor',
    'VB6Processor',
    'PowerBuilderProcessor',
    'RProcessor',
    'VerilogProcessor',
]

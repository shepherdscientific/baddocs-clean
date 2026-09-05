"""Base processor for all languages.

A processor turns a source file into (a) a list of documentable *elements*
(symbols) and (b) a validation decision. Most language processors currently
provide only a light/no structural pass -- the LLM still writes prose from the
raw source -- while the Verilog/SystemVerilog processor performs real structural
extraction (modules, ports, parameters, instances). The defaults here let a
light processor participate in the pipeline (prose-only) without crashing;
processors override ``extract_symbols`` to contribute structure.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class ProcessingResult:
    """Outcome of processing a single file."""
    path: str
    language: str
    elements: List[Dict[str, Any]] = field(default_factory=list)


class BaseProcessor(ABC):
    """Base class for language processors."""

    # Max file size to read (bytes); overridable via config['max_file_size_mb'].
    DEFAULT_MAX_BYTES = 2 * 1024 * 1024

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        self.language: str | None = None
        self.config = config or {}

    @abstractmethod
    def parse(self, code: str) -> Dict[str, Any]:
        """Parse source code into a structural dict."""

    @abstractmethod
    def extract_symbols(self, code: str) -> List[Dict[str, Any]]:
        """Extract documentable symbols from code (may be empty)."""

    # ------------------------------------------------------------------ #
    # Pipeline hooks (sensible defaults; processors rarely need to override)
    # ------------------------------------------------------------------ #
    def _max_bytes(self) -> int:
        mb = self.config.get("max_file_size_mb")
        return int(mb * 1024 * 1024) if mb else self.DEFAULT_MAX_BYTES

    def validate_file(self, file_path: Any) -> bool:
        """True if the file exists and is small enough to process."""
        p = Path(file_path)
        try:
            return p.is_file() and p.stat().st_size <= self._max_bytes()
        except OSError:
            return False

    def process_file(self, file_path: Any) -> ProcessingResult:
        """Read the file and return its extracted elements (may be empty)."""
        p = Path(file_path)
        code = p.read_text(encoding="utf-8", errors="replace")
        return ProcessingResult(
            path=str(file_path),
            language=self.language or "unknown",
            elements=self.extract_symbols(code),
        )

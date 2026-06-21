"""Evidence package.

Import concrete evidence types and workers from their owning modules. The
package root intentionally stays lightweight so importing a dataclass does not
load PDF, OCR, or local ML runtimes into the FastAPI process.
"""

__all__: list[str] = []

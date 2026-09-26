# Messy-document acceptance

The generated acceptance suite exercises the public folder check with actual
`pypdf`, `python-docx`, and `python-pptx` readers. Run it from the `rag-preflight`
source directory after installing the optional readers:

```sh
python -m pip install -e '.[pdf,office]'
python scripts/messy_document_acceptance.py --output /tmp/messy-result.json
```

The temporary fixture contains:

| Input | Required observation |
|---|---|
| Invalid UTF-8 text | Read failure classified as `invalid_utf8` |
| Empty and damaged PDFs | Plain-language read failures |
| Encrypted PDF | Rejected as encrypted when no password is supplied |
| Image-only PDF | Empty page plus bounded possible-OCR warning |
| 1,000-paragraph DOCX with a table | Document body and table text processed |
| Eight-slide image-heavy PPTX | Seven slides without text remain visible as empty units |
| Static HTML with script content | Visible body retained; script text excluded |
| Independent expected-file list | Missing PDF reported definitively |
| Unsupported CSV | Counted and excluded from the supported scope |

The script asserts every observation before emitting JSON. CI runs it on Linux
and Windows. Generated fixtures are deterministic, license-safe regression
evidence. They do not represent an external production corpus, OCR accuracy,
password handling, arbitrary Office features, or parser behavior at every file
size. Teams should still run `rag-preflight check` on a bounded, non-sensitive
sample of their own documents before adopting a reader policy.

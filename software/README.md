# Software analysis tools

Python utilities for comparing ARM images, matching library functions, and
extracting address ranges from user-supplied files.

| Tool | Purpose |
|---|---|
| [compare.py](tools/compare.py) | Compare ELF functions with a flat image; optionally show Thumb disassembly |
| [libmatch.py](tools/libmatch.py) | Find relocatable ARM object and archive functions in an image |
| [extract.py](tools/extract.py) | Extract an address range and record its SHA-256 hash |
| [tests/](tools/tests/) | Synthetic C fixtures and regression checks |
| [check_public_tree.py](tools/check_public_tree.py) | Check staged files against the publication allowlist |

## Usage

Install Python 3 and the dependencies in [requirements.txt](requirements.txt).
Run these commands from the software directory, replacing the example paths
with your own input and output paths:

```sh
python -m pip install -r requirements.txt
python tools/compare.py --elf /path/to/built.elf --bin /path/to/built.bin --dump /path/to/reference.bin --out /path/to/compare.md
python tools/libmatch.py --objdir /path/to/objects --dump /path/to/reference.bin --out /path/to/matches.tsv
python tools/extract.py --dump /path/to/reference.bin --base 0x10000000 --start 0x10000100 --end 0x10000200 --name sample --datadir /path/to/output
```

`compare.py` uses the end of the reference image as its default code boundary;
use `--code-end` to restrict it. Address masking assumes RP2040 flash and RAM
ranges. `MATCH-ADDR` is a heuristic classification, not a semantic proof.
Reports may include input bytes and disassembly.

## Tests

Fixture tests require `arm-none-eabi-gcc`, its matching `ar` and `objcopy`, and
the Python dependencies. Set `CC` to the compiler path if it is not on `PATH`.

```sh
python tools/tests/run_tests.py /path/to/disposable-test-directory
```

The runner recreates `objs`, `objs_mut`, and `data` beneath the supplied directory.
Use a dedicated disposable directory.

## Contributions

Review the staged diff and run `python tools/check_public_tree.py --worktree`
before committing. [public-files.txt](public-files.txt) lists permitted files.
The guard checks paths, file types, size, and UTF-8 encoding; it does not audit
content, licensing, or secrets.

To enable the commit hook, run this from the repository root:

```sh
git config --local core.hooksPath software/.githooks
```

See [NOTICE.md](NOTICE.md) for licensing information.

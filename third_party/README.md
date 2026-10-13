# Third-party source

`keystone-engine-0.9.2.tar.gz` is the unmodified source distribution published on [PyPI](https://pypi.org/project/keystone-engine/0.9.2/#files). It contains the assembler core, its LLVM sources, Python bindings and build scripts. Keeping the upstream archive intact makes its provenance clear without mixing its files into the project's patch catalogue.

- Size: 2,813,059 bytes.
- SHA256: `2f7af62dab0ce6c2732dbb4f31cfa2184a8a149e280b96b92ebc0db84c6e50f5`.
- The shipped core matches the Windows x64 wheel from the same PyPI release: `keystone_engine-0.9.2-py2.py3-none-win_amd64.whl`.
- Wheel SHA256: `c91db1ff16d9d094e00d1827107d1b4afd5e63ce19b491a0140e660635000e8b`.
- Core DLL SHA256: `3ac03927981fca588c95b2cd1f2f1d64dc33dbd55b362fc7742163647746c3e8`.

Both archives were checked against PyPI's published hashes, and the DLL was compared byte-for-byte with the bundled library. This identifies the upstream release; it does not claim a reproduction of the wheel's original compiler environment.

The archive's `src/COPYING`, `src/EXCEPTIONS-CLIENT` and component notices apply to Keystone and its incorporated code. The Python binding has its own BSD notice. Our project's MIT license does not replace any of those terms. The [launcher notice file](../docs/launcher-third-party.txt) reproduces those notices and identifies the other runtime components.

Extract the archive into a separate development directory to inspect or build it. Its `setup.py`, `src/CMakeLists.txt` and `src/nmake-dll.bat` describe the upstream Python and Windows build paths. Ordinary players do not build it. Our launcher build currently uses the pinned wheel in `requirements-launcher.txt`.

For release, offer the complete contributor source ZIP alongside the matching player ZIP, from the same release location, and retain this archive in it. Do not provide only an upstream link. Preserve that pairing when mirroring a release. Independently authored launcher sources use MIT; original game material and each dependency retain their separate terms.

libffi is downloaded during the launcher build from the Python project's pinned
binary-dependency commit. Its MIT-style notice appears in the launcher notices;
its URL and hash are recorded by the builder. It does not add a binary to this
source tree. OpenSSL's license and author list are also retained in the notices.
The Python runtime includes its own license and Windows binary-build conditions.

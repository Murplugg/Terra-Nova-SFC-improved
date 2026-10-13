# What the downloads contain

TNova Native has two matching downloads: a portable player setup ZIP and a contributor source ZIP. Setup generates the adapted game on the recipient's machine from verified originals. Neither download supplies a prepared native game image or executable/resource delta.

## Player setup

The player ZIP contains the setup script, maintained generators, the Windows display/audio bridge, the bundled launcher and its runtime, configuration, integrity manifests and dependency notices. It requires the supported English retail installation, both demos and the retail CD image.

Setup checks 344 original input entries and produces 1,781 installation entries: 809 copies from original assets, eight locally generated files, and 964 support or runtime files. Of the latter, 956 belong to the launcher bundle. These file counts describe the installation, not the number of patches.

The eight generated files are:

| File | How setup produces it |
| --- | --- |
| `native-template.bin` | Relocates the original executable, applies the maintained feature changes and compiles collision helpers with locally decoded geometry. Declared paths are adjusted when creating the installed executable. |
| `menu-retail-art.res` | Copies the original Load Game button frame for the Prequel entry. |
| `menu-demo-art.res` | Combines original menu records and replaces the demo advertising caption with retail background pixels. |
| `menu-retail.res` | Applies the main-menu, campaign-entry and room-handling changes to original menu bytecode. |
| `menu-demo.res` | Builds mission selection and Main Menu return from original demo records. |
| `prequel/DATA/RESBABL2.RES` | Adapts original demo menu/debrief scripts and mission labels. |
| `prequel/DATA/RESGAME.RES` | Combines verified retail/demo records, revised help and the original recruitment letter. |
| `prequel/DATA/RESMISS.RES` | Arranges the four demo missions into the Prequel campaign. |

Generation stages ten verified original files, about 13.7 MB, rather than copying an entire installation into a build directory. Every generated result must match the selected release's size and SHA-256 before the destination is created. Temporary input copies, geometry headers and compiler output are removed when generation finishes. Originals, ordinary saves and existing installations are never overwritten.

One-time setup needs 64-bit Windows Python 3.12. `--tools-cache` obtains the pinned Zig compiler, Capstone and Keystone from their upstream distributions, verifies their archive hashes and retains their notices. Those downloads total about 95 MB and are separate from the player ZIP. An explicit offline route is also available. Playing afterwards needs neither the tools cache nor installed Python.

## Contributor source

The source tree contains readable feature changes and generators, C/assembly helpers, launcher code, tests, documentation, hashes and binary-interface descriptions. The source export excludes original resource archives, complete game executables, generated model headers, snapshots and private research.

Retained original code is read locally in these places:

- The Windows host reads and relocates the original executable objects.
- Map rendering and Prequel integration decode the required original routines and tables from their verified inputs.
- Reflection and infrared loops, two sprite-scaling wrappers and the cursor fallback use `original_inputs.edited_assembly`. Their sources specify input ranges, digests and edits. Unchanged passages come from the user's executable.
- Collision geometry and the cannon's pivot/basis values come from the original model archive. No generated vertex or pose arrays are supplied in the source.
- Menu artwork, narrative and other unchanged resource contents are read from retail/demo archives; source files describe the transformations.

Short expected instructions, displaced hook instructions, addresses, structure offsets, callback mappings and resource identifiers remain visible in patches. They describe the binary interfaces the changes require. Source-based comparison also finds commonplace register-save/restore and original API-call sequences. This account does **not** claim that every published instruction is independent of the original game, or that local generation grants rights to its material.

Tests use synthetic actors, buffers, pixels and clocks. Tests of the retained routines additionally need `test.py --retail-exe`; no captured game code is embedded to make those tests asset-free. Output fingerprints are hashes, not recoverable copies of game resources.

## Terms and reproducibility

The project's MIT grant covers independently authored work to the extent its contributors hold the rights. Original game material remains outside that grant. Third-party software retains its own terms and notices. The source download includes the matching unmodified Keystone source archive; supply both downloads together, including on mirrors. See `LICENSE`, `third_party/README.md` and `docs/launcher-third-party.txt`.

Technical acceptance checks source integrity, complete output identities, installer failure handling and actual package contents. A byte-identical game confirms that this packaging change preserves the accepted executable; it is not legal clearance or proof of compatibility with every Windows system. The development Windows 10 laptop has been tested. Clean-machine and broader hardware acceptance remain unverified.

# Building and testing

## Environment and original inputs

Use Windows x64 with CPython 3.12, including Tk for the launcher, and the **Windows x86_64 Zig 0.15.2** toolchain. Keep the source, dependencies, compiler, originals and build output in separate folders. Do not use Python `-O`: assertions are part of the build checks.

Install `requirements-dev.txt` into a dedicated directory:

```powershell
python -m pip install --target C:\TNBuild\deps -r requirements-dev.txt
$env:PYTHONPATH = 'C:\TNBuild\deps'
python -B test.py
```

Dependency pins: Capstone 5.0.6 (x86 decoding), Keystone 0.9.2 (assembly), Unicorn 2.1.4 (execution tests). Python's standard library handles resource archives, deltas, manifests and ZIPs. Zig compiles the Windows bridge and collision helpers.

The full build currently expects this original-input layout:

```text
originals/
  TNOVA/       English retail v1.09 installation
  TNDEMO1/     downloadable demo contents
  TNDEMO2/     CD demo contents, including _SETUP/__FF.EXE
  _ISO/TNF108.ISO
```

Names alone do not establish compatibility: consumed files are checked by exact size and SHA-256. `engine/release-recipe.json` lists the setup input inventory and CD extents; `resource-manifest.json` lists resource-generation inputs. The retail executable must hash to `b762c54509f1716282c4d357a72013b8d84ba25f17b0483b733678ff81e63dd1`; the CD demo executable to `886568d2d0e15c5bcce5539832cd8bf1fd2c02655825c6ddf3cc77068be2556f`. The pinned Zig executable hash is `d408dd38eed3e5204af841bcebf70502a4dbbb8399a3a3262be55059370bc018`.

## Installed data and disk space

The extracted setup ZIP includes `Setup.cmd`, which opens a folder-picker window
using Windows x64 CPython 3.12 with Tcl/Tk. Select the retail folder, both demo
folders, retail CD ISO, a new destination and the build-tools cache. Browsing for
a destination selects its parent and proposes a new `TNovaNative` folder; the
text field lets you change that name. Selecting the retail folder also fills
empty demo/CD fields when the standard sibling layout exists.

The window calls the same verified installer as the command-line entry. Its
stage indicator remains active during generation; it is not an estimated
percentage or completion time. Setup logs are saved as `TNovaNative-setup-*.log`
in your Windows temporary folder, with an **Open setup log** button. Logs contain
the selected local paths; check them before sharing. After installation, **Open
game folder** leads to `Terra Nova Launcher.exe` (or `Play.cmd` in a developer
package). Existing installations are never overwritten.

Setup shares unchanged game assets with hard links where supported, keeping saves,
settings and generated resources independent. CD-only files are extracted once into
`TNova-shared-data` beside the installation; `--data-cache PATH` selects another
location. Hard links require the same volume. Unsupported links fall back to copies,
and setup reports linked/written bytes and fallback counts. Explorer may still show
the full logical folder size even when the file data is shared.

Use `--data-mode copy` for a fully independent installation, including before editing
original resource files in place. Shared files must be treated as read-only: editing
one linked name changes the others. Moving or deleting the original folder/cache does
not invalidate existing hard links. Copying a game to another drive normally creates
independent files and uses their full space.

## Complete current build

The normal build packages local generators. The optional `--local-generation`
flag is accepted for compatibility and selects the same default. The public
command cannot select a package containing prepared game/resource deltas.

```powershell
python -B build.py --original-root C:\TNBuild\originals --compiler C:\TNBuild\zig\zig.exe --dependencies C:\TNBuild\deps --output C:\TNBuild\output
```

The output directory must not exist. This compiles the bridge and collision helpers, generates the engine and resources, checks the launcher snapshot layout, and produces a setup ZIP containing generators and native support. It never installs or starts the game. Logs and manifests are written beside the outputs.

The developer build checks all final outputs,
but ships their recipes and generators. Player setup repeats that generation
from ten verified original files. All eight generated results must match the
selected release; no prepared game or resource delta is used.

Local-generation setup accepts the usual original locations and destination,
plus `--tools-cache C:\TNovaTools`. With 64-bit Windows CPython 3.12, it prepares
the pinned Zig compiler and Capstone/Keystone wheels in that separate folder.
The initial downloads total about 95 MB; allow about 700 MB for tools and work
space. Every archive is size/hash checked before extraction, and reused tools
are checked against their file inventory. Nothing is installed globally.
Their upstream licenses remain in the cache. The tools are not needed to play.

For offline setup, add `--tool-downloads C:\ToolDownloads` containing the three
archives named in `generation_tools.py`. That option does not fall back to a
network download. Developers can instead supply `--compiler` and
`--dependencies` explicitly. `--check-only` runs the generators and validates
the complete package without creating the game destination. Temporary original
copies, geometry headers and compilation output are removed together.

For the complete player ZIP, create a separate Windows x64 CPython 3.12 virtual environment, install `requirements-launcher.txt`, and add `--launcher-python C:\TNBuild\launcher-env\Scripts\python.exe` to the same command. This freezes the launcher with PyInstaller, bundles its runtime/notices and attaches it to the setup ZIP. After setup, players need no installed Python, compiler or build tools. Without that option, the developer ZIP starts the game through `Play.cmd` but lacks the runtime required for exact Prequel F5/F9 snapshots.

For an engine-only edit, `engine/build_engine.py --help` documents the narrower command. It needs the two original executables, original model archive, compiled bridge and compiler, but not the complete CD packaging inputs.

Launcher packaging selects CPython's published Windows x64 libffi 3.4.4 binary,
verifying its immutable download and SHA-256 before use. This avoids inheriting
an unidentified library from a custom Python installation. The launcher builder
downloads the 40 KB dependency into its output directory; it never replaces the
developer's installed Python files. For a standalone offline launcher build,
pass `--libffi C:\TNBuild\libffi-8.dll` to `build_launcher.py`; the same hash check
applies. The pinned URL and hash are recorded in that script and in each bundle
inventory. The unused optional LZMA extension is excluded. Snapshots use raw
files and JSON, and retain their existing format.

Verify a generated setup before installation:

```powershell
python -B C:\TNBuild\output\package\install_portable.py --original C:\TNBuild\originals --destination C:\Games\TNovaNative --tools-cache C:\TNovaTools --check-only
```

Omit `--check-only` to create that new installation. Setup also accepts separate retail/demo/CD paths; see `--help`. Original input paths may contain Unicode; the native destination must currently be ASCII and at most 115 characters. Never point it at an existing game or save folder.

## Reproducibility and validation

The engine, portable template, regenerated geometry and modified resources have exact expected identities. Bridge comparison normalizes only COFF/debug timestamps and the CodeView GUID, retaining code/data checks. Launcher freezing has environment-dependent metadata; its output inventory is recorded separately rather than claiming byte-for-byte ZIP identity across Python installations.

`test.py` selects only tests supplied in this tree. Synthetic fixtures exercise x86 code through Unicorn and check launcher/installer behavior without a live game. A few checks need retained original routines, which are extracted locally rather than stored in the test files. Without an input they report explicit skips. Run the complete suite with:

```powershell
python -B test.py --retail-exe C:\TNBuild\originals\TNOVA\__FF.EXE --helpers C:\TNBuild\output\engine\helpers
```

The optional `--helpers` argument loads compiled collision helpers from that local build. Their ELF regions and entry points are checked against the source manifest before the execution tests use them. Without a helper folder, compiled-geometry cases report skips; the hook and installation checks still run.

The complete build adds original-input, helper, engine, resource and generated-output validation. Clean-machine/player acceptance is a separate release check.

`reference-layout.json` supplies fixed, neutral image-construction strings. Leave this file unchanged: supply your actual input paths through the build command. The zero padding preserves reserved string lengths and offsets. Those directories are never read or required to exist. Packaging verifies those slots and replaces their contents with installation-root placeholders. The Windows startup routine resolves them in memory from the executable’s folder. The normal executable stays identical across installations and folder moves; no path editing is needed. Move the complete installation, including its retail, prequel and cd folders. External data-folder overrides are not yet supported. Numeric snapshot/code identities and a few internal labels remain compatibility data, not a historical build sequence.

To reproduce the contributor archive, run `python -B export_source.py --output C:\TNBuild\source-export`. It creates that directory and a deterministic sibling ZIP, with a file/hash inventory.

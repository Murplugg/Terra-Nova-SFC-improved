# Credits

## Original game

**Looking Glass Technologies and the original Terra Nova: Strike Force Centauri
team** created the game, engine, artwork, sound, music and missions on which
this project builds. Their work remains the foundation of TNova Native.

## TNova Native

- **Project direction and hands-on playtesting:** the project maintainer, who
  set the priorities, supplied gameplay reports and reference material, and
  tested the changes through the campaign and demo missions.
- **AI assistance:** OpenAI's GPT models through Codex assisted with reverse
  engineering, implementation, test tooling and documentation. Automated checks
  were used alongside human playtesting; their scope and limitations are
  described in the [test guide](docs/testing.md).

## Shared research and community

Thanks to **skw-1337**, maintainer of
[Terra Nova Plus](https://github.com/skw-1337/terra-nova-plus), for sharing patch
sources and findings, discussing the two projects, and providing a useful point
of comparison for rendering, timing and gameplay behavior.

Thanks also to the **TTLG community** for keeping Terra Nova discussion and
modding active, and to everyone who takes the time to report a problem, test a
change or explain how the original game behaves.

## Tools and libraries

This work depends on the people who develop and maintain:

- **Ghidra and ghidra-lx-loader**, **radare2** and **DOSBox-X**, used to inspect
  the original engine and compare its behavior.
- **Capstone**, **Keystone** and **Unicorn**, used to decode, assemble and test
  x86 code.
- **Zig**, used to compile the Windows support layer and collision helpers.
- **Python**, **Tcl/Tk** and **PyInstaller**, used for build tools, the launcher
  and its Windows packaging.
- **Pillow**, **FFmpeg** and **MSS**, used for image, video and desktop inspection.

These acknowledgements complement the [project license](LICENSE),
[third-party source notes](third_party/README.md) and
[dependency notices](docs/launcher-third-party.txt). Those files retain the
component-specific attributions and terms.

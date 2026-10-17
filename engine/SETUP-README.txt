TNova Native - developer setup

This ZIP contains local generators and native support. Setup creates the adapted
executable and edited resources from verified English retail v1.09 files, both
demos and the supported retail CD ISO. It carries no prepared game/resource deltas.

One-time setup needs 64-bit Windows Python 3.12. From this extracted folder:
python -B install_portable.py --original "C:\path\to\originals" --destination "C:\Games\TNovaNative" --tools-cache "C:\TNovaTools"

The original root contains TNOVA, TNDEMO1, TNDEMO2 and _ISO. Separate --retail,
--download-demo, --cd-demo and --cd-image options are also supported; see --help.
Setup downloads about 95 MB of pinned tools into the chosen cache. Allow about
700 MB for tools and temporary work, in addition to the installed game.
Offline setup accepts --tool-downloads; developers may use --compiler and
--dependencies instead. No global tools or administrator installation is needed.

Unchanged assets share disk storage through hard links where supported. CD-only
files are extracted once into TNova-shared-data beside the installation; choose
another cache with --data-cache PATH. Saves/settings/generated files remain private.
Use --data-mode copy for independent resource copies. Treat shared files as read-only;
editing one linked name changes the others. Moving/deleting originals or the cache
does not break existing links. Cross-volume/unsupported links fall back to copies;
setup reports their storage cost. Explorer may still show full logical folder size.

Choose a new destination. Add --check-only to generate and verify without
installing. Originals and existing destinations are never overwritten.
Start Play.cmd after setup. Move the whole installation only while the game is
closed. The destination must be ASCII and at most 115 characters.
Retail and Prequel switch in the same window and share preferences. Ordinary
retail saves work normally. The tools cache is not needed for play.
This unbundled developer ZIP lacks the launcher runtime for exact Prequel F5/F9
snapshots. Use the launcher-bundled player package for those controls.
Tested on the development Windows 10 laptop; clean-machine testing is pending.

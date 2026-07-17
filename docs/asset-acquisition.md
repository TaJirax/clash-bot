# Local game-asset acquisition

This pipeline implements the supplied modding workflow for **read-only
recognition research**:

1. pull the installed APK split files from MEmu;
2. extract `/assets/sc`, `/assets/sc3d`, textures, and metadata;
3. decode `.sctx` texture banks to PNG;
4. downgrade current `.sc` files and reconstruct their XFL resources with
   SC2FLA;
5. patch Supercell Flat/Odin `.glb` models before ordinary glTF tooling reads
   them;
6. index every result by source, role, hash, label, and level when known.

The reverse FLA-to-SC project is cached only as documentation. The bot never
repackages or modifies the game. Original APKs, tools, and generated artwork
stay in ignored local directories and must not be committed or redistributed.

## Sources and compatibility

| Source | Local purpose | Status |
| --- | --- | --- |
| Statscell/clash-assets | labelled hall and unit references | 170 PNGs normalized |
| Supercell Fan Kit | official labelled building/character reference art | 17.5 GB already indexed |
| SC2FLA-FOSS-Edition | `.sc` to XFL/resources | current `.sc` works after read-only downgrade |
| ScDowngrade | current SC v5/v6 compatibility | installed locally |
| SCTX-Converter | SCTX to PNG | 297 files directly decoded |
| SupercellTexture schema + PVRTexTool | newer SCTX fallback | remaining 302 decoded and validated |
| Supercell-Flat-Converter | patch Odin/Supercell GLB | 574/574 models converted |
| SupercellSWF-Animate | FLA-to-SC reference | cached, not installed or used |
| older Supercell-Extractor/coc-sc-extract | historical format reference | not used on current v6 data |

Some repositories do not include a license file. They are retained only in
the ignored local cache. Supercell artwork remains subject to the Supercell
Fan Content Policy regardless of the surrounding tool repository's license.

## Reproduce the cache

Run commands from the repository root. The game instance used here is
`MEmu_1`, exposed by ADB as `127.0.0.1:21513`.

```powershell
# Acquire the approved GitHub references/tools and exact commit manifest.
.venv\Scripts\python.exe scripts\acquire_asset_sources.py

# Pull installed split APKs without modifying the emulator.
.venv\Scripts\python.exe scripts\pull_memu_game_assets.py 127.0.0.1:21513

# Pass the five APK paths recorded in the pull manifest.
.venv\Scripts\python.exe scripts\extract_game_package_assets.py <apk1> <apk2> <apk3> <apk4> <apk5>
```

Use isolated tool environments; these decoder dependencies are not runtime bot
dependencies:

```powershell
python -m venv .tools\flat-converter-venv
.tools\flat-converter-venv\Scripts\python.exe -m pip install -r assets\source_cache\github\supercell_flat_converter\requirements.txt "numpy<2"

python -m venv .tools\sc2fla-venv
.tools\sc2fla-venv\Scripts\python.exe -m pip install -r assets\source_cache\github\sc2fla_foss\requirements.txt zstandard

.venv\Scripts\python.exe scripts\install_sc2_decoder_tools.py
```

Build the decoded caches:

```powershell
.venv\Scripts\python.exe scripts\build_visual_asset_cache.py --source statscell=assets\source_cache\github\statscell_clash_assets

.tools\sc2fla-venv\Scripts\python.exe scripts\convert_sctx_textures.py assets\derived_cache\game_package
.tools\flat-converter-venv\Scripts\python.exe scripts\convert_supercell_flat.py assets\derived_cache\game_package

# Compatibility copies only; original SCTX files remain unchanged.
.tools\flat-converter-venv\Scripts\python.exe scripts\sanitize_sctx_headers.py assets\derived_cache\game_package

# Reconstruct selected families. This mutates only staged copies.
.venv\Scripts\python.exe scripts\extract_sc2fla_project.py buildings
.venv\Scripts\python.exe scripts\extract_sc2fla_project.py chr_balloon

# Index named compositions and their component sprites.
.venv\Scripts\python.exe scripts\index_sc2fla_dump.py
.venv\Scripts\python.exe scripts\sort_sc2fla_assets.py
.venv\Scripts\python.exe scripts\report_asset_coverage.py
```

To build the full SC reconstruction incrementally, first inspect the queue,
then run one group at a time. It resumes completed families and writes a
manifest after every family:

```powershell
.venv\Scripts\python.exe scripts\batch_extract_sc2fla.py
.venv\Scripts\python.exe scripts\batch_extract_sc2fla.py --group units --run
.venv\Scripts\python.exe scripts\index_sc2fla_dump.py
.venv\Scripts\python.exe scripts\sort_sc2fla_assets.py
```

`await_sc2fla_sort.py --group units` can run alongside a batch and refresh the
indexes automatically after the queue has no remaining unit families.

SC2FLA projects contain two different things:

- `LIBRARY/resources/*.png` are component bitmaps with numeric IDs;
- `LIBRARY/exports/*.xml` are named compositions such as
  `barracks_lvl10` that assemble those components.

The index deliberately keeps these roles separate. A component ID is never
used as a building label.

Sorted semantic manifests are written under
`assets/derived_cache/sorted_sc/exports/<category>/<family>/level_<n>/`.
For example, all reconstructed Archer poses/states for level 10 are grouped
under `exports/units/archer/level_10/`; unlabelled animation variants remain
under `unlevelled`.

## Current local inventory

- 5 installed split APKs, 696,264,421 bytes, with SHA-256 hashes;
- 8,510 extracted package files, including 315 SC, 599 SCTX, and 574 GLB;
- 599/599 SCTX atlases decoded to PNG;
- 574/574 Supercell Flat GLBs patched;
- 58,644 SC2FLA PNG resource components;
- 10,968 named SC2FLA vector compositions: 4,929 building and 6,039 unit exports;
- 677 labelled reference images from Statscell and the Fan Kit;
- 71,462 records visible through `clashbot.asset_catalog.AssetCatalog`.

## What this enables—and what it does not

The catalog makes all sources fast to query and gives the training pipeline
far broader coverage. It does **not** make those files detector-ready by
itself. Atlases must be split/reconstructed, 3D models must be rendered from
game-like camera angles, and samples must be combined with labelled real game
frames. The `detector_ready` count remains zero until a sample passes that
labelling and held-out validation process.

Runtime recognition must load a compact trained detector and metadata index,
not scan 17 GB of artwork or compare all 20,000 files against each frame.

## Local asset training index

The repository now builds a lightweight visual retrieval index from every
usable generated candidate and labelled reference PNG:

```powershell
.venv\Scripts\python.exe -m clashbot asset-train
.venv\Scripts\python.exe -m clashbot asset-status --label archer
```

The current index contains 1,625 samples (1,455 synthetic candidates and 170
labelled references), 191 semantic labels, and is saved at
`assets/derived_cache/model/asset_retrieval.npz` with a JSON manifest beside it.
This index is used as an asset-aware retrieval layer; it is not a replacement
for a bounding-box detector. Universal in-game detection still requires
labelled gameplay frames and held-out validation for each camera/zoom state.

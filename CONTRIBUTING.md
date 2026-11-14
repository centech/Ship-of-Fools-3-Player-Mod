# For developers

Players only need the release ZIP and its two Windows scripts. The source and
checks below are for maintaining the mod. Keep game DLLs, backups and saves
outside this repository.

## Setup and portable tests

Use Python 3.10+, Linux/WSL, x64 GCC and GNU binutils. The shipped helper was built
with Ubuntu 22.04's GCC 11.4.0.

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements-dev.txt
python3 third_player_mod/test_payload.py
python3 tools/check_distribution.py
```

Without game files, 16 tests run and 7 game-dependent tests are explicitly skipped.
GitHub Actions runs the portable checks and checks the Windows refusal paths.

## Full local checks

Supply your own exact, unmodified game DLL:

```sh
SOF_TEST_DLL='/path/to/original/GameAssembly.dll' python3 third_player_mod/test_payload.py
```

This enables all 23 tests. Native tests execute instructions from your local file
under Unicorn without launching the game. The required original SHA256 is:

```text
c9e858959f9d6c4d45b74e5d9a60532bb4ea4298b652f06f7272aace61242f67
```

Windows installer integration tests use only temporary DLL copies:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\third_player_mod\test_windows_release.ps1 -OriginalDll 'C:\path\to\original\GameAssembly.dll' -PreviousDll 'C:\path\to\previous\GameAssembly.dll'
```

The previous DLL is optional. It checks migration from an earlier recognized mod.
Run installer parsing/refusal checks without game files with:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\test_windows_safety.ps1
```

## Rebuild and package

```sh
python3 third_player_mod/build.py
python3 third_player_mod/make_release.py --original-dll '/path/to/original/GameAssembly.dll'
python3 third_player_mod/package_release.py
python3 tools/check_distribution.py
```

Add `--previous-dll PATH` to plan generation to verify migration from a recognized
older local DLL. Regenerate the plan whenever the native payload changes. Update
version labels when making a new native release. The Windows integration test
reads its expected output hash from the verified release plan.

The player ZIP deliberately includes only the installer, uninstaller, short
instructions, license and patch data. Source and developer tests stay here.
See [the technical notes](third_player_mod/TECHNICAL.md) for native hooks and
[RELEASING.md](RELEASING.md) for publishing.

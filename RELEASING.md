# Publishing on GitHub

The prepared release is in **dist/**. For this version:

1. Review and commit the repository changes, then push them to GitHub. You can
   use GitHub Desktop or your usual Git tools.
2. On GitHub, open **Releases → Draft a new release**.
3. Create tag **v0.5.0** and title it **Ship of Fools 3 Player Mod 0.5.0**.
4. Copy the text from **dist/RELEASE_NOTES_0.5.0.md** into the description.
5. Attach **Ship-of-Fools-3-Player-Mod-0.5.0.zip** from **dist/**. You can also
   attach the matching **.zip.sha256** file for people who want to check their
   download.
6. Mark it as a **pre-release** while live testing is still limited, then publish
   when you're ready.

Direct players to the named mod ZIP. GitHub's automatically generated source
archives are for developers.

To remake the player ZIP after editing instructions, run:

```sh
python3 third_player_mod/package_release.py
python3 tools/check_distribution.py
```

Only share the curated player ZIP. Game DLLs, backups and personal saves must
stay outside the repository and release. See [CONTRIBUTING.md](CONTRIBUTING.md)
for rebuilding the native mod and running full tests.

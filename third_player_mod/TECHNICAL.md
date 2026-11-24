# Technical notes

This document is for maintainers. Player instructions are in the main README.

## Runtime

The freestanding C/assembly payload uses a spare Rewired gamepad slot and spawns
a copy of P2 through the original scene path. Steam 1.5.4 already provides
spare slots. If a configuration has only two, the helper adds a third. The clone has its own controller,
input and components, but keeps P2's internal player number. Normal scene input
locks and ownership checks remain in the original dispatcher. Actor references
use IL2CPP GC handles that are released during reset/cleanup.

P2 and P3 share the right inventory. The hook closes the previous owner's panel
through the original ToggleInventory, then uses LinkToPlayer to update its actor,
subscriptions, portrait and items. It resolves the current P2 actor from the live
collection, excluding the clone, so changing P2's character does not leave the
handoff bound to a replaced actor.

Four count reads inside GameState.ToGameData are capped at two. That avoids
indexing a two-entry blueprint array with the third live actor. The original two
save slots remain; P3 has no independent persistent inventory. Lighthouse values
and unlock rules are not overridden.

## Binary layout

The builder starts from the exact original DLL. It adds RX `.sofcode`, RW
`.sofdata` and RO `.sofunw` sections with contiguous virtual coverage, retaining
the original exception table and adding Windows unwind records for helpers.
References are position independent under ASLR. The payload uses the Windows
x64 calling convention even when compiled with Linux GCC.

The hook RVAs, original instructions and helper symbols for Steam 1.5.4 are
listed together in `patch_third_player.py`. The standalone release leaves a
zero-filled page before the helper entry point. The Siren Update uses that page
for its own runtime, so both variants can use the same compiled co-op code.

Each release plan copies unchanged bytes and the native exception table from the
recipient's own recognized DLL. It verifies the complete output, keeps a
versioned backup, and replaces the DLL from a staged file. Uninstall reconstructs
the exact DLL for the selected variant. In the Siren case, all campaign hooks
and assets remain installed.

## Validation

The native/emulated suite has 24 tests. Seven need the stock 1.5.4 DLL, and one also needs the Siren Update DLL. They
cover input separation, scene cleanup, inventory handoff after character changes,
original inventory and save-loop instructions, ABI/unwind data, PE sections,
normal ship cleanup, installation and restoration.

Windows checks map the DLL without running game code and exercise both install variants,
repeat install, uninstall, earlier backup preservation and refusal paths on temporary copies.
Automated tests cannot establish behavior for every Unity gameplay system. A
live session should check inventories, character changes, scene transitions,
save/reload and Lighthouse progress after a new completed run.

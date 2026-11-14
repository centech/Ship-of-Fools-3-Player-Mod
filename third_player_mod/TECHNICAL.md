# Technical notes

This document is for maintainers. Player instructions are in the main README.

## Runtime

The freestanding C/assembly payload adds a third Rewired gamepad slot and spawns
a copy of P2 through the original scene path. The clone has its own controller,
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

| RVA | Purpose |
| --- | --- |
| `0x1187030` | Third gamepad slot |
| `0x6DDE70` | Local clone spawning |
| `0x8FED9A` | Gameplay input dispatch |
| `0x6DD430` | Scene cleanup |
| `0x925A20` | Player reset |
| `0x8C0E90` | Inventory handoff |
| `0x8C0490` | Inventory actor selection |
| `0x6C5331`, `0x6C5389`, `0x6C563E`, `0x6C5696` | Save count reads |

Outside these eleven hooks and the new PE sections/headers, the output retains
the original executable bytes. Original ship cleanup remains intact. Regression
checks compare the cleanup call and its unused padding against the original DLL.

## Distribution and migration

The portable plan copies unchanged bytes and exception-table data from the
recipient's own recognized DLL, then writes only the required patches. The full
output is hashed before replacement. Unknown inputs are refused, a verified
backup is retained, and replacement is staged. Uninstall reconstructs the exact
original DLL; it does not blindly restore an older modded backup.

Known older combined packages are accepted for migration. Plan generation resets
their obsolete header/call/padding writes to the original values. These locations
receive no new gameplay hook or helper in the 3 Player Mod.

## Validation

The native/emulated suite has 23 tests; seven need a local original DLL. They
cover input separation, scene cleanup, inventory handoff after character changes,
original inventory and save-loop instructions, ABI/unwind data, PE sections,
normal ship cleanup, installation and restoration.

Windows checks map the DLL without running game code and exercise install,
upgrade, repeat install, uninstall and refusal paths on temporary copies.
Automated tests cannot establish behavior for every Unity gameplay system. A
live session should check inventories, character changes, scene transitions,
save/reload and Lighthouse progress after a new completed run.

/* Ship of Fools supported Windows x64 build: local extra-body prototype.
 * Compiled freestanding; every external call uses the game's Windows x64 ABI.
 * P3 deliberately shares P2's saved identity/menus, but never its input object.
 */
typedef unsigned char u8;
typedef unsigned int u32;
typedef unsigned long long uptr;

/* Exact value-type layout from this build's generated il2cpp.h. In particular,
 * Nullable<T> has the value FIRST and the presence flag AFTER the value. */
struct NullableU64 { uptr value; u8 has_value; };
struct Information {
    uptr achievements;
    struct NullableU64 client_id;
    int dlcs;
    u8 name[128];
    int number;
};
struct NullableInformation { struct Information value; u8 has_value; };
struct NullableInt { int value; u8 has_value; };
struct Blueprint {
    int character;
    struct NullableInformation information;
    struct NullableInt preselected;
    u8 ready;
};
_Static_assert(sizeof(struct Information)==0xa0, "Information size");
_Static_assert(sizeof(struct Blueprint)==0xc0, "Blueprint size");
_Static_assert(__builtin_offsetof(struct Blueprint, information.has_value)==0xa8,
               "Nullable flag must follow the value");
_Static_assert(__builtin_offsetof(struct Blueprint, information.value.number)==0xa4,
               "Player number offset");
extern const u8 image_base[];
extern void original_spawn(void *, void *);
extern void original_reset(void *, void *);
extern void original_despawn(void *, void *);
extern void original_input_awake(void *, void *);
extern void original_inventory_update(void *, void *);
extern u8 original_inventory_match(void *, void *, void *);

#define PTR(p, off) (*(void **)((u8 *)(p) + (off)))
#define BYTE(p, off) (*(u8 *)((u8 *)(p) + (off)))
#define INT(p, off) (*(int *)((u8 *)(p) + (off)))
#define API(rva, type) ((type)((uptr)image_base + (rva)))

typedef void *(*ObjectFn)(void *, void *);
typedef int (*ControllerFn)(void *, int, void *);
typedef void *(*SpawnFn)(void *, void *, void *);
typedef void (*DispatchFn)(void *, int, void *, void *);
typedef u32 (*NewHandleFn)(void *, u8);
typedef void *(*TargetFn)(u32);
typedef void (*FreeHandleFn)(u32);
typedef void *(*StringFn)(const char *);
typedef void (*LogFn)(void *, void *);
typedef void (*MetadataFn)(void *);
typedef void (*AddFn)(void *, void *, void *);
typedef void (*NameFn)(void *, void *, void *);
typedef u8 (*KeyboardFn)(int, void *);
typedef int (*IdFn)(void *, void *);

/* No managed pointers are retained without a GC handle. The scene owns actors;
 * this extra handle is released before scene destruction and player reset. */
struct ModState {
    void *scene;
    u32 clone_handle;
    int controller;
    int ready;
    int spawning;
    u32 scenes;
    u32 joins;
    u32 controller_mask;
    int input_slot;
    u32 buttons_logged;
    u32 second_handle;
    int inventory_owner; /* 2 or 3; P2/P3 share the existing right panel. */
    int inventory_metadata;
};
__attribute__((used)) struct ModState mod_state = { .controller = -1 };

static void log_message(const char *message) {
    void *str = API(0x319600, StringFn)(message);
    if (str) API(0xd9b9b0, LogFn)(str, 0);
}

static void log_controller(int id) {
    char message[] = "[ThirdPlayer] Gameplay button from controller 00.";
    int index = sizeof(message)-4;
    message[index] = '0' + id/10;
    message[index+1] = '0' + id%10;
    log_message(message);
}

static void forget_clone(void) {
    u32 h = mod_state.clone_handle;
    u32 second = mod_state.second_handle;
    mod_state.second_handle = 0;
    mod_state.inventory_owner = 2;
    mod_state.clone_handle = 0;
    mod_state.ready = 0;
    mod_state.spawning = 0;
    mod_state.scene = 0;
    mod_state.buttons_logged = 0;
    if (h) API(0x318cd0, FreeHandleFn)(h);
    if (second) API(0x318cd0, FreeHandleFn)(second);
}

static int local_scene(void *scene) {
    if (!scene || !BYTE(scene, 0x78) || !BYTE(scene, 0x1e) ||
        !BYTE(scene, 0x22)) return 0;
    void *ps = PTR(scene, 0xa0);
    return ps && !BYTE(ps, 0xe1);
}

static int unused_controller(void *scene, int id) {
    if (id <= 0 || !local_scene(scene)) return 0;
    if (API(0xad0880, KeyboardFn)(id, 0)) return 0;
    void *ps = PTR(scene, 0xa0);
    ControllerFn get = API(0x923330, ControllerFn);
    return get(ps, 0, 0) != id && get(ps, 1, 0) != id;
}

/* The shipped Rewired config has keyboard + just two joystick players. Add a
 * third joystick player BEFORE Rewired builds its runtime player list. Reuse the
 * existing pad mappings, which initialization reads into new runtime objects.
 * This changes only the in-memory configuration; no asset bundles are edited. */
void third_input_awake(void *manager, void *method) {
    void *user = manager ? PTR(manager, 0x20) : (void *)0;
    void *list = user ? PTR(user, 0x18) : (void *)0;
    void *items = list ? PTR(list, 0x10) : (void *)0;
    void *template = 0;
    int pads = 0;
    if (items && INT(list, 0x18) <= 32) {
        for (int i = 0; i < INT(list, 0x18); ++i) {
            void *p = PTR(items, 0x20 + i * 8);
            void *maps = p ? PTR(p, 0x30) : (void *)0;
            if (maps && INT(maps, 0x18) > 0 && !BYTE(p, 0x5a)) {
                template = p;
                ++pads;
            }
        }
    }
    if (pads == 2 && template) {
        void *p = API(0x1d36a20, ObjectFn)(template, 0);
        if (p) {
            int id = API(0xce5da0, IdFn)(user, 0);
            INT(p, 0x10) = id;
            void *name = API(0x319600, StringFn)("Player3LocalClone");
            API(0x495c60, NameFn)(p, name, 0);
            API(0x495c50, NameFn)(p, name, 0);
            BYTE(p, 0x28) = 1;
            BYTE(p, 0x58) = 0;
            BYTE(p, 0x59) = 0;
            BYTE(p, 0x5a) = 0;
            API(0x397c60, MetadataFn)((void *)((uptr)image_base + 0x30b2028));
            API(0x23ca7e0, AddFn)(list, p,
                *(void **)((uptr)image_base + 0x30b2028));
            mod_state.input_slot = id;
            log_message("[ThirdPlayer] Added third gamepad input slot.");
        }
    }
    original_input_awake(manager, method);
}

static void *clone_actor(void) {
    return mod_state.clone_handle
        ? API(0x318ce0, TargetFn)(mod_state.clone_handle) : (void *)0;
}

static void assign_controller(void *clone) {
    if (clone && BYTE(clone, 0x1d))
        INT(clone, 0x148) = mod_state.controller;
}

static void join_clone(void *scene, int controller) {
    if (mod_state.spawning || mod_state.clone_handle ||
        !unused_controller(scene, controller)) return;
    void *ps = PTR(scene, 0xa0);
    void *assigned = API(0x9228f0, ObjectFn)(ps, 0);
    if (!assigned || INT(assigned, 0x18) != 2) return;

    /* GetAssignedPlayerBlueprints returns a managed array of 0xc0-byte values.
     * Select by identity instead of relying on the array's order. */
    struct Blueprint *bp = (struct Blueprint *)((u8 *)assigned + 0x20);
    if (!bp->information.has_value || bp->information.value.number != 1) ++bp;
    if (!bp->information.has_value || bp->information.value.number != 1) return;
    u8 copy[0xc0] __attribute__((aligned(16)));
    for (int i = 0; i < 0xc0; ++i) copy[i] = ((u8 *)bp)[i];
    copy[0xb8] = 1; /* Use P2's current selected character immediately. */

    mod_state.spawning = 1;
    mod_state.controller = controller;
    void *actor = API(0x6ddba0, SpawnFn)(scene, copy, 0);
    if (actor) {
        mod_state.clone_handle = API(0x318cf0, NewHandleFn)(actor, 0);
        assign_controller(actor);
        ++mod_state.joins;
        log_message("[ThirdPlayer] Player two clone spawned with an independent gamepad.");
    }
    mod_state.spawning = 0;
}

void third_spawn(void *scene, void *method) {
    forget_clone();
    original_spawn(scene, method);
    if (!local_scene(scene)) return;
    mod_state.scene = scene;
    mod_state.ready = 1;
    ++mod_state.scenes;
    log_message("[ThirdPlayer] Local clone mod ready. Press a button on an unused gamepad after both players join.");
    if (mod_state.controller > 0) join_clone(scene, mod_state.controller);
}

void third_reset(void *ps, void *method) {
    forget_clone();
    mod_state.controller = -1;
    original_reset(ps, method);
}

void third_despawn(void *scene, void *method) {
    if (mod_state.scene == scene) forget_clone();
    original_despawn(scene, method);
}

/* Only InputManager.Tick's gameplay dispatch call is redirected. The original
 * dispatcher still checks scene input locks, pause/cutscenes and actor ownership.
 * Reasserting the clone's field before dispatch also handles deferred Netcode
 * ownership initialization, which otherwise copies P2's controller back in. */
void third_dispatch(void *scene, int controller, void *input, void *method) {
    if (controller >= 0 && controller < 32)
        mod_state.controller_mask |= 1u << controller;
    if (mod_state.scene == scene && mod_state.ready && local_scene(scene)) {
        if (input && BYTE(input, 0x32) && controller >= 0 && controller < 32 &&
            !(mod_state.buttons_logged & (1u << controller))) {
            mod_state.buttons_logged |= 1u << controller;
            log_controller(controller);
        }
        void *actor = clone_actor();
        if (!actor && input && BYTE(input, 0x32)) join_clone(scene, controller);
        actor = clone_actor();
        assign_controller(actor);
    }
    API(0x6dc7f0, DispatchFn)(scene, controller, input, method);
}

/* ToGameData has two positional player-save slots. Its character loop indexes
 * GetAssignedPlayerBlueprints (length two) by the live actor index. Cap ONLY its
 * four count calls; gameplay and camera still see all three actors. This also
 * prevents P3 trinkets being written to an unsupported third vanilla save slot.
 */
int third_save_count(void *players, void *method) {
    int count = API(0x5026e0, IdFn)(players, method);
    return count > 2 ? 2 : count;
}

/* Keep all original inventory widgets, subscriptions, cargo, tooltips and drop
 * actions. LinkToPlayer performs its own unsubscribe/rebind/refresh. Its normal
 * predicate cannot distinguish two actors sharing P2's identity, so direct the
 * right panel to its selected actor while leaving P1's panel alone.
 */
u8 third_inventory_match(void *inventory, void *actor, void *method) {
    void *clone = clone_actor();
    if (clone && INT(inventory, 0x20) == 1) {
        if (mod_state.inventory_owner == 3) return actor == clone;
        if (actor == clone) return 0;
    }
    return original_inventory_match(inventory, actor, method);
}

typedef void (*InventoryFn)(void *, void *);
typedef void (*LinkFn)(void *, void *, void *, void *);
static int inventory_pressed(void *actor) {
    void *input = actor ? PTR(actor, 0x168) : (void *)0;
    return input && BYTE(input, 0x2d);
}

/* Character selection replaces P2's actor. The panel can stay linked to P3
 * throughout that change, so its old P2 handle is no longer an input source.
 * Resolve the current P2 from the injected live collection, excluding the clone
 * and using the game's own identity predicate. Only retain the current actor.
 */
typedef void *(*ItemFn)(void *, int, void *);
static void *current_second_actor(void *inventory, void *clone) {
    void *players = PTR(inventory, 0xc8);
    void *second = 0;
    if (players) {
        if (!mod_state.inventory_metadata) {
            API(0x397c60, MetadataFn)((void *)((uptr)image_base + 0x30ba7b0));
            API(0x397c60, MetadataFn)((void *)((uptr)image_base + 0x30ba880));
            mod_state.inventory_metadata = 1;
        }
        int count = API(0x5026e0, IdFn)(players,
            *(void **)((uptr)image_base + 0x30ba7b0));
        for (int i = 0; i < count; ++i) {
            void *actor = API(0x119c810, ItemFn)(players, i,
                *(void **)((uptr)image_base + 0x30ba880));
            if (actor && actor != clone &&
                original_inventory_match(inventory, actor, 0)) {
                second = actor;
                break;
            }
        }
    }
    void *previous = mod_state.second_handle
        ? API(0x318ce0, TargetFn)(mod_state.second_handle) : (void *)0;
    if (previous != second) {
        if (mod_state.second_handle)
            API(0x318cd0, FreeHandleFn)(mod_state.second_handle);
        mod_state.second_handle = second
            ? API(0x318cf0, NewHandleFn)(second, 0) : 0;
    }
    return second;
}

void third_inventory_update(void *inventory, void *method) {
    void *clone = clone_actor();
    if (clone && mod_state.ready && INT(inventory, 0x20) == 1 &&
        !BYTE(inventory, 0xa8)) {
        void *bound = PTR(inventory, 0xc0);
        void *second = current_second_actor(inventory, clone);
        void *other = bound == clone ? second : clone;
        /* If both press together, the current owner gets priority. Close before
         * switching so the old actor's IsInInventory flag is always cleared.
         * Original Update then consumes the new owner's button exactly once.
         */
        if (second && other && inventory_pressed(other) &&
            !inventory_pressed(bound)) {
            if (BYTE(inventory, 0x90))
                API(0x8c03a0, InventoryFn)(inventory, 0);
            mod_state.inventory_owner = other == clone ? 3 : 2;
            API(0x8bf670, LinkFn)(inventory, 0, 0, 0);
            log_message(other == clone ?
                "[ThirdPlayer] Right inventory panel now belongs to player three." :
                "[ThirdPlayer] Right inventory panel now belongs to player two.");
        }
    }
    original_inventory_update(inventory, method);
}

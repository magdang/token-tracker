/* Optional smoke-test helper: generate a real Wayland pointer motion after a warp.
 * Build with wayland-scanner's wlr-virtual-pointer protocol and libwayland-client.
 * No input device permissions or daemon required.
 */
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>
#include <time.h>
#include <wayland-client.h>
#include "virtual-pointer-client.h"

static struct zwlr_virtual_pointer_manager_v1 *manager;

static void global(void *data, struct wl_registry *registry, uint32_t name,
                   const char *interface, uint32_t version) {
    (void)data;
    (void)version;
    if (strcmp(interface, "zwlr_virtual_pointer_manager_v1") == 0)
        manager = wl_registry_bind(registry, name, &zwlr_virtual_pointer_manager_v1_interface, 1);
}

static void removed(void *data, struct wl_registry *registry, uint32_t name) {
    (void)data;
    (void)registry;
    (void)name;
}

int main(int argc, char **argv) {
    struct wl_display *display = wl_display_connect(NULL);
    if (!display) return 1;
    struct wl_registry *registry = wl_display_get_registry(display);
    const struct wl_registry_listener listener = {global, removed};
    wl_registry_add_listener(registry, &listener, NULL);
    wl_display_roundtrip(display);
    if (!manager) {
        fprintf(stderr, "Compositor does not support virtual pointers\n");
        return 1;
    }
    struct zwlr_virtual_pointer_v1 *pointer =
        zwlr_virtual_pointer_manager_v1_create_virtual_pointer(manager, NULL);
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    uint32_t ms = (uint32_t)(now.tv_sec * 1000 + now.tv_nsec / 1000000);
    zwlr_virtual_pointer_v1_motion(pointer, ms, wl_fixed_from_int(argc == 4 ? atoi(argv[1]) : 1),
                                   wl_fixed_from_int(argc == 4 ? atoi(argv[2]) : 0));
    zwlr_virtual_pointer_v1_frame(pointer);
    wl_display_roundtrip(display);
    zwlr_virtual_pointer_v1_motion(pointer, ms + 1, wl_fixed_from_int(argc == 4 ? 0 : -1), 0);
    zwlr_virtual_pointer_v1_frame(pointer);
    wl_display_roundtrip(display);
    /* Keep the device alive while GTK waits to show a native tooltip. */
    if (argc == 2 || argc == 4) sleep((unsigned)atoi(argv[argc - 1]));
    zwlr_virtual_pointer_v1_destroy(pointer);
    zwlr_virtual_pointer_manager_v1_destroy(manager);
    wl_registry_destroy(registry);
    wl_display_flush(display);
    wl_display_disconnect(display);
    return 0;
}
